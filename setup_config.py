"""
Tela de configuracao - SPARTA AGENTE IA
Tema: preto e amarelo, moderno, com dicas de preenchimento.
"""
import sys
import tkinter as tk
from pathlib import Path

# ── Paleta ────────────────────────────────────────────────────────────────────
BG          = "#050A12"
BG_CARD     = "#08131E"
BG_ENTRY    = "#0C1825"
AMARELO     = "#00D4FF"
AMARELO_ESC = "#007A9E"
BRANCO      = "#C8E8F8"
CINZA       = "#4A6070"
CINZA_ESC   = "#152030"
VERMELHO    = "#FF2255"
VERDE       = "#00CC77"

FONT_TITULO = ("Segoe UI", 14, "bold")
FONT_SUBTIT = ("Segoe UI", 8)
FONT_SECAO  = ("Segoe UI", 8,  "bold")
FONT_LABEL  = ("Segoe UI", 9)
FONT_ENTRY  = ("Consolas", 10)
FONT_BTN    = ("Segoe UI", 10, "bold")
FONT_DICA   = ("Segoe UI", 8)

LARGURA_JANELA = 560

ENV_PATH = (
    Path(sys.executable).parent / ".env"
    if getattr(sys, "frozen", False)
    else Path(".env")
)

CAMPOS = [
    {
        "chave": "CLAUDE_API_KEY",
        "label": "Chave API Claude",
        "obrig": True,
        "senha": True,
        "secao": "INTELIGENCIA ARTIFICIAL",
        "dica": (
            "OBRIGATORIO\n"
            "Acesse: console.anthropic.com\n"
            "Menu: API Keys > Create Key\n"
            "Formato: sk-ant-api03-..."
        ),
    },
    {
        "chave": "CAMERA_ID",
        "label": "ID da camera",
        "obrig": False,
        "senha": False,
        "secao": "CAMERA  (protocolo ONVIF)",
        "dica": (
            "Nome livre para identificar a camera.\n"
            "Aparece nos logs e nos clips salvos.\n"
            "Exemplos: CAM-TAPETE-01, TAPETE-NORTE"
        ),
    },
    {
        "chave": "CAMERA_IP",
        "label": "IP da camera",
        "obrig": True,
        "senha": False,
        "secao": None,
        "dica": (
            "OBRIGATORIO\n"
            "Endereco IP da camera Intelbras na rede.\n"
            "Exemplos: 192.168.1.100  ou  10.0.0.50\n"
            "Consulte o D-Guardian ou o roteador."
        ),
    },
    {
        "chave": "CAMERA_PORTA",
        "label": "Porta ONVIF",
        "obrig": True,
        "senha": False,
        "secao": None,
        "dica": (
            "OBRIGATORIO\n"
            "Porta do servico ONVIF da camera.\n"
            "Intelbras: normalmente  80\n"
            "Alguns modelos usam  8080  ou  8000"
        ),
    },
    {
        "chave": "CAMERA_USUARIO",
        "label": "Usuario da camera",
        "obrig": True,
        "senha": False,
        "secao": None,
        "dica": (
            "OBRIGATORIO\n"
            "Login de acesso a camera.\n"
            "Padrao Intelbras: admin"
        ),
    },
    {
        "chave": "CAMERA_SENHA",
        "label": "Senha da camera",
        "obrig": True,
        "senha": True,
        "secao": None,
        "dica": (
            "OBRIGATORIO\n"
            "Senha de acesso a camera.\n"
            "Definida no momento da instalacao.\n"
            "Consulte o tecnico responsavel."
        ),
    },
    {
        "chave": "INTERVALO_FRAMES",
        "label": "Intervalo de analise (segundos)",
        "obrig": False,
        "senha": False,
        "secao": "OPERACAO",
        "dica": (
            "A cada quantos segundos um frame\n"
            "e enviado para analise pela IA.\n"
            "Recomendado: 3 a 5 segundos.\n"
            "Valores menores = mais custo de API."
        ),
    },
    {
        "chave": "PASTA_CLIPS",
        "label": "Pasta de clips de alerta",
        "obrig": False,
        "senha": False,
        "secao": None,
        "dica": (
            "Pasta onde os videos de alerta\n"
            "serao salvos automaticamente.\n"
            "Ex.: C:\\Alertas  ou  clips_alertas"
        ),
    },
    {
        "chave": "WEBHOOK_URL",
        "label": "Webhook D-Guardian (opcional)",
        "obrig": False,
        "senha": False,
        "secao": None,
        "dica": (
            "OPCIONAL\n"
            "URL do D-Guardian para notificacoes\n"
            "de alerta em tempo real.\n"
            "Deixe em branco se nao usar."
        ),
    },
    {
        "chave": "FASE_PROCESSO",
        "label": "Fase do processo",
        "obrig": False,
        "senha": False,
        "secao": None,
        "dica": (
            "Descreve o momento monitorado.\n"
            "Aparece nos logs e na analise da IA.\n"
            "Ex.: manuseio, lavagem, coleta"
        ),
    },
]

