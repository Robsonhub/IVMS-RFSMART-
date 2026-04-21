"""Painel de API — SPARTA AGENTE IA (somente admin)."""
import logging
import os
import queue as _queue
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import messagebox

import db as _db

log = logging.getLogger(__name__)

BG      = "#0F0F0F"
BG_CARD = "#1A1A1A"
AMA     = "#FFD000"
AESC    = "#B39200"
BCOR    = "#F0F0F0"
CINZA   = "#888888"
CESC    = "#333333"
VERDE   = "#3DCC7E"
VERM    = "#FF4444"
AZUL    = "#336699"

FONT_T  = ("Segoe UI", 11, "bold")
FONT_L  = ("Segoe UI", 9)
FONT_M  = ("Consolas", 9)
FONT_B  = ("Segoe UI", 9, "bold")
FONT_S  = ("Segoe UI", 8)

_ENV_PATH = Path(".") / ".env"

_CUSTO_INPUT  = 3.00
_CUSTO_OUTPUT = 15.00


def _ler_env() -> dict:
    dados = {}
    if _ENV_PATH.exists():
        for linha in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.startswith("#"):
                k, _, v = linha.partition("=")
                dados[k.strip()] = v.strip()
    return dados


def _salvar_env(chave: str, valor: str):
    linhas = []
    encontrou = False
    if _ENV_PATH.exists():
        for linha in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            if linha.startswith(f"{chave}=") or linha.startswith(f"{chave} ="):
                linhas.append(f"{chave}={valor}")
                encontrou = True
            else:
                linhas.append(linha)
    if not encontrou:
        linhas.append(f"{chave}={valor}")
    _ENV_PATH.write_text("\n".join(linhas) + "\n", encoding="utf-8")


def _mascara_key(key: str) -> str:
    if len(key) < 12:
        return "••••••••"
    return key[:10] + "••••••••••••" + key[-4:]


def _verificar_saldo_api(api_key: str) -> dict:
    """
    Tenta obter saldo/créditos via Anthropic API.
    Retorna dict com status e info disponível.
    """
    import requests as _req
    resultado = {"status": "erro", "mensagem": "", "credito": None}
    try:
        # Faz uma requisição mínima para verificar se a chave é válida
        resp = _req.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 1,
                "messages": [{"role": "user", "content": "1"}],
            },
            timeout=10,
        )
        if resp.status_code == 200:
            resultado["status"] = "valida"
            resultado["mensagem"] = "Chave válida — API respondendo normalmente."
        elif resp.status_code == 401:
            resultado["status"] = "invalida"
            resultado["mensagem"] = "Chave inválida ou expirada."
        elif resp.status_code == 429:
            resultado["status"] = "limite"
            resultado["mensagem"] = "Limite de requisições atingido ou créditos esgotados."
        elif resp.status_code == 403:
            resultado["status"] = "sem_credito"
            resultado["mensagem"] = "Sem créditos disponíveis ou acesso bloqueado."
        else:
            resultado["mensagem"] = f"Resposta HTTP {resp.status_code}."
    except Exception as exc:
        resultado["mensagem"] = f"Erro de conexão: {exc}"
    return resultado


