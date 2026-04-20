"""
Painel de Exportação de Dados — SPARTA AGENTE IA
Exporta dados do banco (analises, feedbacks, exemplos_fewshot, perguntas_ia)
para mídia removível ou pasta Nextcloud do projeto de desenvolvimento.
Suporte a exportação incremental (somente registros novos desde o último envio).
"""
import json
import logging
import os
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox

import db as _db

log = logging.getLogger(__name__)

# ── Constantes visuais ─────────────────────────────────────────────────────────
BG      = "#0F0F0F"
BG_CARD = "#1A1A1A"
AMA     = "#FFD000"
AESC    = "#B39200"
BCOR    = "#F0F0F0"
CINZA   = "#888888"
CESC    = "#333333"
VERM    = "#FF4444"
VERDE   = "#3DCC7E"
AZUL    = "#336699"
ROXO    = "#7744CC"
ROXO_E  = "#5533AA"

FONT_T  = ("Segoe UI", 11, "bold")
FONT_L  = ("Segoe UI", 9)
FONT_M  = ("Consolas", 9)
FONT_B  = ("Segoe UI", 9, "bold")
FONT_S  = ("Segoe UI", 8)

# ── Caminhos base ──────────────────────────────────────────────────────────────
_BASE_DIR    = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(".")
_MARKER_FILE = _BASE_DIR / "ultimo_export.json"
_CFG_FILE    = _BASE_DIR / "export_config.json"

# Caminho padrão Nextcloud — usado apenas na primeira execução
_NEXTCLOUD_PADRAO = "c:/Nextcoud/IVMS-RFSMART/dados-campo"

_DEFAULT_CFG = {
    "nextcloud_destino": _NEXTCLOUD_PADRAO,
}


# ── Configuração persistente ───────────────────────────────────────────────────

def _carregar_cfg() -> dict:
    if _CFG_FILE.exists():
        try:
            dados = json.loads(_CFG_FILE.read_text(encoding="utf-8"))
            cfg = dict(_DEFAULT_CFG)
            cfg.update(dados)
            return cfg
        except Exception:
            pass
    return dict(_DEFAULT_CFG)


def _salvar_cfg(cfg: dict):
    _CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Marcador de exportação incremental ────────────────────────────────────────

def _ler_marcador() -> dict:
    if _MARKER_FILE.exists():
        try:
            return json.loads(_MARKER_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"analises": 0, "feedbacks": 0, "exemplos_fewshot": 0, "perguntas_ia": 0}


