"""Tela de login e recuperação de senha — SPARTA AGENTE IA."""
import sys
import tkinter as tk
from tkinter import messagebox

import auth

BG   = "#0F0F0F"
AMA  = "#FFD000"
AESC = "#B39200"
ENT  = "#242424"
BCOR = "#F0F0F0"
CESC = "#333333"
VERM = "#FF4444"
VERDE= "#3DCC7E"
AZUL = "#336699"


def _centralizar(win: tk.Tk | tk.Toplevel):
    win.update_idletasks()
    w  = win.winfo_reqwidth()
    h  = win.winfo_reqheight()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")


def _entry_estilizado(parent, ocultar: bool = False, width: int = 26) -> tk.Entry:
    e = tk.Entry(parent, show="*" if ocultar else "",
                 font=("Consolas", 11), bg=ENT, fg=BCOR,
                 insertbackground=AMA, relief="flat", bd=0,
                 highlightthickness=1, highlightcolor=AMA,
                 highlightbackground=CESC, width=width)
    e.pack(fill="x", ipady=6, pady=(2, 10))
    e.bind("<FocusIn>",  lambda ev, w=e: w.config(highlightbackground=AMA))
    e.bind("<FocusOut>", lambda ev, w=e: w.config(highlightbackground=CESC))
    return e


def _abrir_troca_obrigatoria(parent, usuario: dict, resultado: list):
    """Dialog de troca obrigatória de senha (primeiro acesso ou reset pelo admin)."""
    dlg = tk.Toplevel(parent)
    dlg.title("Troca de Senha Obrigatória")
    dlg.configure(bg=BG)
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.grab_set()
    dlg.protocol("WM_DELETE_WINDOW", lambda: None)  # impede fechar sem trocar

    cab = tk.Frame(dlg, bg=VERM, padx=16, pady=8)
    cab.pack(fill="x")
    tk.Label(cab, text="Troca de Senha Obrigatória",
             font=("Segoe UI", 11, "bold"), bg=VERM, fg=BCOR).pack(side="left")

    corpo = tk.Frame(dlg, bg=BG, padx=24, pady=16)
    corpo.pack(fill="x")

    tk.Label(corpo, text=f"Olá, {usuario['nome']}. Por segurança, você deve\ndefinir uma nova senha antes de continuar.",
             font=("Segoe UI", 9), bg=BG, fg=BCOR, justify="left").pack(anchor="w", pady=(0, 10))

    tk.Label(corpo, text="Nova senha:", font=("Segoe UI", 9), bg=BG, fg=BCOR).pack(anchor="w")
    e_nova = tk.Entry(corpo, show="*", font=("Consolas", 11), bg=ENT, fg=BCOR,
                      insertbackground=AMA, relief="flat", bd=0,
                      highlightthickness=1, highlightcolor=AMA,
                      highlightbackground=CESC, width=28)
    e_nova.pack(fill="x", ipady=6, pady=(2, 8))

    tk.Label(corpo, text="Confirmar senha:", font=("Segoe UI", 9), bg=BG, fg=BCOR).pack(anchor="w")
    e_conf = tk.Entry(corpo, show="*", font=("Consolas", 11), bg=ENT, fg=BCOR,
                      insertbackground=AMA, relief="flat", bd=0,
                      highlightthickness=1, highlightcolor=AMA,
                      highlightbackground=CESC, width=28)
    e_conf.pack(fill="x", ipady=6, pady=(2, 8))

    for w2 in (e_nova, e_conf):
        w2.bind("<FocusIn>",  lambda ev, w=w2: w.config(highlightbackground=AMA))
        w2.bind("<FocusOut>", lambda ev, w=w2: w.config(highlightbackground=CESC))

    lbl_err = tk.Label(corpo, text="", font=("Segoe UI", 8), bg=BG, fg=VERM, wraplength=280)
    lbl_err.pack(anchor="w")

    def _confirmar():
        nova = e_nova.get()
        conf = e_conf.get()
        if len(nova) < 4:
            lbl_err.config(text="Mínimo 4 caracteres."); return
        if nova == "admin123":
            lbl_err.config(text="Escolha uma senha diferente da padrão."); return
        if nova != conf:
            lbl_err.config(text="As senhas não coincidem."); return
        auth.alterar_senha(usuario["id"], nova)
        resultado[0] = usuario
        dlg.destroy()
        parent.destroy()

    btn = tk.Label(corpo, text="  Salvar Nova Senha  ",
                   font=("Segoe UI", 10, "bold"),
                   bg=VERDE, fg=BG, padx=12, pady=8, cursor="hand2")
    btn.bind("<Button-1>", lambda _: _confirmar())
    btn.bind("<Enter>", lambda _: btn.config(bg="#2EAA66"))
    btn.bind("<Leave>", lambda _: btn.config(bg=VERDE))
    btn.pack(fill="x", pady=(8, 0))
    dlg.bind("<Return>", lambda _: _confirmar())

    _centralizar(dlg)
    e_nova.focus_set()


