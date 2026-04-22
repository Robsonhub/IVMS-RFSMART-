"""Constantes de layout, cores e dimensões do mosaico — SPARTA AGENTE IA."""
from pathlib import Path

# ── Dimensões da janela ──────────────────────────────────────────────────────
MOSAIC_W  = 1280
MOSAIC_H  = 720
HDR_H     = 60
TOOLBAR_H = 32
WIN_W     = MOSAIC_W
WIN_H     = HDR_H + TOOLBAR_H + MOSAIC_H
WIN_NAME  = "SPARTA AGENTE IA"

# Resolução interna de captura por slot (redimensiona na renderização)
CAP_W = 640
CAP_H = 360

# Layouts disponíveis: canais → (colunas, linhas)
LAYOUTS = {
    1:  (1, 1),
    4:  (2, 2),
    16: (4, 4),
    32: (8, 4),
}
LAYOUT_ORDER = [1, 4, 16, 32]

# ── Menu de contexto ─────────────────────────────────────────────────────────
CTX_W      = 230
CTX_ITEM_H = 27
CTX_SEP_H  = 10
CTX_PAD_V  = 6
CTX_PAD_H  = 14

# ── Botões da toolbar ────────────────────────────────────────────────────────
_TOOLBAR_BTN_W   = 72
_TOOLBAR_BTN_H   = 22
_TOOLBAR_BTN_GAP = 8
_TOOLBAR_BTN_Y0  = (TOOLBAR_H - _TOOLBAR_BTN_H) // 2

_ACT_BTN_W      = 78
_ACT_BTN_GAP    = 6
_MENU_BTN_W     = 90
_MENU_DROP_W    = 160
_MENU_DROP_ITH  = 30
_MENU_DROP_PAD_V = 8
_MENU_DROP_PAD_H = 14

# ── Cores BGR — paleta RRF Smart Security ────────────────────────────────────
C_BG      = ( 18,  10,   5)
C_CARD    = ( 30,  19,   8)
C_AMARELO = (255, 212,   0)
C_OURO2   = (158, 122,   0)
C_BRANCO  = (248, 232, 200)
C_CINZA   = (112,  96,  74)
C_VERDE   = (119, 204,   0)
C_VERM    = ( 85,  34, 255)
C_LARAN   = (153,  68, 255)
C_AZUL    = (238, 153,   0)

NIVEL_COR = {
    "sem_risco": C_VERDE,
    "atencao":   C_AMARELO,
    "suspeito":  C_LARAN,
    "critico":   C_VERM,
}

CAMERAS_JSON = Path(__file__).parent / "cameras.json"
