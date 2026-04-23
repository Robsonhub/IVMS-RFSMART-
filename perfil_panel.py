"""Painel de perfil do usuário — SPARTA AGENTE IA."""
import tkinter as tk
from tkinter import messagebox

import auth

BG   = "#0F0F0F"
BG2  = "#181818"
AMA  = "#2D7A6E"
AESC = "#1F5C52"
ENT  = "#242424"
BCOR = "#F0F0F0"
CESC = "#333333"
VERM = "#FF4444"
VERDE= "#3DCC7E"
AZUL = "#4499FF"


def abrir_perfil_panel(sessao: dict):
    root = tk.Tk()
    root.title("Meu Perfil — SPARTA AGENTE IA")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    # ── Header ────────────────────────────────────────────────────────────────
    cab = tk.Frame(root, bg=AMA, padx=16, pady=8)
    cab.pack(fill="x")
    tk.Label(cab, text="Meu Perfil",
             font=("Segoe UI", 11, "bold"), bg=AMA, fg=BG).pack(side="left")
    grupo_txt = "Administrador" if sessao.get("grupo") == "administrador" else "Usuário"
    tk.Label(cab, text=grupo_txt,
             font=("Segoe UI", 8), bg=AMA, fg="#665500").pack(side="right")

    corpo = tk.Frame(root, bg=BG, padx=20, pady=14)
    corpo.pack(fill="x")

    lbl_msg = tk.Label(corpo, text="", font=("Segoe UI", 8),
                       bg=BG, fg=VERDE, wraplength=340)

    def _sep():
        tk.Frame(corpo, bg=CESC, height=1).pack(fill="x", pady=8)

    def _titulo(txt: str):
        tk.Label(corpo, text=txt, font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=AMA).pack(anchor="w", pady=(4, 2))

    def _entry(label: str, ocultar: bool = False, valor: str = "") -> tk.Entry:
        tk.Label(corpo, text=label, font=("Segoe UI", 8), bg=BG, fg=BCOR).pack(anchor="w")
        e = tk.Entry(corpo, show="*" if ocultar else "",
                     font=("Consolas", 10), bg=ENT, fg=BCOR,
                     insertbackground=AMA, relief="flat", bd=0,
                     highlightthickness=1, highlightcolor=AMA,
                     highlightbackground=CESC, width=32)
        e.insert(0, valor)
        e.pack(fill="x", ipady=5, pady=(2, 6))
        e.bind("<FocusIn>",  lambda ev, w=e: w.config(highlightbackground=AMA))
        e.bind("<FocusOut>", lambda ev, w=e: w.config(highlightbackground=CESC))
        return e

    def _btn(texto: str, cmd, cor=AMA):
        b = tk.Label(corpo, text=f"  {texto}  ",
                     font=("Segoe UI", 9, "bold"),
                     bg=cor, fg=BG, padx=10, pady=7, cursor="hand2")
        b.bind("<Button-1>", lambda _: cmd())
        esc = "#9E7308" if cor == AMA else "#CC3333" if cor == VERM else "#336699"
        b.bind("<Enter>", lambda _: b.config(bg=esc))
        b.bind("<Leave>", lambda _: b.config(bg=cor))
        b.pack(fill="x", pady=(2, 6))
        return b

    def _msg(texto: str, cor: str = VERDE):
        lbl_msg.config(text=texto, fg=cor)
        lbl_msg.pack(anchor="w", pady=(0, 4))

    # ── Seção 1: Dados pessoais ───────────────────────────────────────────────
    _titulo("Dados Pessoais")
    e_nome = _entry("Nome de usuário", valor=sessao.get("nome", ""))

    def _salvar_nome():
        novo = e_nome.get().strip()
        if not novo:
            _msg("Informe o nome.", VERM); return
        if novo == sessao.get("nome"):
            _msg("Nome não alterado.", AZUL); return
        try:
            auth.atualizar_perfil(sessao["id"], nome=novo)
            sessao["nome"] = novo
            _msg(f"Nome alterado para '{novo}'.")
        except Exception as exc:
            _msg(f"Erro: {exc}", VERM)

    _btn("Salvar Nome", _salvar_nome)
    _sep()

    # ── Seção 2: Alterar senha ────────────────────────────────────────────────
    _titulo("Alterar Senha")
    e_atual = _entry("Senha atual", ocultar=True)
    e_nova  = _entry("Nova senha", ocultar=True)
    e_conf  = _entry("Confirmar nova senha", ocultar=True)

    def _salvar_senha():
        atual = e_atual.get()
        nova  = e_nova.get()
        conf  = e_conf.get()
        if not auth.autenticar(sessao["nome"], atual):
            _msg("Senha atual incorreta.", VERM); return
        if len(nova) < 4:
            _msg("Mínimo 4 caracteres.", VERM); return
        if nova != conf:
            _msg("As senhas não coincidem.", VERM); return
        auth.alterar_senha(sessao["id"], nova)
        e_atual.delete(0, "end")
        e_nova.delete(0, "end")
        e_conf.delete(0, "end")
        _msg("Senha alterada com sucesso.")

    _btn("Alterar Senha", _salvar_senha)
    _sep()

    # ── Seção 3: Recuperação ──────────────────────────────────────────────────
    _titulo("Contato para Recuperação de Senha")
    u = auth.buscar_por_id(sessao["id"]) or {}
    e_email = _entry("E-mail", valor=u.get("email") or "")
    e_tel   = _entry("Telefone", valor=u.get("telefone") or "")

    def _salvar_contato():
        email = e_email.get().strip()
        tel   = e_tel.get().strip()
        if email and "@" not in email:
            _msg("E-mail inválido.", VERM); return
        auth.atualizar_perfil(sessao["id"], email=email, telefone=tel)
        _msg("Dados de contato salvos.")

    _btn("Salvar Contato", _salvar_contato)
    lbl_msg.pack(anchor="w", pady=(0, 4))

    # Centralizar
    root.update_idletasks()
    w  = root.winfo_reqwidth()
    h  = root.winfo_reqheight()
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    root.wait_window(root)
    import gc as _gc; _gc.collect()