def _abrir_recuperacao(parent: tk.Tk):
    """Dialog de recuperação de senha por email ou telefone."""
    dlg = tk.Toplevel(parent)
    dlg.title("Recuperar Senha")
    dlg.configure(bg=BG)
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.grab_set()

    cab = tk.Frame(dlg, bg=AMA, padx=16, pady=8)
    cab.pack(fill="x")
    tk.Label(cab, text="Recuperação de Senha",
             font=("Segoe UI", 11, "bold"), bg=AMA, fg=BG).pack(side="left")

    corpo = tk.Frame(dlg, bg=BG, padx=24, pady=16)
    corpo.pack(fill="x")

    tk.Label(corpo,
             text="Informe o e-mail ou telefone cadastrado:",
             font=("Segoe UI", 9), bg=BG, fg=BCOR).pack(anchor="w")
    e_contato = _entry_estilizado(corpo, width=28)

    lbl_err = tk.Label(corpo, text="", font=("Segoe UI", 8),
                       bg=BG, fg=VERM, wraplength=280)
    lbl_err.pack(anchor="w")

    # Frame para nova senha (inicialmente oculto)
    frm_nova = tk.Frame(corpo, bg=BG)
    _usuario_encontrado = [None]

    lbl_nova  = tk.Label(frm_nova, text="Nova senha:", font=("Segoe UI", 9), bg=BG, fg=BCOR)
    e_nova    = tk.Entry(frm_nova, show="*", font=("Consolas", 11), bg=ENT, fg=BCOR,
                         insertbackground=AMA, relief="flat", bd=0,
                         highlightthickness=1, highlightcolor=AMA,
                         highlightbackground=CESC, width=28)
    lbl_conf  = tk.Label(frm_nova, text="Confirmar:", font=("Segoe UI", 9), bg=BG, fg=BCOR)
    e_conf    = tk.Entry(frm_nova, show="*", font=("Consolas", 11), bg=ENT, fg=BCOR,
                         insertbackground=AMA, relief="flat", bd=0,
                         highlightthickness=1, highlightcolor=AMA,
                         highlightbackground=CESC, width=28)
    for w2 in (e_nova, e_conf):
        w2.bind("<FocusIn>",  lambda ev, w=w2: w.config(highlightbackground=AMA))
        w2.bind("<FocusOut>", lambda ev, w=w2: w.config(highlightbackground=CESC))

    def _buscar():
        contato = e_contato.get().strip()
        if not contato:
            lbl_err.config(text="Informe o e-mail ou telefone.", fg=VERM); return
        usuario = auth.buscar_por_email(contato) or auth.buscar_por_telefone(contato)
        if not usuario:
            lbl_err.config(text="Nenhum usuário encontrado com esse contato.", fg=VERM)
            return
        _usuario_encontrado[0] = usuario
        lbl_err.config(
            text=f"Usuário encontrado: {usuario['nome']}. Defina a nova senha.",
            fg=VERDE
        )
        e_contato.config(state="disabled")
        btn_buscar.config(state="disabled")
        lbl_nova.pack(anchor="w", pady=(8, 0))
        e_nova.pack(fill="x", ipady=5, pady=(2, 6))
        lbl_conf.pack(anchor="w")
        e_conf.pack(fill="x", ipady=5, pady=(2, 6))
        frm_nova.pack(fill="x")
        btn_redefinir.pack(fill="x", pady=(4, 0))
        e_nova.focus_set()

    def _redefinir():
        usuario = _usuario_encontrado[0]
        if not usuario:
            return
        nova = e_nova.get()
        conf = e_conf.get()
        if len(nova) < 4:
            lbl_err.config(text="Mínimo 4 caracteres.", fg=VERM); return
        if nova != conf:
            lbl_err.config(text="As senhas não coincidem.", fg=VERM); return
        auth.alterar_senha(usuario["id"], nova)
        messagebox.showinfo("Senha Redefinida",
                            f"Senha de '{usuario['nome']}' redefinida com sucesso!",
                            parent=dlg)
        dlg.destroy()

    btn_buscar = tk.Label(corpo, text="  Buscar  ",
                          font=("Segoe UI", 10, "bold"),
                          bg=AMA, fg=BG, padx=12, pady=8, cursor="hand2")
    btn_buscar.bind("<Button-1>", lambda _: _buscar())
    btn_buscar.bind("<Enter>", lambda _: btn_buscar.config(bg=AESC))
    btn_buscar.bind("<Leave>", lambda _: btn_buscar.config(bg=AMA))
    btn_buscar.pack(fill="x", pady=(6, 0))

    btn_redefinir = tk.Label(frm_nova, text="  Redefinir Senha  ",
                             font=("Segoe UI", 10, "bold"),
                             bg=AZUL, fg=BCOR, padx=12, pady=8, cursor="hand2")
    btn_redefinir.bind("<Button-1>", lambda _: _redefinir())
    btn_redefinir.bind("<Enter>", lambda _: btn_redefinir.config(bg="#4477BB"))
    btn_redefinir.bind("<Leave>", lambda _: btn_redefinir.config(bg=AZUL))

    _centralizar(dlg)
    dlg.wait_window()