PADROES = {
    "CLAUDE_API_KEY":   "",
    "CAMERA_ID":        "CAM-TAPETE-01",
    "CAMERA_IP":        "192.168.1.100",
    "CAMERA_PORTA":     "80",
    "CAMERA_USUARIO":   "admin",
    "CAMERA_SENHA":     "",
    "INTERVALO_FRAMES": "3",
    "PASTA_CLIPS":      "clips_alertas",
    "WEBHOOK_URL":      "",
    "FASE_PROCESSO":    "manuseio",
}


# ── .env ──────────────────────────────────────────────────────────────────────
def _ler_env() -> dict:
    vals = dict(PADROES)
    if ENV_PATH.exists():
        for linha in ENV_PATH.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if "=" in linha and not linha.startswith("#"):
                k, _, v = linha.partition("=")
                if k.strip() in vals:
                    vals[k.strip()] = v.strip()
    return vals


def _salvar_env(valores: dict):
    ENV_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in valores.items()) + "\n",
        encoding="utf-8",
    )


# ── Tooltip ───────────────────────────────────────────────────────────────────
class Tooltip:
    def __init__(self, widget, texto: str):
        self._w, self._txt, self._tip = widget, texto, None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _=None):
        x = self._w.winfo_rootx() + self._w.winfo_width() + 6
        y = self._w.winfo_rooty()
        self._tip = tw = tk.Toplevel(self._w)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        tw.configure(bg=AMARELO)
        inner = tk.Frame(tw, bg=BG_CARD, padx=12, pady=8)
        inner.pack(padx=1, pady=1)
        tk.Label(inner, text=self._txt, bg=BG_CARD, fg=BRANCO,
                 font=FONT_DICA, justify="left").pack()

    def _hide(self, _=None):
        if self._tip:
            self._tip.destroy()
            self._tip = None


# ── Widgets ───────────────────────────────────────────────────────────────────
def _make_entry(pai, show="") -> tk.Entry:
    e = tk.Entry(
        pai, show=show, font=FONT_ENTRY,
        bg=BG_ENTRY, fg=BRANCO, insertbackground=AMARELO,
        relief="flat", bd=0,
        highlightthickness=1, highlightcolor=AMARELO, highlightbackground=CINZA_ESC,
    )
    e.bind("<FocusIn>",  lambda _: e.config(highlightbackground=AMARELO))
    e.bind("<FocusOut>", lambda _: e.config(highlightbackground=CINZA_ESC))
    return e


def _make_button(pai, texto, cmd, bg=AMARELO, fg=BG) -> tk.Label:
    b = tk.Label(pai, text=texto, font=FONT_BTN,
                 bg=bg, fg=fg, padx=18, pady=10, cursor="hand2")
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>",    lambda _: b.config(bg=AMARELO_ESC))
    b.bind("<Leave>",    lambda _: b.config(bg=bg))
    return b


def _separador(pai):
    tk.Frame(pai, bg=CINZA_ESC, height=1).pack(fill="x", pady=(2, 14))


