"""CameraSlot — captura de frame RTSP por câmera com análise local de movimento."""
import logging
import os
import threading
import time

import cv2
import numpy as np

# Força transporte TCP para RTSP (evita bloqueio de portas UDP em redes com NAT/firewall)
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|timeout;15000000",  # timeout em µs (15 s)
)

from local_analyzer import AnalisadorLocal
from mosaic_constants import CAP_W, CAP_H

log = logging.getLogger(__name__)


def _mesclar_bboxes(boxes: list, gap: int = 20) -> list:
    """Mescla bounding boxes sobrepostos ou próximos (gap px)."""
    if not boxes:
        return []
    merged = True
    result = list(boxes)
    while merged:
        merged = False
        novo = []
        usado = [False] * len(result)
        for i, (ax1, ay1, ax2, ay2) in enumerate(result):
            if usado[i]:
                continue
            mx1, my1, mx2, my2 = ax1, ay1, ax2, ay2
            for j, (bx1, by1, bx2, by2) in enumerate(result):
                if i == j or usado[j]:
                    continue
                if bx1 - gap <= mx2 and bx2 + gap >= mx1 and \
                   by1 - gap <= my2 and by2 + gap >= my1:
                    mx1 = min(mx1, bx1)
                    my1 = min(my1, by1)
                    mx2 = max(mx2, bx2)
                    my2 = max(my2, by2)
                    usado[j] = True
                    merged = True
            novo.append((mx1, my1, mx2, my2))
            usado[i] = True
        result = novo
    return result


