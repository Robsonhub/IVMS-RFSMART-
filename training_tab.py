"""
Aba de Treinamento de IA — SPARTA AGENTE IA
Tema: amarelo/preto (#FFD000 / #0F0F0F), consistente com o restante do sistema.
"""
import json
import threading
import tkinter as tk
from tkinter import ttk

import db

# ── Paleta ─────────────────────────────────────────────────────────────────────
BG          = "#0F0F0F"
BG_CARD     = "#1A1A1A"
AMARELO     = "#FFD000"
AMARELO_ESC = "#B39200"
BRANCO      = "#F0F0F0"
CINZA       = "#888888"
CINZA_ESC   = "#333333"
VERMELHO    = "#FF4444"
VERDE       = "#3DCC7E"
LARANJA     = "#FF6400"
AZUL        = "#4A9EFF"

NIVEL_COR = {
    "sem_risco": VERDE,
    "atencao":   AMARELO,
    "suspeito":  LARANJA,
    "critico":   VERMELHO,
}

FONT_TITULO = ("Segoe UI", 13, "bold")
FONT_LABEL  = ("Segoe UI", 9)
FONT_MONO   = ("Consolas", 9)
FONT_BTN    = ("Segoe UI", 9, "bold")
FONT_SMALL  = ("Segoe UI", 8)


def _btn(pai, texto, cmd, bg=AMARELO, fg=BG):
    hover = AMARELO_ESC if bg == AMARELO else (
        "#4a4a4a" if bg == CINZA_ESC else
        "#2eaa60" if bg == VERDE else
        "#cc2222" if bg == VERMELHO else
        "#2e7acc" if bg == AZUL else bg
    )
    b = tk.Label(pai, text=texto, font=FONT_BTN,
                 bg=bg, fg=fg, padx=12, pady=7, cursor="hand2")
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>",    lambda _: b.config(bg=hover))
    b.bind("<Leave>",    lambda _: b.config(bg=bg))
    return b


# ── Diálogo de Chat com IA ─────────────────────────────────────────────────────

