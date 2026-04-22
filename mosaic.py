"""
Mosaico de cameras - SPARTA AGENTE IA
Suporte a layouts 1CH / 4CH / 16CH / 32CH, expansao de slot e analise IA compartilhada.
"""
import json
import logging
import math
import queue
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

# Limita OpenCV a 1 thread interno — soma aos flags `threads;1` do ffmpeg e
# evita contenção de GIL com httpx (Claude API) durante cap.read().
cv2.setNumThreads(1)

try:
    from PIL import Image as _PilImg, ImageDraw as _PilDraw, ImageFont as _PilFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from camera_slot import CameraSlot, _mesclar_bboxes
from mosaic_constants import (
    MOSAIC_W, MOSAIC_H, HDR_H, TOOLBAR_H, WIN_W, WIN_H, WIN_NAME,
    CAP_W, CAP_H, LAYOUTS, LAYOUT_ORDER,
    CTX_W, CTX_ITEM_H, CTX_SEP_H, CTX_PAD_V, CTX_PAD_H,
    _TOOLBAR_BTN_W, _TOOLBAR_BTN_H, _TOOLBAR_BTN_GAP, _TOOLBAR_BTN_Y0,
    _ACT_BTN_W, _ACT_BTN_GAP, _MENU_BTN_W, _MENU_DROP_W,
    _MENU_DROP_ITH, _MENU_DROP_PAD_V, _MENU_DROP_PAD_H,
    C_BG, C_CARD, C_AMARELO, C_OURO2, C_BRANCO, C_CINZA,
    C_VERDE, C_VERM, C_LARAN, C_AZUL, NIVEL_COR, CAMERAS_JSON,
)

# ── Logo da empresa ────────────────────────────────────────────────────────────
_LOGO_PATH  = next(
    (p for p in [
        Path(__file__).parent / "assets" / "logo_dark.png",
        Path(__file__).parent / "assets" / "logo_dark.png.png",
    ] if p.exists()),
    Path(__file__).parent / "assets" / "logo_dark.png",
)
_logo_cache: np.ndarray | None = None

def _carregar_logo(altura: int) -> np.ndarray | None:
    """Carrega e redimensiona o logo para a altura do cabeçalho (cache por altura)."""
    global _logo_cache
    if _logo_cache is not None and _logo_cache.shape[0] == altura:
        return _logo_cache
    if not _LOGO_PATH.exists():
        return None
    try:
        logo = cv2.imread(str(_LOGO_PATH), cv2.IMREAD_UNCHANGED)
        if logo is None:
            return None
        h_orig, w_orig = logo.shape[:2]
        w_new = int(w_orig * altura / h_orig)
        logo = cv2.resize(logo, (w_new, altura), interpolation=cv2.INTER_AREA)
        _logo_cache = logo
        return logo
    except Exception:
        return None


def _blend_logo(img: np.ndarray, logo: np.ndarray, x: int, y: int):
    """Cola o logo (com ou sem canal alpha) sobre img nas coordenadas (x, y)."""
    lh, lw = logo.shape[:2]
    ih, iw = img.shape[:2]
    x0, y0 = max(x, 0), max(y, 0)
    x1, y1 = min(x + lw, iw), min(y + lh, ih)
    if x1 <= x0 or y1 <= y0:
        return
    lx0, ly0 = x0 - x, y0 - y
    lx1, ly1 = lx0 + (x1 - x0), ly0 + (y1 - y0)
    src = logo[ly0:ly1, lx0:lx1]
    dst = img[y0:y1, x0:x1]
    if logo.shape[2] == 4:
        alpha = src[:, :, 3:4].astype(np.float32) / 255.0
        img[y0:y1, x0:x1] = (src[:, :, :3] * alpha + dst * (1 - alpha)).astype(np.uint8)
    else:
        # Fundo preto do logo é transparente via multiply
        mask = src.max(axis=2, keepdims=True).astype(np.float32) / 255.0
        img[y0:y1, x0:x1] = (src.astype(np.float32) * mask +
                               dst.astype(np.float32) * (1 - mask)).astype(np.uint8)

log = logging.getLogger(__name__)

# Status global da API Claude (atualizado pelo worker de análise)
_api_online: bool = True

# Referência global aos slots ativos — preenchida por rodar_mosaico()
_slots_ref: dict = {}


def recalibrar_todos():
    """Dispara recalibração de thresholds locais em todos os slots ativos."""
    for slot in _slots_ref.values():
        try:
            slot.analisador_local.recalibrar()
        except Exception:
            pass
    log.info("Recalibração de thresholds disparada para %d câmeras", len(_slots_ref))


def ajuste_direto_todos(direcao: str):
    """Aplica ajuste imediato de sensibilidade a todas as câmeras ativas."""
    for slot in _slots_ref.values():
        try:
            slot.analisador_local.ajuste_direto(direcao)
        except Exception:
            pass


def _vision_label() -> str:
    """Retorna label do motor de visão sem bloquear (lê singleton se já inicializado)."""
    try:
        from vision_engine import VisionEngine
        eng = VisionEngine._instancia
        if eng is not None:
            return eng.modelo_label
    except Exception:
        pass
    return "LOCAL"


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


def _toolbar_action_rects(win_w: int, n: int = 0) -> list:
    """Retorna lista com o rect do botão ☰ Menu, alinhado à direita."""
    x1 = win_w - 10
    x0 = x1 - _MENU_BTN_W
    return [(x0, _TOOLBAR_BTN_Y0, x1, _TOOLBAR_BTN_Y0 + _TOOLBAR_BTN_H)]