class CameraSlot:
    """Representa um slot do mosaico: captura RTSP + análise local de movimento."""

    def __init__(self, idx: int, cfg_cam: dict):
        self.idx              = idx
        self.cfg              = cfg_cam
        self.frame            = None
        self.resultado        = {}
        self.em_analise       = False
        self.deteccoes_locais: list = []
        self.frames_recentes: list = []
        self._BUFFER_MAX = 100
        self.analisador_local = AnalisadorLocal(camera_id=cfg_cam.get("id", str(idx)))
        self._lock            = threading.Lock()
        self._cap             = None
        self._rodando         = False
        self._expandido       = False
        self._trocar          = threading.Event()
        self._bgsub           = cv2.createBackgroundSubtractorMOG2(
                                    history=300, varThreshold=50, detectShadows=False)
        self._thread          = threading.Thread(target=self._loop, daemon=True)

        # Zonas de detecção — lista de {"nome", "zona": [x1,y1,x2,y2], "cor_idx"}
        # Migração automática do formato antigo (zona_deteccao singular)
        zonas_novas = cfg_cam.get("zonas_deteccao")
        if zonas_novas is None:
            zona_velha = cfg_cam.get("zona_deteccao")
            zonas_novas = [{"nome": "Zona 1", "zona": zona_velha, "cor_idx": 0}] if zona_velha else []
        self.zonas_roi: list   = zonas_novas
        self._movimento_na_zona = False
        # Modo expansão: ativado pela IA quando detecta corpo parcial na zona,
        # faz o worker analisar o frame completo para rastrear o responsável.
        self.modo_expansao: bool = False

    def iniciar(self, rtsp_uri: str, rtsp_sub: str = ""):
        self._uri_main  = rtsp_uri
        self._uri_sub   = rtsp_sub
        self._uri_ativo = rtsp_sub if rtsp_sub else rtsp_uri
        self._rodando   = True
        self._thread.start()

    def set_expandido(self, expandido: bool):
        """Troca para stream principal ao expandir, sub-stream ao minimizar."""
        if not self._rodando:
            return
        self._expandido = expandido
        novo = self._uri_main if (expandido or not self._uri_sub) else self._uri_sub
        if novo and novo != self._uri_ativo:
            self._uri_ativo = novo
            self._trocar.set()

    def parar(self):
        self._rodando = False
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=10)
        with self._lock:
            cap = self._cap
            self._cap = None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def set_zonas(self, zonas: list):
        """Atualiza lista de zonas em tempo real. zonas=[] significa câmera toda."""
        with self._lock:
            self.zonas_roi        = zonas
            self._movimento_na_zona = False
        self.modo_expansao = False

    def get_movimento_na_zona(self) -> bool:
        """Retorna True se houve qualquer movimento dentro de alguma zona na última verificação."""
        with self._lock:
            return self._movimento_na_zona

    def _checar_movimento_na_zona(self, bboxes_mov: list, w: int, h: int) -> bool:
        """
        Retorna True se qualquer bbox de movimento se sobrepõe a alguma zona configurada.
        Sem zonas configuradas: qualquer movimento no frame dispara análise.
        Não usa HOG — a IA decide o que fazer com o que entrou na zona.
        """
        if not self.zonas_roi:
            return bool(bboxes_mov)

        for zd in self.zonas_roi:
            coord = zd.get("zona", [])
            if len(coord) != 4:
                continue
            zx1 = int(coord[0] * w); zy1 = int(coord[1] * h)
            zx2 = int(coord[2] * w); zy2 = int(coord[3] * h)
            if any(bx1 < zx2 and bx2 > zx1 and by1 < zy2 and by2 > zy1
                   for bx1, by1, bx2, by2 in bboxes_mov):
                return True
        return False

    def get_frame(self):
        with self._lock:
            return self.frame.copy() if self.frame is not None else None

    def set_resultado(self, r: dict):
        with self._lock:
            self.resultado  = r
            self.em_analise = False

    def get_resultado(self):
        with self._lock:
            return dict(self.resultado)

    def get_deteccoes_locais(self) -> list:
        with self._lock:
            return list(self.deteccoes_locais)

    def _loop(self):
        cam_id = self.cfg.get("id", str(self.idx))
        atraso = 1.0
        while self._rodando:
            self._trocar.clear()
            uri = self._uri_ativo
            with self._lock:
                old_cap = self._cap
                self._cap = None
            if old_cap:
                try:
                    old_cap.release()
                except Exception:
                    pass
            new_cap = cv2.VideoCapture()
            new_cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 15_000)
            new_cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 15_000)
            new_cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            new_cap.open(uri, cv2.CAP_FFMPEG)
            with self._lock:
                self._cap = new_cap
            if not new_cap.isOpened():
                log.warning("[%s] Stream não abriu — tentando em %.0fs", cam_id, atraso)
                time.sleep(atraso)
                atraso = min(atraso * 2, 30)
                continue
            log.info("[%s] Stream RTSP conectado (%s)", cam_id,
                     "PRINCIPAL" if uri == self._uri_main else "SUB")
            atraso = 1.0
            falhas = 0
            while self._rodando and not self._trocar.is_set():
                with self._lock:
                    cap = self._cap
                if cap is None:
                    break
                try:
                    ok, frame = cap.read()
                except Exception:
                    break
                if not ok:
                    falhas += 1
                    if falhas >= 5:
                        log.warning("[%s] Falha ao ler frames — reconectando", cam_id)
                        break
                    time.sleep(0.1)
                    continue
                falhas = 0
                if self._expandido:
                    fh, fw = frame.shape[:2]
                    escala = min(1280 / fw, 720 / fh, 1.0)
                    tw = int(fw * escala)
                    th = int(fh * escala)
                    thumb = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_LINEAR)
                else:
                    thumb = cv2.resize(frame, (CAP_W, CAP_H),
                                       interpolation=cv2.INTER_LINEAR)
                small = thumb if not self._expandido else cv2.resize(
                    frame, (CAP_W, CAP_H), interpolation=cv2.INTER_LINEAR)
                bboxes = []
                try:
                    mask = self._bgsub.apply(small)
                    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,
                                            np.ones((5, 5), np.uint8))
                    mask = cv2.dilate(mask, np.ones((7, 7), np.uint8), iterations=2)
                    contornos, _ = cv2.findContours(
                        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    for cnt in contornos:
                        if cv2.contourArea(cnt) < 800:
                            continue
                        x, y, bw, bh = cv2.boundingRect(cnt)
                        bboxes.append((x, y, x + bw, y + bh))
                    bboxes = _mesclar_bboxes(bboxes, gap=20)
                except Exception:
                    pass
                na_zona = self._checar_movimento_na_zona(bboxes, CAP_W, CAP_H)
                with self._lock:
                    self.frame             = thumb
                    self.deteccoes_locais  = bboxes
                    self._movimento_na_zona = na_zona
                    self.frames_recentes.append(small.copy())
                    if len(self.frames_recentes) > self._BUFFER_MAX:
                        self.frames_recentes.pop(0)