class ChatDialog:
    """Janela de conversa livre com a IA sobre uma análise específica."""

    _SYSTEM = (
        "Você é o assistente de calibração do SPARTA AGENTE IA, sistema de vigilância "
        "para garimpo de ouro. Sua função é ajudar o operador a explicar o que "
        "realmente aconteceu em uma cena detectada pela câmera, para que o sistema "
        "aprenda corretamente. Faça perguntas claras e objetivas quando precisar de "
        "mais detalhes. Responda sempre em português brasileiro. Seja conciso."
    )

    def __init__(self, parent: tk.Misc, analise: dict, on_salvar_obs=None):
        self._on_salvar_obs = on_salvar_obs
        self._historico: list[dict] = []
        self._analise = analise

        self._win = tk.Toplevel(parent)
        self._win.title("Conversar com IA — Explicar Ocorrência")
        self._win.configure(bg=BG)
        self._win.geometry("680x540")
        self._win.resizable(True, True)
        self._win.grab_set()
        self._win.attributes("-topmost", True)

        self._montar_ui()
        self._mensagem_inicial()

    def _montar_ui(self):
        a = self._analise
        comps = json.loads(a["comportamentos"]) if a.get("comportamentos") else []
        resumo = (
            f"Câmera: {a.get('camera_id','?')}  |  "
            f"{str(a.get('timestamp_analise',''))[:19]}  |  "
            f"Nível: {a.get('nivel_risco','?').upper()}  |  "
            f"Confiança: {a.get('confianca',0)*100:.0f}%"
        )

        # Cabeçalho
        cab = tk.Frame(self._win, bg=AMARELO, padx=16, pady=8)
        cab.pack(fill="x")
        tk.Label(cab, text="Conversar com IA sobre esta análise",
                 font=("Segoe UI", 10, "bold"), bg=AMARELO, fg=BG).pack(side="left")

        # Contexto
        ctx = tk.Frame(self._win, bg=BG_CARD, padx=14, pady=8)
        ctx.pack(fill="x")
        tk.Label(ctx, text=resumo, font=FONT_MONO, bg=BG_CARD, fg=CINZA).pack(anchor="w")
        if comps:
            desc = " | ".join(comps[:2]) + ("..." if len(comps) > 2 else "")
            tk.Label(ctx, text=f"Detectado: {desc}", font=FONT_SMALL,
                     bg=BG_CARD, fg=BRANCO, wraplength=640, justify="left").pack(anchor="w")

        # Histórico do chat
        frm_hist = tk.Frame(self._win, bg=BG)
        frm_hist.pack(fill="both", expand=True, padx=10, pady=(8, 0))

        self._txt_hist = tk.Text(
            frm_hist, bg="#111111", fg=BRANCO, font=("Segoe UI", 9),
            wrap="word", state="disabled", relief="flat",
            highlightthickness=1, highlightbackground=CINZA_ESC,
            spacing1=4, spacing3=4,
        )
        sb_hist = ttk.Scrollbar(frm_hist, orient="vertical",
                                command=self._txt_hist.yview)
        self._txt_hist.configure(yscrollcommand=sb_hist.set)
        sb_hist.pack(side="right", fill="y")
        self._txt_hist.pack(fill="both", expand=True)

        self._txt_hist.tag_configure("ia",  foreground=AMARELO, font=("Segoe UI", 9, "bold"))
        self._txt_hist.tag_configure("vc",  foreground=VERDE,   font=("Segoe UI", 9, "bold"))
        self._txt_hist.tag_configure("msg", foreground=BRANCO,  font=("Segoe UI", 9))

        # Área de digitação
        frm_input = tk.Frame(self._win, bg=BG_CARD, padx=10, pady=8)
        frm_input.pack(fill="x", padx=10, pady=(4, 0))

        self._txt_input = tk.Text(
            frm_input, bg="#242424", fg=BRANCO, font=("Segoe UI", 9),
            height=3, wrap="word", relief="flat",
            insertbackground=AMARELO,
            highlightthickness=1, highlightbackground=CINZA_ESC,
        )
        self._txt_input.pack(fill="x")
        self._txt_input.bind("<Return>", self._on_enter)
        self._txt_input.bind("<Shift-Return>", lambda e: None)

        # Botões
        frm_btns = tk.Frame(self._win, bg=BG, padx=10, pady=8)
        frm_btns.pack(fill="x")

        _btn(frm_btns, "  Enviar  ", self._enviar,
             bg=AMARELO, fg=BG).pack(side="left")
        tk.Label(frm_btns, text="Enter envia  |  Shift+Enter nova linha",
                 font=FONT_SMALL, bg=BG, fg=CINZA).pack(side="left", padx=10)

        self._btn_salvar = _btn(frm_btns, "  Salvar como Observação  ",
                                self._salvar_obs, bg=VERDE, fg=BG)
        self._btn_salvar.pack(side="right", padx=(0, 4))
        self._btn_salvar.pack_forget()

        _btn(frm_btns, "  Fechar  ", self._win.destroy,
             bg=CINZA_ESC, fg=BRANCO).pack(side="right", padx=(0, 6))

    def _mensagem_inicial(self):
        a = self._analise
        comps = json.loads(a["comportamentos"]) if a.get("comportamentos") else []
        nivel = a.get("nivel_risco", "atencao").upper()

        msg_ia = (
            f"Analisei esta cena e classifiquei como **{nivel}** "
            f"com {a.get('confianca',0)*100:.0f}% de confiança.\n\n"
            f"Comportamentos detectados:\n" +
            "\n".join(f"• {c}" for c in comps) +
            "\n\nO que realmente estava acontecendo neste momento? "
            "Pode descrever com suas próprias palavras."
        )
        self._adicionar_mensagem("IA", msg_ia)
        self._historico.append({"role": "assistant", "content": msg_ia})

    def _on_enter(self, event):
        if not (event.state & 0x1):  # Shift não pressionado
            self._enviar()
            return "break"

    def _enviar(self):
        texto = self._txt_input.get("1.0", "end-1c").strip()
        if not texto:
            return
        self._txt_input.delete("1.0", "end")
        self._adicionar_mensagem("Você", texto)
        self._historico.append({"role": "user", "content": texto})
        threading.Thread(target=self._chamar_ia, daemon=True).start()

    def _chamar_ia(self):
        try:
            from config import CLAUDE_API_KEY
            import anthropic as _ant
            client = _ant.Anthropic(api_key=CLAUDE_API_KEY)

            a = self._analise
            comps = json.loads(a["comportamentos"]) if a.get("comportamentos") else []
            contexto = (
                f"Análise: câmera={a.get('camera_id')}, "
                f"nível={a.get('nivel_risco')}, "
                f"confiança={a.get('confianca',0)*100:.0f}%, "
                f"comportamentos detectados: {'; '.join(comps)}, "
                f"ação recomendada: {a.get('acao_recomendada','N/A')}"
            )
            system = f"{self._SYSTEM}\n\nContexto da análise em debate:\n{contexto}"

            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=512,
                system=system,
                messages=self._historico,
            )
            resposta = resp.content[0].text
            self._historico.append({"role": "assistant", "content": resposta})
            self._win.after(0, lambda: self._adicionar_mensagem("IA", resposta))
            self._win.after(0, lambda: self._btn_salvar.pack(side="right", padx=(0, 4)))
        except Exception as exc:
            self._win.after(0, lambda: self._adicionar_mensagem(
                "IA", f"Erro ao conectar com a IA: {exc}"))

    def _adicionar_mensagem(self, remetente: str, texto: str):
        self._txt_hist.configure(state="normal")
        tag = "ia" if remetente == "IA" else "vc"
        self._txt_hist.insert("end", f"{remetente}:\n", tag)
        self._txt_hist.insert("end", f"{texto}\n\n", "msg")
        self._txt_hist.configure(state="disabled")
        self._txt_hist.see("end")

    def _salvar_obs(self):
        # Monta resumo da conversa para a observação
        linhas = []
        for m in self._historico:
            role = "IA" if m["role"] == "assistant" else "Operador"
            linhas.append(f"[{role}] {m['content']}")
        resumo = "\n".join(linhas)
        if self._on_salvar_obs:
            self._on_salvar_obs(resumo)
        self._win.destroy()