# ── Campo individual ──────────────────────────────────────────────────────────
def _montar_campo(pai, cfg: dict, valores: dict, entradas: dict):
    bloco = tk.Frame(pai, bg=BG)
    bloco.pack(fill="x", pady=(0, 10))

    topo = tk.Frame(bloco, bg=BG)
    topo.pack(fill="x")

    sufixo    = "  [obrigatorio]" if cfg["obrig"] else ""
    cor_label = AMARELO if cfg["obrig"] else BRANCO
    tk.Label(topo, text=cfg["label"] + sufixo, font=FONT_LABEL,
             bg=BG, fg=cor_label).pack(side="left")

    btn_ajuda = tk.Label(topo, text=" ? ", font=("Segoe UI", 8, "bold"),
                         bg=CINZA_ESC, fg=AMARELO, cursor="question_arrow",
                         relief="flat", padx=3)
    btn_ajuda.pack(side="left", padx=(6, 0))
    Tooltip(btn_ajuda, cfg["dica"])

    row = tk.Frame(bloco, bg=BG)
    row.pack(fill="x", pady=(4, 0))

    show    = "*" if cfg["senha"] else ""
    entrada = _make_entry(row, show=show)
    entrada.insert(0, valores.get(cfg["chave"], ""))
    entrada.pack(side="left", fill="x", expand=True, ipady=6)
    entradas[cfg["chave"]] = entrada

    if cfg["senha"]:
        olho = tk.Label(row, text="[ver]", font=FONT_DICA,
                        bg=BG_ENTRY, fg=CINZA, cursor="hand2", padx=6)
        olho.pack(side="left")

        def _toggle(e=entrada, o=olho):
            if e.cget("show") == "*":
                e.config(show="")
                o.config(text="[ocultar]", fg=AMARELO)
            else:
                e.config(show="*")
                o.config(text="[ver]", fg=CINZA)

        olho.bind("<Button-1>", lambda _: _toggle())