def _desenhar_grafico(canvas: tk.Canvas, dados: list):
    canvas.update_idletasks()
    largura = canvas.winfo_width()
    altura  = canvas.winfo_height()
    if largura <= 1:
        largura = 480
    canvas.delete("all")

    COR_IN_FILL  = "#0D2040"
    COR_IN_LINE  = "#5599EE"
    COR_OUT_FILL = "#2D1000"
    COR_OUT_LINE = "#EE8844"
    COR_GRID     = "#282828"

    if not dados:
        canvas.create_text(largura // 2, altura // 2,
                           text="Sem análises no período selecionado.",
                           fill=CINZA, font=FONT_S)
        return

    pad_l, pad_r, pad_t, pad_b = 52, 16, 18, 30
    area_w = largura - pad_l - pad_r
    area_h = altura  - pad_t - pad_b

    n        = len(dados)
    vals_in  = [d.get("tok_in",  0) or 0 for d in dados]
    vals_out = [d.get("tok_out", 0) or 0 for d in dados]
    vals_tot = [i + o for i, o in zip(vals_in, vals_out)]
    max_val  = max(max(vals_tot), 1)

    def x_for(i):
        if n <= 1:
            return pad_l + area_w // 2
        return pad_l + int(i * area_w / (n - 1))

    def y_for(v):
        return pad_t + int(area_h * (1 - v / max_val))

    yb = pad_t + area_h

    # Grid horizontal
    for frac in (0.25, 0.5, 0.75, 1.0):
        gy  = pad_t + int(area_h * (1 - frac))
        val = int(max_val * frac)
        lbl = f"{val//1000}k" if val >= 1000 else str(val)
        canvas.create_line(pad_l, gy, largura - pad_r, gy, fill=COR_GRID, dash=(4, 4))
        canvas.create_text(pad_l - 4, gy, text=lbl, anchor="e",
                           fill=CINZA, font=("Consolas", 7))

    # Eixo Y
    canvas.create_line(pad_l, pad_t, pad_l, yb + 1, fill="#363636")

    # Área preenchida — total (entrada)
    if n >= 2:
        pts_tot  = [(x_for(i), y_for(vals_tot[i])) for i in range(n)]
        poly_tot = pts_tot + [(x_for(n - 1), yb), (x_for(0), yb)]
        canvas.create_polygon([c for pt in poly_tot for c in pt],
                              fill=COR_IN_FILL, outline="", smooth=True)
        canvas.create_line([c for pt in pts_tot for c in pt],
                           fill=COR_IN_LINE, width=2, smooth=True)
    elif n == 1:
        canvas.create_oval(x_for(0) - 4, y_for(vals_tot[0]) - 4,
                           x_for(0) + 4, y_for(vals_tot[0]) + 4,
                           fill=COR_IN_LINE, outline="")

    # Área preenchida — saída
    if n >= 2:
        pts_out  = [(x_for(i), y_for(vals_out[i])) for i in range(n)]
        poly_out = pts_out + [(x_for(n - 1), yb), (x_for(0), yb)]
        canvas.create_polygon([c for pt in poly_out for c in pt],
                              fill=COR_OUT_FILL, outline="", smooth=True)
        canvas.create_line([c for pt in pts_out for c in pt],
                           fill=COR_OUT_LINE, width=2, smooth=True)
    elif n == 1:
        canvas.create_oval(x_for(0) - 3, y_for(vals_out[0]) - 3,
                           x_for(0) + 3, y_for(vals_out[0]) + 3,
                           fill=COR_OUT_LINE, outline="")

    # Pontos de dados
    for i in range(n):
        x  = x_for(i)
        yt = y_for(vals_tot[i])
        yo = y_for(vals_out[i])
        canvas.create_oval(x - 3, yt - 3, x + 3, yt + 3,
                           fill=COR_IN_LINE, outline=BG_CARD, width=1)
        canvas.create_oval(x - 2, yo - 2, x + 2, yo + 2,
                           fill=COR_OUT_LINE, outline=BG_CARD, width=1)

    # Labels eixo X (espaçadas para não sobrepor)
    step = max(1, n // 8)
    for i in range(0, n, step):
        dia = (dados[i].get("dia", "") or "")[-5:]
        canvas.create_text(x_for(i), yb + 4, text=dia,
                           anchor="n", fill=CINZA, font=("Consolas", 7))

    # Legenda
    canvas.create_rectangle(pad_l,       3, pad_l + 10, 11, fill=COR_IN_LINE,  outline="")
    canvas.create_text(pad_l + 13, 7, text="Entrada+Saída", anchor="w",
                       fill=CINZA, font=("Consolas", 7))
    canvas.create_rectangle(pad_l + 100, 3, pad_l + 110, 11, fill=COR_OUT_LINE, outline="")
    canvas.create_text(pad_l + 113, 7, text="Saída", anchor="w",
                       fill=CINZA, font=("Consolas", 7))


def _link_btn(pai, texto, url, bg=AZUL):
    b = tk.Label(pai, text=f"  ↗  {texto}  ", font=FONT_S,
                 bg=bg, fg=BCOR, padx=8, pady=5, cursor="hand2")
    cor_hover = "#4477BB" if bg == AZUL else "#2EAA66"
    b.bind("<Button-1>", lambda _: webbrowser.open(url))
    b.bind("<Enter>",    lambda _: b.config(bg=cor_hover))
    b.bind("<Leave>",    lambda _: b.config(bg=bg))
    return b


def abrir_api_panel(api_online: bool = True):
    env = _ler_env()
    chave_atual = env.get("CLAUDE_API_KEY", "")

    root = tk.Tk()
    root.title("SPARTA AGENTE IA — Painel de API")
    root.configure(bg=BG)
    root.resizable(True, True)
    root.minsize(560, 500)
    root.attributes("-topmost", True)
    root.grab_set()

    # ── Cabeçalho ──────────────────────────────────────────────────────────────
    cab = tk.Frame(root, bg=AMA, padx=16, pady=10)
    cab.pack(fill="x")
    tk.Label(cab, text="Painel de API — Claude", font=FONT_T, bg=AMA, fg=BG).pack(side="left")
    cor_st = VERDE if api_online else VERM
    tk.Label(cab, text=("● ONLINE" if api_online else "● OFFLINE"),
             font=("Segoe UI", 9, "bold"), bg=AMA, fg=cor_st).pack(side="right")

    # ── Links rápidos ──────────────────────────────────────────────────────────
    frm_links = tk.Frame(root, bg="#111111", padx=16, pady=6)
    frm_links.pack(fill="x")
    tk.Label(frm_links, text="Acesso rápido:", font=FONT_S,
             bg="#111111", fg=CINZA).pack(side="left", padx=(0, 8))
    for txt, url in [
        ("Console",            "https://console.anthropic.com"),
        ("Chaves de API",      "https://console.anthropic.com/settings/keys"),
        ("Saldo / Faturamento","https://console.anthropic.com/settings/billing"),
        ("Documentação",       "https://docs.anthropic.com"),
        ("Status",             "https://status.anthropic.com"),
    ]:
        l = tk.Label(frm_links, text=txt, font=("Segoe UI", 8, "underline"),
                     bg="#111111", fg="#5599EE", cursor="hand2", padx=(6))
        l.pack(side="left")
        l.bind("<Button-1>", lambda _, u=url: webbrowser.open(u))
        l.bind("<Enter>",    lambda _, w=l: w.config(fg="#88CCFF"))
        l.bind("<Leave>",    lambda _, w=l: w.config(fg="#5599EE"))

    # ── Rodapé fixo (empacotado ANTES do conteúdo para garantir espaço) ────────
    frm_rod = tk.Frame(root, bg="#111111", padx=20, pady=8)
    frm_rod.pack(fill="x", side="bottom")
    tk.Frame(frm_rod, bg=CESC, height=1).pack(fill="x", pady=(0, 6))

    _after_id = [None]

    def _fechar():
        if _after_id[0]:
            try:
                root.after_cancel(_after_id[0])
            except Exception:
                pass
        root.destroy()

    b_fechar = tk.Label(frm_rod, text="   Fechar   ", font=FONT_B,
                        bg=CESC, fg=BCOR, padx=14, pady=7, cursor="hand2")
    b_fechar.bind("<Button-1>", lambda _: _fechar())
    b_fechar.bind("<Enter>",    lambda _: b_fechar.config(bg="#555555"))
    b_fechar.bind("<Leave>",    lambda _: b_fechar.config(bg=CESC))
    b_fechar.pack(side="right")

    root.protocol("WM_DELETE_WINDOW", _fechar)

    # ── Abas (empacotadas depois do rodapé para preencher o meio) ─────────────
    frm_tabs = tk.Frame(root, bg="#111111")
    frm_tabs.pack(fill="x")

    frm_corpo = tk.Frame(root, bg=BG)
    frm_corpo.pack(fill="both", expand=True)

    abas_btn      = []
    abas_conteudo = []
    aba_sel       = [0]

    def _mudar_aba(i):
        aba_sel[0] = i
        for j, (btn, frm) in enumerate(zip(abas_btn, abas_conteudo)):
            if j == i:
                btn.config(bg=BG, fg=AMA)
                frm.pack(fill="both", expand=True, padx=20, pady=14)
            else:
                btn.config(bg="#111111", fg=CINZA)
                frm.pack_forget()

    for titulo in ("Uso de Tokens", "Saldo & Chave", "Informações"):
        frm = tk.Frame(frm_corpo, bg=BG)
        abas_conteudo.append(frm)
        b = tk.Label(frm_tabs, text=f"  {titulo}  ", font=FONT_B,
                     bg="#111111", fg=CINZA, pady=8, cursor="hand2")
        b.pack(side="left")
        idx = len(abas_btn)
        b.bind("<Button-1>", lambda _, i=idx: _mudar_aba(i))
        abas_btn.append(b)

    # ══════════════════════════════════════════════════════════════════════════
    # ABA 0 — Uso de Tokens
    # ══════════════════════════════════════════════════════════════════════════
    frm_uso = abas_conteudo[0]

    frm_cards = tk.Frame(frm_uso, bg=BG)
    frm_cards.pack(fill="x", pady=(0, 10))

    sv_tok_in   = tk.StringVar(value="—")
    sv_tok_out  = tk.StringVar(value="—")
    sv_analises = tk.StringVar(value="—")
    sv_custo    = tk.StringVar(value="—")

    def _card(pai, titulo, sv, cor=AMA):
        f = tk.Frame(pai, bg=BG_CARD, padx=12, pady=8)
        f.pack(side="left", expand=True, fill="x", padx=(0, 6))
        tk.Label(f, text=titulo, font=FONT_S,  bg=BG_CARD, fg=CINZA).pack(anchor="w")
        tk.Label(f, textvariable=sv, font=("Segoe UI", 13, "bold"),
                 bg=BG_CARD, fg=cor).pack(anchor="w")

    _card(frm_cards, "Tokens Entrada", sv_tok_in,   "#6BBFFF")
    _card(frm_cards, "Tokens Saída",   sv_tok_out,  "#FF9966")
    _card(frm_cards, "Análises",       sv_analises, VERDE)
    _card(frm_cards, "Custo est. USD", sv_custo,    AMA)

    frm_per = tk.Frame(frm_uso, bg=BG)
    frm_per.pack(anchor="w", pady=(0, 4))
    tk.Label(frm_per, text="GRÁFICO DE USO DIÁRIO — período:",
             font=("Segoe UI", 8, "bold"), bg=BG, fg=AMA).pack(side="left")

    dados_cache  = [[]]
    btn_periodo  = {}

    for dias, lbl in [(7, "7 dias"), (14, "14 dias"), (30, "30 dias")]:
        b = tk.Label(frm_per, text=f"  {lbl}  ", font=FONT_S,
                     bg=CESC, fg=BCOR, cursor="hand2", padx=4, pady=2)
        b.pack(side="left", padx=(6, 0))
        b.bind("<Button-1>", lambda _, d=dias: _carregar_uso(d))
        btn_periodo[dias] = b

    canvas = tk.Canvas(frm_uso, bg=BG_CARD, height=180,
                       highlightthickness=1, highlightbackground=CESC)
    canvas.pack(fill="x", pady=(4, 8))
    canvas.bind("<Configure>", lambda _: _desenhar_grafico(canvas, dados_cache[0]))

    sv_loading = tk.StringVar(value="Carregando dados...")
    tk.Label(frm_uso, textvariable=sv_loading, font=FONT_S,
             bg=BG, fg=CINZA).pack(anchor="w")

    tk.Label(frm_uso, text="DETALHE POR DIA (últimos 10)",
             font=("Segoe UI", 8, "bold"), bg=BG, fg=AMA).pack(anchor="w", pady=(6, 2))
    sv_tabela = tk.StringVar(value="")
    frm_tab = tk.Frame(frm_uso, bg=BG_CARD, padx=10, pady=8)
    frm_tab.pack(fill="x")
    tk.Label(frm_tab, textvariable=sv_tabela, font=("Consolas", 8),
             bg=BG_CARD, fg=BCOR, justify="left").pack(anchor="w")

    _q: _queue.Queue = _queue.Queue()

    def _poll():
        try:
            while True:
                tipo, dado = _q.get_nowait()
                if tipo == "uso":
                    dados, tot_in, tot_out, tot_an, custo, linhas = dado
                    dados_cache[0] = dados
                    sv_tok_in.set(f"{tot_in:,}")
                    sv_tok_out.set(f"{tot_out:,}")
                    sv_analises.set(f"{tot_an:,}")
                    sv_custo.set(f"${custo:.4f}")
                    sv_tabela.set(linhas)
                    sv_loading.set(f"Atualizado — {datetime.now().strftime('%H:%M:%S')}")
                    _desenhar_grafico(canvas, dados)
                elif tipo == "saldo":
                    res = dado
                    cor = VERDE if res["status"] == "valida" else (
                          VERM  if res["status"] in ("invalida","sem_credito","limite")
                          else CINZA)
                    sv_saldo_status.set(res["mensagem"])
                    lbl_saldo_status.config(fg=cor)
                    b_verificar_saldo.config(text="  Verificar Novamente  ")
        except _queue.Empty:
            pass
        try:
            _after_id[0] = root.after(200, _poll)
        except Exception:
            pass

    def _carregar_uso(dias: int = 30):
        for d, b in btn_periodo.items():
            b.config(bg=AMA if d == dias else CESC,
                     fg=BG  if d == dias else BCOR)
        sv_loading.set("Carregando...")

        def _run():
            try:
                dados   = _db.estatisticas_tokens(dias)
                tot_in  = sum(d.get("tok_in",  0) or 0 for d in dados)
                tot_out = sum(d.get("tok_out", 0) or 0 for d in dados)
                tot_an  = sum(d.get("analises", 0) or 0 for d in dados)
                custo   = (tot_in  / 1_000_000) * _CUSTO_INPUT + \
                          (tot_out / 1_000_000) * _CUSTO_OUTPUT

                cab_tab = f"{'Data':<12}{'Entrada':>10}{'Saída':>10}{'Análises':>9}"
                sep_tab = "─" * 43
                linhas  = [cab_tab, sep_tab]
                for d in reversed(dados[-10:]):
                    linhas.append(
                        f"{d['dia']:<12}{(d['tok_in'] or 0):>10,}"
                        f"{(d['tok_out'] or 0):>10,}{(d['analises'] or 0):>9,}"
                    )
                if not dados:
                    linhas = ["Nenhuma análise registrada no período."]

                _q.put(("uso", (dados, tot_in, tot_out, tot_an, custo,
                                "\n".join(linhas))))
            except Exception as exc:
                _q.put(("uso", ([], 0, 0, 0, 0.0, f"Erro ao carregar: {exc}")))

        threading.Thread(target=_run, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════════════
    # ABA 1 — Saldo & Chave
    # ══════════════════════════════════════════════════════════════════════════
    frm_chave = abas_conteudo[1]

    # ── Saldo disponível ───────────────────────────────────────────────────────
    tk.Label(frm_chave, text="SALDO DISPONÍVEL", font=("Segoe UI", 8, "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(0, 6))

    frm_saldo = tk.Frame(frm_chave, bg=BG_CARD, padx=14, pady=12)
    frm_saldo.pack(fill="x", pady=(0, 6))

    tk.Label(frm_saldo,
             text="A Anthropic não expõe o saldo via API pública.\n"
                  "Clique no botão abaixo para verificar diretamente na plataforma:",
             font=FONT_S, bg=BG_CARD, fg=CINZA, justify="left").pack(anchor="w")

    frm_s_btns = tk.Frame(frm_saldo, bg=BG_CARD)
    frm_s_btns.pack(fill="x", pady=(8, 0))

    b_billing = _link_btn(frm_s_btns,
                          "Ver Saldo e Faturamento (console.anthropic.com)",
                          "https://console.anthropic.com/settings/billing",
                          bg="#1A6B1A")
    b_billing.pack(side="left")

    tk.Frame(frm_chave, bg=CESC, height=1).pack(fill="x", pady=(4, 10))

    # ── Verificar chave ────────────────────────────────────────────────────────
    tk.Label(frm_chave, text="VERIFICAR CHAVE DE API", font=("Segoe UI", 8, "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(0, 6))

    frm_verif = tk.Frame(frm_chave, bg=BG_CARD, padx=14, pady=10)
    frm_verif.pack(fill="x", pady=(0, 10))

    sv_saldo_status = tk.StringVar(value="Clique em 'Verificar' para testar a chave.")
    lbl_saldo_status = tk.Label(frm_verif, textvariable=sv_saldo_status,
                                font=FONT_L, bg=BG_CARD, fg=CINZA,
                                wraplength=420, justify="left")
    lbl_saldo_status.pack(anchor="w", pady=(0, 8))

    b_verificar_saldo = tk.Label(frm_verif, text="  Verificar Status da Chave  ",
                                 font=FONT_B, bg=AZUL, fg=BCOR,
                                 padx=12, pady=7, cursor="hand2")
    b_verificar_saldo.pack(anchor="w")
    b_verificar_saldo.bind("<Enter>", lambda _: b_verificar_saldo.config(bg="#4477BB"))
    b_verificar_saldo.bind("<Leave>", lambda _: b_verificar_saldo.config(bg=AZUL))

    def _verificar_saldo():
        b_verificar_saldo.config(text="  Verificando...  ")
        sv_saldo_status.set("Fazendo requisição de teste à API...")
        lbl_saldo_status.config(fg=CINZA)

        def _run():
            res = _verificar_saldo_api(chave_atual)
            _q.put(("saldo", res))

        threading.Thread(target=_run, daemon=True).start()

    b_verificar_saldo.bind("<Button-1>", lambda _: _verificar_saldo())

    tk.Frame(frm_chave, bg=CESC, height=1).pack(fill="x", pady=(4, 10))

    # ── Chave atual ────────────────────────────────────────────────────────────
    tk.Label(frm_chave, text="CHAVE DE API", font=("Segoe UI", 8, "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(0, 6))

    frm_atual = tk.Frame(frm_chave, bg=BG_CARD, padx=14, pady=10)
    frm_atual.pack(fill="x", pady=(0, 10))
    tk.Label(frm_atual, text="Chave mascarada:", font=FONT_S,
             bg=BG_CARD, fg=CINZA).pack(anchor="w")
    sv_mask = tk.StringVar(value=_mascara_key(chave_atual))
    tk.Label(frm_atual, textvariable=sv_mask, font=("Consolas", 9),
             bg=BG_CARD, fg=VERDE).pack(anchor="w", pady=(2, 0))
    tk.Label(frm_atual,
             text=f"Prefixo: {chave_atual[:20]}..." if chave_atual else "(não configurada)",
             font=FONT_S, bg=BG_CARD, fg=CINZA).pack(anchor="w")

    tk.Label(frm_chave, text="TROCAR CHAVE", font=("Segoe UI", 8, "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(0, 4))

    sv_nova = tk.StringVar()
    frm_ent = tk.Frame(frm_chave, bg=BG)
    frm_ent.pack(fill="x", pady=(0, 4))
    ent = tk.Entry(frm_ent, textvariable=sv_nova, show="•", font=FONT_M,
                   bg="#242424", fg=BCOR, insertbackground=AMA, relief="flat",
                   bd=0, highlightthickness=1, highlightcolor=AMA,
                   highlightbackground=CESC, width=50)
    ent.pack(side="left", ipady=5, fill="x", expand=True)
    b_eye = tk.Label(frm_ent, text="👁", font=("Segoe UI", 11),
                     bg=BG, fg=CINZA, cursor="hand2", padx=6)
    b_eye.pack(side="left")
    b_eye.bind("<Button-1>",
               lambda _: ent.config(show="" if ent.cget("show") == "•" else "•"))

    sv_msg = tk.StringVar(value="")
    lbl_msg = tk.Label(frm_chave, textvariable=sv_msg, font=FONT_S,
                       bg=BG, fg=VERDE, wraplength=440)
    lbl_msg.pack(anchor="w", pady=(0, 6))
    tk.Label(frm_chave,
             text="A nova chave será salva no .env e aplicada no próximo reinício.",
             font=FONT_S, bg=BG, fg=CINZA).pack(anchor="w", pady=(0, 8))

    def _salvar_chave():
        nova = sv_nova.get().strip()
        if not nova:
            sv_msg.set("Digite a nova chave.")
            lbl_msg.config(fg=VERM)
            return
        if not nova.startswith("sk-ant-"):
            sv_msg.set("Chave inválida — deve começar com 'sk-ant-'.")
            lbl_msg.config(fg=VERM)
            return
        if not messagebox.askyesno("Confirmar",
                "Substituir a chave de API atual?\n\nReinicie o sistema para aplicar.",
                parent=root):
            return
        _salvar_env("CLAUDE_API_KEY", nova)
        sv_mask.set(_mascara_key(nova))
        sv_nova.set("")
        sv_msg.set("Chave salva com sucesso! Reinicie o sistema.")
        lbl_msg.config(fg=VERDE)
        log.info("Chave de API atualizada via painel")

    b_salvar = tk.Label(frm_chave, text="  Salvar Nova Chave  ",
                        font=FONT_B, bg=AMA, fg=BG, padx=12, pady=8, cursor="hand2")
    b_salvar.bind("<Button-1>", lambda _: _salvar_chave())
    b_salvar.bind("<Enter>",    lambda _: b_salvar.config(bg=AESC))
    b_salvar.bind("<Leave>",    lambda _: b_salvar.config(bg=AMA))
    b_salvar.pack(anchor="w")

    # ══════════════════════════════════════════════════════════════════════════
    # ABA 2 — Informações
    # ══════════════════════════════════════════════════════════════════════════
    frm_info = abas_conteudo[2]

    infos = [
        ("Modelo",          "Claude Sonnet 4.6"),
        ("ID do modelo",    "claude-sonnet-4-6"),
        ("Preço entrada",   f"${_CUSTO_INPUT:.2f} / 1M tokens"),
        ("Preço saída",     f"${_CUSTO_OUTPUT:.2f} / 1M tokens"),
        ("Cache entrada",   "~$0.30 / 1M tokens (economia ~90%)"),
        ("Endpoint",        "api.anthropic.com/v1/messages"),
        ("Servidor update", env.get("UPDATE_SERVER_URL", "(não configurado)")),
        ("Status da API",   "ONLINE" if api_online else "OFFLINE"),
        ("Verificado em",   datetime.now().strftime("%d/%m/%Y %H:%M:%S")),
    ]

    frm_ic = tk.Frame(frm_info, bg=BG_CARD, padx=14, pady=12)
    frm_ic.pack(fill="x", pady=(0, 12))
    for k, v in infos:
        fr = tk.Frame(frm_ic, bg=BG_CARD)
        fr.pack(fill="x", pady=2)
        tk.Label(fr, text=f"{k}:", font=FONT_S, bg=BG_CARD,
                 fg=CINZA, width=18, anchor="w").pack(side="left")
        tk.Label(fr, text=v, font=FONT_M, bg=BG_CARD,
                 fg=BCOR, anchor="w").pack(side="left")

    tk.Label(frm_info, text="LINKS ÚTEIS", font=("Segoe UI", 8, "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(4, 6))

    for txt, url in [
        ("Saldo e Faturamento",    "https://console.anthropic.com/settings/billing"),
        ("Gerenciar Chaves de API","https://console.anthropic.com/settings/keys"),
        ("Console Principal",      "https://console.anthropic.com"),
        ("Status da Plataforma",   "https://status.anthropic.com"),
        ("Documentação da API",    "https://docs.anthropic.com/en/api/getting-started"),
    ]:
        _link_btn(frm_info, txt, url).pack(anchor="w", pady=(0, 4))

    # ── Inicialização ──────────────────────────────────────────────────────────
    _mudar_aba(0)
    _after_id[0] = root.after(200, _poll)

    root.update_idletasks()
    w = max(root.winfo_reqwidth(), 550)
    h = root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    root.after(400, lambda: _carregar_uso(30))
    root.wait_window()
    import gc as _gc; _gc.collect()
