"""
Mosaico de cameras - SPARTA AGENTE IA
Suporte a layouts 1CH / 4CH / 16CH / 32CH, expansao de slot e analise IA compartilhada.
"""
import json
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

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

# Botoes da toolbar
_TOOLBAR_BTN_W = 72
_TOOLBAR_BTN_H = 24
_TOOLBAR_BTN_GAP = 8
_TOOLBAR_BTN_Y0 = (TOOLBAR_H - _TOOLBAR_BTN_H) // 2

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
        self.idx        = idx
        self.cfg        = cfg_cam
        self.frame      = None       # armazenado em CAP_W x CAP_H
        self.resultado  = {}
        self.em_analise = False
        self._lock      = threading.Lock()
        self._cap       = None
        self._rodando   = False
        self._thread    = threading.Thread(target=self._loop, daemon=True)

    def iniciar(self, rtsp_uri: str):
        self._uri     = rtsp_uri
        self._rodando = True
        self._thread.start()

    def parar(self):
        self._rodando = False

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

    def _loop(self):
        atraso = 1.0
        while self._rodando:
            if self._cap:
                self._cap.release()
            self._cap = cv2.VideoCapture(self._uri)
            if not self._cap.isOpened():
                time.sleep(atraso)
                atraso = min(atraso * 2, 30)
                continue
            atraso = 1.0
            while self._rodando:
                ok, frame = self._cap.read()
                if not ok:
                    break
                thumb = cv2.resize(frame, (CAP_W, CAP_H),
                                   interpolation=cv2.INTER_LINEAR)
                with self._lock:
                    self.frame = thumb


# ── Fila de analise IA ────────────────────────────────────────────────────────
class FilaAnalise:
    def __init__(self, intervalo: int = 3):
        self._q         = queue.Queue()
        self._intervalo = intervalo
        self._ultimo    = {}
        self._thread    = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def enfileirar(self, slot: CameraSlot, frame_id: str, frame):
        agora = time.monotonic()
        if agora - self._ultimo.get(slot.idx, 0) < self._intervalo:
            return
        if slot.em_analise:
            return
        slot.em_analise = True
        self._ultimo[slot.idx] = agora
        self._q.put((slot, frame_id, frame.copy()))

    def _worker(self):
        from analyzer import analisar_frame
        import db
        while True:
            slot, frame_id, frame = self._q.get()
            try:
                camera_id = slot.cfg["id"]
                resultado, tokens_in, tokens_out = analisar_frame(
                    frame, frame_id, camera_id=camera_id
                )
                slot.set_resultado(resultado)
                nivel = resultado.get("nivel_risco", "sem_risco")
                log.info("[%s] %s (%.0f%%) | tokens: %d/%d",
                         camera_id, nivel.upper(),
                         resultado.get("confianca", 0) * 100,
                         tokens_in, tokens_out)
                if resultado.get("alerta"):
                    log.warning("[%s] ALERTA: %s", camera_id,
                                resultado.get("acao_recomendada"))

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
                log.error("[%s] Erro IA: %s", slot.cfg["id"], exc)
                slot.em_analise = False
            finally:
                self._q.task_done()


