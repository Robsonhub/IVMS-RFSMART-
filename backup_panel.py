"""Painel de backup avançado — SPARTA AGENTE IA (somente admin)."""
import json
import logging
import queue as _queue
import shutil
import sqlite3
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import db as _db

log = logging.getLogger(__name__)

BG       = "#0F0F0F"
BG_CARD  = "#1A1A1A"
AMA      = "#FFD000"
AESC     = "#B39200"
BCOR     = "#F0F0F0"
CINZA    = "#888888"
CESC     = "#333333"
VERM     = "#FF4444"
VERDE    = "#3DCC7E"
AZUL     = "#336699"

FONT_T   = ("Segoe UI", 11, "bold")
FONT_L   = ("Segoe UI", 9)
FONT_M   = ("Consolas", 9)
FONT_B   = ("Segoe UI", 9, "bold")

_CFG_FILE       = Path(".") / "backup_config.json"
_CAMERAS_JSON   = Path(".") / "cameras.json"
_ENV_FILE       = Path(".") / ".env"

_DEFAULT_CFG = {
    "destino":          "",
    "compactar":        True,
    "modo":             "manual",       # "manual" | "automatico"
    "intervalo_horas":  6.0,
    "max_backups":      20,
}

# Thread do agendador automático (singleton)
_auto_thread: threading.Thread | None = None
_auto_stop   = threading.Event()

# Sinaliza ao mosaic que câmeras precisam ser recarregadas após restore
_reload_cameras_needed = False


def precisa_recarregar_cameras() -> bool:
    """Chamado pelo mosaic após fechar o painel; consome e retorna o flag."""
    global _reload_cameras_needed
    r = _reload_cameras_needed
    _reload_cameras_needed = False
    return r


# ── Config ─────────────────────────────────────────────────────────────────────

def _carregar_cfg() -> dict:
    try:
        if _CFG_FILE.exists():
            dados = json.loads(_CFG_FILE.read_text(encoding="utf-8"))
            cfg = dict(_DEFAULT_CFG)
            cfg.update(dados)
            return cfg
    except Exception:
        pass
    return dict(_DEFAULT_CFG)


def _salvar_cfg(cfg: dict):
    _CFG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Motor de backup ────────────────────────────────────────────────────────────

def _fazer_backup_avancado(destino: str, compactar: bool, max_backups: int) -> Path:
    """
    Cria um ZIP contendo: banco de dados, cameras.json e .env.
    compactar=True  → ZIP_DEFLATED (menor tamanho)
    compactar=False → ZIP_STORED   (sem compressão, mais rápido)
    """
    dest_dir = Path(destino)
    dest_dir.mkdir(parents=True, exist_ok=True)

    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    saida = dest_dir / f"sparta_backup_{ts}.zip"

    compression = zipfile.ZIP_DEFLATED if compactar else zipfile.ZIP_STORED
    comp_level  = 6 if compactar else None

    # Copia WAL-safe do banco
    tmp_db = dest_dir / f"_tmp_{ts}.db"
    try:
        src = sqlite3.connect(str(_db.DB_PATH))
        dst = sqlite3.connect(str(tmp_db))
        src.backup(dst)
        src.close()
        dst.close()

        kw = {"compression": compression}
        if comp_level is not None:
            kw["compresslevel"] = comp_level

        with zipfile.ZipFile(saida, "w", **kw) as zf:
            zf.write(tmp_db, "sparta_analytics.db")

            if _CAMERAS_JSON.exists():
                zf.write(_CAMERAS_JSON, "cameras.json")

            if _ENV_FILE.exists():
                zf.write(_ENV_FILE, ".env")
    finally:
        tmp_db.unlink(missing_ok=True)

    log.info("Backup salvo: %s", saida)

    # Remove backups excedentes (mais antigos primeiro)
    todos = sorted(dest_dir.glob("sparta_backup_*.zip"))
    for old in todos[:-max_backups]:
        old.unlink(missing_ok=True)
        log.debug("Backup antigo removido: %s", old.name)

    return saida


