"""
Janela de status de conexao ONVIF - SPARTA AGENTE IA
Retorna: ('ok', rtsp_uri) | ('reconfigurar',) | ('sair',)
"""
import threading
import tkinter as tk
from datetime import datetime

BG          = "#0F0F0F"
BG_CARD     = "#1A1A1A"
AMARELO     = "#FFD000"
AMARELO_ESC = "#B39200"
BRANCO      = "#F0F0F0"
CINZA       = "#888888"
CINZA_ESC   = "#333333"
VERDE       = "#3DCC7E"
VERMELHO    = "#FF4444"

FONT_TITULO = ("Segoe UI", 14, "bold")
FONT_SUB    = ("Segoe UI", 8)
FONT_INFO   = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 9)
FONT_STATUS = ("Segoe UI", 11, "bold")
FONT_BTN    = ("Segoe UI", 9, "bold")
FONT_DICA   = ("Segoe UI", 8)


def _btn(pai, texto, cmd, bg=AMARELO, fg=BG):
    hover = AMARELO_ESC if bg == AMARELO else "#555555"
    b = tk.Label(pai, text=texto, font=FONT_BTN,
                 bg=bg, fg=fg, padx=14, pady=9, cursor="hand2")
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>",    lambda _: b.config(bg=hover))
    b.bind("<Leave>",    lambda _: b.config(bg=bg))
    return b