# ── Janela principal ──────────────────────────────────────────────────────────
def abrir_configuracao(ao_salvar=None):
    valores  = _ler_env()
    entradas = {}

    janela = tk.Tk()
    janela.title("SPARTA AGENTE IA  -  Configuracao")
    janela.configure(bg=BG)
    janela.resizable(True, True)   # permite redimensionar

    # ── Cabecalho fixo (fora do scroll) ───────────────────────────────────────
    cab = tk.Frame(janela, bg=AMARELO, padx=24, pady=12)
    cab.pack(fill="x", side="top")
    tk.Label(cab, text="SPARTA AGENTE IA",
             font=FONT_TITULO, bg=AMARELO, fg=BG).pack(side="left")
    tk.Label(cab, text="Seguranca Patrimonial  |  Mineracao de Ouro",
             font=FONT_SUBTIT, bg=AMARELO, fg=BG).pack(side="right", anchor="s", pady=(8, 0))

    # ── Botao fixo no rodape (fora do scroll) ─────────────────────────────────
    rodape = tk.Frame(janela, bg=BG, padx=28, pady=16)
    rodape.pack(fill="x", side="bottom")

    tk.Frame(rodape, bg=CINZA_ESC, height=1).pack(fill="x", pady=(0, 12))
    tk.Label(rodape,
             text="Passe o mouse sobre [?] para ver instrucoes de preenchimento",
             font=FONT_DICA, bg=BG, fg=CINZA).pack(anchor="w", pady=(0, 10))

    def salvar():
        novos = {c["chave"]: entradas[c["chave"]].get().strip() for c in CAMPOS}
        for c in CAMPOS:
            if c["obrig"] and not novos[c["chave"]]:
                _erro(janela, entradas[c["chave"]],
                      f"O campo '{c['label']}' e obrigatorio.")
                return
        _salvar_env(novos)
        _sucesso(janela, ao_salvar)

    _make_button(rodape, "  SALVAR E INICIAR MONITORAMENTO  ", salvar).pack(fill="x")

    # ── Area de scroll para os campos ─────────────────────────────────────────
    container = tk.Frame(janela, bg=BG)
    container.pack(fill="both", expand=True, side="top")

    canvas = tk.Canvas(container, bg=BG, highlightthickness=0, bd=0)
    scroll = tk.Scrollbar(container, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)

    scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    corpo = tk.Frame(canvas, bg=BG, padx=28, pady=16)
    janela_id = canvas.create_window((0, 0), window=corpo, anchor="nw")

    def _ajustar_canvas(event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        canvas.itemconfig(janela_id, width=canvas.winfo_width())

    corpo.bind("<Configure>", _ajustar_canvas)
    canvas.bind("<Configure>", _ajustar_canvas)

    # Rolar com mouse
    def _scroll_mouse(event):
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    canvas.bind_all("<MouseWheel>", _scroll_mouse)

    # ── Monta os campos ────────────────────────────────────────────────────────
    secao_atual = None
    for cfg in CAMPOS:
        if cfg["secao"] and cfg["secao"] != secao_atual:
            secao_atual = cfg["secao"]
            if secao_atual != CAMPOS[0]["secao"]:
                tk.Frame(corpo, height=8, bg=BG).pack()
            tk.Label(corpo, text=secao_atual, font=FONT_SECAO,
                     bg=BG, fg=AMARELO).pack(anchor="w")
            _separador(corpo)
        _montar_campo(corpo, cfg, valores, entradas)

    # ── Tamanho da janela: respeita a altura da tela menos a barra de tarefas ─
    janela.update_idletasks()
    sw = janela.winfo_screenwidth()
    sh = janela.winfo_screenheight()
    altura_max = sh - 80           # reserva espaco para barra de tarefas
    altura_conteudo = corpo.winfo_reqheight() + cab.winfo_reqheight() + rodape.winfo_reqheight() + 20
    altura = min(altura_conteudo, altura_max)

    x = (sw - LARGURA_JANELA) // 2
    y = max(0, (sh - altura) // 2)
    janela.geometry(f"{LARGURA_JANELA}x{altura}+{x}+{y}")
    janela.minsize(LARGURA_JANELA, 400)

    janela.mainloop()


# ── Dialogs ───────────────────────────────────────────────────────────────────
def _erro(pai, entrada: tk.Entry, msg: str):
    entrada.config(highlightbackground=VERMELHO)
    entrada.focus_set()
    d = tk.Toplevel(pai)
    d.title("Campo obrigatorio")
    d.configure(bg=BG_CARD)
    d.resizable(False, False)
    d.grab_set()
    tk.Frame(d, bg=VERMELHO, height=4).pack(fill="x")
    tk.Label(d, text=msg, font=FONT_LABEL,
             bg=BG_CARD, fg=BRANCO, padx=24, pady=16).pack()

    def fechar():
        d.destroy()
        entrada.config(highlightbackground=CINZA_ESC)

    _make_button(d, "  OK  ", fechar, bg=VERMELHO, fg=BRANCO).pack(pady=(0, 16))
    d.update_idletasks()
    x = pai.winfo_rootx() + (pai.winfo_width()  - d.winfo_width())  // 2
    y = pai.winfo_rooty() + (pai.winfo_height() - d.winfo_height()) // 2
    d.geometry(f"+{x}+{y}")


def _sucesso(janela, ao_salvar):
    janela.withdraw()
    d = tk.Toplevel()
    d.title("Configuracao salva")
    d.configure(bg=BG_CARD)
    d.resizable(False, False)
    d.grab_set()
    tk.Frame(d, bg=AMARELO, height=4).pack(fill="x")
    tk.Label(d, text="Configuracao salva com sucesso!",
             font=("Segoe UI", 11, "bold"), bg=BG_CARD, fg=VERDE,
             padx=28, pady=18).pack()
    tk.Label(d, text=f"Arquivo: {ENV_PATH}",
             font=FONT_DICA, bg=BG_CARD, fg=CINZA).pack(pady=(0, 16))

    def iniciar():
        d.destroy()
        janela.destroy()
        if ao_salvar:
            ao_salvar()

    _make_button(d, "  INICIAR MONITORAMENTO  ", iniciar).pack(padx=24, pady=(0, 20))
    d.update_idletasks()
    sw = d.winfo_screenwidth()
    sh = d.winfo_screenheight()
    d.geometry(f"+{(sw - d.winfo_width())//2}+{(sh - d.winfo_height())//2}")


if __name__ == "__main__":
    abrir_configuracao()