def _loop_automatico(cfg: dict):
    intervalo_s = int(cfg["intervalo_horas"] * 3600)
    while not _auto_stop.wait(intervalo_s):
        try:
            _fazer_backup_avancado(cfg["destino"], cfg["compactar"], cfg["max_backups"])
        except Exception as exc:
            log.error("Backup automático falhou: %s", exc)


def iniciar_automatico():
    """Inicia o agendador se configurado para automático e destino definido."""
    global _auto_thread
    cfg = _carregar_cfg()
    if cfg["modo"] != "automatico" or not cfg["destino"]:
        return
    _auto_stop.clear()
    _auto_thread = threading.Thread(target=_loop_automatico, args=(cfg,),
                                    daemon=True, name="BackupPanel-Auto")
    _auto_thread.start()
    log.info("Backup automático (painel) iniciado -> %s a cada %.0fh",
             cfg["destino"], cfg["intervalo_horas"])


def parar_automatico():
    _auto_stop.set()


# ── Interface ──────────────────────────────────────────────────────────────────

def _centralizar(win):
    win.update_idletasks()
    w  = win.winfo_reqwidth()
    h  = win.winfo_reqheight()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    win.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")


def _btn(pai, texto, cmd, bg=AMA, fg=BG, width=None):
    kw = {"padx": 12, "pady": 7}
    if width:
        kw["width"] = width
    hover = AESC if bg == AMA else (
        "#2EAA66" if bg == VERDE else
        "#CC2222" if bg == VERM else
        "#4477BB" if bg == AZUL else "#555555"
    )
    b = tk.Label(pai, text=texto, font=FONT_B, bg=bg, fg=fg, cursor="hand2", **kw)
    b.bind("<Button-1>", lambda _: cmd())
    b.bind("<Enter>", lambda _: b.config(bg=hover))
    b.bind("<Leave>", lambda _: b.config(bg=bg))
    return b


def _entry(pai, var, width=36, ocultar=False):
    e = tk.Entry(pai, textvariable=var, show="*" if ocultar else "",
                 font=FONT_M, bg="#242424", fg=BCOR,
                 insertbackground=AMA, relief="flat", bd=0,
                 highlightthickness=1, highlightcolor=AMA,
                 highlightbackground=CESC, width=width)
    e.bind("<FocusIn>",  lambda ev, w=e: w.config(highlightbackground=AMA))
    e.bind("<FocusOut>", lambda ev, w=e: w.config(highlightbackground=CESC))
    return e


