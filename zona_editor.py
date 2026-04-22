"""
Editor de Zonas de Detecção — SPARTA AGENTE IA

Modos:
  Retângulo — clique+arraste para criar; alças nas bordas/cantos para redimensionar;
              arraste pelo interior para mover.
  Polígono  — clique para adicionar vértices; duplo-clique ou Enter para fechar;
              ESC cancela.

Coordenadas normalizadas [0.0–1.0]: imunes a mudança de resolução.
"""
import tkinter as tk
from tkinter import ttk

import cv2
import numpy as np

try:
    from PIL import Image as _PIL, ImageTk as _PILTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# ── Paleta ─────────────────────────────────────────────────────────────────────
BG        = "#050A12"
BG_CARD   = "#08131E"
BG_ROW    = "#0C1E2E"
AMARELO   = "#00D4FF"
BRANCO    = "#C8E8F8"
CINZA     = "#4A6070"
CINZA_ESC = "#152030"
VERDE     = "#00CC77"
VERMELHO  = "#FF2255"

# Cores das zonas (BGR OpenCV | hex Tkinter)
_CORES = [
    {"bgr": (255, 212,   0), "hex": "#00D4FF"},
    {"bgr": (119, 204,   0), "hex": "#00CC77"},
    {"bgr": (153,  68, 255), "hex": "#FF4499"},
    {"bgr": (  0, 165, 255), "hex": "#FFA500"},
    {"bgr": (238, 153,   0), "hex": "#0099EE"},
    {"bgr": (  0, 255, 128), "hex": "#80FF00"},
    {"bgr": (128,   0, 255), "hex": "#8000FF"},
    {"bgr": (255,   0, 128), "hex": "#FF0080"},
]

_CW, _CH   = 760, 430          # dimensões fixas do canvas
_HR        = 6                 # raio de detecção das alças (px)
_HANDLES   = ("nw","n","ne","e","se","s","sw","w")


def _bgr(idx: int) -> tuple:   return _CORES[idx % len(_CORES)]["bgr"]
def _hex(idx: int) -> str:     return _CORES[idx % len(_CORES)]["hex"]


def _zona_bbox(pontos: list) -> list:
    """Bounding box normalizada de uma lista de pontos [[x,y]...]."""
    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]
    return [min(xs), min(ys), max(xs), max(ys)]


def _handle_centers(x1, y1, x2, y2) -> dict:
    """Posições (px) das 8 alças de um retângulo em coordenadas de canvas."""
    mx, my = (x1 + x2) // 2, (y1 + y2) // 2
    return {
        "nw": (x1, y1), "n": (mx, y1), "ne": (x2, y1),
        "e":  (x2, my),
        "se": (x2, y2), "s": (mx, y2), "sw": (x1, y2),
        "w":  (x1, my),
    }


def _cursor_for_handle(h: str) -> str:
    return {
        "nw": "top_left_corner",  "ne": "top_right_corner",
        "se": "bottom_right_corner", "sw": "bottom_left_corner",
        "n":  "top_side",  "s": "bottom_side",
        "e":  "right_side", "w": "left_side",
    }.get(h, "crosshair")


