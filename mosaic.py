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

from local_analyzer import AnalisadorLocal

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

# Menu de contexto (desenhado no OpenCV — sem tkinter)
CTX_W      = 230
CTX_ITEM_H = 27
CTX_SEP_H  = 10
CTX_PAD_V  = 6
CTX_PAD_H  = 14

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
        self.idx             = idx
        self.cfg             = cfg_cam
        self.frame           = None       # armazenado em CAP_W x CAP_H
        self.resultado       = {}
        self.em_analise      = False
        self.analisador_local = AnalisadorLocal(camera_id=cfg_cam.get("id", str(idx)))
        self._lock           = threading.Lock()
        self._cap            = None
        self._rodando        = False
        self._thread         = threading.Thread(target=self._loop, daemon=True)

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
        cam_id = self.cfg.get("id", str(self.idx))
        atraso = 1.0
        while self._rodando:
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
                ok, frame = self._cap.read()
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
        import db
        while True:
            slot, frame_id, frame = self._q.get()
            camera_id = slot.cfg["id"]
            tokens_in = tokens_out = 0
            try:
                from analyzer import analisar_frame
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
                resultado = slot.analisador_local.analisar(frame, frame_id)
                nivel = resultado.get("nivel_risco", "sem_risco")
                log.info("[%s] LOCAL %s (%.0f%%)",
                         camera_id, nivel.upper(),
                         resultado.get("confianca", 0) * 100)

            try:
                slot.set_resultado(resultado)
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
                log.error("[%s] Erro ao salvar resultado: %s", camera_id, exc)
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


