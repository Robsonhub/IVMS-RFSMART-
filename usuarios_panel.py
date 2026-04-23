"""Painel de gerenciamento de usuários — apenas Administrador."""
import tkinter as tk
from tkinter import messagebox

import auth

BG    = "#050A12"
BG2   = "#08131E"
BG3   = "#0A1520"
AMA   = "#C4900A"
AESC  = "#9E7308"
ENT   = "#0C1825"
BCOR  = "#C8E8F8"
CESC  = "#152030"
VERM  = "#FF2255"
VERDE = "#00CC77"
CINZA = "#6A8098"
AZUL  = "#2277EE"


def _btn_factory(parent, texto: str, cmd, cor=AMA, pad_x=10, pad_y=6) -> tk.Label:
    esc = {AMA: AESC, VERM: "#BB1144", "#155A8C": "#0E3D66",
           VERDE: "#009955", AZUL: "#1A5FCC",
           "#006677": "#00454D", "#991133": "#6B0A24"}.get(cor, "#0F1A28")
    b = tk.Label(parent, text=f"  {texto}  ",
                 font=("Segoe UI", 9, "bold"),
                 bg=cor, fg=BG if cor == AMA else BCOR,
                 padx=pad_x, pady=pad_y, cursor="hand2", relief="flat")
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>",    lambda _: b.config(bg=esc))
    b.bind("<Leave>",    lambda _: b.config(bg=cor))
    b.pack(side="left", padx=(0, 8))
    return b