def abrir_backup_panel(parent=None, sessao: dict | None = None):
    global _auto_thread

    cfg = _carregar_cfg()

    root = tk.Toplevel(parent) if parent else tk.Tk()
    root.title("SPARTA AGENTE IA — Backup Avançado")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.grab_set()

    # ── Cabeçalho ──────────────────────────────────────────────────────────────
    cab = tk.Frame(root, bg=AMA, padx=16, pady=10)
    cab.pack(fill="x")
    tk.Label(cab, text="Backup Avançado", font=FONT_T, bg=AMA, fg=BG).pack(side="left")
    tk.Label(cab, text="(somente administrador)", font=("Segoe UI", 8),
             bg=AMA, fg="#666600").pack(side="right")

    corpo = tk.Frame(root, bg=BG, padx=24, pady=16)
    corpo.pack(fill="both")

    # ── Destino ────────────────────────────────────────────────────────────────
    tk.Label(corpo, text="DESTINO DO BACKUP", font=("Segoe UI", 8, "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(0, 4))

    frm_dest = tk.Frame(corpo, bg=BG)
    frm_dest.pack(fill="x", pady=(0, 4))

    sv_dest = tk.StringVar(value=cfg["destino"])
    e_dest  = _entry(frm_dest, sv_dest, width=38)
    e_dest.pack(side="left", ipady=5)

    def _browse():
        p = filedialog.askdirectory(title="Selecione a pasta de destino")
        if p:
            sv_dest.set(p)

    _btn(frm_dest, " Procurar ", _browse, bg=CESC, fg=BCOR).pack(side="left", padx=(6, 0))

    tk.Label(corpo, text="Exemplos: \\\\servidor\\backup  |  Z:\\Backups\\SPARTA  |  D:\\Backup",
             font=("Segoe UI", 7), bg=BG, fg=CINZA).pack(anchor="w", pady=(0, 4))

    tk.Label(corpo,
             text="Inclui: banco de dados IA  +  configuração de câmeras  +  .env",
             font=("Segoe UI", 8, "italic"), bg=BG, fg=VERDE).pack(anchor="w", pady=(0, 10))

    # ── Opções ─────────────────────────────────────────────────────────────────
    tk.Frame(corpo, bg=CESC, height=1).pack(fill="x", pady=(0, 10))
    tk.Label(corpo, text="OPÇÕES", font=("Segoe UI", 8, "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(0, 6))

    frm_opts = tk.Frame(corpo, bg=BG)
    frm_opts.pack(fill="x", pady=(0, 12))

    var_zip = tk.BooleanVar(value=cfg["compactar"])
    chk_zip = tk.Checkbutton(frm_opts, text="Compactar backup (ZIP_DEFLATED)",
                              variable=var_zip, font=FONT_L,
                              bg=BG, fg=BCOR, selectcolor=CESC,
                              activebackground=BG, activeforeground=BCOR,
                              cursor="hand2")
    chk_zip.pack(anchor="w")

    frm_max = tk.Frame(frm_opts, bg=BG)
    frm_max.pack(anchor="w", pady=(6, 0))
    tk.Label(frm_max, text="Manter últimos:", font=FONT_L, bg=BG, fg=BCOR).pack(side="left")
    sv_max = tk.StringVar(value=str(cfg["max_backups"]))
    tk.Spinbox(frm_max, from_=1, to=100, textvariable=sv_max, width=5,
               font=FONT_M, bg="#242424", fg=BCOR,
               insertbackground=AMA, relief="flat",
               buttonbackground=CESC).pack(side="left", padx=(6, 0))
    tk.Label(frm_max, text="arquivos", font=FONT_L, bg=BG, fg=CINZA).pack(side="left", padx=(4, 0))

    # ── Modo ───────────────────────────────────────────────────────────────────
    tk.Frame(corpo, bg=CESC, height=1).pack(fill="x", pady=(0, 10))
    tk.Label(corpo, text="MODO DE BACKUP", font=("Segoe UI", 8, "bold"),
             bg=BG, fg=AMA).pack(anchor="w", pady=(0, 6))

    var_modo = tk.StringVar(value=cfg["modo"])

    frm_modo = tk.Frame(corpo, bg=BG)
    frm_modo.pack(anchor="w")
    tk.Radiobutton(frm_modo, text="Manual (sob demanda)",
                   variable=var_modo, value="manual",
                   font=FONT_L, bg=BG, fg=BCOR, selectcolor=CESC,
                   activebackground=BG, cursor="hand2").pack(anchor="w")
    tk.Radiobutton(frm_modo, text="Automático (agendado)",
                   variable=var_modo, value="automatico",
                   font=FONT_L, bg=BG, fg=BCOR, selectcolor=CESC,
                   activebackground=BG, cursor="hand2").pack(anchor="w")

    frm_int = tk.Frame(corpo, bg=BG)
    frm_int.pack(anchor="w", pady=(6, 0))
    tk.Label(frm_int, text="Intervalo automático:", font=FONT_L,
             bg=BG, fg=BCOR).pack(side="left")
    sv_int = tk.StringVar(value=str(cfg["intervalo_horas"]))
    tk.Spinbox(frm_int, from_=1, to=168, increment=1, textvariable=sv_int,
               width=5, font=FONT_M, bg="#242424", fg=BCOR,
               insertbackground=AMA, relief="flat",
               buttonbackground=CESC).pack(side="left", padx=(6, 0))
    tk.Label(frm_int, text="horas", font=FONT_L, bg=BG, fg=CINZA).pack(side="left", padx=(4, 0))

    # ── Status ─────────────────────────────────────────────────────────────────
    tk.Frame(corpo, bg=CESC, height=1).pack(fill="x", pady=(10, 0))
    sv_status = tk.StringVar(value="")
    lbl_status = tk.Label(corpo, textvariable=sv_status, font=FONT_L,
                          bg=BG, fg=VERDE, wraplength=440, justify="left")
    lbl_status.pack(anchor="w", pady=(6, 0))

    # ── Histórico de backups ───────────────────────────────────────────────────
    frm_hist = tk.Frame(corpo, bg=BG_CARD, padx=12, pady=8)
    frm_hist.pack(fill="x", pady=(10, 0))
    tk.Label(frm_hist, text="BACKUPS EXISTENTES NO DESTINO",
             font=("Segoe UI", 8, "bold"), bg=BG_CARD, fg=AMA).pack(anchor="w")
    sv_hist = tk.StringVar(value="(selecione um destino para listar)")
    tk.Label(frm_hist, textvariable=sv_hist, font=("Consolas", 8),
             bg=BG_CARD, fg=CINZA, justify="left").pack(anchor="w")

    def _atualizar_historico():
        dest = sv_dest.get().strip()
        if not dest or not Path(dest).exists():
            sv_hist.set("(pasta não encontrada)")
            return
        arquivos = sorted(Path(dest).glob("sparta_backup_*.zip"), reverse=True)
        if not arquivos:
            sv_hist.set("Nenhum backup encontrado.")
        else:
            linhas = []
            for a in arquivos[:8]:
                tam = a.stat().st_size / 1024
                unidade = "KB" if tam < 1024 else "MB"
                if unidade == "MB":
                    tam /= 1024
                # Detecta conteúdo do ZIP
                conteudo = ""
                try:
                    with zipfile.ZipFile(a, "r") as zf:
                        nomes = zf.namelist()
                        partes = []
                        if any(n.endswith(".db") for n in nomes):
                            partes.append("BD")
                        if "cameras.json" in nomes:
                            partes.append("CAM")
                        if ".env" in nomes:
                            partes.append("ENV")
                        conteudo = "+".join(partes)
                except Exception:
                    conteudo = "?"
                linhas.append(f"  {a.name}  ({tam:.1f} {unidade})  [{conteudo}]")
            if len(arquivos) > 8:
                linhas.append(f"  ... e mais {len(arquivos)-8} arquivo(s)")
            sv_hist.set("\n".join(linhas))

    # ── Botões ─────────────────────────────────────────────────────────────────
    frm_btns = tk.Frame(corpo, bg=BG)
    frm_btns.pack(fill="x", pady=(14, 0))

    def _salvar_config():
        dest = sv_dest.get().strip()
        if not dest:
            sv_status.set("Informe o destino do backup.")
            lbl_status.config(fg=VERM)
            return
        try:
            max_b = int(sv_max.get())
            inter = float(sv_int.get())
        except ValueError:
            sv_status.set("Valores de configuração inválidos.")
            lbl_status.config(fg=VERM)
            return

        nova_cfg = {
            "destino":         dest,
            "compactar":       var_zip.get(),
            "modo":            var_modo.get(),
            "intervalo_horas": inter,
            "max_backups":     max_b,
        }
        _salvar_cfg(nova_cfg)

        parar_automatico()
        if nova_cfg["modo"] == "automatico":
            _auto_stop.clear()
            threading.Thread(target=_loop_automatico, args=(nova_cfg,),
                             daemon=True, name="BackupPanel-Auto").start()
            sv_status.set(f"Configuração salva. Backup automático ativo a cada {inter:.0f}h.")
        else:
            sv_status.set("Configuração salva.")
        lbl_status.config(fg=VERDE)
        _atualizar_historico()

    # Fila para comunicação thread-worker → loop Tkinter
    _q: _queue.Queue = _queue.Queue()
    _after_id = [None]

    def _poll_queue():
        try:
            while True:
                tipo, dados = _q.get_nowait()
                if tipo == "status":
                    msg, cor = dados
                    sv_status.set(msg)
                    lbl_status.config(fg=cor)
                elif tipo == "historico":
                    _atualizar_historico()
        except _queue.Empty:
            pass
        try:
            _after_id[0] = root.after(150, _poll_queue)
        except Exception:
            pass

    _after_id[0] = root.after(150, _poll_queue)

    def _fechar():
        if _after_id[0] is not None:
            try:
                root.after_cancel(_after_id[0])
            except Exception:
                pass
        root.destroy()

    def _set_status(msg: str, cor: str = VERDE):
        sv_status.set(msg)
        lbl_status.config(fg=cor)

    def _set_status_thread(msg: str, cor: str = VERDE):
        _q.put(("status", (msg, cor)))

    def _fazer_backup_agora():
        dest = sv_dest.get().strip()
        if not dest:
            _set_status("Informe o destino antes de fazer backup.", VERM)
            return
        try:
            max_b = int(sv_max.get())
        except ValueError:
            max_b = 20
        compactar = var_zip.get()

        _set_status("Realizando backup completo (BD + câmeras + config)...", AMA)
        root.update_idletasks()

        def _run():
            try:
                saida = _fazer_backup_avancado(dest, compactar, max_b)
                tam   = saida.stat().st_size / 1024
                unid  = "KB" if tam < 1024 else "MB"
                if unid == "MB":
                    tam /= 1024
                # Lista conteúdo do ZIP gerado
                with zipfile.ZipFile(saida, "r") as zf:
                    itens = ", ".join(zf.namelist())
                _set_status_thread(
                    f"Backup concluído: {saida.name}  ({tam:.1f} {unid})\n"
                    f"Conteúdo: {itens}"
                )
                _q.put(("historico", None))
            except Exception as exc:
                _set_status_thread(f"Erro: {exc}", VERM)

        threading.Thread(target=_run, daemon=True).start()

    def _restaurar_backup():
        """Restaura BD + cameras.json + .env de um arquivo ZIP de backup."""
        global _reload_cameras_needed

        arq = filedialog.askopenfilename(
            title="Selecione o arquivo de backup para restaurar",
            filetypes=[("Backup SPARTA", "*.zip *.db"), ("Arquivo ZIP", "*.zip"),
                       ("Banco SQLite", "*.db")],
        )
        if not arq:
            return
        arq = Path(arq)

        # Detecta o que contém o backup
        tem_cameras = False
        tem_env     = False
        tem_db      = False
        if arq.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(arq, "r") as zf:
                    nomes = zf.namelist()
                    tem_db      = any(n.endswith(".db") for n in nomes)
                    tem_cameras = "cameras.json" in nomes
                    tem_env     = ".env" in nomes
            except Exception as exc:
                messagebox.showerror("Erro", f"Não foi possível abrir o ZIP:\n{exc}", parent=root)
                return
        else:
            tem_db = True  # arquivo .db legado

        partes = []
        if tem_db:
            partes.append("banco de dados IA")
        if tem_cameras:
            partes.append("configuração de câmeras")
        if tem_env:
            partes.append("arquivo .env")

        if not messagebox.askyesno(
            "Confirmar Restauração",
            f"Restaurar o backup:\n\n  {arq.name}\n\n"
            f"Conteúdo encontrado:\n  • " + "\n  • ".join(partes) + "\n\n"
            "O estado atual será salvo como segurança antes de restaurar.\n\n"
            "Deseja continuar?",
            parent=root,
        ):
            return

        _set_status("Restaurando backup...", AMA)
        root.update_idletasks()

        def _run():
            global _reload_cameras_needed
            try:
                ts_seg = datetime.now().strftime("%Y%m%d_%H%M%S")

                # ── Segurança do estado atual ──────────────────────────────────
                seg_dir = _db.DB_PATH.parent / f"_pre_restore_{ts_seg}"
                seg_dir.mkdir(exist_ok=True)

                src = sqlite3.connect(str(_db.DB_PATH))
                dst = sqlite3.connect(str(seg_dir / "sparta_analytics.db"))
                src.backup(dst)
                src.close()
                dst.close()

                if _CAMERAS_JSON.exists():
                    shutil.copy2(_CAMERAS_JSON, seg_dir / "cameras.json")
                if _ENV_FILE.exists():
                    shutil.copy2(_ENV_FILE, seg_dir / ".env")

                log.info("Segurança pré-restauração salva em: %s", seg_dir.name)

                # ── Restauração ───────────────────────────────────────────────
                restaurou_cameras = False

                if arq.suffix.lower() == ".zip":
                    import tempfile
                    with tempfile.TemporaryDirectory() as tmpdir:
                        tmpdir = Path(tmpdir)
                        with zipfile.ZipFile(arq, "r") as zf:
                            zf.extractall(tmpdir)
                            nomes = zf.namelist()

                        # Banco de dados — copia via sqlite3.backup (evita lock)
                        db_nomes = [n for n in nomes if n.endswith(".db")]
                        if db_nomes:
                            extraido = tmpdir / db_nomes[0]
                            src2 = sqlite3.connect(str(extraido))
                            dst2 = sqlite3.connect(str(_db.DB_PATH))
                            src2.backup(dst2)
                            src2.close()
                            dst2.close()

                        # cameras.json
                        cam_tmp = tmpdir / "cameras.json"
                        if cam_tmp.exists():
                            shutil.copy2(cam_tmp, _CAMERAS_JSON)
                            restaurou_cameras = True
                            log.info("cameras.json restaurado do backup")

                        # .env
                        env_tmp = tmpdir / ".env"
                        if env_tmp.exists():
                            shutil.copy2(env_tmp, _ENV_FILE)
                            log.info(".env restaurado do backup")

                else:
                    # Legado: apenas arquivo .db
                    src2 = sqlite3.connect(str(arq))
                    dst2 = sqlite3.connect(str(_db.DB_PATH))
                    src2.backup(dst2)
                    src2.close()
                    dst2.close()

                if restaurou_cameras:
                    _reload_cameras_needed = True

                msg = "Restauração concluída!\n"
                msg += "Câmeras serão recarregadas automaticamente." if restaurou_cameras else ""
                msg += "\nSegurança pré-restauração: " + seg_dir.name
                _set_status_thread(msg)
                log.info("Restauração concluída. cameras=%s", restaurou_cameras)

            except Exception as exc:
                _set_status_thread(f"Erro na restauração: {exc}", VERM)
                log.error("Erro na restauração: %s", exc)

        threading.Thread(target=_run, daemon=True).start()

    _btn(frm_btns, " Salvar Config ",   _salvar_config).pack(side="left")
    _btn(frm_btns, " Backup Agora ",    _fazer_backup_agora,
         bg=AZUL, fg=BCOR).pack(side="left", padx=(6, 0))
    _btn(frm_btns, " Restaurar ",       _restaurar_backup,
         bg=VERM, fg=BCOR).pack(side="left", padx=(6, 0))
    _btn(frm_btns, " Listar ",          _atualizar_historico,
         bg=CESC, fg=BCOR).pack(side="left", padx=(6, 0))
    _btn(frm_btns, " Fechar ",          _fechar,
         bg=CESC, fg=BCOR).pack(side="right")

    root.protocol("WM_DELETE_WINDOW", _fechar)
    _centralizar(root)
    _atualizar_historico()
    root.wait_window()
    import gc as _gc
    _gc.collect()
