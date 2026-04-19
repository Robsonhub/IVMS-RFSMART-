"""
Analisador comportamental local — SPARTA AGENTE IA
Detecta comportamentos suspeitos usando apenas OpenCV (sem internet).
Cada câmera tem sua própria instância para manter estado independente.
Calibra-se automaticamente a partir dos resultados históricos do Claude.
"""
import logging
import threading
from collections import deque
from datetime import datetime, timezone

import cv2
import numpy as np

log = logging.getLogger(__name__)

# ── Thresholds padrão (ajustados pelo calibrator.py) ──────────────────────────
THRESHOLDS_PADRAO = {
    "motion_atencao":          0.03,   # fração da imagem em movimento
    "motion_suspeito":         0.07,
    "motion_critico":          0.14,
    "tapete_motion_suspeito":  0.05,   # movimento na zona do tapete
    "optical_flow_rapido":     3.5,    # magnitude média do fluxo óptico (gestos bruscos)
    "bbox_agachamento":        1.35,   # razão h/w abaixo disso = agachamento/curvamento
    "frames_parado_alerta":    150,    # frames sem movimento (~30s estimados)
    "max_pessoas":             1,
    # Zonas relativas (x1, y1, x2, y2) em fração da imagem — configuráveis
    "zona_tapete":             (0.05, 0.50, 0.95, 0.98),
    "zona_corpo_superior":     (0.05, 0.00, 0.95, 0.55),
}