def abrir_usuarios_panel(sessao: dict):
    if not auth.eh_admin(sessao):
        return

    root = tk.Tk()
    root.title("Gerenciar Usuarios — SPARTA AGENTE IA")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    # ── Header ────────────────────────────────────────────────────────────────
    cab = tk.Frame(root, bg=AMA, padx=16, pady=9)
    cab.pack(fill="x")
    tk.Label(cab, text="SPARTA  —  Gerenciamento de Usuarios",
             font=("Segoe UI", 11, "bold"), bg=AMA, fg=BG).pack(side="left")
    tk.Label(cab, text="Administrador",
             font=("Segoe UI", 8), bg=AMA, fg="#003B4D").pack(side="right")

    # ── Lista de usuarios ─────────────────────────────────────────────────────
    frm_lista = tk.Frame(root, bg=BG3, padx=12, pady=10)
    frm_lista.pack(fill="both", padx=0)

    hdr_frame = tk.Frame(frm_lista, bg=BG3)
    hdr_frame.pack(fill="x")
    for txt, wd in [("Nome", 18), ("Grupo", 14), ("Ativo", 6), ("Contato", 22)]:
        tk.Label(hdr_frame, text=txt, font=("Segoe UI", 8, "bold"),
                 bg=BG3, fg=AMA, width=wd, anchor="w").pack(side="left", padx=3)

    tk.Frame(frm_lista, bg=CESC, height=1).pack(fill="x", pady=(3, 0))

    lista_frame = tk.Frame(frm_lista, bg=BG3)
    lista_frame.pack(fill="both")

    linhas: list[dict] = []
    selecionado = [None]
    lbl_msg = None  # referencia criada apos form

    def _cor_grupo(grupo: str) -> str:
        return AMA if grupo == "administrador" else CINZA

    def _renderizar():
        for w in lista_frame.winfo_children():
            w.destroy()
        linhas.clear()
        for i, u in enumerate(auth.listar_usuarios()):
            cor = _cor_grupo(u["grupo"])
            row = tk.Frame(lista_frame, bg=BG2 if i % 2 == 0 else BG3, cursor="hand2")
            row.pack(fill="x")
            row.bind("<Button-1>", lambda _, uid=u["id"]: _selecionar(uid))
            widgets = []
            contato = u.get("email") or u.get("telefone") or "—"
            for val, wd in [(u["nome"], 18), (u["grupo"], 14),
                            ("Sim" if u["ativo"] else "Nao", 6), (contato, 22)]:
                lbl = tk.Label(row, text=val, font=("Consolas", 9),
                               bg=row["bg"], fg=cor, width=wd, anchor="w")
                lbl.pack(side="left", padx=3, pady=2)
                lbl.bind("<Button-1>", lambda _, uid=u["id"]: _selecionar(uid))
                widgets.append(lbl)
            linhas.append({"id": u["id"], "nome": u["nome"], "grupo": u["grupo"],
                           "row": row, "widgets": widgets})

    def _selecionar(uid: int):
        selecionado[0] = uid
        for linha in linhas:
            ativo = linha["id"] == uid
            bg = "#0E2A42" if ativo else (BG2 if linhas.index(linha) % 2 == 0 else BG3)
            fg = AMA if ativo else _cor_grupo(linha["grupo"])
            linha["row"].config(bg=bg)
            for w in linha["widgets"]:
                w.config(bg=bg, fg=fg)
        # Preenche form de edicao
        u = next((l for l in linhas if l["id"] == uid), None)
        if u and e_edit_nome:
            e_edit_nome.delete(0, "end")
            e_edit_nome.insert(0, u["nome"])
            e_edit_senha.delete(0, "end")

    _renderizar()

    tk.Frame(root, bg=CESC, height=1).pack(fill="x")

    # ── Formulario: Novo usuario ──────────────────────────────────────────────
    frm_novo = tk.Frame(root, bg=BG, padx=14, pady=10)
    frm_novo.pack(fill="x")

    tk.Label(frm_novo, text="Criar Novo Usuario", font=("Segoe UI", 9, "bold"),
             bg=BG, fg=BCOR).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

    def _entry(parent, row, col, label, ocultar=False, width=14):
        tk.Label(parent, text=label, font=("Segoe UI", 8),
                 bg=BG, fg=BCOR).grid(row=row, column=col, sticky="w", padx=(0, 4))
        e = tk.Entry(parent, show="*" if ocultar else "",
                     font=("Consolas", 9), bg=ENT, fg=BCOR,
                     insertbackground=AMA, relief="flat", bd=0,
                     highlightthickness=1, highlightcolor=AMA,
                     highlightbackground=CESC, width=width)
        e.grid(row=row, column=col + 1, padx=(0, 12), pady=2, sticky="w")
        e.bind("<FocusIn>",  lambda ev, w=e: w.config(highlightbackground=AMA))
        e.bind("<FocusOut>", lambda ev, w=e: w.config(highlightbackground=CESC))
        return e

    e_nome  = _entry(frm_novo, 1, 0, "Nome:")
    e_senha = _entry(frm_novo, 1, 2, "Senha:", ocultar=True)

    tk.Label(frm_novo, text="Grupo:", font=("Segoe UI", 8),
             bg=BG, fg=BCOR).grid(row=2, column=0, sticky="w", pady=(6, 0))
    grupo_var = tk.StringVar(value="usuario")
    frm_radio = tk.Frame(frm_novo, bg=BG)
    frm_radio.grid(row=2, column=1, columnspan=5, sticky="w", pady=(6, 0))
    for val, txt in [("administrador", "Administrador"), ("usuario", "Usuario")]:
        tk.Radiobutton(frm_radio, text=txt, variable=grupo_var, value=val,
                       font=("Segoe UI", 9), bg=BG, fg=BCOR,
                       selectcolor=ENT, activebackground=BG,
                       activeforeground=AMA).pack(side="left", padx=(0, 12))

    lbl_novo_msg = tk.Label(frm_novo, text="", font=("Segoe UI", 8),
                            bg=BG, fg=VERM, wraplength=420)
    lbl_novo_msg.grid(row=3, column=0, columnspan=6, sticky="w", pady=(4, 0))

    def _criar():
        nome  = e_nome.get().strip()
        senha = e_senha.get()
        if not nome:
            lbl_novo_msg.config(text="Informe o nome.", fg=VERM); return
        if len(senha) < 4:
            lbl_novo_msg.config(text="Senha minima: 4 caracteres.", fg=VERM); return
        try:
            auth.criar_usuario(nome, senha, grupo_var.get())
            lbl_novo_msg.config(text=f"Usuario '{nome}' criado.", fg=VERDE)
            e_nome.delete(0, "end")
            e_senha.delete(0, "end")
            _renderizar()
        except Exception as exc:
            lbl_novo_msg.config(text=f"Erro: {exc}", fg=VERM)

    tk.Frame(root, bg=CESC, height=1).pack(fill="x", padx=14)

    # ── Formulario: Editar usuario selecionado ────────────────────────────────
    frm_edit = tk.Frame(root, bg=BG, padx=14, pady=10)
    frm_edit.pack(fill="x")

    tk.Label(frm_edit, text="Editar Usuario Selecionado  (selecione na lista acima)",
             font=("Segoe UI", 9, "bold"), bg=BG, fg=BCOR
             ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 6))

    e_edit_nome  = _entry(frm_edit, 1, 0, "Novo nome:")
    e_edit_senha = _entry(frm_edit, 1, 2, "Nova senha:", ocultar=True)

    lbl_edit_msg = tk.Label(frm_edit, text="", font=("Segoe UI", 8),
                            bg=BG, fg=VERM, wraplength=420)
    lbl_edit_msg.grid(row=2, column=0, columnspan=6, sticky="w", pady=(4, 0))

    def _salvar_nome_edit():
        uid = selecionado[0]
        if uid is None:
            lbl_edit_msg.config(text="Selecione um usuario.", fg=VERM); return
        novo = e_edit_nome.get().strip()
        if not novo:
            lbl_edit_msg.config(text="Informe o novo nome.", fg=VERM); return
        try:
            auth.atualizar_perfil(uid, nome=novo)
            lbl_edit_msg.config(text=f"Nome atualizado para '{novo}'.", fg=VERDE)
            _renderizar()
        except Exception as exc:
            lbl_edit_msg.config(text=f"Erro: {exc}", fg=VERM)

    def _redefinir_senha():
        uid = selecionado[0]
        if uid is None:
            lbl_edit_msg.config(text="Selecione um usuario.", fg=VERM); return
        nova = e_edit_senha.get()
        if len(nova) < 4:
            lbl_edit_msg.config(text="Senha minima: 4 caracteres.", fg=VERM); return
        u = next((l for l in linhas if l["id"] == uid), None)
        nome_u = u["nome"] if u else "?"
        if messagebox.askyesno("Confirmar", f"Redefinir senha de '{nome_u}'?", parent=root):
            auth.alterar_senha(uid, nova)
            e_edit_senha.delete(0, "end")
            lbl_edit_msg.config(text=f"Senha de '{nome_u}' redefinida.", fg=VERDE)

    def _remover():
        uid = selecionado[0]
        if uid is None:
            lbl_edit_msg.config(text="Selecione um usuario.", fg=VERM); return
        if uid == sessao["id"]:
            lbl_edit_msg.config(text="Nao e possivel remover o usuario logado.", fg=VERM); return
        nome_u = next((l["nome"] for l in linhas if l["id"] == uid), "?")
        if messagebox.askyesno("Confirmar", f"Remover usuario '{nome_u}'?", parent=root):
            auth.remover_usuario(uid)
            selecionado[0] = None
            lbl_edit_msg.config(text=f"Usuario '{nome_u}' removido.", fg=VERDE)
            _renderizar()

    def _trocar_grupo():
        uid = selecionado[0]
        if uid is None:
            lbl_edit_msg.config(text="Selecione um usuario.", fg=VERM); return
        if uid == sessao["id"]:
            lbl_edit_msg.config(text="Nao e possivel alterar o proprio grupo.", fg=VERM); return
        u = next((l for l in linhas if l["id"] == uid), None)
        if not u:
            return
        novo = "usuario" if u["grupo"] == "administrador" else "administrador"
        auth.alterar_grupo(uid, novo)
        lbl_edit_msg.config(text=f"Grupo alterado para '{novo}'.", fg=VERDE)
        _renderizar()

    tk.Frame(root, bg=CESC, height=1).pack(fill="x", padx=14)

    # ── Botoes de acao ────────────────────────────────────────────────────────
    frm_btns = tk.Frame(root, bg=BG, padx=14, pady=10)
    frm_btns.pack(fill="x")

    # Novo usuario
    tk.Label(frm_btns, text="Novo:  ", font=("Segoe UI", 8), bg=BG, fg=CINZA
             ).pack(side="left")
    _btn_factory(frm_btns, "Criar Usuario", _criar, cor=AMA)

    tk.Frame(frm_btns, bg=CESC, width=1, height=20).pack(side="left", padx=8)

    # Edicao do selecionado
    tk.Label(frm_btns, text="Selecionado:  ", font=("Segoe UI", 8), bg=BG, fg=CINZA
             ).pack(side="left")
    _btn_factory(frm_btns, "Salvar Nome",    _salvar_nome_edit, cor=AZUL)
    _btn_factory(frm_btns, "Redefinir Senha",_redefinir_senha,  cor="#155A8C")
    _btn_factory(frm_btns, "Trocar Grupo",   _trocar_grupo,     cor="#006677")
    _btn_factory(frm_btns, "Remover",        _remover,          cor="#991133")

    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w,  h  = root.winfo_reqwidth(),   root.winfo_reqheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    root.wait_window(root)
    import gc as _gc; _gc.collect()
