"""
Mosaico de cameras - SPARTA AGENTE IA
Suporte a layouts 1CH / 4CH / 16CH / 32CH, expansao de slot e analise IA compartilhada.
"""
import json
import logging
import queue
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

try:
    from PIL import Image as _PilImg, ImageDraw as _PilDraw, ImageFont as _PilFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from local_analyzer import AnalisadorLocal

log = logging.getLogger(__name__)

# Status global da API Claude (atualizado pelo worker de análise)
_api_online: bool = True

# ── Dimensoes fixas da area de video ─────────────────────────────────────────
MOSAIC_W  = 1280
MOSAIC_H  = 720
HDR_H     = 36
TOOLBAR_H = 32
WIN_W     = MOSAIC_W
WIN_H     = HDR_H + TOOLBAR_H + MOSAIC_H
WIN_NAME  = "SPARTA AGENTE IA"

# Resolucao interna de captura por slot (redimensiona na renderizacao)
CAP_W = 640
CAP_H = 360

# Layouts disponiveis: canais → (colunas, linhas)
LAYOUTS = {
    1:  (1, 1),
    4:  (2, 2),
    16: (4, 4),
    32: (8, 4),
}
LAYOUT_ORDER = [1, 4, 16, 32]

# Menu de contexto (desenhado no OpenCV — sem tkinter)
CTX_W      = 230
CTX_ITEM_H = 27
CTX_SEP_H  = 10
CTX_PAD_V  = 6
CTX_PAD_H  = 14

# Botoes da toolbar (layout)
_TOOLBAR_BTN_W   = 72
_TOOLBAR_BTN_H   = 22
_TOOLBAR_BTN_GAP = 8
_TOOLBAR_BTN_Y0  = (TOOLBAR_H - _TOOLBAR_BTN_H) // 2

# Botoes de acao (Sair / Treinar / Usuarios)
_ACT_BTN_W   = 78
_ACT_BTN_GAP = 6

# Cores BGR
C_BG      = ( 15,  15,  15)
C_CARD    = ( 30,  30,  30)
C_AMARELO = (  0, 208, 255)
C_BRANCO  = (240, 240, 240)
C_CINZA   = (120, 120, 120)
C_VERDE   = ( 61, 204, 126)
C_VERM    = ( 68,  68, 255)
C_LARAN   = (  0, 100, 255)

NIVEL_COR = {
    "sem_risco": C_VERDE,
    "atencao":   C_AMARELO,
    "suspeito":  C_LARAN,
    "critico":   C_VERM,
}

CAMERAS_JSON = Path(__file__).parent / "cameras.json"


# ── Slot de camera ────────────────────────────────────────────────────────────
class CameraSlot:
    def __init__(self, idx: int, cfg_cam: dict):
        self.idx              = idx
        self.cfg              = cfg_cam
        self.frame            = None
        self.resultado        = {}
        self.em_analise       = False
        self.deteccoes_locais: list = []
        self.analisador_local = AnalisadorLocal(camera_id=cfg_cam.get("id", str(idx)))
        self._lock            = threading.Lock()
        self._cap             = None
        self._rodando         = False
        self._bgsub           = cv2.createBackgroundSubtractorMOG2(
                                    history=300, varThreshold=50, detectShadows=False)
        self._thread          = threading.Thread(target=self._loop, daemon=True)

    def iniciar(self, rtsp_uri: str):
        self._uri     = rtsp_uri
        self._rodando = True
        self._thread.start()

    def parar(self):
        self._rodando = False
        if self._cap is not None:
            self._cap.release()
            self._cap = None

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
            with self._lock:
                if self._cap:
                    self._cap.release()
                self._cap = cv2.VideoCapture(self._uri)
            self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 8000)
            self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000)
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not self._cap.isOpened():
                log.warning("[%s] Stream não abriu — tentando em %.0fs", cam_id, atraso)
                time.sleep(atraso)
                atraso = min(atraso * 2, 30)
                continue
            log.info("[%s] Stream RTSP conectado", cam_id)
            atraso = 1.0
            falhas = 0
            while self._rodando:
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
                thumb = cv2.resize(frame, (CAP_W, CAP_H),
                                   interpolation=cv2.INTER_LINEAR)
                # Detecção local por subtração de fundo
                bboxes = []
                try:
                    mask = self._bgsub.apply(thumb)
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
                with self._lock:
                    self.frame = thumb
                    self.deteccoes_locais = bboxes


def _safe_text(s: str) -> str:
    """Remove acentos para compatibilidade com FONT_HERSHEY do OpenCV."""
    return unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode("ascii")


def _cor_clara(cor: tuple, delta: int = 40) -> tuple:
    return tuple(min(255, int(c) + delta) for c in cor[:3])


# ── Cache de fontes PIL ────────────────────────────────────────────────────────
_FONT_CACHE: dict = {}
_SEGOE_PATHS = [
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
]
_SEGOE_BOLD_PATHS = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]


def _get_font(size: int, bold: bool = False):
    key = (size, bold)
    if key not in _FONT_CACHE:
        paths = _SEGOE_BOLD_PATHS if bold else _SEGOE_PATHS
        for p in paths:
            try:
                _FONT_CACHE[key] = _PilFont.truetype(p, size)
                break
            except Exception:
                pass
        if key not in _FONT_CACHE:
            _FONT_CACHE[key] = _PilFont.load_default()
    return _FONT_CACHE[key]


def _txt_size(text: str, size: int, bold: bool = False) -> tuple[int, int]:
    """Retorna (largura, altura) do texto com a fonte PIL."""
    if not _PIL_OK:
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, size / 30, 1)
        return tw, th
    font = _get_font(size, bold)
    bb = font.getbbox(text)
    return bb[2] - bb[0], bb[3] - bb[1]


def _pil_render(img: np.ndarray,
                texts: list,
                src_rect: tuple | None = None) -> None:
    """Converte img (ou região) para PIL, renderiza todos os textos, copia de volta.
    texts = [(str, x, y, size_px, color_bgr, bold), ...]
    src_rect = (x0, y0, x1, y1) para renderizar numa sub-região (mais rápido).
    """
    if not _PIL_OK or not texts:
        return
    H, W = img.shape[:2]
    if src_rect:
        rx0, ry0, rx1, ry1 = (max(0, src_rect[0]), max(0, src_rect[1]),
                               min(W, src_rect[2]), min(H, src_rect[3]))
        roi = img[ry0:ry1, rx0:rx1]
        offset_x, offset_y = rx0, ry0
    else:
        roi = img
        offset_x, offset_y = 0, 0

    pil = _PilImg.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
    draw = _PilDraw.Draw(pil)
    for (text, x, y, size, color_bgr, bold) in texts:
        font = _get_font(size, bold)
        bb = font.getbbox(text)
        draw.text((x - offset_x - bb[0], y - offset_y - bb[1]),
                  text, font=font,
                  fill=(int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0])))
    result = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
    if src_rect:
        img[ry0:ry1, rx0:rx1] = result
    else:
        np.copyto(img, result)