# ── Palavras-chave para decisão inteligente de análise ────────────────────────
# Indica corpo parcial entrando na zona → expandir para câmera toda
_KW_CORPO_PARCIAL = {
    "mão", "mãos", "braço", "antebraço", "perna", "pé", "pés", "dedo", "dedos",
    "ombro", "cotovelo", "joelho", "tornozelo",
    "hand", "hands", "arm", "forearm", "leg", "foot", "feet", "finger", "fingers",
    "shoulder", "elbow", "knee", "ankle",
}
# Indica cena repetitiva/contínua sem risco real → suprimir chamadas
_KW_CENA_REPETITIVA = {
    "água", "water", "gotejamento", "dripping", "escorrendo", "flowing",
    "continuo", "continua", "constante", "repetitivo", "repetitiva",
    "vento", "wind", "sombra", "shadow", "reflexo", "reflection",
}


def _fingerprint_cena(resultado: dict) -> str:
    """Identificador compacto da cena para detectar repetição."""
    nivel = resultado.get("nivel_risco", "sem_risco")
    comps = tuple(sorted(c[:50] for c in resultado.get("comportamentos_detectados", [])))
    return f"{nivel}|{hash(comps)}"


def _detectar_corpo_parcial(resultado: dict) -> bool:
    texto = " ".join(
        resultado.get("comportamentos_detectados", []) +
        [resultado.get("posicao_na_cena", ""), resultado.get("acao_recomendada", "")]
    ).lower()
    return any(kw in texto for kw in _KW_CORPO_PARCIAL)


def _detectar_cena_repetitiva(resultado: dict) -> bool:
    texto = " ".join(
        resultado.get("comportamentos_detectados", []) +
        [resultado.get("posicao_na_cena", "")]
    ).lower()
    return any(kw in texto for kw in _KW_CENA_REPETITIVA)