class AnalisadorLocal:
    """
    Detecta comportamentos suspeitos frame a frame usando OpenCV puro.
    Thread-safe. Uma instância por câmera para estado independente.
    """

    def __init__(self, camera_id: str = "?"):
        self.camera_id    = camera_id
        self._lock        = threading.Lock()
        self.thresholds   = dict(THRESHOLDS_PADRAO)

        # Background subtraction — aprende o ambiente ao longo do tempo
        self._bg = cv2.createBackgroundSubtractorMOG2(
            history=500, varThreshold=40, detectShadows=True
        )

        # HOG person detector (incluso no OpenCV, sem modelo externo)
        self._hog = cv2.HOGDescriptor()
        self._hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

        # Estado temporal por câmera
        self._historico_motion  = deque(maxlen=30)
        self._historico_pessoas = deque(maxlen=10)
        self._historico_bbox    = deque(maxlen=15)
        self._frames_parado     = 0
        self._frame_count       = 0
        self._prev_gray_roi     = None   # para optical flow

        # Dispara calibração inicial assíncrona
        threading.Thread(target=self._calibrar, daemon=True).start()

    # ── Calibração ────────────────────────────────────────────────────────────

    def _calibrar(self):
        """Ajusta thresholds com base no histórico do Claude no banco."""
        try:
            import db
            from calibrator import calcular_thresholds
            novos = calcular_thresholds(db.get_connection(), self.camera_id)
            if novos:
                with self._lock:
                    self.thresholds.update(novos)
                log.info("[%s] Thresholds locais calibrados: %s",
                         self.camera_id, novos)
        except Exception as exc:
            log.debug("[%s] Calibração local ignorada: %s", self.camera_id, exc)

    def recalibrar(self):
        """Chamada externamente após novos feedbacks do admin."""
        threading.Thread(target=self._calibrar, daemon=True).start()

    # ── Análise principal ─────────────────────────────────────────────────────

    def analisar(self, frame, frame_id: str = "") -> dict:
        with self._lock:
            return self._analisar(frame, frame_id)

    def _analisar(self, frame, frame_id: str) -> dict:
        self._frame_count += 1
        h, w = frame.shape[:2]
        thr  = self.thresholds

        # ── 1. Background subtraction — movimento geral ───────────────────────
        fg         = self._bg.apply(frame)
        fg_bin     = (fg > 200).astype(np.uint8)      # ignora sombras (127-200)
        motion_ratio = float(fg_bin.sum()) / (h * w)
        self._historico_motion.append(motion_ratio)
        avg_motion   = float(np.mean(self._historico_motion))

        # ── 2. Movimento na zona do tapete ────────────────────────────────────
        zt  = thr["zona_tapete"]
        tx1 = int(zt[0] * w);  ty1 = int(zt[1] * h)
        tx2 = int(zt[2] * w);  ty2 = int(zt[3] * h)
        roi_tapete   = fg_bin[ty1:ty2, tx1:tx2]
        tapete_ratio = float(roi_tapete.sum()) / max(roi_tapete.size, 1)

        # ── 3. Detecção de pessoas (HOG — a cada 5 frames para performance) ───
        if self._frame_count % 5 == 0:
            small  = cv2.resize(frame, (320, 240))
            sx, sy = w / 320.0, h / 240.0
            p_small, _ = self._hog.detectMultiScale(
                small, winStride=(8, 8), padding=(4, 4), scale=1.05
            )
            pessoas = [(int(px*sx), int(py*sy), int(pw*sx), int(ph*sy))
                       for (px, py, pw, ph) in p_small]
            self._historico_pessoas.append(pessoas)
        else:
            pessoas = list(self._historico_pessoas[-1]) \
                      if self._historico_pessoas else []

        n_pessoas = len(pessoas)

        # ── 4. Análise de postura — razão h/w do bounding box ─────────────────
        agachado = False
        if pessoas:
            px, py, pw, ph = pessoas[0]
            ratio_hbbox = ph / max(pw, 1)
            self._historico_bbox.append(ratio_hbbox)
            agachado = ratio_hbbox < thr["bbox_agachamento"]

        # ── 5. Rastreamento de imobilidade ────────────────────────────────────
        if avg_motion < 0.004:
            self._frames_parado += 1
        else:
            self._frames_parado = max(0, self._frames_parado - 5)

        # ── 6. Optical flow — gestos bruscos de mãos (a cada 3 frames) ────────
        flow_magnitude = 0.0
        if pessoas and self._frame_count % 3 == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            zs   = thr["zona_corpo_superior"]
            rx1  = int(zs[0] * w); ry1 = int(zs[1] * h)
            rx2  = int(zs[2] * w); ry2 = int(zs[3] * h)
            roi_gray = gray[ry1:ry2, rx1:rx2]
            if (self._prev_gray_roi is not None
                    and self._prev_gray_roi.shape == roi_gray.shape):
                flow = cv2.calcOpticalFlowFarneback(
                    self._prev_gray_roi, roi_gray, None,
                    0.5, 3, 15, 3, 5, 1.2, 0
                )
                mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                flow_magnitude = float(np.mean(mag))
            self._prev_gray_roi = roi_gray

        # ── 7. Motor de regras comportamentais ────────────────────────────────
        eventos   = []
        nivel     = "sem_risco"
        alerta    = False
        confianca = 0.50
        acao      = "Monitoramento normal"

        ORDEM = ["sem_risco", "atencao", "suspeito", "critico"]

        def _elevar(novo, conf=0.0):
            nonlocal nivel, confianca
            if ORDEM.index(novo) > ORDEM.index(nivel):
                nivel = novo
            confianca = min(0.93, confianca + conf)

        # Regra 1 — múltiplas pessoas
        if n_pessoas > thr.get("max_pessoas", 1):
            eventos.append(f"{n_pessoas} pessoas detectadas na area restrita")
            _elevar("critico", 0.28)
            alerta = True
            acao   = "Acionar supervisor — segunda pessoa detectada"

        # Regra 2 — movimento geral
        if motion_ratio > thr["motion_critico"]:
            eventos.append("Agitacao intensa na cena")
            _elevar("critico", 0.18)
        elif motion_ratio > thr["motion_suspeito"]:
            eventos.append("Nivel de movimento suspeito")
            _elevar("suspeito", 0.12)
        elif motion_ratio > thr["motion_atencao"]:
            eventos.append("Variacao de movimento acima do padrao")
            _elevar("atencao", 0.06)

        # Regra 3 — movimento na zona do tapete
        if tapete_ratio > thr["tapete_motion_suspeito"]:
            eventos.append("Atividade detectada na zona do tapete de ouro")
            _elevar("suspeito", 0.14)

        # Regra 4 — postura de agachamento
        if agachado and n_pessoas > 0:
            eventos.append("Postura de agachamento / curvamento detectada")
            _elevar("suspeito", 0.10)

        # Regra 5 — gestos bruscos de mãos
        if flow_magnitude > thr["optical_flow_rapido"]:
            eventos.append(f"Movimento rapido de maos (intensidade {flow_magnitude:.1f})")
            _elevar("suspeito", 0.09)

        # Regra 6 — imobilidade prolongada sobre o tapete
        seg_parado = self._frames_parado / max(self._frame_count, 1) * self._frame_count / 5
        if self._frames_parado > thr["frames_parado_alerta"]:
            eventos.append(f"Operador parado sem movimentacao ha tempo prolongado")
            _elevar("atencao", 0.06)

        if not eventos:
            eventos.append("Cena dentro do padrao esperado")
            confianca = 0.60

        if nivel in ("suspeito", "critico"):
            alerta = True
            if acao == "Monitoramento normal":
                acao = "Revisar gravacao — comportamento suspeito detectado"

        return {
            "alerta":                    alerta,
            "nivel_risco":               nivel,
            "comportamentos_detectados": eventos,
            "posicao_na_cena":           f"{n_pessoas} pessoa(s) na cena",
            "acao_recomendada":          acao,
            "revisar_clip":              alerta,
            "janela_revisao_segundos":   30 if alerta else 0,
            "confianca":                 round(confianca, 2),
            "timestamp_analise":         datetime.now(timezone.utc).isoformat(),
            "frame_id":                  frame_id,
            "fonte":                     "local",   # distingue de "claude"
        }