# ── Renderizacao dos slots ────────────────────────────────────────────────────
def _slot_vazio(idx: int, hover: bool, w: int, h: int) -> np.ndarray:
    bg  = (45, 45, 45) if hover else C_CARD
    img = np.full((h, w, 3), bg, dtype=np.uint8)
    borda = C_AMARELO if hover else C_CINZA
    cv2.rectangle(img, (1, 1), (w - 2, h - 2), borda, 1)

    escala = max(0.28, min(0.55, w / 580))
    txt = "+ Adicionar"
    tw  = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, escala, 1)[0][0]
    cv2.putText(img, txt, ((w - tw) // 2, h // 2),
                cv2.FONT_HERSHEY_SIMPLEX, escala, C_AMARELO, 1)
    if h > 80:
        num = f"Slot {idx + 1}"
        cv2.putText(img, num, (6, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, C_CINZA, 1)
    return img


def _slot_camera(slot: CameraSlot, w: int, h: int) -> np.ndarray:
    frame = slot.get_frame()
    if frame is None:
        img = np.full((h, w, 3), C_CARD, dtype=np.uint8)
        cv2.putText(img, "Conectando...", (max(4, w // 5), h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, max(0.3, w / 900), C_CINZA, 1)
        return img

    img = cv2.resize(frame, (w, h), interpolation=cv2.INTER_LINEAR)
    res = slot.get_resultado()
    nivel = res.get("nivel_risco", "")
    cor   = NIVEL_COR.get(nivel, C_CINZA)

    bar_h = max(16, h // 14)
    escala = max(0.28, min(0.50, w / 640))

    # Barra superior
    cv2.rectangle(img, (0, 0), (w, bar_h), (0, 0, 0), -1)
    cv2.putText(img, slot.cfg["id"], (4, bar_h - 4),
                cv2.FONT_HERSHEY_SIMPLEX, escala, C_BRANCO, 1)

    if nivel:
        r = max(4, bar_h // 3)
        cv2.circle(img, (w - r - 4, bar_h // 2), r, cor, -1)
        if w > 120:
            etiq = nivel.upper()
            tw = cv2.getTextSize(etiq, cv2.FONT_HERSHEY_SIMPLEX, escala * 0.8, 1)[0][0]
            cv2.putText(img, etiq, (w - r * 2 - tw - 6, bar_h - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, escala * 0.8, cor, 1)

    # Barra de alerta inferior
    if res.get("alerta") and res.get("acao_recomendada") and h > 60:
        acao = res["acao_recomendada"]
        max_chars = max(10, w // 7)
        acao = acao[:max_chars]
        cv2.rectangle(img, (0, h - bar_h), (w, h), (0, 0, 0), -1)
        cv2.putText(img, acao, (4, h - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, escala * 0.85, cor, 1)

    return img


# ── Cabecalho ─────────────────────────────────────────────────────────────────
def _cabecalho(n_ativas: int, layout: int) -> np.ndarray:
    img = np.full((HDR_H, WIN_W, 3), (20, 20, 20), dtype=np.uint8)
    cv2.rectangle(img, (0, HDR_H - 2), (WIN_W, HDR_H), C_AMARELO, -1)
    cv2.putText(img, "SPARTA AGENTE IA", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, C_AMARELO, 1)
    cols, rows = LAYOUTS[layout]
    info = (f"{n_ativas} cam  |  {cols}x{rows}  |  "
            f"{datetime.now().strftime('%H:%M:%S')}")
    tw = cv2.getTextSize(info, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)[0][0]
    cv2.putText(img, info, (WIN_W - tw - 10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, C_CINZA, 1)
    return img


# ── Toolbar de layout ─────────────────────────────────────────────────────────
def _toolbar(layout_atual: int, hover_btn: int) -> np.ndarray:
    img = np.full((TOOLBAR_H, WIN_W, 3), (25, 25, 25), dtype=np.uint8)
    cv2.line(img, (0, TOOLBAR_H - 1), (WIN_W, TOOLBAR_H - 1), (50, 50, 50), 1)

    labels = ["1CH", "4CH", "16CH", "32CH"]
    for i, (label, val) in enumerate(zip(labels, LAYOUT_ORDER)):
        x0 = 10 + i * (_TOOLBAR_BTN_W + _TOOLBAR_BTN_GAP)
        x1 = x0 + _TOOLBAR_BTN_W
        ativo  = val == layout_atual
        hover  = i == hover_btn and not ativo
        if ativo:
            bg, fg = C_AMARELO, C_BG
        elif hover:
            bg, fg = (60, 60, 60), C_BRANCO
        else:
            bg, fg = (40, 40, 40), C_CINZA

        cv2.rectangle(img, (x0, _TOOLBAR_BTN_Y0), (x1, _TOOLBAR_BTN_Y0 + _TOOLBAR_BTN_H), bg, -1)
        tw = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)[0][0]
        ty = _TOOLBAR_BTN_Y0 + _TOOLBAR_BTN_H - 7
        cv2.putText(img, label, (x0 + (_TOOLBAR_BTN_W - tw) // 2, ty),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, fg, 1)

    # Dica de teclas
    dica = "[Q] Sair  [T] Treinamento  |  Clique na camera para expandir"
    tw = cv2.getTextSize(dica, cv2.FONT_HERSHEY_SIMPLEX, 0.33, 1)[0][0]
    cv2.putText(img, dica, (WIN_W - tw - 10, TOOLBAR_H - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.33, C_CINZA, 1)

    return img


# ── Montagem do mosaico ───────────────────────────────────────────────────────
def _montar_mosaico(slots: dict, state: dict) -> np.ndarray:
    layout    = state["layout"]
    expandido = state["expandido"]
    hover     = state["hover"]
    hover_btn = state["hover_btn"]

    cols, rows = LAYOUTS[layout]
    max_cams   = cols * rows
    slot_w     = MOSAIC_W // cols
    slot_h     = MOSAIC_H // rows

    cab     = _cabecalho(len(slots), layout)
    toolbar = _toolbar(layout, hover_btn)

    if expandido is not None and expandido in slots:
        # Camera expandida ocupa toda a area de video
        video = _slot_camera(slots[expandido], MOSAIC_W, MOSAIC_H)
        cv2.putText(video, "Clique para voltar", (10, MOSAIC_H - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, C_CINZA, 1)
    else:
        celulas = []
        for i in range(max_cams):
            if i in slots:
                celulas.append(_slot_camera(slots[i], slot_w, slot_h))
            else:
                celulas.append(_slot_vazio(i, i == hover, slot_w, slot_h))

        linhas = []
        for r in range(rows):
            linha = np.hstack(celulas[r * cols:(r + 1) * cols])
            linhas.append(linha)
        video = np.vstack(linhas)

    return np.vstack([cab, toolbar, video])


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
def _dialogo_adicionar(slot_idx: int) -> dict | None:
    import tkinter as tk

    BG2 = "#0F0F0F"; AMA = "#FFD000"; AESC = "#B39200"
    ENT = "#242424"; BCOR = "#F0F0F0"; CESC = "#333333"

    resultado = []
    d = tk.Tk()
    d.title(f"Adicionar Camera - Slot {slot_idx + 1}")
    d.configure(bg=BG2)
    d.resizable(False, False)

    cab2 = tk.Frame(d, bg=AMA, padx=20, pady=10)
    cab2.pack(fill="x")
    tk.Label(cab2, text=f"SPARTA AGENTE IA  -  Slot {slot_idx + 1}",
             font=("Segoe UI", 12, "bold"), bg=AMA, fg=BG2).pack(side="left")

    corpo = tk.Frame(d, bg=BG2, padx=24, pady=16)
    corpo.pack()

    campos = [
        ("ID da Camera", "id",      False, f"CAM-{slot_idx+1:02d}"),
        ("IP da Camera", "ip",      False, "192.168.1.100"),
        ("Porta ONVIF",  "porta",   False, "80"),
        ("Usuario",      "usuario", False, "admin"),
        ("Senha",        "senha",   True,  ""),
    ]
    entradas = {}

    for label, chave, senha, padrao in campos:
        tk.Label(corpo, text=label, font=("Segoe UI", 9),
                 bg=BG2, fg=BCOR).pack(anchor="w")
        show = "*" if senha else ""
        e = tk.Entry(corpo, show=show, font=("Consolas", 10),
                     bg=ENT, fg=BCOR, insertbackground=AMA,
                     relief="flat", bd=0,
                     highlightthickness=1, highlightcolor=AMA,
                     highlightbackground=CESC, width=36)
        e.insert(0, padrao)
        e.pack(fill="x", ipady=5, pady=(2, 10))
        e.bind("<FocusIn>",  lambda ev, w=e: w.config(highlightbackground=AMA))
        e.bind("<FocusOut>", lambda ev, w=e: w.config(highlightbackground=CESC))
        entradas[chave] = e

    sv_erro = tk.StringVar()
    tk.Label(corpo, textvariable=sv_erro, font=("Segoe UI", 8),
             bg=BG2, fg="#FF4444").pack(anchor="w")

    def confirmar():
        cfg_cam = {k: v.get().strip() for k, v in entradas.items()}
        if not cfg_cam["ip"]:
            sv_erro.set("IP obrigatorio.")
            return
        sv_erro.set("Testando conexao ONVIF...")
        d.update()
        try:
            from video_capture import _descobrir_rtsp
            uri = _descobrir_rtsp(cfg_cam["ip"], int(cfg_cam["porta"]),
                                  cfg_cam["usuario"], cfg_cam["senha"])
            cfg_cam["rtsp_uri"] = uri
            resultado.append(cfg_cam)
            d.destroy()
        except Exception as exc:
            sv_erro.set(f"Erro: {str(exc)[:70]}")

    btn = tk.Label(corpo, text="  Conectar e Adicionar  ",
                   font=("Segoe UI", 10, "bold"),
                   bg=AMA, fg=BG2, padx=14, pady=9, cursor="hand2")
    btn.bind("<Button-1>", lambda _: confirmar())
    btn.bind("<Enter>",    lambda _: btn.config(bg=AESC))
    btn.bind("<Leave>",    lambda _: btn.config(bg=AMA))
    btn.pack(fill="x", pady=(6, 0))

    d.update_idletasks()
    sw, sh = d.winfo_screenwidth(), d.winfo_screenheight()
    w, h   = d.winfo_reqwidth(), d.winfo_reqheight()
    d.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")
    d.mainloop()

    return resultado[0] if resultado else None


def _abrir_training_tab():
    try:
        from training_tab import abrir_training
        abrir_training()
    except Exception as exc:
        log.error("Erro ao abrir aba de treinamento: %s", exc)


# ── Loop principal ────────────────────────────────────────────────────────────
def rodar_mosaico(cfg_principal, rtsp_principal: str, intervalo_ia: int = 3):
    cam0_cfg = {
        "id":      cfg_principal.CAMERA_ID,
        "ip":      cfg_principal.CAMERA_IP,
        "porta":   cfg_principal.CAMERA_PORTA,
        "usuario": cfg_principal.CAMERA_USUARIO,
        "senha":   cfg_principal.CAMERA_SENHA,
        "rtsp_uri": rtsp_principal,
    }

    slots: dict[int, CameraSlot] = {}
    fila  = FilaAnalise(intervalo=intervalo_ia)

    # Estado compartilhado entre main loop e callback de mouse
    state = {
        "layout":    4,    # layout ativo: 1 | 4 | 16 | 32
        "expandido": None, # idx do slot expandido ou None
        "hover":     -1,   # slot sob o cursor
        "hover_btn": -1,   # botao da toolbar sob o cursor
    }

    def _adicionar_slot(idx: int, cfg_cam: dict):
        slot = CameraSlot(idx, cfg_cam)
        slot.iniciar(cfg_cam["rtsp_uri"])
        slots[idx] = slot

    _adicionar_slot(0, cam0_cfg)

    for cam_salva in _carregar_cameras():
        idx = cam_salva.get("slot_idx")
        if idx is not None and idx != 0 and idx < 32:
            try:
                from video_capture import _descobrir_rtsp
                uri = _descobrir_rtsp(cam_salva["ip"], int(cam_salva["porta"]),
                                      cam_salva["usuario"], cam_salva["senha"])
                cam_salva["rtsp_uri"] = uri
                _adicionar_slot(idx, cam_salva)
                log.info("Camera restaurada no slot %d: %s", idx, cam_salva["id"])
            except Exception as exc:
                log.warning("Slot %d: falha ao restaurar - %s", idx, exc)

    frame_idx: dict[int, int] = {}

    cv2.namedWindow(WIN_NAME, cv2.WINDOW_AUTOSIZE)

    def _btn_index_at(x: int) -> int:
        """Retorna indice do botao de layout em x, ou -1."""
        for i in range(len(LAYOUT_ORDER)):
            x0 = 10 + i * (_TOOLBAR_BTN_W + _TOOLBAR_BTN_GAP)
            x1 = x0 + _TOOLBAR_BTN_W
            if x0 <= x <= x1:
                return i
        return -1

    def _slot_index_at(x: int, y: int) -> int:
        """Converte coordenada de tela em indice de slot na grade atual."""
        vy = y - HDR_H - TOOLBAR_H
        if vy < 0:
            return -1
        cols, rows = LAYOUTS[state["layout"]]
        slot_w = MOSAIC_W // cols
        slot_h = MOSAIC_H // rows
        col = x // slot_w
        row = vy // slot_h
        if 0 <= col < cols and 0 <= row < rows:
            return row * cols + col
        return -1

    def on_mouse(event, x, y, flags, param):
        # Cabecalho
        if y < HDR_H:
            state["hover"]     = -1
            state["hover_btn"] = -1
            return

        # Toolbar
        if y < HDR_H + TOOLBAR_H:
            state["hover"]     = -1
            state["hover_btn"] = _btn_index_at(x)
            if event == cv2.EVENT_LBUTTONDOWN:
                bi = _btn_index_at(x)
                if bi >= 0:
                    novo_layout = LAYOUT_ORDER[bi]
                    if state["layout"] != novo_layout:
                        state["layout"]    = novo_layout
                        state["expandido"] = None
                        log.info("Layout alterado para %dCH", novo_layout)
            return

        state["hover_btn"] = -1

        # Area de video — modo expandido
        if state["expandido"] is not None:
            state["hover"] = -1
            if event == cv2.EVENT_LBUTTONDOWN:
                state["expandido"] = None
            return

        # Area de video — grade
        idx = _slot_index_at(x, y)
        state["hover"] = idx

        if event == cv2.EVENT_LBUTTONDOWN and idx >= 0:
            if idx in slots:
                state["expandido"] = idx
                log.info("Slot %d expandido", idx)
            else:
                threading.Thread(
                    target=lambda i=idx: _abrir_dialogo(i),
                    daemon=True
                ).start()

    def _abrir_dialogo(slot_idx: int):
        cfg_cam = _dialogo_adicionar(slot_idx)
        if cfg_cam:
            cfg_cam["slot_idx"] = slot_idx
            _adicionar_slot(slot_idx, cfg_cam)
            extras = [{**s.cfg, "slot_idx": i} for i, s in slots.items() if i != 0]
            _salvar_cameras(extras)
            log.info("Camera adicionada no slot %d: %s", slot_idx, cfg_cam["id"])

    cv2.setMouseCallback(WIN_NAME, on_mouse)
    log.info("Mosaico iniciado. Pressione Q para encerrar, T para treinamento.")

    try:
        while True:
            for idx, slot in list(slots.items()):
                frame = slot.get_frame()
                if frame is not None:
                    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
                    fid = f"{slot.cfg['id']}_{ts}_{frame_idx.get(idx, 0):04d}"
                    frame_idx[idx] = frame_idx.get(idx, 0) + 1
                    fila.enfileirar(slot, fid, frame)

            mosaico = _montar_mosaico(slots, state)
            cv2.imshow(WIN_NAME, mosaico)

            key = cv2.waitKey(100) & 0xFF

            if cv2.getWindowProperty(WIN_NAME, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == ord("q"):
                break
            elif key == 27:                 # ESC fecha expansao ou encerra
                if state["expandido"] is not None:
                    state["expandido"] = None
                else:
                    break
            elif key in (ord("t"), ord("T")):
                threading.Thread(target=_abrir_training_tab, daemon=True).start()

    finally:
        for slot in slots.values():
            slot.parar()
        cv2.destroyAllWindows()
        log.info("Mosaico encerrado.")