def _salvar_marcador(marcador: dict):
    _MARKER_FILE.write_text(
        json.dumps(marcador, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Motor de exportação ────────────────────────────────────────────────────────

def _exportar_dados(destino: Path, incremental: bool) -> tuple[Path, dict]:
    """
    Gera ZIP com JSON de cada tabela.
    incremental=True → somente registros com id > último exportado.
    Retorna (caminho_zip, estatísticas).
    """
    destino.mkdir(parents=True, exist_ok=True)

    marcador = _ler_marcador() if incremental else \
        {"analises": 0, "feedbacks": 0, "exemplos_fewshot": 0, "perguntas_ia": 0}

    conn = _db.get_connection()

    def _query(tabela: str, id_min: int) -> list:
        rows = conn.execute(
            f"SELECT * FROM {tabela} WHERE id > ? ORDER BY id", (id_min,)
        ).fetchall()
        return [dict(r) for r in rows]

    analises  = _query("analises",         marcador["analises"])
    feedbacks = _query("feedbacks",        marcador["feedbacks"])
    exemplos  = _query("exemplos_fewshot", marcador["exemplos_fewshot"])
    perguntas = _query("perguntas_ia",     marcador["perguntas_ia"])

    stats = {
        "analises":         len(analises),
        "feedbacks":        len(feedbacks),
        "exemplos_fewshot": len(exemplos),
        "perguntas_ia":     len(perguntas),
    }

    total = sum(stats.values())
    if total == 0 and incremental:
        raise ValueError("Nenhum dado novo desde o último envio.")

    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    modo    = "incremental" if incremental else "completo"
    zip_path = destino / f"sparta_dados_{modo}_{ts}.zip"

    meta = {
        "gerado_em":         datetime.now().isoformat(),
        "modo":              modo,
        "marcador_anterior": marcador,
        "registros":         stats,
        "total":             total,
    }

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("analises.json",         json.dumps(analises,  ensure_ascii=False, indent=2))
        zf.writestr("feedbacks.json",        json.dumps(feedbacks, ensure_ascii=False, indent=2))
        zf.writestr("exemplos_fewshot.json", json.dumps(exemplos,  ensure_ascii=False, indent=2))
        zf.writestr("perguntas_ia.json",     json.dumps(perguntas, ensure_ascii=False, indent=2))
        zf.writestr("export_meta.json",      json.dumps(meta,      ensure_ascii=False, indent=2))

    novo_marcador = dict(marcador)
    for tabela, lista in [("analises", analises), ("feedbacks", feedbacks),
                           ("exemplos_fewshot", exemplos), ("perguntas_ia", perguntas)]:
        if lista:
            novo_marcador[tabela] = max(r["id"] for r in lista)
    _salvar_marcador(novo_marcador)

    return zip_path, stats


# ── Helpers de UI ──────────────────────────────────────────────────────────────

def _centralizar(win):
    win.update_idletasks()
    w  = win.winfo_reqwidth()
    h  = win.winfo_reqheight()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")


def _btn(pai, texto, cmd, bg=AMA, fg=BG):
    hover = {AMA: AESC, VERDE: "#2EAA66", VERM: "#CC2222",
             AZUL: "#4477BB", ROXO: ROXO_E}.get(bg, "#555555")
    b = tk.Label(pai, text=texto, font=FONT_B, bg=bg, fg=fg,
                 cursor="hand2", padx=12, pady=7)
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>",    lambda _: b.config(bg=hover))
    b.bind("<Leave>",    lambda _: b.config(bg=bg))
    return b


def _secao(pai, titulo):
    tk.Frame(pai, bg=CESC, height=1).pack(fill="x", pady=(10, 6))
    tk.Label(pai, text=titulo, font=(FONT_S[0], FONT_S[1], "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(0, 4))


# ── Painel principal ───────────────────────────────────────────────────────────

def abrir_export_panel(parent=None, sessao: dict | None = None):
    cfg = _carregar_cfg()

    root = tk.Toplevel(parent) if parent else tk.Tk()
    root.title("SPARTA — Exportar Dados para Desenvolvimento")
    root.configure(bg=BG)
    root.resizable(True, True)
    root.minsize(520, 0)
    root.attributes("-topmost", True)
    root.grab_set()

    # ── Cabeçalho ──────────────────────────────────────────────────────────────
    cab = tk.Frame(root, bg=ROXO, padx=16, pady=10)
    cab.pack(fill="x")
    tk.Label(cab, text="Exportar Dados para Desenvolvimento",
             font=FONT_T, bg=ROXO, fg=BCOR).pack(side="left")
    tk.Label(cab, text="(admin)", font=FONT_S, bg=ROXO, fg="#CCBBFF").pack(side="right")

    corpo = tk.Frame(root, bg=BG, padx=24, pady=16)
    corpo.pack(fill="both")

    # ── Estatísticas do banco ──────────────────────────────────────────────────
    _secao(corpo, "SITUAÇÃO ATUAL DO BANCO")

    frm_stats = tk.Frame(corpo, bg=BG_CARD, padx=12, pady=10)
    frm_stats.pack(fill="x", pady=(0, 4))
    sv_stats = tk.StringVar(value="Carregando...")
    tk.Label(frm_stats, textvariable=sv_stats, font=FONT_M,
             bg=BG_CARD, fg=BCOR, justify="left").pack(anchor="w")

    def _carregar_stats():
        try:
            conn = _db.get_connection()
            na   = conn.execute("SELECT COUNT(*) FROM analises").fetchone()[0]
            nf   = conn.execute("SELECT COUNT(*) FROM feedbacks").fetchone()[0]
            ne   = conn.execute("SELECT COUNT(*) FROM exemplos_fewshot").fetchone()[0]
            np_  = conn.execute("SELECT COUNT(*) FROM perguntas_ia").fetchone()[0]

            marc   = _ler_marcador()
            na_nov = conn.execute("SELECT COUNT(*) FROM analises WHERE id > ?",
                                  (marc["analises"],)).fetchone()[0]
            nf_nov = conn.execute("SELECT COUNT(*) FROM feedbacks WHERE id > ?",
                                  (marc["feedbacks"],)).fetchone()[0]
            ne_nov = conn.execute("SELECT COUNT(*) FROM exemplos_fewshot WHERE id > ?",
                                  (marc["exemplos_fewshot"],)).fetchone()[0]
            np_nov = conn.execute("SELECT COUNT(*) FROM perguntas_ia WHERE id > ?",
                                  (marc["perguntas_ia"],)).fetchone()[0]

            total_novo = na_nov + nf_nov + ne_nov + np_nov
            ultimo_str = "nunca" if all(v == 0 for v in marc.values()) else \
                f"ID analise={marc['analises']}  feedbacks={marc['feedbacks']}"

            sv_stats.set(
                f"  analises:         {na:>6}  ({na_nov} novos)\n"
                f"  feedbacks:        {nf:>6}  ({nf_nov} novos)\n"
                f"  exemplos_fewshot: {ne:>6}  ({ne_nov} novos)\n"
                f"  perguntas_ia:     {np_:>6}  ({np_nov} novos)\n"
                f"\n  Total de novos registros: {total_novo}\n"
                f"  Último envio: {ultimo_str}"
            )
        except Exception as exc:
            sv_stats.set(f"Erro ao ler banco: {exc}")

    _carregar_stats()

    # ── Destino Nextcloud (caminho salvo e editável) ───────────────────────────
    _secao(corpo, "DESTINO NEXTCLOUD (PROJETO DEV)")

    frm_nc = tk.Frame(corpo, bg=BG)
    frm_nc.pack(fill="x", pady=(0, 2))

    sv_nc = tk.StringVar(value=cfg["nextcloud_destino"])
    e_nc  = tk.Entry(frm_nc, textvariable=sv_nc, font=FONT_M,
                     bg="#242424", fg=BCOR, insertbackground=AMA,
                     relief="flat", bd=0, highlightthickness=1,
                     highlightcolor=AMA, highlightbackground=CESC, width=44)
    e_nc.bind("<FocusIn>",  lambda ev, w=e_nc: w.config(highlightbackground=AMA))
    e_nc.bind("<FocusOut>", lambda ev, w=e_nc: w.config(highlightbackground=CESC))
    e_nc.pack(side="left", ipady=5)

    def _browse_nc():
        p = filedialog.askdirectory(title="Selecione pasta de destino Nextcloud")
        if p:
            sv_nc.set(p)
            # Salva imediatamente ao selecionar via browse
            _salvar_cfg({**_carregar_cfg(), "nextcloud_destino": p})

    _btn(frm_nc, " ... ", _browse_nc, bg=CESC, fg=BCOR).pack(side="left", padx=(6, 0))

    tk.Label(corpo,
             text="Caminho salvo por máquina em export_config.json. "
                  "O cliente Nextcloud sincroniza ao detectar o arquivo.",
             font=FONT_S, bg=BG, fg=CINZA, wraplength=460, justify="left"
             ).pack(anchor="w", pady=(2, 8))

    # ── Modo incremental ───────────────────────────────────────────────────────
    _secao(corpo, "MODO DE EXPORTAÇÃO")

    var_inc = tk.BooleanVar(value=True)
    tk.Checkbutton(corpo,
                   text="Exportação incremental (somente novos registros desde o último envio)",
                   variable=var_inc, font=FONT_L,
                   bg=BG, fg=BCOR, selectcolor=CESC,
                   activebackground=BG, activeforeground=BCOR,
                   cursor="hand2").pack(anchor="w")
    tk.Label(corpo,
             text="  Desmarcado → exporta o banco inteiro (pode ser grande).",
             font=FONT_S, bg=BG, fg=CINZA).pack(anchor="w", pady=(2, 0))

    # ── Área de resultado (status + botão Abrir Pasta) ─────────────────────────
    tk.Frame(corpo, bg=CESC, height=1).pack(fill="x", pady=(10, 4))

    frm_resultado = tk.Frame(corpo, bg=BG)
    frm_resultado.pack(fill="x")

    sv_status  = tk.StringVar(value="")
    lbl_status = tk.Label(frm_resultado, textvariable=sv_status, font=FONT_L,
                          bg=BG, fg=VERDE, wraplength=440, justify="left")
    lbl_status.pack(anchor="w", side="left", fill="x", expand=True)

    # Botão "Abrir Pasta" — aparece apenas após exportação bem-sucedida
    _ultima_pasta: list[Path] = [None]
    btn_abrir = _btn(frm_resultado, " Abrir Pasta ", lambda: None, bg=VERDE, fg=BG)
    # não é empacotado agora — aparece dinamicamente

    def _mostrar_btn_abrir(pasta: Path):
        _ultima_pasta[0] = pasta
        def _abrir():
            try:
                os.startfile(str(_ultima_pasta[0]))
            except Exception as exc:
                log.error("Não foi possível abrir pasta: %s", exc)
        btn_abrir.bind("<Button-1>", lambda _: _abrir())
        btn_abrir.pack(side="right", padx=(8, 0))

    def _esconder_btn_abrir():
        btn_abrir.pack_forget()

    def _set_status(msg: str, cor: str = VERDE, pasta: Path = None):
        sv_status.set(msg)
        lbl_status.config(fg=cor)
        if pasta:
            _mostrar_btn_abrir(pasta)
        else:
            _esconder_btn_abrir()

    # ── Botões de ação ─────────────────────────────────────────────────────────
    tk.Frame(corpo, bg=CESC, height=1).pack(fill="x", pady=(8, 10))
    frm_btns = tk.Frame(corpo, bg=BG)
    frm_btns.pack(fill="x")

    def _executar_export(destino: Path, modo_label: str, nextcloud: bool = False):
        """Roda exportação em thread e exibe resultado com caminho completo."""
        _set_status(f"Exportando para:\n  {destino} ...", AMA)
        root.update_idletasks()
        incremental = var_inc.get()

        def _run():
            try:
                zip_path, stats = _exportar_dados(destino, incremental)
                tam  = zip_path.stat().st_size / 1024
                unid = "KB" if tam < 1024 else "MB"
                if unid == "MB":
                    tam /= 1024

                linhas_status = [
                    f"Exportação concluída  ({tam:.1f} {unid}):",
                    f"  Arquivo: {zip_path.name}",
                    f"  Pasta:   {destino}",
                ]
                for k, v in stats.items():
                    linhas_status.append(f"  {k}: {v} registros")
                if nextcloud:
                    linhas_status.append("  → Nextcloud irá sincronizar automaticamente.")

                resumo_popup = (
                    f"Exportação concluída com sucesso!\n\n"
                    f"Arquivo: {zip_path.name}\n"
                    f"Tamanho: {tam:.1f} {unid}\n"
                    f"Pasta: {destino}\n\n"
                    + "\n".join(f"  {k}: {v} registros" for k, v in stats.items())
                    + ("\n\n→ Nextcloud sincronizará automaticamente." if nextcloud else "")
                )

                root.after(0, lambda: _set_status("\n".join(linhas_status), VERDE, destino))
                root.after(0, _carregar_stats)
                root.after(100, lambda: messagebox.showinfo(
                    "Exportação Concluída", resumo_popup, parent=root
                ))
            except ValueError as exc:
                root.after(0, lambda: _set_status(str(exc), AMA))
                root.after(100, lambda: messagebox.showwarning(
                    "Nada a exportar", str(exc), parent=root
                ))
            except Exception as exc:
                root.after(0, lambda: _set_status(f"Erro: {exc}", VERM))
                root.after(100, lambda: messagebox.showerror(
                    "Erro na Exportação", str(exc), parent=root
                ))
                log.error("Exportação falhou: %s", exc)

        threading.Thread(target=_run, daemon=True).start()

    def _enviar_nextcloud():
        caminho = sv_nc.get().strip()
        if not caminho:
            _set_status("Informe o caminho Nextcloud de destino.", VERM)
            return
        dest = Path(caminho)
        if not dest.parent.exists():
            _set_status(
                f"Caminho não encontrado:\n  {dest}\n"
                "Verifique se o Nextcloud está instalado nesta máquina.",
                VERM
            )
            return
        # Persiste o caminho antes de exportar
        _salvar_cfg({**_carregar_cfg(), "nextcloud_destino": caminho})
        _executar_export(dest, "Nextcloud", nextcloud=True)

    def _exportar_midia():
        pasta = filedialog.askdirectory(
            title="Selecione a mídia removível ou pasta de destino"
        )
        if not pasta:
            return
        _executar_export(Path(pasta), "Mídia Removível")

    def _resetar_marcador():
        if messagebox.askyesno(
            "Resetar Marcador",
            "Isso fará a próxima exportação incremental enviar TODOS os dados.\n\nContinuar?",
            parent=root,
        ):
            _salvar_marcador({"analises": 0, "feedbacks": 0,
                              "exemplos_fewshot": 0, "perguntas_ia": 0})
            _set_status("Marcador resetado. Próxima exportação enviará tudo.", AMA)
            _carregar_stats()

    _btn(frm_btns, " Enviar ao Nextcloud ", _enviar_nextcloud,
         bg=ROXO, fg=BCOR).pack(side="left")
    _btn(frm_btns, " Exportar p/ Mídia ",   _exportar_midia,
         bg=AZUL, fg=BCOR).pack(side="left", padx=(6, 0))
    _btn(frm_btns, " Resetar Marcador ",    _resetar_marcador,
         bg=CESC, fg=BCOR).pack(side="left", padx=(6, 0))
    _btn(frm_btns, " Fechar ",
         root.destroy, bg=CESC, fg=BCOR).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    _centralizar(root)
    root.wait_window()