def _pil_rounded_rect(img: np.ndarray, x0: int, y0: int, x1: int, y1: int,
                      color_bgr: tuple, radius: int = 6,
                      outline_bgr: tuple | None = None, outline_w: int = 1):
    """Desenha retângulo com cantos arredondados usando PIL."""
    if not _PIL_OK:
        cv2.rectangle(img, (x0, y0), (x1, y1), color_bgr, -1)
        return
    H, W = img.shape[:2]
    px0, py0 = max(0, x0), max(0, y0)
    px1, py1 = min(W, x1 + 1), min(H, y1 + 1)
    roi = img[py0:py1, px0:px1]
    pil = _PilImg.fromarray(cv2.cvtColor(roi, cv2.COLOR_BGR2RGB))
    draw = _PilDraw.Draw(pil)
    fill_rgb = (int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0]))
    outline_rgb = None
    if outline_bgr:
        outline_rgb = (int(outline_bgr[2]), int(outline_bgr[1]), int(outline_bgr[0]))
    rx0, ry0 = x0 - px0, y0 - py0
    rx1, ry1 = x1 - px0, y1 - py0
    r = min(radius, (rx1 - rx0) // 2, (ry1 - ry0) // 2)
    draw.rounded_rectangle([rx0, ry0, rx1, ry1], radius=r,
                            fill=fill_rgb, outline=outline_rgb, width=outline_w)
    img[py0:py1, px0:px1] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


def _draw_btn_bg(img: np.ndarray, x0: int, y0: int, x1: int, y1: int,
                 bg: tuple, hover: bool = False, shadow: bool = True,
                 radius: int = 6) -> tuple:
    """Desenha fundo do botão com cantos arredondados. Retorna a cor usada."""
    bg_r = _cor_clara(bg, 38) if hover else bg
    if shadow:
        _pil_rounded_rect(img, x0 + 3, y0 + 3, x1 + 3, y1 + 3,
                          (0, 0, 0), radius=radius)
    hl = _cor_clara(bg_r, 45)
    _pil_rounded_rect(img, x0, y0, x1, y1, bg_r, radius=radius,
                      outline_bgr=hl, outline_w=1)
    return bg_r


def _draw_modern_btn(img: np.ndarray, x0: int, y0: int, x1: int, y1: int,
                     label: str, bg: tuple, fg: tuple,
                     hover: bool = False, shadow: bool = True,
                     font_size: int = 11, bold: bool = False):
    """Botão moderno com sombra, highlight e texto PIL de alta qualidade."""
    _draw_btn_bg(img, x0, y0, x1, y1, bg, hover=hover, shadow=shadow)
    tw, th = _txt_size(label, font_size, bold)
    tx = x0 + max(2, (x1 - x0 - tw) // 2)
    ty = y0 + (y1 - y0 - th) // 2
    _pil_render(img, [(label, tx, ty, font_size, fg, bold)],
                src_rect=(x0, y0, x1 + 4, y1 + 4))


def _toolbar_action_rects(win_w: int, n: int) -> list:
    """Retorna lista de (x0,y0,x1,y1) dos botões de ação, alinhados à direita."""
    rects, x = [], win_w - 10
    for _ in range(n):
        x1, x0 = x, x - _ACT_BTN_W
        rects.insert(0, (x0, _TOOLBAR_BTN_Y0, x1, _TOOLBAR_BTN_Y0 + _TOOLBAR_BTN_H))
        x = x0 - _ACT_BTN_GAP
    return rects


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


# ── Fila de analise IA ────────────────────────────────────────────────────────
class FilaAnalise:
    # Intervalo mínimo entre análises por câmera (segundos)
    INTERVALO_PADRAO = 8

    def __init__(self, intervalo: int = INTERVALO_PADRAO):
        self._q         = queue.Queue()
        self._intervalo = intervalo
        self._ultimo    = {}
        self._thread    = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def enfileirar(self, slot: CameraSlot, frame_id: str, frame):
        # Gate 1: intervalo mínimo entre análises
        agora = time.monotonic()
        if agora - self._ultimo.get(slot.idx, 0) < self._intervalo:
            return
        # Gate 2: não enfileirar se já está analisando
        if slot.em_analise:
            return
        # Gate 3: só enfileirar se há movimento detectado pelo OpenCV
        if not slot.get_deteccoes_locais():
            return
        slot.em_analise = True
        self._ultimo[slot.idx] = agora
        self._q.put((slot, frame_id, frame.copy()))

    def _worker(self):
        global _api_online
        import db
        while True:
            slot, frame_id, frame = self._q.get()
            camera_id = slot.cfg["id"]
            tokens_in = tokens_out = 0
            try:
                from analyzer import triagem_haiku, analisar_frame

                # Estágio 1 — triagem Haiku: há pessoa no frame?
                pessoa_detectada, conf_haiku = triagem_haiku(frame, frame_id, camera_id)
                if not pessoa_detectada:
                    resultado = {
                        "alerta": False,
                        "nivel_risco": "sem_risco",
                        "comportamentos_detectados": ["Sem pessoa detectada na triagem"],
                        "posicao_na_cena": "",
                        "acao_recomendada": "",
                        "revisar_clip": False,
                        "janela_revisao_segundos": 0,
                        "confianca": conf_haiku,
                        "timestamp_analise": "",
                        "frame_id": frame_id,
                        "objetos_detectados": [],
                        "fonte": "haiku-triagem",
                    }
                    nivel = "sem_risco"
                    log.info("[%s] Haiku: sem pessoa — análise Opus ignorada", camera_id)
                else:
                    # Estágio 2 — análise completa com Opus
                    resultado, tokens_in, tokens_out = analisar_frame(
                        frame, frame_id, camera_id=camera_id
                    )
                    nivel = resultado.get("nivel_risco", "sem_risco")
                    log.info("[%s] Claude %s (%.0f%%) | tokens: %d/%d",
                             camera_id, nivel.upper(),
                             resultado.get("confianca", 0) * 100,
                             tokens_in, tokens_out)
            except Exception as exc:
                log.warning("[%s] Claude indisponivel (%s) — usando analise local",
                            camera_id, exc)
                _api_online = False
                resultado = slot.analisador_local.analisar(frame, frame_id)
                nivel = resultado.get("nivel_risco", "sem_risco")
                log.info("[%s] LOCAL %s (%.0f%%)",
                         camera_id, nivel.upper(),
                         resultado.get("confianca", 0) * 100)
            else:
                _api_online = True

            try:
                slot.set_resultado(resultado)
                if resultado.get("alerta"):
                    log.warning("[%s] ALERTA: %s", camera_id,
                                resultado.get("acao_recomendada"))
                    try:
                        import sound_alert
                        sound_alert.tocar_se_novo(nivel)
                    except Exception:
                        pass
                    try:
                        from alert_handler import enviar_webhook
                        enviar_webhook(resultado, camera_id)
                    except Exception:
                        pass

                from config import FASE_PROCESSO, PASTA_CLIPS
                clip_path = (
                    str(PASTA_CLIPS / f"alerta_{frame_id}.mp4")
                    if resultado.get("alerta") else None
                )
                db.salvar_analise(
                    resultado=resultado,
                    frame_id=frame_id,
                    camera_id=camera_id,
                    fase=FASE_PROCESSO,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    clip_path=clip_path,
                )
            except Exception as exc:
                log.error("[%s] Erro ao salvar resultado: %s", camera_id, exc)
                slot.em_analise = False
            finally:
                self._q.task_done()


# ── Renderizacao dos slots ────────────────────────────────────────────────────
def _slot_vazio(idx: int, hover: bool, w: int, h: int) -> np.ndarray:
    bg = (38, 38, 38) if hover else C_CARD
    img = np.full((h, w, 3), bg, dtype=np.uint8)
    borda = C_AMARELO if hover else (52, 52, 52)
    cv2.rectangle(img, (1, 1), (w - 2, h - 2), borda, 1)

    pil_texts = []
    FS_SLOT = max(9, min(12, h // 20))
    FS_ADD  = max(9, min(13, w // 50))

    if h > 50:
        btn_r = max(14, min(30, min(w, h) // 6))
        cx, cy = w // 2, h // 2
        if h > 90:
            cy -= 14

        if hover:
            cv2.circle(img, (cx + 4, cy + 4), btn_r + 3, (0, 0, 0), -1)
        btn_bg = C_AMARELO if hover else (58, 58, 58)
        cv2.circle(img, (cx, cy), btn_r, btn_bg, -1)
        cv2.ellipse(img, (cx, cy), (btn_r, btn_r), 0, 200, 340, _cor_clara(btn_bg, 60), 1)

        icon_cor = (15, 15, 15) if hover else (100, 100, 100)
        arm = max(5, btn_r // 2)
        cv2.line(img, (cx - arm, cy), (cx + arm, cy), icon_cor, 2)
        cv2.line(img, (cx, cy - arm), (cx, cy + arm), icon_cor, 2)

        if h > 90:
            txt = "Adicionar Camera"
            txt_cor = C_AMARELO if hover else C_CINZA
            tw, th = _txt_size(txt, FS_ADD)
            ty = cy + btn_r + 10
            pil_texts.append((txt, (w - tw) // 2, ty, FS_ADD, txt_cor, False))

    sw, sh = _txt_size(f"Slot {idx + 1}", FS_SLOT)
    pil_texts.append((f"Slot {idx + 1}", 6, 4, FS_SLOT, C_CINZA, False))
    _pil_render(img, pil_texts)
    return img


def _desenhar_bbox(img: np.ndarray, x1: int, y1: int, x2: int, y2: int,
                   cor: tuple, label: str = "", escala: float = 0.35):
    """Desenha bounding box com cantos em L (estilo câmera IP)."""
    espessura = 2
    canto = max(8, min(20, (x2 - x1) // 4, (y2 - y1) // 4))
    # Cantos em L
    for px, py, dx, dy in [
        (x1, y1,  1,  1), (x2, y1, -1,  1),
        (x1, y2,  1, -1), (x2, y2, -1, -1),
    ]:
        cv2.line(img, (px, py), (px + dx * canto, py), cor, espessura)
        cv2.line(img, (px, py), (px, py + dy * canto), cor, espessura)
    # Linha de borda fina completa (semi-transparente via blending não disponível aqui — usa retângulo leve)
    cv2.rectangle(img, (x1, y1), (x2, y2), (*cor[:3],), 1)
    if label and (x2 - x1) > 40:
        tw, th = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)[0]
        ly = max(y1 - 4, th + 2)
        cv2.rectangle(img, (x1, ly - th - 2), (x1 + tw + 6, ly + 2), cor, -1)
        cv2.putText(img, label, (x1 + 3, ly),
                    cv2.FONT_HERSHEY_SIMPLEX, escala, (0, 0, 0), 1)


def _desenhar_bboxes(img: np.ndarray, res: dict, deteccoes_locais: list,
                     w: int, h: int, cor: tuple, bar_h: int):
    """Boxes dinâmicos (MOG2) têm prioridade — seguem o movimento em tempo real.
    Fallback para boxes estáticos do Claude apenas quando não há movimento detectado."""
    escala = max(0.28, min(0.40, w / 800))

    if deteccoes_locais:
        sx = w / CAP_W
        sy = h / CAP_H
        for (bx1, by1, bx2, by2) in deteccoes_locais:
            x1 = int(bx1 * sx)
            y1 = int(by1 * sy) + bar_h
            x2 = int(bx2 * sx)
            y2 = int(by2 * sy)
            if x2 <= x1 or y2 <= y1:
                continue
            _desenhar_bbox(img, x1, y1, x2, y2, cor, "", escala)
    else:
        objetos = res.get("objetos_detectados", [])
        for obj in objetos:
            bbox = obj.get("bbox_norm", [])
            if len(bbox) != 4:
                continue
            x1 = int(bbox[0] * w)
            y1 = int(bbox[1] * h) + bar_h
            x2 = int(bbox[2] * w)
            y2 = int(bbox[3] * h)
            if x2 <= x1 or y2 <= y1:
                continue
            label = _safe_text(obj.get("tipo", "objeto"))
            _desenhar_bbox(img, x1, y1, x2, y2, cor, label, escala)


def _desenhar_ia_overlay(img: np.ndarray, res: dict, em_analise: bool,
                         w: int, h: int, bar_h: int, cor: tuple, escala: float):
    """Painel semitransparente inferior — sempre mostra ultimo resultado detectado."""
    if h < 120:
        return
    if not res and not em_analise:
        return

    linha_h = max(14, int(escala * 30))
    panel_h = bar_h + linha_h * 3 + 10

    y0 = h - panel_h
    roi = img[y0:h, 0:w]
    fundo = np.zeros_like(roi)
    cv2.addWeighted(roi, 0.38, fundo, 0.62, 0, roi)
    img[y0:h, 0:w] = roi

    FS_ST  = max(9, min(12, w // 70))   # status line
    FS_DET = max(8, min(11, w // 80))   # comportamentos
    pil_texts = []
    y = y0 + linha_h

    if not res:
        pil_texts.append(("IA: Aguardando analise...", 6, y, FS_ST, (130, 130, 130), False))
        _pil_render(img, pil_texts, src_rect=(0, y0, w, h))
        return

    nivel  = res.get("nivel_risco", "")
    icone  = {"sem_risco": "OK", "atencao": "!", "suspeito": "!!", "critico": "ALERTA"}.get(nivel, "?")
    conf   = res.get("confianca", 0.0)
    pos    = _safe_text(res.get("posicao_na_cena", ""))
    comps  = res.get("comportamentos_detectados", [])
    fonte  = "IA-Claude" if res.get("fonte") != "local" else "IA-Local"
    upd    = "  ..." if em_analise else ""

    status_txt = f"[{icone}] {nivel.upper()}  {fonte}  {int(conf * 100)}%{upd}"
    pil_texts.append((status_txt, 6, y, FS_ST, cor, True))
    y += linha_h

    max_chars = max(14, w // 7)
    for comp in comps[:2]:
        txt = ("- " + _safe_text(comp))[:max_chars]
        pil_texts.append((txt, 6, y, FS_DET, (210, 210, 210), False))
        y += linha_h

    if pos and w > 200:
        pil_texts.append((">> " + _safe_text(pos)[:max_chars], 6, y,
                           FS_DET, (150, 150, 150), False))

    _pil_render(img, pil_texts, src_rect=(0, y0, w, h))

    bar_w = max(1, int(w * conf))
    cv2.rectangle(img, (0, h - 3), (bar_w, h), cor, -1)
    cv2.rectangle(img, (bar_w, h - 3), (w, h), (30, 30, 30), -1)


def _slot_camera(slot: CameraSlot, w: int, h: int,
                 closeable: bool = False, show_close: bool = False) -> np.ndarray:
    frame = slot.get_frame()
    if frame is None:
        img = np.full((h, w, 3), C_CARD, dtype=np.uint8)
        cv2.putText(img, "Conectando...", (max(4, w // 5), h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, max(0.3, w / 900), C_CINZA, 1)
        return img

    img = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)
    res        = slot.get_resultado()
    deteccoes  = slot.get_deteccoes_locais()
    em_analise = slot.em_analise
    nivel      = res.get("nivel_risco", "")
    cor        = NIVEL_COR.get(nivel, C_CINZA)

    bar_h  = max(16, h // 14)
    escala = max(0.28, min(0.50, w / 640))

    # ── Bounding boxes ────────────────────────────────────────────────────────
    if nivel or deteccoes:
        _desenhar_bboxes(img, res, deteccoes, w, h, cor, bar_h)

    # ── Barra superior ────────────────────────────────────────────────────────
    cv2.rectangle(img, (0, 0), (w, bar_h), (0, 0, 0), -1)
    cv2.putText(img, slot.cfg["id"], (4, bar_h - 4),
                cv2.FONT_HERSHEY_SIMPLEX, escala, C_BRANCO, 1)

    if nivel:
        fonte_tag = "L" if res.get("fonte") == "local" else "C"
        fonte_cor = (100, 180, 255) if fonte_tag == "L" else (80, 200, 80)
        r = max(4, bar_h // 3)
        cv2.circle(img, (w - r - 4, bar_h // 2), r, cor, -1)
        if w > 120:
            etiq = nivel.upper()
            tw = cv2.getTextSize(etiq, cv2.FONT_HERSHEY_SIMPLEX, escala * 0.8, 1)[0][0]
            cv2.putText(img, etiq, (w - r * 2 - tw - 6, bar_h - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, escala * 0.8, cor, 1)
        if w > 80:
            cv2.putText(img, fonte_tag, (4 + cv2.getTextSize(slot.cfg["id"],
                        cv2.FONT_HERSHEY_SIMPLEX, escala, 1)[0][0] + 6, bar_h - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, escala * 0.7, fonte_cor, 1)

    # ── Botão fechar (X) ──────────────────────────────────────────────────────
    if closeable and show_close:
        btn_w = max(24, bar_h + 6)
        cv2.rectangle(img, (w - btn_w, 0), (w, bar_h), (60, 60, 180), -1)
        cv2.rectangle(img, (w - btn_w, 0), (w, bar_h), (100, 100, 220), 1)
        cx = w - btn_w // 2
        cy = bar_h // 2
        sz = max(4, bar_h // 4)
        cv2.line(img, (cx - sz, cy - sz), (cx + sz, cy + sz), (220, 220, 255), 2)
        cv2.line(img, (cx + sz, cy - sz), (cx - sz, cy + sz), (220, 220, 255), 2)

    # ── Overlay IA pensando ───────────────────────────────────────────────────
    if (res or em_analise) and h > 120:
        _desenhar_ia_overlay(img, res, em_analise, w, h, bar_h, cor, escala)

    return img


# ── Cabecalho ─────────────────────────────────────────────────────────────────
def _cabecalho(n_ativas: int, layout: int, win_w: int,
               usuario_nome: str = "", usuario_grupo: str = "",
               api_online: bool = True, hover_api: bool = False) -> np.ndarray:
    img = np.full((HDR_H, win_w, 3), (18, 18, 18), dtype=np.uint8)
    cv2.rectangle(img, (0, HDR_H - 2), (win_w, HDR_H), C_AMARELO, -1)

    # Indicador de status da API (bolinha colorida — clicável para admin)
    api_cor  = (0, 200, 60) if api_online else (0, 60, 220)
    api_txt  = "API OK" if api_online else "API OFF"
    api_tcor = (200, 255, 200) if api_online else (150, 150, 255)
    cx, cy = 175, HDR_H // 2
    if hover_api:
        cv2.rectangle(img, (155, 2), (265, HDR_H - 3), (40, 40, 40), -1)
        cv2.rectangle(img, (155, 2), (265, HDR_H - 3), (70, 70, 70), 1)
    cv2.circle(img, (cx, cy), 5, api_cor, -1)
    cv2.circle(img, (cx, cy), 5, _cor_clara(api_cor, 60), 1)
    atw, ath = _txt_size(api_txt, 9)

    cols, rows = LAYOUTS[layout]
    info = f"{n_ativas} cam  |  {cols}x{rows}  |  {datetime.now().strftime('%H:%M:%S')}"

    pil_texts = []
    pil_texts.append((api_txt, cx + 8, cy - ath // 2, 9, api_tcor, False))
    TITULO_SIZE = 15
    INFO_SIZE   = 11
    BADGE_SIZE  = 11

    # Título
    pil_texts.append(("SPARTA AGENTE IA", 10, (HDR_H - TITULO_SIZE) // 2 - 1,
                       TITULO_SIZE, C_AMARELO, True))

    # Badge de usuário
    if usuario_nome:
        grupo_label = "ADM" if usuario_grupo == "administrador" else "USR"
        badge_cor   = (0, 180, 80) if usuario_grupo == "administrador" else (80, 80, 180)
        badge_txt   = f" {usuario_nome} [{grupo_label}] "
        bw, bh      = _txt_size(badge_txt, BADGE_SIZE, bold=True)
        bx = win_w - bw - 18
        by = (HDR_H - bh) // 2
        cv2.rectangle(img, (bx - 6, by - 3), (bx + bw + 6, by + bh + 3), badge_cor, -1)
        cv2.rectangle(img, (bx - 6, by - 3), (bx + bw + 6, by + bh + 3),
                      _cor_clara(badge_cor, 40), 1)
        pil_texts.append((badge_txt, bx, by, BADGE_SIZE, (255, 255, 255), True))
        iw, ih = _txt_size(info, INFO_SIZE)
        pil_texts.append((info, bx - iw - 16, (HDR_H - ih) // 2, INFO_SIZE, C_CINZA, False))
    else:
        iw, ih = _txt_size(info, INFO_SIZE)
        pil_texts.append((info, win_w - iw - 12, (HDR_H - ih) // 2, INFO_SIZE, C_CINZA, False))

    _pil_render(img, pil_texts)
    return img


# ── Toolbar de layout ─────────────────────────────────────────────────────────
def _toolbar(layout_atual: int, hover_btn: int, win_w: int,
             hover_act_btn: int = -1, is_admin: bool = False,
             cam_slots: set | None = None) -> np.ndarray:
    img = np.full((TOOLBAR_H, win_w, 3), (20, 20, 20), dtype=np.uint8)
    cv2.line(img, (0, 0), (win_w, 0), (45, 45, 45), 1)
    cv2.line(img, (0, TOOLBAR_H - 1), (win_w, TOOLBAR_H - 1), (10, 10, 10), 1)

    BTN_FS = 11  # font size para botões
    pil_texts = []

    cols_c, rows_c = LAYOUTS[layout_atual]
    n_slots_atual = cols_c * rows_c

    # Botoes de layout (esquerda)
    labels = ["1CH", "4CH", "16CH", "32CH"]
    for i, (label, val) in enumerate(zip(labels, LAYOUT_ORDER)):
        x0 = 10 + i * (_TOOLBAR_BTN_W + _TOOLBAR_BTN_GAP)
        x1 = x0 + _TOOLBAR_BTN_W
        y0b, y1b = _TOOLBAR_BTN_Y0, _TOOLBAR_BTN_Y0 + _TOOLBAR_BTN_H
        ativo = val == layout_atual
        hover = (i == hover_btn) and not ativo
        if ativo:
            bg_r = _draw_btn_bg(img, x0, y0b, x1, y1b, C_AMARELO, hover=False)
            fg = C_BG
        else:
            bg_r = _draw_btn_bg(img, x0, y0b, x1, y1b, (45, 45, 45), hover=hover)
            fg = C_BRANCO if hover else C_CINZA
        tw, th = _txt_size(label, BTN_FS, bold=ativo)
        pil_texts.append((label, x0 + (x1 - x0 - tw) // 2, y0b + (y1b - y0b - th) // 2,
                           BTN_FS, fg, ativo))

        # Bolinha verde: câmera existe neste layout mas está fora do layout atual
        if cam_slots and not ativo:
            cols_l, rows_l = LAYOUTS[val]
            n_l = cols_l * rows_l
            # Câmeras visíveis neste layout mas ocultas no layout atual
            tem_oculta = any(n_slots_atual <= s < n_l for s in cam_slots)
            if tem_oculta:
                cx, cy = x1 - 6, y0b + 6
                cv2.circle(img, (cx, cy), 5, (0, 180, 60), -1)
                cv2.circle(img, (cx, cy), 5, (0, 255, 100), 1)

    # Separador
    sep_x = 10 + 4 * (_TOOLBAR_BTN_W + _TOOLBAR_BTN_GAP) + 6
    cv2.line(img, (sep_x, 4), (sep_x, TOOLBAR_H - 4), (55, 55, 55), 1)

    # Botoes de acao (direita)
    action_defs = [
        ("Sair",    (55, 45, 185), (235, 225, 255)),
        ("Treinar", (25, 105, 145),(195, 240, 255)),
    ]
    if is_admin:
        action_defs.append(("Usuarios", (30, 125, 50), (185, 255, 195)))
        action_defs.append(("Backup",   (130, 80, 20), (255, 210, 160)))
        action_defs.append(("Update",   (20, 80, 130), (160, 210, 255)))

    rects = _toolbar_action_rects(win_w, len(action_defs))
    for i, ((label, bg, fg), (x0, y0, x1, y1)) in enumerate(zip(action_defs, rects)):
        _draw_btn_bg(img, x0, y0, x1, y1, bg, hover=(i == hover_act_btn))
        tw, th = _txt_size(label, BTN_FS)
        pil_texts.append((label, x0 + (x1 - x0 - tw) // 2, y0 + (y1 - y0 - th) // 2,
                           BTN_FS, fg, False))

    _pil_render(img, pil_texts)
    return img


# ── Montagem do mosaico ───────────────────────────────────────────────────────
def _montar_mosaico(slots: dict, state: dict) -> np.ndarray:
    layout    = state["layout"]
    expandido = state["expandido"]
    hover     = state["hover"]
    hover_btn = state["hover_btn"]
    win_w     = state["win_w"]
    win_h     = state["win_h"]

    mosaic_w = win_w
    mosaic_h = max(1, win_h - HDR_H - TOOLBAR_H)

    cols, rows = LAYOUTS[layout]
    max_cams   = cols * rows
    slot_w     = max(1, mosaic_w // cols)
    slot_h     = max(1, mosaic_h // rows)

    cab     = _cabecalho(len(slots), layout, win_w,
                         state.get("usuario_nome", ""),
                         state.get("usuario_grupo", ""),
                         api_online=state.get("api_online", True),
                         hover_api=state.get("hover_api", False))
    toolbar = _toolbar(layout, hover_btn, win_w,
                       hover_act_btn=state.get("hover_act_btn", -1),
                       is_admin=(state.get("usuario_grupo") == "administrador"),
                       cam_slots=set(slots.keys()))

    if expandido is not None and expandido in slots:
        video = _slot_camera(slots[expandido], mosaic_w, mosaic_h,
                             closeable=True, show_close=True)
        cv2.putText(video, "Clique para voltar", (10, mosaic_h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, C_CINZA, 1)
    else:
        celulas = []
        for i in range(max_cams):
            if i in slots:
                celulas.append(_slot_camera(slots[i], slot_w, slot_h,
                                            closeable=True, show_close=(i == hover)))
            else:
                celulas.append(_slot_vazio(i, i == hover, slot_w, slot_h))

        linhas = []
        for r in range(rows):
            linha = np.hstack(celulas[r * cols:(r + 1) * cols])
            linhas.append(linha)
        video = np.vstack(linhas)

    frame = np.vstack([cab, toolbar, video])

    if state.get("ctx_menu"):
        frame = _desenhar_ctx_menu(frame, state["ctx_menu"])

    # ── Visual de drag & drop ─────────────────────────────────────────────────
    if state.get("drag_started") and state.get("drag_from") is not None:
        drag_tgt = state.get("drag_target", -1)
        mx, my   = state["drag_x"], state["drag_y"]

        # Highlight no slot alvo
        if drag_tgt >= 0 and expandido is None:
            col_t = drag_tgt % cols
            row_t = drag_tgt // cols
            hx0 = col_t * slot_w
            hy0 = HDR_H + TOOLBAR_H + row_t * slot_h
            hx1 = hx0 + slot_w - 1
            hy1 = hy0 + slot_h - 1
            cv2.rectangle(frame, (hx0, hy0), (hx1, hy1), (0, 200, 255), 3)

        # Miniatura da câmera seguindo o cursor
        src_slot = slots.get(state["drag_from"])
        if src_slot is not None:
            mini_w, mini_h = 160, 90
            mini_frame = src_slot.get_frame()
            if mini_frame is not None:
                mini = cv2.resize(mini_frame, (mini_w, mini_h))
                tx = max(0, min(mx - mini_w // 2, frame.shape[1] - mini_w))
                ty = max(0, min(my - mini_h // 2, frame.shape[0] - mini_h))
                roi = frame[ty:ty+mini_h, tx:tx+mini_w]
                blended = cv2.addWeighted(roi, 0.3, mini, 0.7, 0)
                frame[ty:ty+mini_h, tx:tx+mini_w] = blended
                cv2.rectangle(frame, (tx, ty), (tx+mini_w-1, ty+mini_h-1),
                              (0, 200, 255), 2)
                cam_id = src_slot.cfg.get("id", "")
                cv2.putText(frame, cam_id, (tx+4, ty+mini_h-6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)

    return frame


# ── Persistencia de cameras ────────────────────────────────────────────────────
def _carregar_cameras() -> list:
    if CAMERAS_JSON.exists():
        try:
            return json.loads(CAMERAS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _salvar_cameras(lista: list):
    CAMERAS_JSON.write_text(
        json.dumps(lista, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── Dialogo de adicionar camera ───────────────────────────────────────────────
def _dialogo_adicionar(slot_idx: int, cfg_atual: dict = None) -> dict | None:
    import tkinter as tk
    import queue as _queue
    import threading as _th

    BG2 = "#0F0F0F"; AMA = "#FFD000"; AESC = "#B39200"
    ENT = "#242424"; BCOR = "#F0F0F0"; CESC = "#333333"
    VERDE = "#3DCC7E"; VERM = "#FF4444"

    resultado = []
    fila_ui   = _queue.Queue()   # worker → main thread (thread-safe)

    d = tk.Tk()
    d.title(f"Adicionar Camera — Slot {slot_idx + 1}")
    d.configure(bg=BG2)
    d.resizable(False, False)

    cab2 = tk.Frame(d, bg=AMA, padx=20, pady=10)
    cab2.pack(fill="x")
    tk.Label(cab2, text=f"SPARTA AGENTE IA  —  Slot {slot_idx + 1}",
             font=("Segoe UI", 12, "bold"), bg=AMA, fg=BG2).pack(side="left")

    corpo = tk.Frame(d, bg=BG2, padx=24, pady=14)
    corpo.pack()

    c = cfg_atual or {}

    def _entry(label, ocultar=False, padrao=""):
        tk.Label(corpo, text=label, font=("Segoe UI", 9), bg=BG2, fg=BCOR).pack(anchor="w")
        e = tk.Entry(corpo, show="*" if ocultar else "",
                     font=("Consolas", 10), bg=ENT, fg=BCOR,
                     insertbackground=AMA, relief="flat", bd=0,
                     highlightthickness=1, highlightcolor=AMA,
                     highlightbackground=CESC, width=38)
        e.insert(0, padrao)
        e.pack(fill="x", ipady=5, pady=(2, 8))
        e.bind("<FocusIn>",  lambda ev, w=e: w.config(highlightbackground=AMA))
        e.bind("<FocusOut>", lambda ev, w=e: w.config(highlightbackground=CESC))
        return e

    e_id   = _entry("ID da Camera",           False, c.get("id",      f"CAM-{slot_idx+1:02d}"))
    e_ip   = _entry("IP da Camera",           False, c.get("ip",      "192.168.1.100"))
    e_port = _entry("Porta ONVIF",            False, c.get("porta",   "80"))
    e_user = _entry("Usuário",                False, c.get("usuario", "admin"))
    e_pw   = _entry("Senha",                  True,  c.get("senha",   ""))
    e_ch   = _entry("Canal (1, 2, 3...)",     False, str(c.get("canal", "1")))

    tk.Frame(corpo, bg="#333333", height=1).pack(fill="x", pady=(4, 8))
    tk.Label(corpo, text="URI RTSP manual (opcional — substitui descoberta ONVIF)",
             font=("Segoe UI", 8), bg=BG2, fg="#888888").pack(anchor="w")
    e_rtsp = tk.Entry(corpo, font=("Consolas", 9), bg=ENT, fg=BCOR,
                      insertbackground=AMA, relief="flat", bd=0,
                      highlightthickness=1, highlightcolor=AMA,
                      highlightbackground=CESC, width=38)
    e_rtsp.insert(0, c.get("rtsp_uri", ""))
    e_rtsp.pack(fill="x", ipady=4, pady=(2, 10))
    e_rtsp.bind("<FocusIn>",  lambda ev: e_rtsp.config(highlightbackground=AMA))
    e_rtsp.bind("<FocusOut>", lambda ev: e_rtsp.config(highlightbackground=CESC))

    lbl_status = tk.Label(corpo, text="", font=("Segoe UI", 8),
                          bg=BG2, fg=VERM, wraplength=320, justify="left")
    lbl_status.pack(anchor="w", pady=(0, 4))

    btn = tk.Label(corpo, text="  Conectar e Adicionar  ",
                   font=("Segoe UI", 10, "bold"),
                   bg=AMA, fg=BG2, padx=14, pady=9, cursor="hand2")
    btn.bind("<Enter>", lambda _: btn.config(bg=AESC))
    btn.bind("<Leave>", lambda _: btn.config(bg=AMA))
    btn.pack(fill="x", pady=(2, 0))

    _ocupado = [False]

    def _set_status(msg, cor=None):
        """Atualiza label de status — sempre na main thread via fila."""
        fila_ui.put(("status", msg, cor or VERM))

    def _worker(cfg_cam, uri_manual):
        try:
            if uri_manual:
                uri = uri_manual
            else:
                _set_status("Conectando via ONVIF...", AMA)
                from video_capture import _descobrir_rtsp
                canal = int(cfg_cam.get("canal") or "1")
                uri = _descobrir_rtsp(
                    cfg_cam["ip"], int(cfg_cam["porta"]),
                    cfg_cam["usuario"], cfg_cam["senha"],
                    canal=canal,
                )

            _set_status("Testando stream RTSP...", AMA)
            cap = cv2.VideoCapture(uri)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 6000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 6000)
            ok = cap.isOpened()
            cap.release()
            if not ok:
                raise RuntimeError("Stream não abriu. Verifique URI e credenciais.")

            cfg_cam["rtsp_uri"] = uri
            resultado.append(cfg_cam)
            fila_ui.put(("ok",))
        except Exception as exc:
            fila_ui.put(("erro", str(exc)[:150]))

    def _iniciar():
        if _ocupado[0]:
            return
        uri_manual = e_rtsp.get().strip()
        cfg_cam = {
            "id":      e_id.get().strip()   or f"CAM-{slot_idx+1:02d}",
            "ip":      e_ip.get().strip(),
            "porta":   e_port.get().strip() or "80",
            "usuario": e_user.get().strip(),
            "senha":   e_pw.get().strip(),
            "canal":   e_ch.get().strip()   or "1",
        }
        if not cfg_cam["ip"] and not uri_manual:
            lbl_status.config(text="Informe o IP ou uma URI RTSP manual.", fg=VERM)
            return
        _ocupado[0] = True
        btn.config(bg="#666600")
        lbl_status.config(text="Aguarde...", fg=AMA)
        _th.Thread(target=_worker, args=(cfg_cam, uri_manual), daemon=True).start()

    btn.bind("<Button-1>", lambda _: _iniciar())

    d.update_idletasks()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    ww, wh = d.winfo_reqwidth(), d.winfo_reqheight()
    d.geometry(f"+{(sw-ww)//2}+{(sh-wh)//2}")

    while True:
        try:
            if not d.winfo_exists():
                break
            while not fila_ui.empty():
                msg = fila_ui.get_nowait()
                if msg[0] == "status":
                    lbl_status.config(text=msg[1], fg=msg[2])
                elif msg[0] == "ok":
                    lbl_status.config(text="Conectado!", fg=VERDE)
                    d.after(500, d.destroy)
                elif msg[0] == "erro":
                    lbl_status.config(text=f"Erro: {msg[1]}", fg=VERM)
                    _ocupado[0] = False
                    btn.config(bg=AMA)
            d.update()
        except Exception:
            break

    return resultado[0] if resultado else None


# ── Menu de contexto OpenCV ───────────────────────────────────────────────────

def _ctx_itens(slot_idx: int, slots: dict) -> list:
    if slot_idx in slots:
        cam_id = slots[slot_idx].cfg["id"]
        return [
            {"label": cam_id,                "action": None,         "header": True},
            {"sep": True},
            {"label": "Abrir em tela cheia", "action": "expandir"},
            {"label": "Reiniciar conexao",   "action": "reiniciar"},
            {"sep": True},
            {"label": "Renomear camera",     "action": "renomear"},
            {"label": "Configurar camera",   "action": "configurar"},
            {"sep": True},
            {"label": "Fechar camera",       "action": "fechar",     "danger": True},
        ]
    return [{"label": "Adicionar camera", "action": "adicionar"}]


def _ctx_geometry(ctx: dict, iw: int, ih: int):
    """Retorna (x0, y0, total_h) do menu de contexto."""
    total_h = CTX_PAD_V
    for item in ctx["items"]:
        total_h += CTX_SEP_H if item.get("sep") else CTX_ITEM_H
    total_h += CTX_PAD_V
    x0 = min(ctx["mx"], iw - CTX_W - 2)
    y0 = min(ctx["my"], ih - total_h - 2)
    return x0, y0, total_h


def _ctx_hit(ctx: dict, x: int, y: int, iw: int, ih: int) -> int:
    """Retorna índice do item clicável em (x,y) ou -1."""
    x0, y0, _ = _ctx_geometry(ctx, iw, ih)
    if not (x0 <= x <= x0 + CTX_W):
        return -1
    cy = y0 + CTX_PAD_V
    for i, item in enumerate(ctx["items"]):
        if item.get("sep"):
            cy += CTX_SEP_H
            continue
        if cy <= y < cy + CTX_ITEM_H and not item.get("header"):
            return i
        cy += CTX_ITEM_H
    return -1


def _ctx_inside(ctx: dict, x: int, y: int, iw: int, ih: int) -> bool:
    x0, y0, total_h = _ctx_geometry(ctx, iw, ih)
    return x0 <= x <= x0 + CTX_W and y0 <= y <= y0 + total_h


def _desenhar_ctx_menu(img: np.ndarray, ctx: dict) -> np.ndarray:
    iw, ih = img.shape[1], img.shape[0]
    x0, y0, total_h = _ctx_geometry(ctx, iw, ih)
    x1 = x0 + CTX_W
    y1 = y0 + total_h
    hover = ctx.get("hover", -1)

    # Sombra
    cv2.rectangle(img, (x0 + 4, y0 + 4), (x1 + 4, y1 + 4), (0, 0, 0), -1)
    # Fundo
    cv2.rectangle(img, (x0, y0), (x1, y1), (28, 28, 28), -1)
    cv2.rectangle(img, (x0, y0), (x1, y1), (75, 75, 75), 1)

    cy = y0 + CTX_PAD_V
    for i, item in enumerate(ctx["items"]):
        if item.get("sep"):
            mid = cy + CTX_SEP_H // 2
            cv2.line(img, (x0 + 8, mid), (x1 - 8, mid), (65, 65, 65), 1)
            cy += CTX_SEP_H
            continue

        iy1 = cy + CTX_ITEM_H
        if item.get("header"):
            cv2.putText(img, item["label"], (x0 + CTX_PAD_H, cy + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, C_AMARELO, 1)
        else:
            if i == hover:
                bg = (35, 18, 18) if item.get("danger") else (45, 45, 12)
                cv2.rectangle(img, (x0 + 1, cy), (x1 - 1, iy1), bg, -1)
            cor = (80, 80, 230) if item.get("danger") else (210, 210, 210)
            if i == hover:
                cor = (60, 60, 255) if item.get("danger") else C_AMARELO
            cv2.putText(img, item["label"], (x0 + CTX_PAD_H, cy + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, cor, 1)
        cy = iy1

    return img


# ── Loop principal ────────────────────────────────────────────────────────────
def rodar_mosaico(cfg_principal, sessao: dict = None, intervalo_ia: int = 3):
    import auth as _auth
    _admin = _auth.eh_admin(sessao)
    _usuario_nome = sessao["nome"] if sessao else "—"
    _usuario_grupo = sessao["grupo"] if sessao else "usuario"

    slots: dict[int, CameraSlot] = {}
    fila  = FilaAnalise(intervalo=intervalo_ia)

    # Estado compartilhado entre main loop e callback de mouse
    state = {
        "layout":        4,
        "expandido":     None,
        "hover":         -1,
        "hover_btn":     -1,
        "hover_act_btn": -1,
        "req_action":    None,
        "win_w":         WIN_W,
        "win_h":         WIN_H,
        "ctx_menu":      None,
        "usuario_nome":  _usuario_nome,
        "usuario_grupo": _usuario_grupo,
        "api_online":    True,
        "hover_api":     False,   # mouse sobre indicador API no cabeçalho
        # Drag & drop
        "drag_from":     None,   # slot_idx sendo arrastado
        "drag_sx":       0,      # mouse X no inicio do drag
        "drag_sy":       0,      # mouse Y no inicio do drag
        "drag_x":        0,      # posição atual do mouse durante drag
        "drag_y":        0,
        "drag_started":  False,  # True após mover > threshold
        "drag_target":   -1,     # slot sob o cursor durante drag
    }

    def _adicionar_slot(idx: int, cfg_cam: dict):
        slot = CameraSlot(idx, cfg_cam)
        slot.iniciar(cfg_cam["rtsp_uri"])
        slots[idx] = slot

    def _salvar_todos():
        _salvar_cameras([{**s.cfg, "slot_idx": i} for i, s in slots.items()])

    # Restaura câmeras salvas na sessão anterior
    for cam_cfg in _carregar_cameras():
        idx = cam_cfg.get("slot_idx", 0)
        if idx not in slots:
            _adicionar_slot(idx, cam_cfg)
            log.info("Camera restaurada: %s -> slot %d", cam_cfg.get("id"), idx)

    frame_idx: dict[int, int] = {}

    cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN_NAME, WIN_W, WIN_H)

    # Cursor seta — carregado uma vez e aplicado no callback do mouse
    try:
        import ctypes as _ct
        _arrow_cursor = _ct.windll.user32.LoadCursorW(0, 32512)  # IDC_ARROW
    except Exception:
        _arrow_cursor = None

    def _btn_index_at(x: int) -> int:
        for i in range(len(LAYOUT_ORDER)):
            x0 = 10 + i * (_TOOLBAR_BTN_W + _TOOLBAR_BTN_GAP)
            x1 = x0 + _TOOLBAR_BTN_W
            if x0 <= x <= x1:
                return i
        return -1

    def _slot_index_at(x: int, y: int) -> int:
        vy = y - HDR_H - TOOLBAR_H
        if vy < 0:
            return -1
        win_w = state["win_w"]
        win_h = state["win_h"]
        mosaic_w = win_w
        mosaic_h = max(1, win_h - HDR_H - TOOLBAR_H)
        cols, rows = LAYOUTS[state["layout"]]
        slot_w = max(1, mosaic_w // cols)
        slot_h = max(1, mosaic_h // rows)
        col = x // slot_w
        row = vy // slot_h
        if 0 <= col < cols and 0 <= row < rows:
            return row * cols + col
        return -1

    def _hit_close_btn(x: int, y: int, slot_idx: int) -> bool:
        """Retorna True se (x,y) está sobre o botão X do slot_idx na grade."""
        win_w = state["win_w"]
        win_h = state["win_h"]
        mosaic_h = max(1, win_h - HDR_H - TOOLBAR_H)
        cols, rows = LAYOUTS[state["layout"]]
        slot_w = max(1, win_w // cols)
        slot_h = max(1, mosaic_h // rows)
        row = slot_idx // cols
        col = slot_idx % cols
        rx  = (col + 1) * slot_w          # borda direita do slot
        ty  = HDR_H + TOOLBAR_H + row * slot_h
        bar_h = max(16, slot_h // 14)
        zone  = max(32, bar_h + 8)        # zona de clique generosa
        hit = (rx - zone) <= x <= rx and ty <= y <= (ty + bar_h)
        log.debug("hit_close slot=%d x=%d y=%d rx=%d ty=%d bar_h=%d zone=%d → %s",
                  slot_idx, x, y, rx, ty, bar_h, zone, hit)
        return hit

    def _hit_close_btn_expandido(x: int, y: int) -> bool:
        """Retorna True se (x,y) está sobre o botão X na visão expandida."""
        win_w = state["win_w"]
        win_h = state["win_h"]
        mosaic_h = max(1, win_h - HDR_H - TOOLBAR_H)
        bar_h = max(16, mosaic_h // 14)
        btn_w = max(24, bar_h + 6)
        wy0 = HDR_H + TOOLBAR_H
        return (win_w - btn_w) <= x <= win_w and wy0 <= y <= (wy0 + bar_h)

    def _remover_slot(idx: int):
        if idx not in slots:
            return
        slot = slots.pop(idx)
        _salvar_todos()
        log.info("Camera removida do slot %d", idx)
        threading.Thread(target=slot.parar, daemon=True).start()

    def _executar_acao(slot_idx: int, action: str):
        if action == "expandir":
            state["expandido"] = slot_idx

        elif action == "reiniciar":
            s = slots.get(slot_idx)
            if s:
                cfg_bkp = dict(s.cfg)
                s.parar()
                time.sleep(0.3)
                novo = CameraSlot(slot_idx, cfg_bkp)
                novo.iniciar(cfg_bkp["rtsp_uri"])
                slots[slot_idx] = novo
                log.info("Conexao reiniciada: slot %d", slot_idx)

        elif action == "renomear":
            s = slots.get(slot_idx)
            if s:
                import tkinter as tk
                from tkinter import simpledialog
                r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
                novo = simpledialog.askstring(
                    "Renomear Camera", "Novo nome:",
                    initialvalue=s.cfg["id"], parent=r
                )
                r.destroy()
                if novo and novo.strip():
                    s.cfg["id"] = novo.strip()
                    _salvar_todos()
                    log.info("Camera renomeada: %s", novo.strip())

        elif action == "configurar":
            s = slots.get(slot_idx)
            if s:
                cfg_novo = _dialogo_adicionar(slot_idx, cfg_atual=s.cfg)
                if cfg_novo:
                    s.parar()
                    cfg_novo["slot_idx"] = slot_idx
                    novo = CameraSlot(slot_idx, cfg_novo)
                    novo.iniciar(cfg_novo["rtsp_uri"])
                    slots[slot_idx] = novo
                    _salvar_todos()
                    log.info("Camera reconfigurada: slot %d", slot_idx)

        elif action == "fechar":
            if state["expandido"] == slot_idx:
                state["expandido"] = None
            _remover_slot(slot_idx)

        elif action == "adicionar":
            _abrir_dialogo(slot_idx)

    def on_mouse(event, x, y, flags, param):
        if _arrow_cursor:
            try:
                import ctypes as _ct
                _ct.windll.user32.SetCursor(_arrow_cursor)
            except Exception:
                pass

        iw = state["win_w"]; ih = state["win_h"]

        # ── Menu de contexto aberto — tratar primeiro ─────────────────────────
        if state["ctx_menu"] is not None:
            ctx = state["ctx_menu"]
            if event == cv2.EVENT_MOUSEMOVE:
                ctx["hover"] = _ctx_hit(ctx, x, y, iw, ih)
                return
            if event == cv2.EVENT_LBUTTONDOWN:
                hit = _ctx_hit(ctx, x, y, iw, ih)
                slot_idx = ctx["slot_idx"]
                state["ctx_menu"] = None
                if hit >= 0:
                    action = ctx["items"][hit].get("action")
                    if action:
                        _executar_acao(slot_idx, action)
                return
            if event in (cv2.EVENT_RBUTTONDOWN, cv2.EVENT_MBUTTONDOWN):
                state["ctx_menu"] = None
                return
            return

        # Cabecalho — clique no indicador API abre painel (somente admin)
        if y < HDR_H:
            state["hover"]     = -1
            state["hover_btn"] = -1
            state["hover_api"] = _admin and 155 <= x <= 265
            if event == cv2.EVENT_LBUTTONDOWN and _admin and 155 <= x <= 265:
                _panel_pendente[0] = "api"
            return
        state["hover_api"] = False

        # Toolbar
        if y < HDR_H + TOOLBAR_H:
            state["hover"] = -1
            bi = _btn_index_at(x)
            _n_act = 5 if state.get("usuario_grupo") == "administrador" else 2
            act_rects = _toolbar_action_rects(state["win_w"], _n_act)
            ai = -1
            for _i, (ax0, _ay0, ax1, _ay1) in enumerate(act_rects):
                if ax0 <= x <= ax1:
                    ai = _i
                    break
            state["hover_btn"]     = bi if ai < 0 else -1
            state["hover_act_btn"] = ai
            if event == cv2.EVENT_LBUTTONDOWN:
                if bi >= 0:
                    novo_layout = LAYOUT_ORDER[bi]
                    if state["layout"] != novo_layout:
                        state["layout"]    = novo_layout
                        state["expandido"] = None
                        log.info("Layout alterado para %dCH", novo_layout)
                elif ai >= 0:
                    state["req_action"] = ai
            return

        state["hover_btn"] = -1

        # Area de video — modo expandido
        if state["expandido"] is not None:
            state["hover"] = -1
            if event == cv2.EVENT_RBUTTONDOWN:
                state["ctx_menu"] = {
                    "slot_idx": state["expandido"],
                    "mx": x, "my": y, "hover": -1,
                    "items": _ctx_itens(state["expandido"], slots),
                }
                return
            if event == cv2.EVENT_LBUTTONDOWN:
                exp = state["expandido"]
                if _hit_close_btn_expandido(x, y) and exp != 0:
                    state["expandido"] = None
                    _remover_slot(exp)
                else:
                    state["expandido"] = None
            return

        # Area de video — grade
        idx = _slot_index_at(x, y)
        state["hover"] = idx

        if event == cv2.EVENT_RBUTTONDOWN and idx >= 0 and _admin:
            state["ctx_menu"] = {
                "slot_idx": idx,
                "mx": x, "my": y, "hover": -1,
                "items": _ctx_itens(idx, slots),
            }
            return

        # Drag em andamento — atualizar posição e alvo
        if event == cv2.EVENT_MOUSEMOVE and state["drag_from"] is not None:
            state["drag_x"] = x
            state["drag_y"] = y
            dx = abs(x - state["drag_sx"])
            dy = abs(y - state["drag_sy"])
            if dx > 8 or dy > 8:
                state["drag_started"] = True
            state["drag_target"] = idx if state["drag_started"] else -1
            return

        # Soltar drag
        if event == cv2.EVENT_LBUTTONUP and state["drag_from"] is not None:
            src     = state["drag_from"]
            dst     = state["drag_target"]
            started = state["drag_started"]
            state["drag_from"]    = None
            state["drag_started"] = False
            state["drag_target"]  = -1
            if started and dst >= 0 and dst != src:
                slot_src = slots.get(src)
                slot_dst = slots.get(dst)
                if slot_src:
                    if slot_dst:
                        slots[src] = slot_dst
                        slots[dst] = slot_src
                    else:
                        slots[dst] = slot_src
                        del slots[src]
                    _salvar_todos()
                    log.info("Camera movida (drag): slot %d -> %d", src, dst)
            elif not started and src in slots:
                hit_x = _hit_close_btn(x, y, src)
                if hit_x:
                    if _admin:
                        _remover_slot(src)
                else:
                    state["expandido"] = src
                    log.info("Slot %d expandido", src)
            return

        if event == cv2.EVENT_LBUTTONDOWN and idx >= 0:
            if idx in slots:
                hit_x = _hit_close_btn(x, y, idx)
                if hit_x:
                    if _admin:
                        _remover_slot(idx)
                else:
                    # Inicia drag (confirma movimento depois)
                    state["drag_from"]   = idx
                    state["drag_sx"]     = x
                    state["drag_sy"]     = y
                    state["drag_x"]      = x
                    state["drag_y"]      = y
                    state["drag_started"] = False
                    state["drag_target"] = -1
            else:
                if _admin:
                    _abrir_dialogo(idx)

    def _abrir_dialogo(slot_idx: int):
        cfg_cam = _dialogo_adicionar(slot_idx)
        if cfg_cam:
            cfg_cam["slot_idx"] = slot_idx
            _adicionar_slot(slot_idx, cfg_cam)
            _salvar_todos()
            log.info("Camera adicionada no slot %d: %s", slot_idx, cfg_cam["id"])

    cv2.setMouseCallback(WIN_NAME, on_mouse)
    log.info("Mosaico iniciado. Q=encerrar | P=perfil | T=treinamento | U=usuarios (admin)")

    # Painel pendente: abre direto na thread principal para evitar Tcl_AsyncDelete
    _panel_pendente: list = [None]  # ["treinar"|"usuarios"|"backup"|"update"|"perfil"]

    def _abrir_panel(nome: str):
        """Abre painel Tkinter na thread principal (entre frames do OpenCV)."""
        import gc
        if nome == "treinar":
            from training_tab import abrir_training
            abrir_training()
        elif nome == "usuarios":
            from usuarios_panel import abrir_usuarios_panel
            abrir_usuarios_panel(sessao)
        elif nome == "backup":
            from backup_panel import abrir_backup_panel, precisa_recarregar_cameras
            abrir_backup_panel(sessao=sessao)
            if precisa_recarregar_cameras():
                log.info("Restauração detectada — recarregando câmeras do cameras.json...")
                for slot in list(slots.values()):
                    slot.parar()
                slots.clear()
                for cam_cfg in _carregar_cameras():
                    idx = cam_cfg.get("slot_idx", 0)
                    if idx not in slots:
                        _adicionar_slot(idx, cam_cfg)
                        log.info("Camera restaurada: %s -> slot %d",
                                 cam_cfg.get("id"), idx)
        elif nome == "update":
            from auto_updater import abrir_dialog_update
            abrir_dialog_update()
        elif nome == "perfil":
            from perfil_panel import abrir_perfil_panel
            abrir_perfil_panel(sessao)
        elif nome == "api":
            from api_panel import abrir_api_panel
            abrir_api_panel(api_online=_api_online)
        gc.collect()
        # Restaura callback do mouse (Tkinter pode ter alterado foco)
        try:
            cv2.setMouseCallback(WIN_NAME, on_mouse)
        except Exception:
            pass

    try:
        while True:
            # Atualiza dimensoes reais da janela (suporta maximizar / redimensionar)
            rect = cv2.getWindowImageRect(WIN_NAME)
            if rect[2] > 0 and rect[3] > 0:
                state["win_w"] = rect[2]
                state["win_h"] = rect[3]

            for idx, slot in list(slots.items()):
                frame = slot.get_frame()
                if frame is not None:
                    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
                    fid = f"{slot.cfg['id']}_{ts}_{frame_idx.get(idx, 0):04d}"
                    frame_idx[idx] = frame_idx.get(idx, 0) + 1
                    fila.enfileirar(slot, fid, frame)

            # Processa acao solicitada pelos botoes da toolbar
            if state["req_action"] is not None:
                ai = state["req_action"]
                state["req_action"] = None
                _acoes = ["sair", "treinar"] + (
                    ["usuarios", "backup", "update"] if _admin else []
                )
                acao = _acoes[ai] if ai < len(_acoes) else None
                if acao == "sair":
                    break
                elif acao in ("treinar", "usuarios", "backup", "update"):
                    _panel_pendente[0] = acao

            state["api_online"] = _api_online
            mosaico = _montar_mosaico(slots, state)
            cv2.imshow(WIN_NAME, mosaico)

            key = cv2.waitKey(33) & 0xFF  # ~30fps

            if cv2.getWindowProperty(WIN_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("q"):
                break
            elif key == 27:
                if state["expandido"] is not None:
                    state["expandido"] = None
                else:
                    break
            elif key in (ord("t"), ord("T")) and _admin:
                _panel_pendente[0] = "treinar"
            elif key in (ord("u"), ord("U")) and _admin:
                _panel_pendente[0] = "usuarios"
            elif key in (ord("p"), ord("P")) and sessao:
                _panel_pendente[0] = "perfil"

            # Abre painel pendente na thread principal (evita Tcl_AsyncDelete)
            if _panel_pendente[0] is not None:
                nome = _panel_pendente[0]
                _panel_pendente[0] = None
                _abrir_panel(nome)

    finally:
        for slot in slots.values():
            slot.parar()
        cv2.destroyAllWindows()
        log.info("Mosaico encerrado.")