def abrir_login() -> dict:
    resultado = [None]

    root = tk.Tk()
    root.title("SPARTA AGENTE IA — Login")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    cab = tk.Frame(root, bg=AMA, padx=20, pady=10)
    cab.pack(fill="x")
    tk.Label(cab, text="SPARTA AGENTE IA",
             font=("Segoe UI", 13, "bold"), bg=AMA, fg=BG).pack(side="left")
    tk.Label(cab, text="Sistema de Monitoramento",
             font=("Segoe UI", 8), bg=AMA, fg="#555500").pack(side="right", padx=4)

    corpo = tk.Frame(root, bg=BG, padx=30, pady=20)
    corpo.pack()

    tk.Label(corpo, text="Usuário", font=("Segoe UI", 9), bg=BG, fg=BCOR).pack(anchor="w")
    e_user = _entry_estilizado(corpo)

    tk.Label(corpo, text="Senha", font=("Segoe UI", 9), bg=BG, fg=BCOR).pack(anchor="w")
    e_pw = _entry_estilizado(corpo, ocultar=True)

    lbl_err = tk.Label(corpo, text="", font=("Segoe UI", 8),
                       bg=BG, fg=VERM, wraplength=260)
    lbl_err.pack(anchor="w", pady=(0, 4))

    def _tentar():
        nome  = e_user.get().strip()
        senha = e_pw.get()
        if not nome:
            lbl_err.config(text="Informe o usuário.")
            return
        usuario = auth.autenticar(nome, senha)
        if usuario:
            auth.registrar_login(nome, True, usuario["id"])
            if auth.precisa_trocar_senha(usuario["id"]):
                _abrir_troca_obrigatoria(root, usuario, resultado)
                return
            resultado[0] = usuario
            root.destroy()
        else:
            auth.registrar_login(nome, False)
            lbl_err.config(text="Usuário ou senha incorretos.")
            e_pw.delete(0, "end")
            e_pw.focus_set()

    btn_entrar = tk.Label(corpo, text="  Entrar  ",
                          font=("Segoe UI", 10, "bold"),
                          bg=AMA, fg=BG, padx=14, pady=9, cursor="hand2")
    btn_entrar.bind("<Button-1>", lambda _: _tentar())
    btn_entrar.bind("<Enter>", lambda _: btn_entrar.config(bg=AESC))
    btn_entrar.bind("<Leave>", lambda _: btn_entrar.config(bg=AMA))
    btn_entrar.pack(fill="x", pady=(0, 4))

    btn_rec = tk.Label(corpo, text="Esqueci a senha",
                       font=("Segoe UI", 8, "underline"),
                       bg=BG, fg="#888888", cursor="hand2")
    btn_rec.bind("<Button-1>", lambda _: _abrir_recuperacao(root))
    btn_rec.bind("<Enter>", lambda _: btn_rec.config(fg=AMA))
    btn_rec.bind("<Leave>", lambda _: btn_rec.config(fg="#888888"))
    btn_rec.pack(anchor="center", pady=(0, 2))

    root.bind("<Return>", lambda _: _tentar())
    e_user.focus_set()

    _centralizar(root)
    root.protocol("WM_DELETE_WINDOW", lambda: sys.exit(0))
    root.mainloop()

    if resultado[0] is None:
        sys.exit(0)
    return resultado[0]