class StatusConexao:
    """
    Janela de status ONVIF.
    Chame .mostrar(cfg) — bloqueia ate o usuario decidir.
    Retorna ('ok', uri) | ('reconfigurar',) | ('sair',)
    """

    def mostrar(self, cfg) -> tuple:
        self._cfg        = cfg
        self._resultado  = ("sair",)
        self._cancelado  = False
        self._tentativa  = 0
        self._pulsando   = False
        self._conectando = False

        j = tk.Tk()
        self._j = j
        j.title("SPARTA AGENTE IA - Status de Conexao")
        j.configure(bg=BG)
        j.resizable(False, False)
        j.protocol("WM_DELETE_WINDOW", self._fechar)

        # Cabecalho
        cab = tk.Frame(j, bg=AMARELO, padx=24, pady=12)
        cab.pack(fill="x")
        tk.Label(cab, text="SPARTA AGENTE IA",
                 font=FONT_TITULO, bg=AMARELO, fg=BG).pack(side="left")
        tk.Label(cab, text="Verificando conexao ONVIF",
                 font=FONT_SUB, bg=AMARELO, fg=BG).pack(side="right", anchor="s", pady=(8, 0))

        corpo = tk.Frame(j, bg=BG, padx=28, pady=20)
        corpo.pack(fill="both")

        # Card de info
        card = tk.Frame(corpo, bg=BG_CARD, padx=16, pady=12)
        card.pack(fill="x", pady=(0, 18))
        for label, valor in [
            ("Camera:",  cfg.CAMERA_ID),
            ("IP:",      f"{cfg.CAMERA_IP}  :  porta {cfg.CAMERA_PORTA}"),
            ("Usuario:", cfg.CAMERA_USUARIO),
        ]:
            row = tk.Frame(card, bg=BG_CARD)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=label, font=FONT_INFO,
                     bg=BG_CARD, fg=CINZA, width=10, anchor="w").pack(side="left")
            tk.Label(row, text=valor, font=FONT_MONO,
                     bg=BG_CARD, fg=BRANCO, anchor="w").pack(side="left")

        # LED + status
        led_row = tk.Frame(corpo, bg=BG)
        led_row.pack(fill="x", pady=(0, 4))

        cv = tk.Canvas(led_row, width=22, height=22,
                       bg=BG, highlightthickness=0)
        cv.pack(side="left", padx=(0, 12))
        self._oval    = cv.create_oval(2, 2, 20, 20, fill=AMARELO_ESC, outline="")
        self._canvas  = cv

        self._sv_status = tk.StringVar(value="Aguardando...")
        tk.Label(led_row, textvariable=self._sv_status,
                 font=FONT_STATUS, bg=BG, fg=BRANCO).pack(side="left")

        self._sv_detalhe = tk.StringVar(value="")
        tk.Label(corpo, textvariable=self._sv_detalhe,
                 font=FONT_DICA, bg=BG, fg=CINZA,
                 justify="left", wraplength=360).pack(anchor="w")

        self._sv_hora = tk.StringVar(value="")
        tk.Label(corpo, textvariable=self._sv_hora,
                 font=FONT_DICA, bg=BG, fg=CINZA).pack(anchor="w", pady=(2, 16))

        tk.Frame(corpo, bg=CINZA_ESC, height=1).pack(fill="x", pady=(0, 14))

        # Botoes
        br = tk.Frame(corpo, bg=BG)
        br.pack(fill="x")
        self._btn_retry = _btn(br, "  Tentar Novamente  ", self._tentar_agora, AMARELO, BG)
        self._btn_retry.pack(side="left", expand=True, fill="x", padx=(0, 8))
        _btn(br, "  Corrigir Configuracao  ", self._corrigir, CINZA_ESC, BRANCO).pack(
            side="left", expand=True, fill="x")

        # Centraliza
        j.update_idletasks()
        sw, sh = j.winfo_screenwidth(), j.winfo_screenheight()
        w, h   = j.winfo_reqwidth(), j.winfo_reqheight()
        j.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

        j.after(300, self._tentar)
        j.mainloop()
        # Libera refs tkinter na thread principal para evitar Tcl_AsyncDelete
        self._sv_status = None
        self._sv_detalhe = None
        self._sv_hora = None
        self._canvas = None
        self._j = None
        return self._resultado

    # ── Logica ────────────────────────────────────────────────────────────────

    def _tentar(self):
        if self._cancelado or self._conectando:
            return
        self._conectando = True
        self._tentativa += 1
        self._sv_status.set(f"Conectando... tentativa {self._tentativa}")
        self._sv_detalhe.set(
            f"Consultando {self._cfg.CAMERA_IP} porta {self._cfg.CAMERA_PORTA} via ONVIF"
        )
        self._sv_hora.set(f"Iniciado: {datetime.now().strftime('%H:%M:%S')}")
        self._set_led(AMARELO_ESC)
        self._pulsando = True
        self._pulsar(True)
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        try:
            from video_capture import _descobrir_rtsp
            uri = _descobrir_rtsp(
                self._cfg.CAMERA_IP,
                self._cfg.CAMERA_PORTA,
                self._cfg.CAMERA_USUARIO,
                self._cfg.CAMERA_SENHA,
            )
            if not self._cancelado:
                self._j.after(0, lambda: self._sucesso(uri))
        except Exception as exc:
            if not self._cancelado:
                msg = str(exc)
                self._j.after(0, lambda: self._erro(msg))

    def _sucesso(self, uri):
        self._pulsando   = False
        self._conectando = False
        self._set_led(VERDE)
        self._sv_status.set("Conectado!")
        self._sv_detalhe.set("Camera acessivel. Iniciando monitoramento em 2 segundos...")
        self._sv_hora.set(f"Conectado: {datetime.now().strftime('%H:%M:%S')}")
        self._resultado = ("ok", uri)
        self._j.after(2000, self._j.destroy)

    def _erro(self, msg):
        self._pulsando   = False
        self._conectando = False
        self._set_led(VERMELHO)
        self._sv_status.set("Falha na conexao")

        if "timed out" in msg or "Timeout" in msg:
            detalhe = (f"Camera nao respondeu em {self._cfg.CAMERA_IP}:{self._cfg.CAMERA_PORTA}\n"
                       "Verifique o IP, a porta ONVIF e se a VPN esta conectada.")
        elif "refused" in msg.lower():
            detalhe = (f"Conexao recusada em {self._cfg.CAMERA_IP}:{self._cfg.CAMERA_PORTA}\n"
                       "Verifique a porta ONVIF (padrao Intelbras: 80).")
        elif "401" in msg or "nauthorized" in msg:
            detalhe = "Usuario ou senha incorretos.\nClique em 'Corrigir Configuracao'."
        else:
            detalhe = msg[:120]

        self._sv_detalhe.set(detalhe)
        self._sv_hora.set(f"Falhou: {datetime.now().strftime('%H:%M:%S')}")

    def _tentar_agora(self):
        if not self._conectando:
            self._tentar()

    def _corrigir(self):
        self._cancelado  = True
        self._pulsando   = False
        self._resultado  = ("reconfigurar",)
        self._j.destroy()

    def _fechar(self):
        self._cancelado = True
        self._pulsando  = False
        self._resultado = ("sair",)
        self._j.destroy()

    # ── LED ───────────────────────────────────────────────────────────────────

    def _set_led(self, cor):
        try:
            self._canvas.itemconfig(self._oval, fill=cor)
        except Exception:
            pass

    def _pulsar(self, ligado: bool):
        if not self._pulsando or self._cancelado:
            return
        try:
            self._set_led(AMARELO if ligado else "#7A6000")
            self._j.after(450, self._pulsar, not ligado)
        except Exception:
            pass