# ── TrainingTab ────────────────────────────────────────────────────────────────

class TrainingTab:
    def __init__(self, root: tk.Tk):
        self._root = root
        self._analise_selecionada = None
        self._filtro_nivel        = tk.StringVar(value="todos")
        self._filtro_camera       = tk.StringVar(value="todas")
        self._filtro_data_inicio  = tk.StringVar(value="")
        self._filtro_data_fim     = tk.StringVar(value="")

        root.title("SPARTA AGENTE IA — Treinamento de IA")
        root.configure(bg=BG)
        root.geometry("1100x720")
        root.minsize(900, 580)

        self._montar_cabecalho()
        self._montar_corpo()
        self._carregar_dados()

    # ── Cabecalho ──────────────────────────────────────────────────────────────

    def _montar_cabecalho(self):
        cab = tk.Frame(self._root, bg=AMARELO, padx=20, pady=10)
        cab.pack(fill="x")
        tk.Label(cab, text="SPARTA AGENTE IA  —  Treinamento de IA",
                 font=FONT_TITULO, bg=AMARELO, fg=BG).pack(side="left")

        self._sv_badge = tk.StringVar(value="")
        self._lbl_badge = tk.Label(cab, textvariable=self._sv_badge,
                                   font=FONT_BTN, bg=VERMELHO, fg=BRANCO,
                                   padx=10, pady=3)

    # ── Corpo ──────────────────────────────────────────────────────────────────

    def _montar_corpo(self):
        topo = tk.Frame(self._root, bg=BG_CARD, padx=16, pady=10)
        topo.pack(fill="x")
        self._montar_filtros(topo)
        self._montar_estatisticas_resumidas(topo)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CINZA_ESC, foreground=BRANCO,
                        padding=[14, 6], font=FONT_LABEL)
        style.map("TNotebook.Tab",
                  background=[("selected", AMARELO)],
                  foreground=[("selected", BG)])
        style.configure("Treeview", background=BG_CARD, foreground=BRANCO,
                        fieldbackground=BG_CARD, rowheight=22)
        style.configure("Treeview.Heading", background=CINZA_ESC,
                        foreground=BRANCO, font=FONT_LABEL)
        style.map("Treeview", background=[("selected", AMARELO_ESC)])

        self._nb = ttk.Notebook(self._root)
        self._nb.pack(fill="both", expand=True, padx=8, pady=(4, 8))

        aba1 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba1, text="  Detecções  ")
        self._montar_aba_deteccoes(aba1)

        aba2 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba2, text="  Perguntas (0)  ")
        self._aba2 = aba2
        self._montar_aba_perguntas(aba2)

        aba3 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba3, text="  Estatísticas  ")
        self._montar_aba_estatisticas(aba3)

        aba4 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba4, text="  Tokens  ")
        self._montar_aba_tokens(aba4)

        aba5 = tk.Frame(self._nb, bg=BG)
        self._nb.add(aba5, text="  Tendências  ")
        self._montar_aba_tendencias(aba5)

    def _montar_filtros(self, pai):
        f = tk.Frame(pai, bg=BG_CARD)
        f.pack(side="left")

        tk.Label(f, text="FILTROS", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")

        row1 = tk.Frame(f, bg=BG_CARD)
        row1.pack(fill="x", pady=2)

        tk.Label(row1, text="Nível:", font=FONT_LABEL,
                 bg=BG_CARD, fg=CINZA).pack(side="left")
        ttk.Combobox(row1, textvariable=self._filtro_nivel, width=11, state="readonly",
                     values=["todos", "sem_risco", "atencao", "suspeito", "critico"]
                     ).pack(side="left", padx=(4, 12))

        tk.Label(row1, text="Câmera:", font=FONT_LABEL,
                 bg=BG_CARD, fg=CINZA).pack(side="left")
        self._cb_camera = ttk.Combobox(row1, textvariable=self._filtro_camera,
                                       width=13, state="readonly")
        self._cb_camera.pack(side="left", padx=(4, 0))

        row2 = tk.Frame(f, bg=BG_CARD)
        row2.pack(fill="x", pady=2)

        tk.Label(row2, text="De:", font=FONT_LABEL, bg=BG_CARD, fg=CINZA).pack(side="left")
        tk.Entry(row2, textvariable=self._filtro_data_inicio, font=FONT_MONO,
                 bg="#242424", fg=BRANCO, insertbackground=AMARELO,
                 relief="flat", width=11).pack(side="left", padx=(4, 8))
        tk.Label(row2, text="Até:", font=FONT_LABEL, bg=BG_CARD, fg=CINZA).pack(side="left")
        tk.Entry(row2, textvariable=self._filtro_data_fim, font=FONT_MONO,
                 bg="#242424", fg=BRANCO, insertbackground=AMARELO,
                 relief="flat", width=11).pack(side="left", padx=(4, 0))
        tk.Label(row2, text="(AAAA-MM-DD)", font=FONT_SMALL,
                 bg=BG_CARD, fg=CINZA).pack(side="left", padx=(6, 0))

        brow = tk.Frame(f, bg=BG_CARD)
        brow.pack(anchor="w", pady=(6, 0))
        _btn(brow, " Filtrar ", self._carregar_dados).pack(side="left")
        _btn(brow, " Exportar Excel ", self._exportar_excel,
             bg=CINZA_ESC, fg=BRANCO).pack(side="left", padx=(8, 0))

    def _montar_estatisticas_resumidas(self, pai):
        f = tk.Frame(pai, bg=BG_CARD, padx=24)
        f.pack(side="right", anchor="ne")
        tk.Label(f, text="RESUMO", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")
        self._sv_resumo = tk.StringVar(value="Carregando...")
        tk.Label(f, textvariable=self._sv_resumo, font=FONT_MONO,
                 bg=BG_CARD, fg=BRANCO, justify="left").pack(anchor="w")

    # ── Aba 1: Detecções ───────────────────────────────────────────────────────

    def _montar_aba_deteccoes(self, pai):
        cols = ("hora", "camera", "nivel", "confianca", "feedback")
        self._tree = ttk.Treeview(pai, columns=cols, show="headings", height=14)

        for col, larg, anc in [
            ("hora",      145, "w"),
            ("camera",    130, "w"),
            ("nivel",     110, "center"),
            ("confianca",  80, "center"),
            ("feedback",   90, "center"),
        ]:
            self._tree.heading(col, text=col.capitalize())
            self._tree.column(col, width=larg, anchor=anc)

        self._tree.tag_configure("sem_risco", foreground=VERDE)
        self._tree.tag_configure("atencao",   foreground=AMARELO)
        self._tree.tag_configure("suspeito",  foreground=LARANJA)
        self._tree.tag_configure("critico",   foreground=VERMELHO,
                                 font=("Segoe UI", 9, "bold"))

        sb = ttk.Scrollbar(pai, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=sb.set)
        self._tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb.pack(side="left", fill="y", pady=8)
        self._tree.bind("<<TreeviewSelect>>", self._on_selecionar)

        # Painel de detalhes + feedback
        painel = tk.Frame(pai, bg=BG_CARD, padx=16, pady=14, width=320)
        painel.pack(side="left", fill="y", padx=8, pady=8)
        painel.pack_propagate(False)

        tk.Label(painel, text="DETALHES", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")

        self._sv_detalhe = tk.StringVar(value="Selecione uma deteccao")
        tk.Label(painel, textvariable=self._sv_detalhe, font=FONT_MONO,
                 bg=BG_CARD, fg=BRANCO, wraplength=270,
                 justify="left").pack(anchor="w", pady=(4, 12))

        tk.Frame(painel, bg=CINZA_ESC, height=1).pack(fill="x", pady=(0, 10))

        tk.Label(painel, text="FEEDBACK DO ADMIN", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")

        brow = tk.Frame(painel, bg=BG_CARD)
        brow.pack(fill="x", pady=6)
        _btn(brow, "Correto", lambda: self._salvar_feedback("correto"),
             bg=VERDE, fg=BG).pack(side="left", expand=True, fill="x", padx=(0, 4))
        _btn(brow, "Falso Positivo", lambda: self._salvar_feedback("falso_positivo"),
             bg=VERMELHO, fg=BRANCO).pack(side="left", expand=True, fill="x")

        # Botão de chat com IA
        _btn(painel, "  Conversar com IA sobre esta ocorrência  ",
             self._abrir_chat, bg=AZUL, fg=BRANCO).pack(fill="x", pady=(2, 8))

        tk.Frame(painel, bg=CINZA_ESC, height=1).pack(fill="x", pady=(0, 8))

        tk.Label(painel, text="Observação / Explicação:",
                 font=FONT_LABEL, bg=BG_CARD, fg=CINZA).pack(anchor="w", pady=(0, 2))
        tk.Label(painel,
                 text="Descreva o que realmente acontecia na cena.",
                 font=FONT_SMALL, bg=BG_CARD, fg=CINZA, wraplength=270,
                 justify="left").pack(anchor="w", pady=(0, 4))

        # Campo de texto multi-linha para observação
        frm_obs = tk.Frame(painel, bg=BG_CARD)
        frm_obs.pack(fill="x")
        self._text_obs = tk.Text(
            frm_obs, font=FONT_MONO, bg="#242424", fg=BRANCO,
            insertbackground=AMARELO, relief="flat",
            highlightthickness=1, highlightbackground=CINZA_ESC,
            height=4, wrap="word",
        )
        sb_obs = ttk.Scrollbar(frm_obs, orient="vertical",
                               command=self._text_obs.yview)
        self._text_obs.configure(yscrollcommand=sb_obs.set)
        sb_obs.pack(side="right", fill="y")
        self._text_obs.pack(fill="x")

        self._sv_fb_status = tk.StringVar(value="")
        tk.Label(painel, textvariable=self._sv_fb_status,
                 font=FONT_LABEL, bg=BG_CARD, fg=VERDE).pack(anchor="w", pady=(5, 0))

        tk.Frame(painel, bg=CINZA_ESC, height=1).pack(fill="x", pady=(10, 8))
        tk.Label(painel, text="DICA", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")
        tk.Label(painel,
                 text="Use o chat para explicar o contexto\nda ocorrência. A observação salva\nenriquece o exemplo few-shot e\nmelhora a precisão da IA.",
                 font=FONT_SMALL, bg=BG_CARD, fg=CINZA, justify="left").pack(anchor="w")

    # ── Aba 2: Perguntas ───────────────────────────────────────────────────────

    def _montar_aba_perguntas(self, pai):
        canvas = tk.Canvas(pai, bg=BG, highlightthickness=0)
        sb = ttk.Scrollbar(pai, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)

        self._frame_perguntas = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=self._frame_perguntas, anchor="nw")

        def _cfg(e):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(win, width=canvas.winfo_width())

        self._frame_perguntas.bind("<Configure>", _cfg)
        canvas.bind("<Configure>", _cfg)

    # ── Aba 3: Estatísticas ────────────────────────────────────────────────────

    def _montar_aba_estatisticas(self, pai):
        f = tk.Frame(pai, bg=BG, padx=28, pady=24)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="METRICAS DE DESEMPENHO DA IA",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=AMARELO).pack(anchor="w", pady=(0, 16))
        self._sv_stats_full = tk.StringVar(value="")
        tk.Label(f, textvariable=self._sv_stats_full, font=("Consolas", 10),
                 bg=BG, fg=BRANCO, justify="left").pack(anchor="w")

    # ── Aba 4: Tokens ──────────────────────────────────────────────────────────

    def _montar_aba_tokens(self, pai):
        f = tk.Frame(pai, bg=BG, padx=28, pady=24)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="USO DE TOKENS — ÚLTIMOS 30 DIAS",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=AMARELO).pack(anchor="w", pady=(0, 12))
        self._sv_tokens = tk.StringVar(value="Carregando...")
        tk.Label(f, textvariable=self._sv_tokens, font=("Consolas", 9),
                 bg=BG, fg=BRANCO, justify="left").pack(anchor="w")

    def _atualizar_aba_tokens(self):
        try:
            dados = db.estatisticas_tokens(dias=30)
        except Exception:
            self._sv_tokens.set("Erro ao carregar dados de tokens.")
            return

        if not dados:
            self._sv_tokens.set("Nenhuma análise registrada ainda.")
            return

        total_in = sum(r["tok_in"] or 0 for r in dados)
        total_out = sum(r["tok_out"] or 0 for r in dados)
        custo_estimado = (total_in * 15 + total_out * 75) / 1_000_000

        linhas = [
            f"{'DIA':<12}  {'ANÁLISES':>8}  {'TOK ENTRADA':>12}  {'TOK SAÍDA':>10}",
            "─" * 50,
        ]
        for r in dados[-15:]:
            linhas.append(
                f"{r['dia']:<12}  {r['analises']:>8}  {r['tok_in'] or 0:>12,}  {r['tok_out'] or 0:>10,}"
            )
        linhas += [
            "─" * 50,
            f"{'TOTAL':<12}  {'':>8}  {total_in:>12,}  {total_out:>10,}",
            "",
            f"Custo estimado (30d): US$ {custo_estimado:.4f}",
            f"  (entrada: ${total_in*15/1_000_000:.4f}  |  saída: ${total_out*75/1_000_000:.4f})",
        ]
        self._sv_tokens.set("\n".join(linhas))

    # ── Aba 5: Tendências ──────────────────────────────────────────────────────

    def _montar_aba_tendencias(self, pai):
        f = tk.Frame(pai, bg=BG, padx=28, pady=24)
        f.pack(fill="both", expand=True)
        tk.Label(f, text="TENDÊNCIAS DE ALERTAS — ÚLTIMOS 7 DIAS",
                 font=("Segoe UI", 11, "bold"), bg=BG, fg=AMARELO).pack(anchor="w", pady=(0, 12))
        self._sv_tendencias = tk.StringVar(value="Carregando...")
        tk.Label(f, textvariable=self._sv_tendencias, font=("Consolas", 9),
                 bg=BG, fg=BRANCO, justify="left").pack(anchor="w")

    # ── Lógica ────────────────────────────────────────────────────────────────

    def _exportar_excel(self):
        from tkinter import filedialog, messagebox

        def _gerar():
            try:
                import report_generator
                destino = filedialog.asksaveasfilename(
                    defaultextension=".xlsx",
                    filetypes=[("Excel", "*.xlsx")],
                    title="Salvar relatório Excel",
                )
                if not destino:
                    return
                caminho = report_generator.gerar_excel_do_db(
                    data_inicio=self._filtro_data_inicio.get().strip() or None,
                    data_fim=self._filtro_data_fim.get().strip() or None,
                    camera_id=self._filtro_camera.get() if self._filtro_camera.get() != "todas" else None,
                    destino=destino,
                )
                self._root.after(0, lambda: messagebox.showinfo(
                    "Exportação concluída", f"Relatório salvo em:\n{caminho}"))
            except Exception as exc:
                self._root.after(0, lambda: messagebox.showerror("Erro", str(exc)))

        threading.Thread(target=_gerar, daemon=True).start()

    def _carregar_dados(self):
        analises = db.buscar_analises_filtradas(
            nivel_risco=self._filtro_nivel.get(),
            camera_id=self._filtro_camera.get(),
            data_inicio=self._filtro_data_inicio.get().strip() or None,
            data_fim=self._filtro_data_fim.get().strip() or None,
            limite=300,
        )

        cameras = ["todas"] + db.buscar_cameras_distintas()
        self._cb_camera["values"] = cameras

        for item in self._tree.get_children():
            self._tree.delete(item)

        fb_map = self._mapa_feedbacks()

        for a in analises:
            hora = a["timestamp_analise"][:19].replace("T", " ")
            conf = f"{a['confianca']*100:.0f}%"
            nivel = a["nivel_risco"]
            fb = fb_map.get(a["id"], "—")
            self._tree.insert("", "end",
                              values=(hora, a["camera_id"], nivel.upper(), conf, fb),
                              iid=str(a["id"]),
                              tags=(nivel,))

        self._atualizar_estatisticas()
        self._atualizar_perguntas()
        self._atualizar_aba_tokens()
        self._atualizar_tendencias()

    def _mapa_feedbacks(self) -> dict:
        conn = db.get_connection()
        rows = conn.execute(
            "SELECT analise_id, rotulo FROM feedbacks ORDER BY created_at ASC"
        ).fetchall()
        result = {}
        for r in rows:
            result[r["analise_id"]] = "Correto" if r["rotulo"] == "correto" else "Falso Pos."
        return result

    def _on_selecionar(self, _event):
        sel = self._tree.selection()
        if not sel:
            return
        analise_id = int(sel[0])
        conn = db.get_connection()
        row = conn.execute("SELECT * FROM analises WHERE id=?", (analise_id,)).fetchone()
        if not row:
            return

        self._analise_selecionada = dict(row)
        comps = json.loads(row["comportamentos"]) if row["comportamentos"] else []
        texto = (
            f"Camera:    {row['camera_id']}\n"
            f"Horario:   {row['timestamp_analise'][:19]}\n"
            f"Nivel:     {row['nivel_risco'].upper()}\n"
            f"Confianca: {row['confianca']*100:.0f}%\n"
            f"Tokens:    {row['tokens_entrada'] or 0}/{row['tokens_saida'] or 0}\n\n"
            f"Comportamentos:\n" +
            "\n".join(f"  - {c}" for c in comps) +
            f"\n\nAcao:\n  {row['acao_recomendada'] or '---'}"
        )
        self._sv_detalhe.set(texto)
        self._sv_fb_status.set("")
        self._text_obs.delete("1.0", "end")

    def _abrir_chat(self):
        if not self._analise_selecionada:
            self._sv_fb_status.set("Selecione uma deteccao primeiro.")
            return

        def _ao_salvar(resumo: str):
            self._text_obs.delete("1.0", "end")
            self._text_obs.insert("1.0", resumo)
            self._sv_fb_status.set("Conversa salva na observação — confirme com Correto ou Falso Positivo.")

        ChatDialog(self._root, self._analise_selecionada, on_salvar_obs=_ao_salvar)

    def _salvar_feedback(self, rotulo: str):
        if not self._analise_selecionada:
            self._sv_fb_status.set("Selecione uma deteccao primeiro.")
            return
        analise_id = self._analise_selecionada["id"]
        obs = self._text_obs.get("1.0", "end-1c").strip()

        def _gravar():
            db.salvar_feedback(analise_id, rotulo, obs)

        threading.Thread(target=_gravar, daemon=True).start()

        status = "Salvo: CORRETO" if rotulo == "correto" else "Salvo: FALSO POSITIVO"
        self._sv_fb_status.set(status)
        self._text_obs.delete("1.0", "end")
        self._root.after(600, self._carregar_dados)

    def _atualizar_estatisticas(self):
        stats = db.estatisticas()
        taxa = stats.get("taxa_falsos_positivos")
        taxa_str = f"{taxa*100:.1f}%" if taxa is not None else "sem dados"

        self._sv_resumo.set(
            f"Total: {stats['total_analises']}  |  "
            f"Alertas: {stats['total_alertas']}  |  "
            f"Falsos Pos.: {stats['falsos_positivos']} ({taxa_str})"
        )

        self._sv_stats_full.set(
            f"Total de analises:         {stats['total_analises']}\n"
            f"Total de alertas:          {stats['total_alertas']}\n"
            f"Feedbacks dados:           {stats['com_feedback']}\n"
            f"  - Corretos:              {stats['corretos']}\n"
            f"  - Falsos positivos:      {stats['falsos_positivos']}\n"
            f"Taxa de falsos positivos:  {taxa_str}\n"
            f"Perguntas pendentes:       {stats['perguntas_pendentes']}\n"
            f"Exemplos few-shot ativos:  {stats['exemplos_fewshot']}\n"
        )

    def _atualizar_perguntas(self):
        perguntas = db.buscar_perguntas_pendentes()
        n = len(perguntas)

        if n > 0:
            self._sv_badge.set(f"  {n} pergunta(s) pendente(s)  ")
            self._lbl_badge.pack(side="right", padx=(0, 8))
        else:
            self._sv_badge.set("")
            self._lbl_badge.pack_forget()

        self._nb.tab(1, text=f"  Perguntas ({n})  ")

        for w in self._frame_perguntas.winfo_children():
            w.destroy()

        if not perguntas:
            tk.Label(self._frame_perguntas, text="Nenhuma pergunta pendente.",
                     font=FONT_LABEL, bg=BG, fg=CINZA,
                     padx=24, pady=24).pack()
            return

        for p in perguntas:
            self._montar_card_pergunta(p)

    def _montar_card_pergunta(self, p: dict):
        card = tk.Frame(self._frame_perguntas, bg=BG_CARD, padx=18, pady=14)
        card.pack(fill="x", padx=12, pady=6)

        nivel = p.get("nivel_risco", "atencao")
        cor = NIVEL_COR.get(nivel, CINZA)
        conf = p.get("confianca", 0)
        cabecalho = (
            f"{p.get('camera_id','?')}  |  "
            f"{str(p.get('timestamp_analise',''))[:19]}  |  "
            f"{nivel.upper()}  |  Conf: {conf*100:.0f}%"
        )
        tk.Label(card, text=cabecalho, font=FONT_MONO,
                 bg=BG_CARD, fg=cor).pack(anchor="w")

        tk.Label(card, text=p["pergunta"], font=FONT_LABEL,
                 bg=BG_CARD, fg=BRANCO, wraplength=700,
                 justify="left", pady=8).pack(anchor="w")

        # Opções rápidas
        opcoes = json.loads(p["opcoes"]) if p.get("opcoes") else []
        if opcoes:
            tk.Label(card, text="Resposta rápida:", font=FONT_SMALL,
                     bg=BG_CARD, fg=CINZA).pack(anchor="w", pady=(0, 4))
            brow = tk.Frame(card, bg=BG_CARD)
            brow.pack(fill="x")
            for op in opcoes:
                _btn(brow, op,
                     lambda pid=p["id"], r=op: self._responder_pergunta(pid, r),
                     bg=CINZA_ESC, fg=BRANCO).pack(side="left", padx=(0, 6), pady=(0, 6))

        # Separador
        tk.Frame(card, bg=CINZA_ESC, height=1).pack(fill="x", pady=(8, 8))

        # Explicação livre
        tk.Label(card,
                 text="Ou explique com suas palavras o que acontecia na cena:",
                 font=FONT_SMALL, bg=BG_CARD, fg=CINZA).pack(anchor="w", pady=(0, 4))

        frm_txt = tk.Frame(card, bg=BG_CARD)
        frm_txt.pack(fill="x")
        txt = tk.Text(
            frm_txt, font=("Segoe UI", 9), bg="#242424", fg=BRANCO,
            insertbackground=AMARELO, height=3, wrap="word", relief="flat",
            highlightthickness=1, highlightbackground=CINZA_ESC,
        )
        sb_txt = ttk.Scrollbar(frm_txt, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=sb_txt.set)
        sb_txt.pack(side="right", fill="y")
        txt.pack(fill="x")
        txt.insert("1.0", "Ex: o operador estava ajustando o equipamento, não havia risco...")

        txt.bind("<FocusIn>", lambda e, t=txt: t.delete("1.0", "end")
                 if t.get("1.0", "end-1c").startswith("Ex:") else None)

        brow2 = tk.Frame(card, bg=BG_CARD)
        brow2.pack(anchor="w", pady=(6, 0))
        _btn(brow2, "  Enviar Explicação  ",
             lambda pid=p["id"], t=txt: self._responder_pergunta_livre(pid, t),
             bg=AZUL, fg=BRANCO).pack(side="left")

    def _atualizar_tendencias(self):
        try:
            t = db.tendencias(dias=7)
        except Exception:
            self._sv_tendencias.set("Erro ao carregar tendências.")
            return

        linhas = [f"Período: últimos {t['dias']} dias\n"]

        linhas.append("ALERTAS POR NÍVEL:")
        if t["por_nivel"]:
            for r in t["por_nivel"]:
                bar = "█" * min(r["total"], 40)
                linhas.append(f"  {r['nivel_risco'].upper():<10} {r['total']:>5}  {bar}")
        else:
            linhas.append("  Nenhum alerta no período.")

        linhas.append("\nALERTAS POR CÂMERA:")
        if t["por_camera"]:
            for r in t["por_camera"]:
                bar = "█" * min(r["alertas"], 40)
                linhas.append(f"  {r['camera_id']:<16} {r['alertas']:>5}  {bar}")
        else:
            linhas.append("  Nenhum alerta no período.")

        self._sv_tendencias.set("\n".join(linhas))

    def _responder_pergunta(self, pergunta_id: int, resposta: str):
        threading.Thread(
            target=lambda: db.responder_pergunta(pergunta_id, resposta),
            daemon=True
        ).start()
        self._root.after(500, self._carregar_dados)

    def _responder_pergunta_livre(self, pergunta_id: int, txt_widget: tk.Text):
        texto = txt_widget.get("1.0", "end-1c").strip()
        if not texto or texto.startswith("Ex:"):
            return
        self._responder_pergunta(pergunta_id, texto)


# ── Ponto de entrada ───────────────────────────────────────────────────────────

def abrir_training():
    root = tk.Tk()
    TrainingTab(root)
    root.wait_window(root)
    import gc as _gc; _gc.collect()


if __name__ == "__main__":
    abrir_training()