# ── Fila de analise IA ────────────────────────────────────────────────────────
class FilaAnalise:
    INTERVALO_PADRAO  = 8    # segundos — intervalo base entre análises
    BACKOFF_MEDIO     = 60   # cena repetida 3-5x
    BACKOFF_ALTO      = 300  # cena repetida 6+x (5 minutos)
    REPS_MEDIO        = 3
    REPS_ALTO         = 6

    def __init__(self, intervalo: int = INTERVALO_PADRAO):
        self._q              = queue.Queue()
        self._intervalo      = intervalo
        self._ultimo         = {}   # {slot.idx: monotonic}
        self._cena_hash      = {}   # {slot.idx: str} — fingerprint da última análise
        self._repeticoes     = {}   # {slot.idx: int} — quantas vezes a mesma cena repetiu
        self._intervalo_slot = {}   # {slot.idx: int} — cooldown adaptativo atual
        self._thread         = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def enfileirar(self, slot: CameraSlot, frame_id: str, frame):
        # Gate 1: cooldown adaptativo por câmera
        agora = time.monotonic()
        cooldown = self._intervalo_slot.get(slot.idx, self._intervalo)
        if agora - self._ultimo.get(slot.idx, 0) < cooldown:
            return
        # Gate 2: não enfileirar se já está analisando
        if slot.em_analise:
            return
        # Gate 3: qualquer movimento na zona (ou câmera toda se sem zona)
        if not slot.get_movimento_na_zona():
            return
        slot.em_analise = True
        self._ultimo[slot.idx] = agora
        self._q.put((slot, frame_id, frame.copy()))

    def _atualizar_backoff(self, slot: CameraSlot, resultado: dict, camera_id: str):
        """Ajusta cooldown com base na repetição da cena."""
        fp = _fingerprint_cena(resultado)
        if fp == self._cena_hash.get(slot.idx):
            self._repeticoes[slot.idx] = self._repeticoes.get(slot.idx, 0) + 1
        else:
            self._cena_hash[slot.idx]    = fp
            self._repeticoes[slot.idx]   = 0
            self._intervalo_slot[slot.idx] = self._intervalo  # cena nova → reset

        reps = self._repeticoes[slot.idx]
        if reps >= self.REPS_ALTO or _detectar_cena_repetitiva(resultado):
            novo = self.BACKOFF_ALTO
        elif reps >= self.REPS_MEDIO:
            novo = self.BACKOFF_MEDIO
        else:
            novo = self._intervalo

        atual = self._intervalo_slot.get(slot.idx, self._intervalo)
        if novo != atual:
            self._intervalo_slot[slot.idx] = novo
            log.info("[%s] Backoff ajustado para %ds (cena repetida %dx)",
                     camera_id, novo, reps)

    def _atualizar_expansao(self, slot: CameraSlot, resultado: dict, camera_id: str):
        """Ativa/desativa modo expansão com base no que a IA detectou."""
        nivel = resultado.get("nivel_risco", "sem_risco")
        corpo_parcial = _detectar_corpo_parcial(resultado)

        if corpo_parcial and not slot.modo_expansao:
            slot.modo_expansao = True
            self._intervalo_slot[slot.idx] = self._intervalo  # análise frequente ao expandir
            self._repeticoes[slot.idx]     = 0
            log.info("[%s] Corpo parcial detectado — monitoramento expandido (câmera toda)",
                     camera_id)
        elif slot.modo_expansao and nivel == "sem_risco" and not corpo_parcial:
            slot.modo_expansao = False
            log.info("[%s] Cena limpa — voltando ao monitoramento por zona", camera_id)

    def _worker(self):
        global _api_online
        import db
        while True:
            slot, frame_id, frame = self._q.get()
            camera_id = slot.cfg["id"]
            tokens_in = tokens_out = 0
            try:
                from analyzer import triagem_haiku, analisar_frame

                zonas = slot.zonas_roi
                em_expansao = slot.modo_expansao

                if zonas and not em_expansao:
                    # Zonas configuradas e sem expansão: recorta para a união das zonas.
                    fh, fw = frame.shape[:2]
                    all_coords = [z["zona"] for z in zonas if z.get("zona")]
                    if all_coords:
                        ux1 = min(c[0] for c in all_coords)
                        uy1 = min(c[1] for c in all_coords)
                        ux2 = max(c[2] for c in all_coords)
                        uy2 = max(c[3] for c in all_coords)
                        rx1, ry1 = int(ux1 * fw), int(uy1 * fh)
                        rx2, ry2 = int(ux2 * fw), int(uy2 * fh)
                        frame_analise = frame[ry1:ry2, rx1:rx2] if (rx2 > rx1 and ry2 > ry1) else frame
                        pct = (ux2 - ux1) * (uy2 - uy1) * 100
                        log.info("[%s] %d zona(s) ROI — %.0f%% do frame",
                                 camera_id, len(zonas), pct)
                    else:
                        frame_analise = frame
                    resultado, tokens_in, tokens_out = analisar_frame(
                        frame_analise, frame_id, camera_id=camera_id
                    )
                else:
                    # Sem zona OU modo expansão: analisa câmera toda.
                    if em_expansao:
                        log.info("[%s] Modo expansão — câmera completa", camera_id)
                    if zonas:
                        # Expansão com zona: pula triagem Haiku, analisa tudo com Opus
                        resultado, tokens_in, tokens_out = analisar_frame(
                            frame, frame_id, camera_id=camera_id
                        )
                    else:
                        # Sem zona: triagem Haiku antes do Opus
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
                            log.info("[%s] Haiku: sem pessoa — Opus ignorado", camera_id)
                        else:
                            resultado, tokens_in, tokens_out = analisar_frame(
                                frame, frame_id, camera_id=camera_id
                            )

                nivel = resultado.get("nivel_risco", "sem_risco")
                if tokens_in or tokens_out:
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
                # Inteligência pós-análise: backoff e expansão
                self._atualizar_backoff(slot, resultado, camera_id)
                self._atualizar_expansao(slot, resultado, camera_id)

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
                clip_path = None
                if resultado.get("alerta"):
                    clip_path = str(PASTA_CLIPS / f"alerta_{frame_id}.mp4")
                    try:
                        from alert_handler import salvar_clip
                        salvar_clip(list(slot.frames_recentes), frame_id)
                    except Exception as exc:
                        log.warning("[%s] Falha ao salvar clip: %s", camera_id, exc)
                        clip_path = None
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
    bg = (40, 22, 12) if hover else C_CARD
    img = np.full((h, w, 3), bg, dtype=np.uint8)

    # Grid pontilhado de fundo (estilo HUD)
    dot_step = max(16, min(28, min(w, h) // 10))
    dot_cor  = (38, 22, 10) if not hover else (55, 35, 18)
    for gx in range(dot_step, w - 1, dot_step):
        for gy in range(dot_step, h - 1, dot_step):
            cv2.circle(img, (gx, gy), 1, dot_cor, -1)

    # Colchetes de canto (estilo tático)
    arm   = max(10, min(24, min(w, h) // 8))
    borda = C_AMARELO if hover else (90, 70, 30)
    thick = 2 if hover else 1
    for px, py, dx, dy in [(1, 1, 1, 0), (w-2, 1, -1, 0),
                            (1, h-2, 1, 0), (w-2, h-2, -1, 0)]:
        sx = 1 if dx > 0 else w - 2
        sy = py
        ex = sx + dx * arm
        cv2.line(img, (sx, sy), (ex, sy), borda, thick)
        ey = sy + (arm if py == 1 else -arm)
        cv2.line(img, (sx, sy), (sx, ey), borda, thick)

    pil_texts = []
    FS_SLOT = max(8, min(10, h // 22))
    FS_ADD  = max(8, min(11, w // 55))

    cx, cy = w // 2, h // 2

    if h > 50:
        r_out = max(14, min(32, min(w, h) // 7))
        r_in  = max(4,  r_out // 3)
        gap   = r_out // 4
        reticle_cor = C_AMARELO if hover else (75, 70, 90)
        shadow_cor  = (0, 0, 0)

        cy_ico = cy - 12 if h > 90 else cy

        # Sombra do reticle
        if hover:
            cv2.circle(img, (cx + 2, cy_ico + 2), r_out, shadow_cor, 1)

        # Círculo externo
        cv2.circle(img, (cx, cy_ico), r_out, reticle_cor, 1)
        # Círculo interno
        cv2.circle(img, (cx, cy_ico), r_in, reticle_cor, 1)
        # Linhas da mira (com gap central)
        for lx0, ly0, lx1, ly1 in [
            (cx - r_out, cy_ico, cx - gap, cy_ico),
            (cx + gap,   cy_ico, cx + r_out, cy_ico),
            (cx, cy_ico - r_out, cx, cy_ico - gap),
            (cx, cy_ico + gap,   cx, cy_ico + r_out),
        ]:
            cv2.line(img, (lx0, ly0), (lx1, ly1), reticle_cor, 1)

        # Ícone + no centro do reticle
        icon_cor = (10, 8, 14) if hover else (80, 75, 95)
        mini_arm = max(3, r_in // 2)
        cv2.line(img, (cx - mini_arm, cy_ico), (cx + mini_arm, cy_ico), icon_cor, 2)
        cv2.line(img, (cx, cy_ico - mini_arm), (cx, cy_ico + mini_arm), icon_cor, 2)

        if h > 90:
            txt     = "[ ADICIONAR CAMERA ]"
            txt_cor = C_AMARELO if hover else (80, 75, 95)
            tw, _   = _txt_size(txt, FS_ADD)
            pil_texts.append((txt, (w - tw) // 2, cy_ico + r_out + 8, FS_ADD, txt_cor, False))

    lbl = f"SLOT {idx + 1:02d}"
    pil_texts.append((lbl, 6, 4, FS_SLOT, (65, 60, 78), False))
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


def _desenhar_zonas(img: np.ndarray, slot, w: int, h: int, escala: float):
    """Renderiza overlay de zonas de detecção sobre img (in-place)."""
    _CZ = [
        (255,212,0),(119,204,0),(153,68,255),(0,165,255),
        (238,153,0),(0,255,128),(128,0,255),(255,0,128),
    ]
    zonas_slot = getattr(slot, "zonas_roi", [])
    for zi, zd in enumerate(zonas_slot):
        cor_z  = _CZ[zd.get("cor_idx", zi) % len(_CZ)]
        nome_z = zd.get("nome", f"Zona {zi+1}")

        if zd.get("tipo") == "poly":
            pts_n = zd.get("pontos", [])
            if len(pts_n) >= 3:
                pts = np.array([[int(p[0]*w), int(p[1]*h)]
                                for p in pts_n], np.int32)
                cv2.polylines(img, [pts], True, cor_z, 2)
                for pt in pts:
                    cv2.circle(img, tuple(pt), max(3, int(escala*8)), cor_z, -1)
                cx = int(np.mean([p[0] for p in pts_n]) * w)
                cy = int(np.mean([p[1] for p in pts_n]) * h)
                cv2.putText(img, nome_z, (max(2, cx-18), cy),
                            cv2.FONT_HERSHEY_SIMPLEX, escala*0.55, cor_z, 2)
        else:
            coord = zd.get("zona", [])
            if len(coord) != 4:
                continue
            zx1 = int(coord[0]*w); zy1 = int(coord[1]*h)
            zx2 = int(coord[2]*w); zy2 = int(coord[3]*h)
            cv2.rectangle(img, (zx1,zy1), (zx2,zy2), cor_z, 1)
            arm_z = max(4, min(10, min(zx2-zx1, zy2-zy1)//6))
            for (px, py, dx, dy) in [
                (zx1,zy1, 1, 1),(zx2,zy1,-1, 1),
                (zx1,zy2, 1,-1),(zx2,zy2,-1,-1),
            ]:
                cv2.line(img,(px,py),(px+dx*arm_z,py),cor_z,2)
                cv2.line(img,(px,py),(px,py+dy*arm_z),cor_z,2)
            if (zx2-zx1)>30 and (zy2-zy1)>12:
                cv2.putText(img, nome_z, (zx1+3, zy1+11),
                            cv2.FONT_HERSHEY_SIMPLEX, escala*0.50, cor_z, 1)


def _slot_camera(slot: CameraSlot, w: int, h: int,
                 closeable: bool = False, show_close: bool = False,
                 show_bar: bool = False) -> np.ndarray:
    escala = max(0.28, min(0.50, w / 640))
    frame = slot.get_frame()
    if frame is None:
        img = np.full((h, w, 3), C_CARD, dtype=np.uint8)
        # Grid pontilhado no slot offline
        for gx in range(20, w - 1, 20):
            for gy in range(20, h - 1, 20):
                cv2.circle(img, (gx, gy), 1, (35, 30, 40), -1)
        cv2.putText(img, "[ CONECTANDO... ]", (max(4, w // 5), h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, max(0.3, w / 900), C_CINZA, 1)
        _desenhar_zonas(img, slot, w, h, escala)
        return img

    img = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)
    res        = slot.get_resultado()
    deteccoes  = slot.get_deteccoes_locais()
    em_analise = slot.em_analise
    nivel      = res.get("nivel_risco", "")
    cor        = NIVEL_COR.get(nivel, C_CINZA)
    confianca  = float(res.get("confianca", 0.0)) if res else 0.0

    bar_h  = max(16, h // 14)

    # ── Scan line animada durante análise IA ──────────────────────────────────
    if em_analise and h > 60:
        scan_y = int((time.time() * 80) % (h - bar_h)) + bar_h
        overlay = img.copy()
        cv2.line(overlay, (0, scan_y), (w - 1, scan_y), C_AMARELO, 1)
        cv2.addWeighted(overlay, 0.25, img, 0.75, 0, img)

    # ── Bounding boxes ────────────────────────────────────────────────────────
    if nivel or deteccoes:
        _desenhar_bboxes(img, res, deteccoes, w, h, cor, bar_h)

    # ── Borda pulsante em alerta crítico ──────────────────────────────────────
    if nivel == "critico":
        pulse = abs(math.sin(time.time() * 3.5))
        bint  = int(80 + 175 * pulse)
        bcor  = (30, 30, bint)   # vermelho pulsante
        cv2.rectangle(img, (0, 0), (w - 1, h - 1), bcor, 3)
    elif nivel in ("suspeito", "atencao"):
        cv2.rectangle(img, (0, 0), (w - 1, h - 1), cor, 1)

    # ── Colchetes táticos de canto ────────────────────────────────────────────
    arm   = max(10, min(20, min(w, h) // 9))
    bcor  = cor if nivel else (80, 75, 90)
    bth   = 2 if nivel else 1
    # topo-esquerda
    cv2.line(img, (0, 0), (arm, 0), bcor, bth)
    cv2.line(img, (0, 0), (0, arm), bcor, bth)
    # topo-direita
    cv2.line(img, (w - 1 - arm, 0), (w - 1, 0), bcor, bth)
    cv2.line(img, (w - 1, 0), (w - 1, arm), bcor, bth)
    # baixo-esquerda
    cv2.line(img, (0, h - 1 - arm), (0, h - 1), bcor, bth)
    cv2.line(img, (0, h - 1), (arm, h - 1), bcor, bth)
    # baixo-direita
    cv2.line(img, (w - 1, h - 1 - arm), (w - 1, h - 1), bcor, bth)
    cv2.line(img, (w - 1 - arm, h - 1), (w - 1, h - 1), bcor, bth)

    # ── Overlay das zonas de detecção ────────────────────────────────────────────
    _desenhar_zonas(img, slot, w, h, escala)

    # ── Barra superior semitransparente (só no hover ou expandido) ───────────
    cam_id = slot.cfg.get("id", f"CAM{slot.idx + 1}")
    if show_bar:
        overlay = img.copy()
        cv2.rectangle(overlay, (0, 0), (w, bar_h), (5, 4, 8), -1)
        cv2.addWeighted(overlay, 0.75, img, 0.25, 0, img)
        cv2.line(img, (0, bar_h), (w, bar_h), C_OURO2, 1)
        cv2.putText(img, cam_id, (4, bar_h - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, escala, C_AMARELO, 1)
        if nivel:
            fonte_tag = "L" if res.get("fonte") == "local" else "IA"
            fonte_cor = (180, 130, 60) if fonte_tag == "L" else (80, 200, 120)
            r = max(4, bar_h // 3)
            cv2.circle(img, (w - r - 4, bar_h // 2), r, cor, -1)
            if w > 120:
                etiq = nivel.upper()
                tw = cv2.getTextSize(etiq, cv2.FONT_HERSHEY_SIMPLEX, escala * 0.8, 1)[0][0]
                cv2.putText(img, etiq, (w - r * 2 - tw - 6, bar_h - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, escala * 0.8, cor, 1)
            if w > 80:
                id_w = cv2.getTextSize(cam_id, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)[0][0]
                cv2.putText(img, fonte_tag, (id_w + 8, bar_h - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, escala * 0.65, fonte_cor, 1)

    # ── Barra de confiança na base ────────────────────────────────────────────
    if nivel and confianca > 0 and h > 40:
        bar_conf_w = max(1, int(w * confianca))
        cv2.rectangle(img, (0, h - 3), (w - 1, h - 1), (20, 18, 24), -1)
        cv2.rectangle(img, (0, h - 3), (bar_conf_w, h - 1), cor, -1)

    # ── Timestamp no canto inferior direito ───────────────────────────────────
    if h > 80 and w > 100:
        ts_txt = datetime.now().strftime("%H:%M:%S")
        ts_w   = cv2.getTextSize(ts_txt, cv2.FONT_HERSHEY_SIMPLEX, escala * 0.65, 1)[0][0]
        cv2.putText(img, ts_txt, (w - ts_w - 4, h - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, escala * 0.65, (60, 55, 75), 1)

    # ── Botão fechar (X) ──────────────────────────────────────────────────────
    if closeable and show_close:
        btn_w = max(24, bar_h + 6)
        cv2.rectangle(img, (w - btn_w, 0), (w - 1, bar_h), (40, 35, 60), -1)
        cv2.rectangle(img, (w - btn_w, 0), (w - 1, bar_h), C_VERM, 1)
        cx_ = w - btn_w // 2
        cy_ = bar_h // 2
        sz_ = max(4, bar_h // 4)
        cv2.line(img, (cx_ - sz_, cy_ - sz_), (cx_ + sz_, cy_ + sz_), (200, 200, 255), 2)
        cv2.line(img, (cx_ + sz_, cy_ - sz_), (cx_ - sz_, cy_ + sz_), (200, 200, 255), 2)

    # ── Overlay IA pensando ───────────────────────────────────────────────────
    if (res or em_analise) and h > 120:
        _desenhar_ia_overlay(img, res, em_analise, w, h, bar_h, cor, escala)

    return img


# Posição do botão API no cabeçalho — atualizada a cada render e usada pelo mouse handler
_api_btn_range: list[int] = [342, 466]   # [x0, x1]


# ── Cabecalho ─────────────────────────────────────────────────────────────────
def _cabecalho(n_ativas: int, layout: int, win_w: int,
               usuario_nome: str = "", usuario_grupo: str = "",
               api_online: bool = True, hover_api: bool = False,
               vision_label: str = "") -> np.ndarray:
    img = np.full((HDR_H, win_w, 3), C_BG, dtype=np.uint8)

    # Linha de circuito decorativa no topo (3px ouro)
    cv2.line(img, (0, 0), (win_w, 0), C_OURO2, 1)
    # Linha de acento ouro na base do cabeçalho (mais espessa)
    cv2.line(img, (0, HDR_H - 1), (win_w, HDR_H - 1), C_AMARELO, 2)
    cv2.line(img, (0, HDR_H - 3), (win_w, HDR_H - 3), C_OURO2, 1)

    # Pontos de circuito decorativos (canto esquerdo)
    for px in range(4, 50, 12):
        cv2.circle(img, (px, HDR_H - 1), 2, C_OURO2, -1)

    pil_texts = []
    logo_w = 0

    # ── Logo (se existir em assets/logo_dark.png) ──────────────────────────────
    logo = _carregar_logo(HDR_H - 4)
    if logo is not None:
        _blend_logo(img, logo, 4, 2)
        logo_w = logo.shape[1] + 10

    # ── Linha divisória entre as duas faixas do header ─────────────────────────
    _ROW1_H = 40  # faixa superior: logo + título + api + stats
    cv2.line(img, (0, _ROW1_H), (win_w, _ROW1_H), (28, 24, 35), 1)

    # ── Título (faixa superior, centrado verticalmente em _ROW1_H/2) ─────────
    titulo_x = logo_w + 6
    pil_texts.append(("SPARTA AGENTE IA",
                       titulo_x, 6, 15, C_AMARELO, True))

    # ── Indicador API (clicável para admin) ────────────────────────────────────
    api_cor  = (0, 200, 60) if api_online else (50, 50, 210)
    api_txt  = "API OK" if api_online else "API OFF"
    api_tcor = (180, 255, 180) if api_online else (150, 150, 255)
    api_x    = titulo_x + 280
    # Sincroniza posição com mouse handler
    _api_btn_range[0] = api_x - 4
    _api_btn_range[1] = api_x + 120
    api_cy   = _ROW1_H // 2

    if hover_api:
        cv2.rectangle(img, (api_x - 4, 2), (api_x + 120, _ROW1_H - 2), (35, 30, 40), -1)
        cv2.rectangle(img, (api_x - 4, 2), (api_x + 120, _ROW1_H - 2), C_OURO2, 1)

    # Bolinha pulsante (usa sin do tempo)
    pulse = int(180 + 75 * abs(math.sin(time.time() * 2)))
    api_glow = tuple(min(255, int(c * pulse / 255)) for c in api_cor)
    cv2.circle(img, (api_x + 6, api_cy), 5, api_cor, -1)
    cv2.circle(img, (api_x + 6, api_cy), 5, api_glow, 1)
    _, ath = _txt_size(api_txt, 9)
    pil_texts.append((api_txt, api_x + 15, api_cy - ath // 2, 9, api_tcor, False))
    if hover_api and vision_label:
        pil_texts.append((vision_label, api_x + 15, api_cy + ath // 2 + 2, 7,
                           (120, 160, 255), False))

    # ── Stats em tempo real (faixa superior, canto direito) ───────────────────
    cols, rows = LAYOUTS[layout]
    hora  = datetime.now().strftime("%H:%M:%S")
    stat1 = f"{n_ativas} CAM  {cols}x{rows}"
    stat2 = hora
    s1w, _ = _txt_size(stat1, 8)
    s2w, _ = _txt_size(stat2, 10)
    stats_x = win_w - max(s1w, s2w) - 160
    pil_texts.append((stat1, stats_x, 5,  8,  C_CINZA,   False))
    pil_texts.append((stat2, stats_x, 18, 11, C_AMARELO, True))

    # ── Slogan — faixa inferior centralizada (y=40 a y=58) ───────────────────
    slogan = "RF SMART SECURITY  |  VIGILANCIA INTELIGENTE POR IA"
    sw, sh = _txt_size(slogan, 9)
    sx = max(titulo_x, (win_w - sw) // 2)
    pil_texts.append((slogan, sx, _ROW1_H + 4, 9, (220, 210, 240), False))

    # ── Badge de usuário (extrema direita) ─────────────────────────────────────
    if usuario_nome:
        grupo_label = "ADM" if usuario_grupo == "administrador" else "USR"
        badge_cor   = (20, 140, 60) if usuario_grupo == "administrador" else (120, 60, 140)
        badge_txt   = f"  {usuario_nome} [{grupo_label}]  "
        bw, bh      = _txt_size(badge_txt, 9, bold=True)
        bx = win_w - bw - 8
        by = (_ROW1_H - bh) // 2
        # Fundo do badge com borda ouro
        cv2.rectangle(img, (bx - 2, by - 3), (bx + bw + 2, by + bh + 3), badge_cor, -1)
        cv2.rectangle(img, (bx - 2, by - 3), (bx + bw + 2, by + bh + 3), C_AMARELO, 1)
        pil_texts.append((badge_txt, bx, by, 9, (255, 255, 255), True))

    _pil_render(img, pil_texts)
    return img


# ── Toolbar de layout ─────────────────────────────────────────────────────────
def _toolbar(layout_atual: int, hover_btn: int, win_w: int,
             hover_act_btn: int = -1, is_admin: bool = False,
             cam_slots: set | None = None,
             menu_aberto: bool = False) -> np.ndarray:
    img = np.full((TOOLBAR_H, win_w, 3), (14, 12, 18), dtype=np.uint8)
    cv2.line(img, (0, 0), (win_w, 0), C_OURO2, 1)
    cv2.line(img, (0, TOOLBAR_H - 1), (win_w, TOOLBAR_H - 1), (8, 6, 12), 1)

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

    # Botão ☰ Menu (direita) — abre dropdown ao clicar
    mx0, my0, mx1, my1 = _toolbar_action_rects(win_w)[0]
    menu_hover = (hover_act_btn == 0)
    bg_menu = (20, 60, 80) if menu_aberto else ((60, 60, 60) if menu_hover else (45, 45, 45))
    _draw_btn_bg(img, mx0, my0, mx1, my1, bg_menu, hover=False)
    lbl_menu = "\u2630 Menu"
    tw, th   = _txt_size(lbl_menu, BTN_FS)
    fg_menu  = C_AMARELO if menu_aberto else (C_BRANCO if menu_hover else C_CINZA)
    pil_texts.append((lbl_menu,
                      mx0 + (mx1 - mx0 - tw) // 2,
                      my0 + (my1 - my0 - th) // 2,
                      BTN_FS, fg_menu, menu_aberto))

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
                         hover_api=state.get("hover_api", False),
                         vision_label=_vision_label())
    toolbar = _toolbar(layout, hover_btn, win_w,
                       hover_act_btn=state.get("hover_act_btn", -1),
                       is_admin=(state.get("usuario_grupo") == "administrador"),
                       cam_slots=set(slots.keys()),
                       menu_aberto=state.get("menu_aberto", False))

    # Sincroniza stream principal/sub conforme slot expandido
    for i, sl in slots.items():
        try:
            sl.set_expandido(i == expandido)
        except Exception:
            pass

    if expandido is not None and expandido in slots:
        video = _slot_camera(slots[expandido], mosaic_w, mosaic_h,
                             closeable=True, show_close=True, show_bar=True)
        cv2.putText(video, "Clique para voltar", (10, mosaic_h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, C_CINZA, 1)
    else:
        celulas = []
        for i in range(max_cams):
            if i in slots:
                celulas.append(_slot_camera(slots[i], slot_w, slot_h,
                                            closeable=True, show_close=(i == hover),
                                            show_bar=(i == hover)))
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

    if state.get("menu_aberto"):
        frame = _desenhar_menu_dropdown(
            frame, state["win_w"],
            state.get("usuario_grupo") == "administrador",
            state.get("menu_hover", -1),
        )

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
    tk.Label(corpo, text="Stream Principal — URI RTSP (opcional — substitui ONVIF)",
             font=("Segoe UI", 8), bg=BG2, fg="#888888").pack(anchor="w")
    e_rtsp = tk.Entry(corpo, font=("Consolas", 9), bg=ENT, fg=BCOR,
                      insertbackground=AMA, relief="flat", bd=0,
                      highlightthickness=1, highlightcolor=AMA,
                      highlightbackground=CESC, width=38)
    e_rtsp.insert(0, c.get("rtsp_uri", ""))
    e_rtsp.pack(fill="x", ipady=4, pady=(2, 6))
    e_rtsp.bind("<FocusIn>",  lambda ev: e_rtsp.config(highlightbackground=AMA))
    e_rtsp.bind("<FocusOut>", lambda ev: e_rtsp.config(highlightbackground=CESC))

    tk.Label(corpo, text="Stream Secundário — URI RTSP baixa resolução (miniatura, opcional)",
             font=("Segoe UI", 8), bg=BG2, fg="#888888").pack(anchor="w")
    e_rtsp_sub = tk.Entry(corpo, font=("Consolas", 9), bg=ENT, fg=BCOR,
                          insertbackground=AMA, relief="flat", bd=0,
                          highlightthickness=1, highlightcolor=AMA,
                          highlightbackground=CESC, width=38)
    e_rtsp_sub.insert(0, c.get("rtsp_uri_sub", ""))
    e_rtsp_sub.pack(fill="x", ipady=4, pady=(2, 10))
    e_rtsp_sub.bind("<FocusIn>",  lambda ev: e_rtsp_sub.config(highlightbackground=AMA))
    e_rtsp_sub.bind("<FocusOut>", lambda ev: e_rtsp_sub.config(highlightbackground=CESC))

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
            "id":           e_id.get().strip()   or f"CAM-{slot_idx+1:02d}",
            "ip":           e_ip.get().strip(),
            "porta":        e_port.get().strip() or "80",
            "usuario":      e_user.get().strip(),
            "senha":        e_pw.get().strip(),
            "canal":        e_ch.get().strip()   or "1",
            "rtsp_uri_sub": e_rtsp_sub.get().strip(),
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
            {"label": "Renomear camera",        "action": "renomear"},
            {"label": "Configurar camera",      "action": "configurar"},
            {"label": "Definir zona de deteccao", "action": "zona"},
            {"sep": True},
            {"label": "Fechar camera",          "action": "fechar",   "danger": True},
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


# ── Menu dropdown (☰ Menu) ────────────────────────────────────────────────────

def _menu_items(is_admin: bool) -> list:
    """Itens do dropdown ☰ Menu."""
    base = [
        {"label": "Treinar",  "action": "treinar",  "cor": (195, 240, 255)},
        {"sep": True},
        {"label": "Sair",     "action": "sair",     "cor": (235, 225, 255), "danger": True},
    ]
    if not is_admin:
        return base
    return [
        {"label": "Usuarios", "action": "usuarios", "cor": (185, 255, 195)},
        {"label": "Backup",   "action": "backup",   "cor": (255, 210, 160)},
        {"label": "Atualizar", "action": "update",    "cor": (160, 210, 255)},
        {"label": "Hardware",  "action": "hardware",  "cor": (210, 190, 255)},
        {"label": "Relatorio",  "action": "relatorio", "cor": (255, 180, 180)},
        {"sep": True},
        {"label": "Treinar",   "action": "treinar",   "cor": (195, 240, 255)},
        {"sep": True},
        {"label": "Sair",      "action": "sair",      "cor": (235, 225, 255), "danger": True},
    ]


def _menu_drop_geometry(win_w: int) -> tuple:
    """Retorna (x0, y0, x1, total_h) do painel dropdown."""
    items  = _menu_items(True)   # usa admin=True para calcular tamanho máximo
    total_h = _MENU_DROP_PAD_V * 2
    for it in items:
        total_h += CTX_SEP_H if it.get("sep") else _MENU_DROP_ITH
    btn_rect = _toolbar_action_rects(win_w)[0]
    x1 = btn_rect[2]
    x0 = x1 - _MENU_DROP_W
    y0 = HDR_H + TOOLBAR_H
    return x0, y0, x1, total_h


def _menu_drop_hit(x: int, y: int, win_w: int, is_admin: bool) -> int:
    """Retorna índice do item clicável em (x,y) ou -1."""
    items  = _menu_items(is_admin)
    btn    = _toolbar_action_rects(win_w)[0]
    drop_x0 = btn[2] - _MENU_DROP_W
    drop_x1 = btn[2]
    if not (drop_x0 <= x <= drop_x1):
        return -1
    cy = HDR_H + TOOLBAR_H + _MENU_DROP_PAD_V
    for i, item in enumerate(items):
        if item.get("sep"):
            cy += CTX_SEP_H
            continue
        if cy <= y < cy + _MENU_DROP_ITH and not item.get("header"):
            return i
        cy += _MENU_DROP_ITH
    return -1


def _desenhar_menu_dropdown(img: np.ndarray, win_w: int,
                             is_admin: bool, hover: int) -> np.ndarray:
    """Desenha o painel dropdown do ☰ Menu sobre o frame."""
    items  = _menu_items(is_admin)
    x0, y0, x1, total_h = _menu_drop_geometry(win_w)
    y1 = y0 + total_h

    # Sombra + fundo
    cv2.rectangle(img, (x0 + 4, y0 + 4), (x1 + 4, y1 + 4), (0, 0, 0), -1)
    cv2.rectangle(img, (x0, y0), (x1, y1), (28, 28, 28), -1)
    cv2.rectangle(img, (x0, y0), (x1, y1), (75, 75, 75), 1)

    cy = y0 + _MENU_DROP_PAD_V
    for i, item in enumerate(items):
        if item.get("sep"):
            mid = cy + CTX_SEP_H // 2
            cv2.line(img, (x0 + 8, mid), (x1 - 8, mid), (65, 65, 65), 1)
            cy += CTX_SEP_H
            continue
        iy1 = cy + _MENU_DROP_ITH
        if i == hover:
            bg = (35, 18, 18) if item.get("danger") else (45, 45, 12)
            cv2.rectangle(img, (x0 + 1, cy), (x1 - 1, iy1), bg, -1)
        cor = (80, 80, 230) if item.get("danger") else item.get("cor", C_BRANCO)
        if i == hover:
            cor = (60, 60, 255) if item.get("danger") else C_AMARELO
        cv2.putText(img, item["label"],
                    (x0 + _MENU_DROP_PAD_H, cy + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, cor, 1)
        cy = iy1
    return img


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

    global _slots_ref
    slots: dict[int, CameraSlot] = {}
    _slots_ref = slots          # expõe para recalibrar_todos() / ajuste_direto_todos()
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
        # Menu dropdown
        "menu_aberto":   False,
        "menu_hover":    -1,
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
        slot.iniciar(cfg_cam["rtsp_uri"], cfg_cam.get("rtsp_uri_sub", ""))
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
                novo.iniciar(cfg_bkp["rtsp_uri"], cfg_bkp.get("rtsp_uri_sub", ""))
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
                    novo.iniciar(cfg_novo["rtsp_uri"], cfg_novo.get("rtsp_uri_sub", ""))
                    slots[slot_idx] = novo
                    _salvar_todos()
                    log.info("Camera reconfigurada: slot %d", slot_idx)

        elif action == "zona":
            if slot_idx in slots:
                _panel_pendente[0] = ("zona", slot_idx)

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
            state["hover_api"] = _admin and _api_btn_range[0] <= x <= _api_btn_range[1]
            if event == cv2.EVENT_LBUTTONDOWN and _admin and _api_btn_range[0] <= x <= _api_btn_range[1]:
                _panel_pendente[0] = "api"
            return
        state["hover_api"] = False

        # Se dropdown aberto — tratar hover/clique antes de tudo
        if state.get("menu_aberto"):
            hit = _menu_drop_hit(x, y, iw, _admin)
            state["menu_hover"] = hit
            if event == cv2.EVENT_LBUTTONDOWN:
                state["menu_aberto"] = False
                if hit >= 0:
                    action = _menu_items(_admin)[hit].get("action")
                    if action:
                        state["req_action"] = action
            elif event in (cv2.EVENT_RBUTTONDOWN, cv2.EVENT_MBUTTONDOWN):
                state["menu_aberto"] = False
            return

        # Toolbar
        if y < HDR_H + TOOLBAR_H:
            state["hover"] = -1
            bi = _btn_index_at(x)
            menu_rect = _toolbar_action_rects(state["win_w"])[0]
            on_menu = menu_rect[0] <= x <= menu_rect[2]
            state["hover_btn"]     = bi if not on_menu else -1
            state["hover_act_btn"] = 0 if on_menu else -1
            if event == cv2.EVENT_LBUTTONDOWN:
                if bi >= 0:
                    novo_layout = LAYOUT_ORDER[bi]
                    if state["layout"] != novo_layout:
                        state["layout"]    = novo_layout
                        state["expandido"] = None
                        log.info("Layout alterado para %dCH", novo_layout)
                elif on_menu:
                    state["menu_aberto"] = not state.get("menu_aberto", False)
                    state["menu_hover"]  = -1
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
        elif nome == "hardware":
            from hardware_panel import abrir_hardware_panel
            abrir_hardware_panel()
        elif nome == "relatorio":
            from error_reporter import abrir_painel_relatorio
            abrir_painel_relatorio()
        elif isinstance(nome, tuple) and nome[0] == "zona":
            slot = slots.get(nome[1])
            if slot:
                import tkinter as _tk
                r = _tk.Tk(); r.withdraw(); r.attributes("-topmost", True)

                def _ao_salvar_zonas(zonas, _slot=slot):
                    _slot.set_zonas(zonas)
                    _slot.cfg["zonas_deteccao"] = zonas
                    _slot.cfg.pop("zona_deteccao", None)  # remove formato antigo
                    _salvar_todos()
                    for z in zonas:
                        log.info("[%s] zona salva: nome=%s tipo=%s pontos=%s",
                                 _slot.cfg["id"], z.get("nome"), z.get("tipo"),
                                 len(z.get("pontos", [])) if z.get("tipo") == "poly" else "n/a")

                from zona_editor import ZonaEditorDialog
                ZonaEditorDialog(r, slot, on_salvar=_ao_salvar_zonas)
                r.mainloop()
                r.destroy()
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

            # Processa acao solicitada pelo dropdown ☰ Menu
            if state["req_action"] is not None:
                acao = state["req_action"]
                state["req_action"] = None
                if acao == "sair":
                    break
                elif acao in ("treinar", "usuarios", "backup", "update", "hardware", "relatorio"):
                    _panel_pendente[0] = acao

            state["api_online"] = _api_online
            mosaico = _montar_mosaico(slots, state)
            cv2.imshow(WIN_NAME, mosaico)

            # Mantém painel de hardware responsivo sem bloquear o loop
            try:
                from hardware_panel import atualizar_janela
                atualizar_janela()
            except Exception:
                pass

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