def _slot_camera(slot: CameraSlot, w: int, h: int, closeable: bool = False, show_close: bool = False) -> np.ndarray:
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

    # Botao fechar (X) — aparece discretamente só com hover
    if closeable and show_close:
        btn_w = max(20, bar_h + 4)
        overlay = img[0:bar_h, w - btn_w:w].copy()
        cv2.rectangle(img, (w - btn_w, 0), (w, bar_h), (30, 30, 30), -1)
        cv2.addWeighted(img[0:bar_h, w - btn_w:w], 0.4, overlay, 0.6, 0,
                        img[0:bar_h, w - btn_w:w])
        tx = cv2.getTextSize("x", cv2.FONT_HERSHEY_SIMPLEX, escala * 0.75, 1)[0][0]
        cv2.putText(img, "x", (w - btn_w + (btn_w - tx) // 2, bar_h - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, escala * 0.75, (180, 180, 180), 1)

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
def _cabecalho(n_ativas: int, layout: int, win_w: int) -> np.ndarray:
    img = np.full((HDR_H, win_w, 3), (20, 20, 20), dtype=np.uint8)
    cv2.rectangle(img, (0, HDR_H - 2), (win_w, HDR_H), C_AMARELO, -1)
    cv2.putText(img, "SPARTA AGENTE IA", (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, C_AMARELO, 1)
    cols, rows = LAYOUTS[layout]
    info = (f"{n_ativas} cam  |  {cols}x{rows}  |  "
            f"{datetime.now().strftime('%H:%M:%S')}")
    tw = cv2.getTextSize(info, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)[0][0]
    cv2.putText(img, info, (win_w - tw - 10, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, C_CINZA, 1)
    return img


# ── Toolbar de layout ─────────────────────────────────────────────────────────
def _toolbar(layout_atual: int, hover_btn: int, win_w: int) -> np.ndarray:
    img = np.full((TOOLBAR_H, win_w, 3), (25, 25, 25), dtype=np.uint8)
    cv2.line(img, (0, TOOLBAR_H - 1), (win_w, TOOLBAR_H - 1), (50, 50, 50), 1)

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
    cv2.putText(img, dica, (win_w - tw - 10, TOOLBAR_H - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.33, C_CINZA, 1)

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

    cab     = _cabecalho(len(slots), layout, win_w)
    toolbar = _toolbar(layout, hover_btn, win_w)

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


def _abrir_training_tab():
    try:
        from training_tab import abrir_training
        abrir_training()
    except Exception as exc:
        log.error("Erro ao abrir aba de treinamento: %s", exc)


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
def rodar_mosaico(cfg_principal, intervalo_ia: int = 3):
    slots: dict[int, CameraSlot] = {}
    fila  = FilaAnalise(intervalo=intervalo_ia)

    # Estado compartilhado entre main loop e callback de mouse
    state = {
        "layout":    4,    # layout ativo: 1 | 4 | 16 | 32
        "expandido": None, # idx do slot expandido ou None
        "hover":     -1,   # slot sob o cursor
        "hover_btn": -1,   # botao da toolbar sob o cursor
        "win_w":     WIN_W,
        "win_h":     WIN_H,
        "ctx_menu":  None, # dict com menu de contexto ativo ou None
    }

    def _adicionar_slot(idx: int, cfg_cam: dict):
        slot = CameraSlot(idx, cfg_cam)
        slot.iniciar(cfg_cam["rtsp_uri"])
        slots[idx] = slot

    def _salvar_todos():
        _salvar_cameras([{**s.cfg, "slot_idx": i} for i, s in slots.items()])

    # Restaura câmeras salvas (todos os slots, incluindo 0)
    for cam_salva in _carregar_cameras():
        idx = cam_salva.get("slot_idx")
        if idx is not None and 0 <= idx < 32:
            if cam_salva.get("rtsp_uri"):
                try:
                    _adicionar_slot(idx, cam_salva)
                    log.info("Camera restaurada no slot %d: %s", idx, cam_salva["id"])
                except Exception as exc:
                    log.warning("Slot %d: falha ao restaurar - %s", idx, exc)

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
        mosaic_w = win_w
        mosaic_h = max(1, win_h - HDR_H - TOOLBAR_H)
        cols, rows = LAYOUTS[state["layout"]]
        slot_w = max(1, mosaic_w // cols)
        slot_h = max(1, mosaic_h // rows)
        row = slot_idx // cols
        col = slot_idx % cols
        sx0 = col * slot_w
        sy0 = HDR_H + TOOLBAR_H + row * slot_h
        bar_h = max(16, slot_h // 14)
        btn_w = max(20, bar_h + 4)
        return (sx0 + slot_w - btn_w) <= x <= (sx0 + slot_w) and sy0 <= y <= (sy0 + bar_h)

    def _hit_close_btn_expandido(x: int, y: int) -> bool:
        """Retorna True se (x,y) está sobre o botão X na visão expandida."""
        win_w = state["win_w"]
        win_h = state["win_h"]
        mosaic_h = max(1, win_h - HDR_H - TOOLBAR_H)
        bar_h = max(16, mosaic_h // 14)
        btn_w = max(20, bar_h + 4)
        wy0 = HDR_H + TOOLBAR_H
        return (win_w - btn_w) <= x <= win_w and wy0 <= y <= (wy0 + bar_h)

    def _remover_slot(idx: int):
        if idx not in slots:
            return
        slots[idx].parar()
        del slots[idx]
        _salvar_todos()
        log.info("Camera removida do slot %d", idx)

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

        if event == cv2.EVENT_RBUTTONDOWN and idx >= 0:
            state["ctx_menu"] = {
                "slot_idx": idx,
                "mx": x, "my": y, "hover": -1,
                "items": _ctx_itens(idx, slots),
            }
            return

        if event == cv2.EVENT_LBUTTONDOWN and idx >= 0:
            if idx in slots:
                if _hit_close_btn(x, y, idx) and idx != 0:
                    _remover_slot(idx)
                else:
                    state["expandido"] = idx
                    log.info("Slot %d expandido", idx)
            else:
                _abrir_dialogo(idx)

    def _abrir_dialogo(slot_idx: int):
        cfg_cam = _dialogo_adicionar(slot_idx)
        if cfg_cam:
            cfg_cam["slot_idx"] = slot_idx
            _adicionar_slot(slot_idx, cfg_cam)
            _salvar_todos()
            log.info("Camera adicionada no slot %d: %s", slot_idx, cfg_cam["id"])

    cv2.setMouseCallback(WIN_NAME, on_mouse)
    log.info("Mosaico iniciado. Pressione Q para encerrar, T para treinamento.")

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
