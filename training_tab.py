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
        "#cc2222" if bg == VERMELHO else bg
    )
    b = tk.Label(pai, text=texto, font=FONT_BTN,
                 bg=bg, fg=fg, padx=12, pady=7, cursor="hand2")
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>",    lambda _: b.config(bg=hover))
    b.bind("<Leave>",    lambda _: b.config(bg=bg))
    return b


class TrainingTab:
    def __init__(self, root: tk.Tk):
        self._root = root
        self._analise_selecionada = None
        self._filtro_nivel  = tk.StringVar(value="todos")
        self._filtro_camera = tk.StringVar(value="todas")
        self._obs_var       = tk.StringVar()

        root.title("SPARTA AGENTE IA — Treinamento de IA")
        root.configure(bg=BG)
        root.geometry("1000x700")
        root.minsize(800, 560)

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
        # Topo: filtros + estatisticas
        topo = tk.Frame(self._root, bg=BG_CARD, padx=16, pady=10)
        topo.pack(fill="x")
        self._montar_filtros(topo)
        self._montar_estatisticas_resumidas(topo)

        # Notebook
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

    def _montar_filtros(self, pai):
        f = tk.Frame(pai, bg=BG_CARD)
        f.pack(side="left")

        tk.Label(f, text="FILTROS", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")

        row = tk.Frame(f, bg=BG_CARD)
        row.pack(fill="x", pady=3)

        tk.Label(row, text="Nível:", font=FONT_LABEL,
                 bg=BG_CARD, fg=CINZA).pack(side="left")
        ttk.Combobox(row, textvariable=self._filtro_nivel, width=12, state="readonly",
                     values=["todos", "sem_risco", "atencao", "suspeito", "critico"]
                     ).pack(side="left", padx=(4, 14))

        tk.Label(row, text="Câmera:", font=FONT_LABEL,
                 bg=BG_CARD, fg=CINZA).pack(side="left")
        self._cb_camera = ttk.Combobox(row, textvariable=self._filtro_camera,
                                       width=14, state="readonly")
        self._cb_camera.pack(side="left", padx=(4, 0))

        _btn(f, "  Filtrar  ", self._carregar_dados).pack(anchor="w", pady=(7, 0))

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
        # Treeview
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
        painel = tk.Frame(pai, bg=BG_CARD, padx=16, pady=14, width=310)
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

        tk.Label(painel, text="Observacao (opcional):", font=FONT_LABEL,
                 bg=BG_CARD, fg=CINZA).pack(anchor="w", pady=(6, 2))
        self._entry_obs = tk.Entry(painel, textvariable=self._obs_var,
                                   font=FONT_MONO, bg="#242424", fg=BRANCO,
                                   insertbackground=AMARELO, relief="flat",
                                   highlightthickness=1,
                                   highlightbackground=CINZA_ESC)
        self._entry_obs.pack(fill="x", ipady=5)

        self._sv_fb_status = tk.StringVar(value="")
        tk.Label(painel, textvariable=self._sv_fb_status,
                 font=FONT_LABEL, bg=BG_CARD, fg=VERDE).pack(anchor="w", pady=(5, 0))

        tk.Frame(painel, bg=CINZA_ESC, height=1).pack(fill="x", pady=(14, 10))
        tk.Label(painel, text="DICA", font=("Segoe UI", 8, "bold"),
                 bg=BG_CARD, fg=AMARELO).pack(anchor="w")
        tk.Label(painel,
                 text="Feedbacks confirmados alimentam\nautomaticamente o banco de\nexemplos few-shot, melhorando\na precisao da IA nas proximas\nanalises.",
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

    # ── Lógica ────────────────────────────────────────────────────────────────

    def _carregar_dados(self):
        analises = db.buscar_analises(
            nivel_risco=self._filtro_nivel.get(),
            camera_id=self._filtro_camera.get(),
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
        self._obs_var.set("")

    def _salvar_feedback(self, rotulo: str):
        if not self._analise_selecionada:
            self._sv_fb_status.set("Selecione uma deteccao primeiro.")
            return
        analise_id = self._analise_selecionada["id"]
        obs = self._obs_var.get().strip()

        def _gravar():
            db.salvar_feedback(analise_id, rotulo, obs)

        threading.Thread(target=_gravar, daemon=True).start()

        status = "Salvo: CORRETO" if rotulo == "correto" else "Salvo: FALSO POSITIVO"
        self._sv_fb_status.set(status)
        self._obs_var.set("")
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

            opcoes = json.loads(p["opcoes"]) if p.get("opcoes") else []
            brow = tk.Frame(card, bg=BG_CARD)
            brow.pack(fill="x")
            for op in opcoes:
                _btn(brow, op,
                     lambda pid=p["id"], r=op: self._responder_pergunta(pid, r),
                     bg=CINZA_ESC, fg=BRANCO).pack(side="left", padx=(0, 6))

    def _responder_pergunta(self, pergunta_id: int, resposta: str):
        threading.Thread(
            target=lambda: db.responder_pergunta(pergunta_id, resposta),
            daemon=True
        ).start()
        self._root.after(500, self._carregar_dados)


# ── Ponto de entrada ───────────────────────────────────────────────────────────

def abrir_training():
    root = tk.Tk()
    TrainingTab(root)
    root.mainloop()


if __name__ == "__main__":
    abrir_training()