class ZonaEditorDialog:
    """
    Editor visual para múltiplas zonas de detecção.

    on_salvar(zonas: list) — callback com lista de dicts:
        {"nome": str, "tipo": "rect"|"poly",
         "zona": [x1,y1,x2,y2],          # bounding box (sempre presente)
         "pontos": [[x,y],...],           # apenas para polígonos
         "cor_idx": int}
    """

    def __init__(self, root: tk.Tk, slot, on_salvar=None):
        self._root      = root
        self._slot      = slot
        self._on_salvar = on_salvar

        # Cópia das zonas (deep)
        src = getattr(slot, "zonas_roi", []) or []
        self._zonas: list[dict] = [dict(z) for z in src]
        for i, z in enumerate(self._zonas):
            z.setdefault("cor_idx", i)
            z.setdefault("tipo", "rect")

        # ── Estado do editor ──────────────────────────────────────────────────
        self._modo       = "idle"   # idle | rect | poly | resize | move
        self._modo_tipo  = "rect"   # tipo padrão: "rect" | "poly"
        self._p1: tuple | None = None   # ponto inicial (canvas px)
        self._p2: tuple | None = None   # ponto atual
        self._poly_pts: list   = []     # [(nx,ny)...] polígono em construção
        self._zona_sel: int | None = None
        # Resize
        self._res_idx    = -1
        self._res_handle = ""
        # Move
        self._mv_idx   = -1
        self._mv_orig  = []
        self._mv_start = (0, 0)
        # Hover
        self._hov_idx    = -1
        self._hov_handle = ""

        # Frame de referência
        self._frame_bgr: np.ndarray | None = None
        self._photo = None

        self._win = tk.Toplevel(root)
        self._win.title(f"Zonas de Detecção — {slot.cfg.get('id','?')}")
        self._win.configure(bg=BG)
        self._win.resizable(False, False)
        self._win.grab_set()
        self._win.protocol("WM_DELETE_WINDOW", self._fechar)

        self._montar_ui()
        self._capturar_frame()
        self._redesenhar()
        self._loop_frame()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _montar_ui(self):
        cam = self._slot.cfg.get("id", "?")

        # Cabeçalho
        cab = tk.Frame(self._win, bg=AMARELO, padx=14, pady=7)
        cab.pack(fill="x")
        tk.Label(cab, text=f"Zonas de Detecção — {cam}",
                 font=("Segoe UI", 10, "bold"), bg=AMARELO, fg=BG).pack(side="left")

        # Canvas de vídeo
        frm_cv = tk.Frame(self._win, bg=BG, padx=8, pady=4)
        frm_cv.pack()
        self._canvas = tk.Canvas(frm_cv, width=_CW, height=_CH, bg="black",
                                  highlightthickness=1, highlightbackground=CINZA,
                                  cursor="crosshair")
        self._canvas.pack()
        self._canvas.bind("<Motion>",          self._on_move)
        self._canvas.bind("<ButtonPress-1>",   self._on_press)
        self._canvas.bind("<B1-Motion>",       self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self._canvas.bind("<Double-Button-1>", self._on_dbl)
        self._win.bind("<Escape>",             self._on_esc)
        self._win.bind("<Return>",             self._on_enter)

        # Barra de ferramentas
        frm_bar = tk.Frame(self._win, bg=BG_CARD, padx=8, pady=5)
        frm_bar.pack(fill="x")

        self._btn_rect = tk.Button(frm_bar, text=" ▭ Retângulo ",
                                    font=("Segoe UI", 9, "bold"),
                                    bg=VERDE, fg=BG, relief="flat",
                                    padx=6, pady=2,
                                    command=lambda: self._definir_tipo("rect"))
        self._btn_rect.pack(side="left")

        self._btn_poly = tk.Button(frm_bar, text=" ✏ Polígono ",
                                    font=("Segoe UI", 9),
                                    bg=CINZA_ESC, fg=BRANCO, relief="flat",
                                    padx=6, pady=2,
                                    command=lambda: self._definir_tipo("poly"))
        self._btn_poly.pack(side="left", padx=(4, 0))

        tk.Frame(frm_bar, bg=CINZA, width=1).pack(side="left", fill="y",
                                                    padx=8)

        tk.Button(frm_bar, text=" + Nova Zona ",
                  font=("Segoe UI", 9),
                  bg="#0C2233", fg=AMARELO, relief="flat",
                  padx=6, pady=2,
                  command=self._iniciar_nova).pack(side="left")

        self._sv_status = tk.StringVar(value="Clique e arraste no vídeo para criar uma zona")
        tk.Label(frm_bar, textvariable=self._sv_status,
                 font=("Segoe UI", 8), bg=BG_CARD, fg=CINZA,
                 padx=10).pack(side="left")

        tk.Button(frm_bar, text=" ↺ ",
                  font=("Segoe UI", 9),
                  bg=CINZA_ESC, fg=BRANCO, relief="flat",
                  padx=4, pady=2,
                  command=lambda: (self._capturar_frame(), self._redesenhar())
                  ).pack(side="right")

        tk.Frame(self._win, bg=CINZA_ESC, height=1).pack(fill="x")

        # Lista de zonas
        tk.Label(self._win, text="  ZONAS CONFIGURADAS",
                 font=("Segoe UI", 8, "bold"), bg=BG, fg=CINZA,
                 pady=4, anchor="w").pack(fill="x")

        frm_scroll = tk.Frame(self._win, bg=BG)
        frm_scroll.pack(fill="both", expand=True, padx=6, pady=(0, 4))

        self._cv_lista = tk.Canvas(frm_scroll, bg=BG, height=110,
                                    highlightthickness=0)
        sb = ttk.Scrollbar(frm_scroll, orient="vertical",
                            command=self._cv_lista.yview)
        self._cv_lista.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self._cv_lista.pack(side="left", fill="both", expand=True)

        self._frm_lista = tk.Frame(self._cv_lista, bg=BG)
        self._cv_lista.create_window((0, 0), window=self._frm_lista,
                                      anchor="nw")
        self._frm_lista.bind("<Configure>",
                              lambda e: self._cv_lista.configure(
                                  scrollregion=self._cv_lista.bbox("all")))
        self._reconstruir_lista()

        tk.Frame(self._win, bg=CINZA_ESC, height=1).pack(fill="x")

        # Rodapé
        frm_fim = tk.Frame(self._win, bg=BG, padx=8, pady=6)
        frm_fim.pack(fill="x")

        tk.Button(frm_fim, text="  Salvar Zonas  ",
                  font=("Segoe UI", 9, "bold"),
                  bg=VERDE, fg=BG, relief="flat",
                  padx=10, pady=3, command=self._salvar).pack(side="left")

        tk.Button(frm_fim, text="  Remover Todas  ",
                  font=("Segoe UI", 9),
                  bg=BG_CARD, fg=BRANCO, relief="flat",
                  padx=8, pady=3,
                  command=self._remover_todas).pack(side="left", padx=(6, 0))

        tk.Button(frm_fim, text="  Cancelar  ",
                  font=("Segoe UI", 9),
                  bg=BG_CARD, fg=CINZA, relief="flat",
                  padx=8, pady=3,
                  command=self._fechar).pack(side="right")

    def _definir_tipo(self, tipo: str):
        self._modo_tipo = tipo
        ativo   = VERDE if tipo == "rect" else CINZA_ESC
        inativo = CINZA_ESC if tipo == "rect" else VERDE
        fg_a    = BG if tipo == "rect" else BRANCO
        fg_i    = BRANCO if tipo == "rect" else BG
        self._btn_rect.config(bg=ativo,   fg=fg_a)
        self._btn_poly.config(bg=inativo, fg=fg_i)
        hint = ("Clique e arraste para criar retângulo"
                if tipo == "rect"
                else "Clique para adicionar vértices  |  Enter / duplo-clique = fechar  |  ESC = cancelar")
        self._sv_status.set(hint)

    def _reconstruir_lista(self):
        for w in self._frm_lista.winfo_children():
            w.destroy()
        if not self._zonas:
            tk.Label(self._frm_lista,
                     text="  Nenhuma zona — câmera toda monitorada.",
                     font=("Segoe UI", 9), bg=BG, fg=CINZA,
                     pady=10).pack(anchor="w")
            return
        for i, z in enumerate(self._zonas):
            self._linha_zona(i, z)
        self._cv_lista.configure(scrollregion=self._cv_lista.bbox("all"))

    def _linha_zona(self, idx: int, z: dict):
        bg_row = BG_ROW if idx == self._zona_sel else BG
        row = tk.Frame(self._frm_lista, bg=bg_row, padx=5, pady=3)
        row.pack(fill="x", pady=1)
        row.bind("<Button-1>", lambda e, i=idx: self._selecionar(i))

        # Cor
        tk.Canvas(row, width=12, height=12,
                  bg=_hex(z.get("cor_idx", idx)),
                  highlightthickness=0).pack(side="left", padx=(0, 6))

        # Tipo badge
        tipo_txt = "POLY" if z.get("tipo") == "poly" else "RECT"
        tk.Label(row, text=tipo_txt, font=("Consolas", 7),
                 bg=bg_row, fg=CINZA, width=4).pack(side="left")

        # Nome
        sv = tk.StringVar(value=z.get("nome", f"Zona {idx+1}"))
        sv.trace_add("write", lambda *a, i=idx, s=sv: self._renomear(i, s))
        tk.Entry(row, textvariable=sv,
                 font=("Segoe UI", 9), bg="#0C1825", fg=BRANCO,
                 insertbackground=AMARELO, relief="flat", width=16,
                 highlightthickness=1, highlightbackground=CINZA_ESC
                 ).pack(side="left", padx=(0, 8))

        # % cobertura
        coord = z.get("zona", [0, 0, 1, 1])
        pct = (coord[2] - coord[0]) * (coord[3] - coord[1]) * 100
        tk.Label(row, text=f"{pct:.0f}%",
                 font=("Segoe UI", 8), bg=bg_row, fg=CINZA,
                 width=5).pack(side="left")

        # Redefinir
        tk.Button(row, text="Redefinir",
                  font=("Segoe UI", 8), bg=CINZA_ESC, fg=BRANCO,
                  relief="flat", padx=3, pady=1,
                  command=lambda i=idx: self._iniciar_redefinir(i)
                  ).pack(side="left", padx=(2, 2))

        # Excluir
        tk.Button(row, text="✕",
                  font=("Segoe UI", 8, "bold"), bg="#180810", fg=VERMELHO,
                  relief="flat", padx=4, pady=1,
                  command=lambda i=idx: self._excluir(i)
                  ).pack(side="left")

    # ── Modo / seleção ────────────────────────────────────────────────────────

    def _iniciar_nova(self):
        self._modo = self._modo_tipo
        hint = ("Arraste no vídeo para definir retângulo"
                if self._modo_tipo == "rect"
                else "Clique para adicionar vértices — Enter/duplo-clique para fechar")
        self._sv_status.set(hint)
        self._poly_pts = []
        self._canvas.config(cursor="crosshair")

    def _iniciar_redefinir(self, idx: int):
        self._zona_sel = idx
        tipo = self._zonas[idx].get("tipo", "rect")
        self._modo = tipo
        self._poly_pts = []
        nome = self._zonas[idx].get("nome", f"Zona {idx+1}")
        self._sv_status.set(f"Redesenhe '{nome}' — substituirá a zona atual")
        self._canvas.config(cursor="crosshair")
        # Marca qual zona será substituída (usamos None para nova, idx para substituição)
        self._redefinir_idx = idx
        self._reconstruir_lista()
        self._redesenhar()

    def _selecionar(self, idx: int):
        self._zona_sel = idx
        self._reconstruir_lista()
        self._redesenhar()

    def _renomear(self, idx: int, sv: tk.StringVar):
        if 0 <= idx < len(self._zonas):
            self._zonas[idx]["nome"] = sv.get()

    def _excluir(self, idx: int):
        if 0 <= idx < len(self._zonas):
            self._zonas.pop(idx)
            if self._zona_sel == idx:
                self._zona_sel = None
            elif self._zona_sel and self._zona_sel > idx:
                self._zona_sel -= 1
            self._reconstruir_lista()
            self._redesenhar()

    def _remover_todas(self):
        self._zonas.clear()
        self._zona_sel = None
        self._modo = "idle"
        self._poly_pts = []
        self._reconstruir_lista()
        self._redesenhar()

    # ── Eventos do canvas ─────────────────────────────────────────────────────

    def _on_move(self, e):
        x, y = e.x, e.y

        # Só verifica hover quando idle
        if self._modo not in ("idle", "rect", "poly"):
            return

        prev_hov = (self._hov_idx, self._hov_handle)

        self._hov_idx    = -1
        self._hov_handle = ""

        for i, z in enumerate(self._zonas):
            if z.get("tipo", "rect") != "rect":
                continue
            coord = z.get("zona", [])
            if len(coord) != 4:
                continue
            px1 = int(coord[0] * _CW); py1 = int(coord[1] * _CH)
            px2 = int(coord[2] * _CW); py2 = int(coord[3] * _CH)
            hcs = _handle_centers(px1, py1, px2, py2)
            # Verifica alças
            for hname, (hx, hy) in hcs.items():
                if abs(x - hx) <= _HR + 2 and abs(y - hy) <= _HR + 2:
                    self._hov_idx    = i
                    self._hov_handle = hname
                    self._canvas.config(cursor=_cursor_for_handle(hname))
                    return
            # Verifica interior (mover)
            if px1 < x < px2 and py1 < y < py2:
                self._hov_idx    = i
                self._hov_handle = "body"
                self._canvas.config(cursor="fleur")
                return

        # Cursor padrão conforme modo
        cur = "crosshair" if self._modo in ("rect", "poly") else "arrow"
        self._canvas.config(cursor=cur)

        # Redesenha se hover mudou (para atualizar destaque)
        if (self._hov_idx, self._hov_handle) != prev_hov:
            self._redesenhar()

    def _on_press(self, e):
        x, y = e.x, e.y

        # ── Redimensionar / mover zona existente (modo idle) ──────────────────
        if self._modo == "idle" or (self._modo in ("rect", "poly") and self._hov_idx >= 0):
            if self._hov_handle and self._hov_handle != "body":
                # Resize
                self._res_idx    = self._hov_idx
                self._res_handle = self._hov_handle
                self._modo       = "resize"
                return
            if self._hov_handle == "body":
                # Move
                self._mv_idx   = self._hov_idx
                self._mv_orig  = list(self._zonas[self._hov_idx]["zona"])
                self._mv_start = (x, y)
                self._selecionar(self._hov_idx)
                self._modo = "move"
                return
            # Clique em área vazia em idle → inicia retângulo
            if self._modo == "idle":
                self._modo = self._modo_tipo
                self._poly_pts = []
                self._redefinir_idx = None

        # ── Polígono — adiciona vértice ───────────────────────────────────────
        if self._modo == "poly":
            nx, ny = x / _CW, y / _CH
            self._poly_pts.append((round(nx, 4), round(ny, 4)))
            n = len(self._poly_pts)
            if n >= 3:
                self._sv_status.set(
                    f"{n} pontos — duplo-clique ou Enter para FECHAR  |  ESC cancela")
            else:
                self._sv_status.set(
                    f"{n} ponto(s) — continue clicando para adicionar vértices")
            self._redesenhar()
            return

        # ── Retângulo — ponto inicial ─────────────────────────────────────────
        if self._modo == "rect":
            self._p1 = (x, y)
            self._p2 = (x, y)

    def _on_drag(self, e):
        x = max(0, min(e.x, _CW - 1))
        y = max(0, min(e.y, _CH - 1))

        if self._modo == "resize":
            self._aplicar_resize(x, y)
            self._redesenhar()
            return

        if self._modo == "move":
            self._aplicar_move(x, y)
            self._redesenhar()
            return

        if self._modo == "rect" and self._p1:
            self._p2 = (x, y)
            self._redesenhar()

    def _on_release(self, e):
        if self._modo in ("resize", "move"):
            # Atualiza bounding box se for polígono
            idx = self._res_idx if self._modo == "resize" else self._mv_idx
            if 0 <= idx < len(self._zonas):
                z = self._zonas[idx]
                if z.get("tipo") == "poly" and z.get("pontos"):
                    z["zona"] = _zona_bbox(z["pontos"])
            self._modo = "idle"
            self._redesenhar()
            return

        if self._modo == "rect" and self._p1 and self._p2:
            self._finalizar_rect()

    def _on_dbl(self, e):
        if self._modo == "poly":
            self._fechar_poligono()

    def _on_esc(self, _e=None):
        if self._modo in ("rect", "poly"):
            self._p1 = self._p2 = None
            self._poly_pts.clear()
            self._modo = "idle"
            self._sv_status.set("Cancelado.")
            self._redesenhar()

    def _on_enter(self, _e=None):
        if self._modo == "poly" and len(self._poly_pts) >= 3:
            self._fechar_poligono()

    # ── Resize / move ─────────────────────────────────────────────────────────

    def _aplicar_resize(self, px: int, py: int):
        idx = self._res_idx
        if not (0 <= idx < len(self._zonas)):
            return
        z = self._zonas[idx]
        coord = list(z.get("zona", [0, 0, 1, 1]))
        x1, y1, x2, y2 = coord
        nx = px / _CW;  ny = py / _CH
        h = self._res_handle
        if "n" in h:  y1 = max(0.0,  min(ny, y2 - 0.02))
        if "s" in h:  y2 = min(1.0,  max(ny, y1 + 0.02))
        if "w" in h:  x1 = max(0.0,  min(nx, x2 - 0.02))
        if "e" in h:  x2 = min(1.0,  max(nx, x1 + 0.02))
        z["zona"] = [round(x1,4), round(y1,4), round(x2,4), round(y2,4)]

    def _aplicar_move(self, px: int, py: int):
        idx = self._mv_idx
        if not (0 <= idx < len(self._zonas)):
            return
        dx = (px - self._mv_start[0]) / _CW
        dy = (py - self._mv_start[1]) / _CH
        ox1, oy1, ox2, oy2 = self._mv_orig
        bw, bh = ox2 - ox1, oy2 - oy1
        nx1 = max(0.0, min(ox1 + dx, 1.0 - bw))
        ny1 = max(0.0, min(oy1 + dy, 1.0 - bh))
        self._zonas[idx]["zona"] = [round(nx1,4), round(ny1,4),
                                     round(nx1+bw,4), round(ny1+bh,4)]

    # ── Finalização de formas ─────────────────────────────────────────────────

    def _finalizar_rect(self):
        cx1, cy1 = self._p1
        cx2, cy2 = self._p2
        self._p1 = self._p2 = None
        nx1, ny1 = min(cx1,cx2)/_CW, min(cy1,cy2)/_CH
        nx2, ny2 = max(cx1,cx2)/_CW, max(cy1,cy2)/_CH
        if (nx2-nx1) < 0.02 or (ny2-ny1) < 0.02:
            self._sv_status.set("Zona muito pequena — tente novamente.")
            self._modo = "idle"
            return
        coord = [round(nx1,4), round(ny1,4), round(nx2,4), round(ny2,4)]
        self._salvar_forma("rect", coord, None)

    def _fechar_poligono(self):
        pts = self._poly_pts
        if len(pts) < 3:
            self._sv_status.set("Mínimo 3 pontos para fechar o polígono.")
            return
        coord = _zona_bbox(pts)
        self._salvar_forma("poly", coord, list(pts))
        self._poly_pts = []

    def _salvar_forma(self, tipo: str, coord: list, pontos):
        idx = getattr(self, "_redefinir_idx", None)
        cor_idx = (len(self._zonas) % len(_CORES)) if idx is None else self._zonas[idx].get("cor_idx", 0)
        nova = {
            "nome":    (self._zonas[idx]["nome"] if idx is not None
                        else f"Zona {len(self._zonas)+1}"),
            "tipo":    tipo,
            "zona":    coord,
            "cor_idx": cor_idx,
        }
        if pontos is not None:
            nova["pontos"] = pontos
        if idx is not None and 0 <= idx < len(self._zonas):
            self._zonas[idx] = nova
            self._zona_sel = idx
        else:
            self._zonas.append(nova)
            self._zona_sel = len(self._zonas) - 1
        self._redefinir_idx = None
        self._modo = "idle"
        self._sv_status.set(f"'{nova['nome']}' salva.")
        self._reconstruir_lista()
        self._redesenhar()

    # ── Renderização ──────────────────────────────────────────────────────────

    def _capturar_frame(self):
        f = self._slot.get_frame()
        if f is not None:
            self._frame_bgr = f.copy()

    def _loop_frame(self):
        try:
            if not self._win.winfo_exists():
                return
        except tk.TclError:
            return
        self._capturar_frame()
        self._redesenhar()
        self._win.after(800, self._loop_frame)

    def _redesenhar(self):
        if self._frame_bgr is not None:
            img = cv2.resize(self._frame_bgr, (_CW, _CH),
                             interpolation=cv2.INTER_LINEAR)
        else:
            img = np.zeros((_CH, _CW, 3), dtype=np.uint8)
            cv2.putText(img, "Aguardando frame...", (_CW//4, _CH//2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (70,70,80), 1)

        # ── Zonas salvas ──────────────────────────────────────────────────────
        for i, z in enumerate(self._zonas):
            cor = _bgr(z.get("cor_idx", i))
            selecionada = (i == self._zona_sel)
            hovered     = (i == self._hov_idx)
            espessura   = 2 if (selecionada or hovered) else 1
            nome_z      = z.get("nome", f"Zona {i+1}")

            if z.get("tipo") == "poly":
                pts_n = z.get("pontos", [])
                if len(pts_n) >= 3:
                    pts = np.array([[int(p[0]*_CW), int(p[1]*_CH)]
                                    for p in pts_n], np.int32)
                    cv2.polylines(img, [pts], True, cor, espessura)
                    cx = int(np.mean([p[0] for p in pts_n]) * _CW)
                    cy = int(np.mean([p[1] for p in pts_n]) * _CH)
                    cv2.putText(img, nome_z, (cx - 20, cy),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.42, cor, 1)
                    for pt in pts:
                        cv2.circle(img, tuple(pt), 4, cor, -1)
            else:
                coord = z.get("zona", [])
                if len(coord) == 4:
                    px1 = int(coord[0]*_CW); py1 = int(coord[1]*_CH)
                    px2 = int(coord[2]*_CW); py2 = int(coord[3]*_CH)
                    cv2.rectangle(img, (px1,py1), (px2,py2), cor, espessura)
                    # Cantos táticos
                    arm = max(5, min(14, min(px2-px1, py2-py1)//5))
                    for (px, py, dx, dy) in [
                        (px1,py1, 1, 1),(px2,py1,-1, 1),
                        (px1,py2, 1,-1),(px2,py2,-1,-1),
                    ]:
                        cv2.line(img,(px,py),(px+dx*arm,py),cor,2)
                        cv2.line(img,(px,py),(px,py+dy*arm),cor,2)
                    if (px2-px1)>30 and (py2-py1)>12:
                        cv2.putText(img, nome_z, (px1+4, py1+13),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, cor, 1)
                    pct = (coord[2]-coord[0])*(coord[3]-coord[1])*100
                    if (px2-px1)>55:
                        tw = cv2.getTextSize(f"{pct:.0f}%",
                             cv2.FONT_HERSHEY_SIMPLEX, 0.38, 1)[0][0]
                        cv2.putText(img, f"{pct:.0f}%", (px2-tw-3, py2-3),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, cor, 1)
                    # Alças (apenas zona selecionada ou hover)
                    if selecionada or hovered:
                        hcs = _handle_centers(px1, py1, px2, py2)
                        for hname, (hx, hy) in hcs.items():
                            activo = (hname == self._hov_handle and i == self._hov_idx)
                            fill = cor if activo else (30,30,40)
                            cv2.rectangle(img, (hx-_HR, hy-_HR),
                                          (hx+_HR, hy+_HR), cor, -1 if activo else 1)

        # ── Retângulo sendo desenhado ─────────────────────────────────────────
        if self._modo == "rect" and self._p1 and self._p2:
            cor_d = _bgr(len(self._zonas) % len(_CORES))
            ax1, ay1 = min(self._p1[0],self._p2[0]), min(self._p1[1],self._p2[1])
            ax2, ay2 = max(self._p1[0],self._p2[0]), max(self._p1[1],self._p2[1])
            ov = img.copy()
            cv2.rectangle(ov,(ax1,ay1),(ax2,ay2),cor_d,-1)
            cv2.addWeighted(ov,0.18,img,0.82,0,img)
            cv2.rectangle(img,(ax1,ay1),(ax2,ay2),cor_d,2)
            pct = (ax2-ax1)*(ay2-ay1)/(_CW*_CH)*100
            cv2.putText(img,f"{pct:.0f}%",(ax1+4,ay2-4),
                        cv2.FONT_HERSHEY_SIMPLEX,0.40,cor_d,1)

        # ── Polígono sendo desenhado ──────────────────────────────────────────
        if self._modo == "poly":
            cor_d = _bgr(len(self._zonas) % len(_CORES))
            pts = [(int(p[0]*_CW), int(p[1]*_CH)) for p in self._poly_pts]
            for pt in pts:
                cv2.circle(img, pt, 5, cor_d, -1)
            if len(pts) >= 2:
                cv2.polylines(img, [np.array(pts, np.int32)], False, cor_d, 1)
            # Linha guia até posição atual do cursor
            if pts:
                cv2.putText(img, f"{len(pts)} ponto(s) — Enter/duplo-clique para fechar",
                            (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, cor_d, 1)

        # ── Banner de modo ────────────────────────────────────────────────────
        if self._modo in ("rect", "poly"):
            label = "DESENHANDO RETÂNGULO" if self._modo == "rect" else "DESENHANDO POLÍGONO"
            cv2.rectangle(img, (0,0), (_CW-1, 20), (15,45,65), -1)
            cv2.putText(img, label, (4,14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255,212,0), 1)

        # ── Exibe ─────────────────────────────────────────────────────────────
        if not _PIL_OK:
            return
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil = _PIL.fromarray(rgb)
        self._photo = _PILTk.PhotoImage(image=pil)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._photo)

    # ── Salvar / fechar ───────────────────────────────────────────────────────

    def _salvar(self):
        # Fecha automaticamente polígono em andamento (evita perda se usuário não pressionou Enter)
        if self._modo == "poly" and len(self._poly_pts) >= 3:
            self._fechar_poligono()

        export = []
        for i, z in enumerate(self._zonas):
            d = {"nome": z.get("nome", f"Zona {i+1}"),
                 "tipo": z.get("tipo", "rect"),
                 "zona": z.get("zona", [0,0,1,1]),
                 "cor_idx": z.get("cor_idx", i)}
            if z.get("tipo") == "poly" and z.get("pontos"):
                d["pontos"] = z["pontos"]
            export.append(d)
        if self._on_salvar:
            self._on_salvar(export)
        self._fechar()

    def _fechar(self):
        try:
            self._win.destroy()
        except Exception:
            pass
        try:
            self._root.quit()
        except Exception:
            pass
