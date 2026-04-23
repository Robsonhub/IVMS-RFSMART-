"""
Tela de configuracao inicial - SPARTA AGENTE IA
Solicita apenas a chave de API do Claude; demais valores ficam com padroes.
"""
import sys
import tkinter as tk
from pathlib import Path

# ── Paleta ────────────────────────────────────────────────────────────────────
BG          = "#050A12"
BG_CARD     = "#08131E"
BG_ENTRY    = "#0C1825"
CIANO       = "#C4900A"
CIANO_ESC   = "#9E7308"
BRANCO      = "#C8E8F8"
CINZA       = "#4A6070"
CINZA_ESC   = "#152030"
VERMELHO    = "#FF2255"
VERDE       = "#00CC77"

FONT_TITULO = ("Segoe UI", 14, "bold")
FONT_SUBTIT = ("Segoe UI", 8)
FONT_LABEL  = ("Segoe UI", 10)
FONT_ENTRY  = ("Consolas", 11)
FONT_BTN    = ("Segoe UI", 10, "bold")
FONT_DICA   = ("Segoe UI", 8)

LARGURA_JANELA = 520

ENV_PATH = (
    Path(sys.executable).parent / ".env"
    if getattr(sys, "frozen", False)
    else Path(".env")
)

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
    linhas = []
    if ENV_PATH.exists():
        existentes = {}
        for linha in ENV_PATH.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if "=" in linha and not linha.startswith("#"):
                k, _, v = linha.partition("=")
                existentes[k.strip()] = v.strip()
        existentes.update(valores)
        valores = existentes
    ENV_PATH.write_text(
        "\n".join(f"{k}={v}" for k, v in valores.items()) + "\n",
        encoding="utf-8",
    )


# ── Helpers de widget ─────────────────────────────────────────────────────────
def _make_entry(pai, show="") -> tk.Entry:
    e = tk.Entry(
        pai, show=show, font=FONT_ENTRY,
        bg=BG_ENTRY, fg=BRANCO, insertbackground=CIANO,
        relief="flat", bd=0,
        highlightthickness=1, highlightcolor=CIANO, highlightbackground=CINZA_ESC,
    )
    e.bind("<FocusIn>",  lambda _: e.config(highlightbackground=CIANO))
    e.bind("<FocusOut>", lambda _: e.config(highlightbackground=CINZA_ESC))
    return e


def _make_button(pai, texto, cmd, bg=CIANO, fg=BG) -> tk.Label:
    b = tk.Label(pai, text=texto, font=FONT_BTN,
                 bg=bg, fg=fg, padx=18, pady=11, cursor="hand2")
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>",    lambda _: b.config(bg=CIANO_ESC if bg == CIANO else "#1E2A38"))
    b.bind("<Leave>",    lambda _: b.config(bg=bg))
    return b


# ── Janela principal ──────────────────────────────────────────────────────────
def abrir_configuracao(ao_salvar=None):
    valores = _ler_env()

    janela = tk.Tk()
    janela.title("SPARTA AGENTE IA  —  Configuracao inicial")
    janela.configure(bg=BG)
    janela.resizable(False, False)

    # Cabecalho
    cab = tk.Frame(janela, bg=CIANO, padx=24, pady=12)
    cab.pack(fill="x")
    tk.Label(cab, text="SPARTA AGENTE IA",
             font=FONT_TITULO, bg=CIANO, fg=BG).pack(side="left")
    tk.Label(cab, text="Seguranca Patrimonial  |  Mineracao de Ouro",
             font=FONT_SUBTIT, bg=CIANO, fg=BG).pack(side="right", anchor="s", pady=(8, 0))

    # Corpo
    corpo = tk.Frame(janela, bg=BG, padx=36, pady=28)
    corpo.pack(fill="both", expand=True)

    # Descricao
    tk.Label(
        corpo,
        text="Para usar a Inteligencia Artificial, informe sua chave de API Claude.",
        font=("Segoe UI", 9), bg=BG, fg=BRANCO, wraplength=440, justify="left",
    ).pack(anchor="w", pady=(0, 6))
    tk.Label(
        corpo,
        text="Sem a chave, o monitoramento local continua funcionando normalmente.",
        font=("Segoe UI", 9), bg=BG, fg=CINZA, wraplength=440, justify="left",
    ).pack(anchor="w", pady=(0, 20))

    # Campo API Key
    tk.Label(corpo, text="Chave API Claude", font=FONT_LABEL,
             bg=BG, fg=CIANO).pack(anchor="w")
    tk.Label(corpo, text="console.anthropic.com  →  API Keys  →  Create Key   (sk-ant-api03-...)",
             font=FONT_DICA, bg=BG, fg=CINZA).pack(anchor="w", pady=(2, 6))

    row = tk.Frame(corpo, bg=BG)
    row.pack(fill="x", pady=(0, 28))

    entrada = _make_entry(row, show="*")
    entrada.insert(0, valores.get("CLAUDE_API_KEY", ""))
    entrada.pack(side="left", fill="x", expand=True, ipady=8)

    olho = tk.Label(row, text="[ver]", font=FONT_DICA,
                    bg=BG_ENTRY, fg=CINZA, cursor="hand2", padx=8, pady=8)
    olho.pack(side="left")

    def _toggle():
        if entrada.cget("show") == "*":
            entrada.config(show="")
            olho.config(text="[ocultar]", fg=CIANO)
        else:
            entrada.config(show="*")
            olho.config(text="[ver]", fg=CINZA)

    olho.bind("<Button-1>", lambda _: _toggle())

    # Separador
    tk.Frame(corpo, bg=CINZA_ESC, height=1).pack(fill="x", pady=(0, 20))

    # Botao principal
    def salvar_e_iniciar():
        chave = entrada.get().strip()
        _salvar_env({"CLAUDE_API_KEY": chave})
        _fechar_e_continuar(janela, ao_salvar)

    _make_button(corpo, "  SALVAR E INICIAR  ", salvar_e_iniciar).pack(fill="x", pady=(0, 10))

    # Botao secundario
    def continuar_sem_api():
        _salvar_env({"CLAUDE_API_KEY": ""})
        _fechar_e_continuar(janela, ao_salvar)

    btn_sem = tk.Label(
        corpo,
        text="Continuar sem chave de API",
        font=("Segoe UI", 9), bg=BG, fg=CINZA, cursor="hand2",
    )
    btn_sem.pack(anchor="center", pady=(0, 4))
    btn_sem.bind("<Enter>", lambda _: btn_sem.config(fg=BRANCO))
    btn_sem.bind("<Leave>", lambda _: btn_sem.config(fg=CINZA))
    btn_sem.bind("<Button-1>", lambda _: continuar_sem_api())

    # Centraliza janela
    janela.update_idletasks()
    sw = janela.winfo_screenwidth()
    sh = janela.winfo_screenheight()
    w  = janela.winfo_reqwidth()
    h  = janela.winfo_reqheight()
    janela.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    janela.mainloop()


def _fechar_e_continuar(janela, ao_salvar):
    janela.destroy()
    if ao_salvar:
        ao_salvar()


if __name__ == "__main__":
    abrir_configuracao()
