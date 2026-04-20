"""Auto-update via GitHub Releases — SPARTA AGENTE IA."""
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import requests

from version import VERSION, APP_NAME

log = logging.getLogger(__name__)

_TIMEOUT = 10


_GITHUB_REPO_DEFAULT = "Robsonhub/IVMS-RFSMART-"


def _github_repo() -> str:
    return os.getenv("GITHUB_REPO", _GITHUB_REPO_DEFAULT)


def _api_url() -> str:
    return f"https://api.github.com/repos/{_github_repo()}/releases/latest"


def _versao_para_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0,)


def verificar_atualizacao() -> tuple[str, dict | str | None]:
    """
    Retorna (status, dado):
      ("nao_configurado", None)  — GITHUB_REPO ausente no .env
      ("erro", msg)              — falha de rede ou HTTP
      ("sem_release", None)      — repositório sem releases publicadas
      ("atualizado", None)       — versão local já é a mais recente
      ("disponivel", dict)       — nova versão disponível
    """
    repo = _github_repo()
    if not repo:
        log.warning("GITHUB_REPO não configurado — auto-update desabilitado")
        return ("nao_configurado", None)

    try:
        resp = requests.get(_api_url(), timeout=_TIMEOUT,
                            headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            return ("sem_release", None)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Falha ao verificar atualizações: %s", exc)
        return ("erro", str(exc))

    versao_remota = data.get("tag_name", "").lstrip("v")
    if not versao_remota:
        return ("sem_release", None)

    if _versao_para_tuple(versao_remota) <= _versao_para_tuple(VERSION):
        log.info("Versão atual (%s) já é a mais recente.", VERSION)
        return ("atualizado", None)

    url_download = None
    tamanho = 0
    for asset in data.get("assets", []):
        if asset["name"].endswith(".zip"):
            url_download = asset["browser_download_url"]
            tamanho = asset.get("size", 0)
            break

    if not url_download:
        log.warning("Release %s sem asset .zip", versao_remota)
        return ("sem_release", None)

    return ("disponivel", {
        "versao":       versao_remota,
        "url_download": url_download,
        "notas":        data.get("body", "")[:500],
        "tamanho":      tamanho,
    })


def _lançar_bat_updater(zip_path: str, app_dir: Path, versao: str) -> bool:
    """Escreve bat no temp e o lança como processo independente para extrair após o app fechar."""
    exe = str(Path(sys.executable))
    bat_path = Path(tempfile.gettempdir()) / "sparta_updater.bat"

    conteudo = (
        "@echo off\n"
        "timeout /t 4 /nobreak >nul\n"
        f"powershell -NoProfile -Command \""
        f"Expand-Archive -LiteralPath '{zip_path}' "
        f"-DestinationPath '{app_dir}' -Force\"\n"
        f"start \"\" \"{exe}\"\n"
        f"del \"{zip_path}\"\n"
        "del \"%~f0\"\n"
    )
    try:
        bat_path.write_text(conteudo, encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        log.info("Atualizador lançado — app encerrará para aplicar v%s", versao)
        return True
    except Exception as exc:
        log.error("Falha ao lançar bat updater: %s", exc)
        return False


def baixar_e_aplicar(info: dict, progresso_cb=None) -> bool | str:
    """
    Baixa o .zip da release e aplica a atualização.
    - Modo frozen (PyInstaller): lança bat externo e retorna "restart"
    - Modo dev: extrai diretamente e retorna True
    - Falha: retorna False
    """
    url     = info["url_download"]
    versao  = info["versao"]
    frozen  = getattr(sys, "frozen", False)
    app_dir = Path(sys.executable).parent if frozen else Path(".")

    log.info("Baixando atualização %s de %s", versao, url)
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total    = int(r.headers.get("content-length", 0)) or info.get("tamanho", 1)
            baixado  = 0
            tmp      = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            for chunk in r.iter_content(chunk_size=65536):
                tmp.write(chunk)
                baixado += len(chunk)
                if progresso_cb and total:
                    progresso_cb(min(baixado / total, 1.0))
            tmp.close()
    except Exception as exc:
        log.error("Falha no download: %s", exc)
        return False

    # App frozen: não pode sobrescrever o próprio exe — usa bat externo
    if frozen:
        ok = _lançar_bat_updater(tmp.name, app_dir, versao)
        return "restart" if ok else False

    # Dev mode: extrai diretamente
    backup_dir = app_dir / f"_backup_pre_update_{VERSION}"
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(app_dir, backup_dir,
                        ignore=shutil.ignore_patterns("*.db", "*.log", "clips", "_backup*"))
        log.info("Backup pré-update salvo em: %s", backup_dir.name)
    except Exception as exc:
        log.warning("Backup pré-update falhou (não crítico): %s", exc)

    try:
        with zipfile.ZipFile(tmp.name, "r") as zf:
            zf.extractall(app_dir)
        log.info("Update %s aplicado com sucesso.", versao)
        return True
    except Exception as exc:
        log.error("Falha ao extrair update: %s", exc)
        return False
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def abrir_dialog_update(parent_tk=None):
    """Abre janela Tkinter mostrando status de update."""
    import queue as _queue
    import tkinter as tk

    BG    = "#0F0F0F"
    AMA   = "#FFD000"
    BCOR  = "#F0F0F0"
    CINZA = "#888888"
    VERM  = "#FF4444"
    VERDE = "#3DCC7E"

    root = tk.Toplevel(parent_tk) if parent_tk else tk.Tk()
    root.title(f"{APP_NAME} — Atualização")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.grab_set()

    cab = tk.Frame(root, bg=AMA, padx=16, pady=8)
    cab.pack(fill="x")
    tk.Label(cab, text="Verificar Atualização",
             font=("Segoe UI", 11, "bold"), bg=AMA, fg=BG).pack(side="left")
    tk.Label(cab, text=f"v{VERSION}",
             font=("Segoe UI", 9), bg=AMA, fg="#666600").pack(side="right")

    corpo = tk.Frame(root, bg=BG, padx=24, pady=16)
    corpo.pack(fill="both")

    sv_icone  = tk.StringVar(value="⏳")
    sv_status = tk.StringVar(value="Verificando atualizações...")
    sv_sub    = tk.StringVar(value="")

    frm_msg = tk.Frame(corpo, bg=BG)
    frm_msg.pack(fill="x", pady=(0, 8))
    lbl_icone = tk.Label(frm_msg, textvariable=sv_icone,
                         font=("Segoe UI", 22), bg=BG, fg=AMA)
    lbl_icone.pack(side="left", padx=(0, 12))
    frm_txt = tk.Frame(frm_msg, bg=BG)
    frm_txt.pack(side="left", fill="x", expand=True)
    lbl_status = tk.Label(frm_txt, textvariable=sv_status,
                          font=("Segoe UI", 10, "bold"),
                          bg=BG, fg=BCOR, wraplength=300, justify="left")
    lbl_status.pack(anchor="w")
    lbl_sub = tk.Label(frm_txt, textvariable=sv_sub,
                       font=("Segoe UI", 8), bg=BG, fg=CINZA,
                       wraplength=300, justify="left")
    lbl_sub.pack(anchor="w")

    frm_prog = tk.Frame(corpo, bg=BG)
    frm_prog.pack(fill="x", pady=(0, 8))
    canvas_prog = tk.Canvas(frm_prog, bg="#222222", height=6,
                            highlightthickness=0, relief="flat")
    canvas_prog.pack(fill="x")
    barra = canvas_prog.create_rectangle(0, 0, 0, 6, fill=AMA, outline="")

    def _set_progresso(pct: float):
        w = canvas_prog.winfo_width()
        canvas_prog.coords(barra, 0, 0, int(w * pct), 6)

    sv_notas = tk.StringVar(value="")
    lbl_notas = tk.Label(corpo, textvariable=sv_notas, font=("Consolas", 8),
                         bg="#1A1A1A", fg="#AAAAAA", wraplength=360,
                         justify="left", padx=8, pady=6)

    frm_btns = tk.Frame(corpo, bg=BG)
    frm_btns.pack(fill="x", pady=(10, 0))

    btn_instalar = tk.Label(frm_btns, text="  Baixar e Instalar  ",
                            font=("Segoe UI", 10, "bold"),
                            bg=VERDE, fg=BG, padx=12, pady=8, cursor="hand2")
    btn_instalar.bind("<Enter>", lambda _: btn_instalar.config(bg="#2EAA66"))
    btn_instalar.bind("<Leave>", lambda _: btn_instalar.config(bg=VERDE))

    _after_id = [None]

    def _fechar():
        if _after_id[0]:
            try:
                root.after_cancel(_after_id[0])
            except Exception:
                pass
        root.destroy()

    def _fechar_para_update():
        """Fecha o app inteiro para o bat updater aplicar a atualização."""
        _fechar()
        if parent_tk:
            try:
                parent_tk.destroy()
            except Exception:
                pass
        os._exit(0)

    btn_fechar = tk.Label(frm_btns, text="  Fechar  ",
                          font=("Segoe UI", 9),
                          bg="#333333", fg=BCOR, padx=12, pady=6, cursor="hand2")
    btn_fechar.bind("<Button-1>", lambda _: _fechar())
    btn_fechar.bind("<Enter>", lambda _: btn_fechar.config(bg="#555555"))
    btn_fechar.bind("<Leave>", lambda _: btn_fechar.config(bg="#333333"))
    btn_fechar.pack(side="right")

    _q: _queue.Queue = _queue.Queue()
    _info = [None]

    def _poll():
        try:
            while True:
                tipo, dados = _q.get_nowait()
                if tipo == "status":
                    icone, msg, sub, cor = dados
                    sv_icone.set(icone)
                    sv_status.set(msg)
                    sv_sub.set(sub)
                    lbl_status.config(fg=cor)
                    lbl_icone.config(fg=cor)
                elif tipo == "progresso":
                    _set_progresso(dados)
                elif tipo == "disponivel":
                    info = dados
                    _info[0] = info
                    sv_notas.set(info["notas"] if info["notas"] else "(sem notas de versão)")
                    lbl_notas.pack(fill="x", pady=(0, 8))
                    btn_instalar.pack(side="left")
                    btn_instalar.bind("<Button-1>", lambda _: _instalar())
                elif tipo == "restart":
                    # App vai fechar em 3s para o bat aplicar a atualização
                    root.after(3000, _fechar_para_update)
        except _queue.Empty:
            pass
        try:
            _after_id[0] = root.after(150, _poll)
        except Exception:
            pass

    def _instalar():
        btn_instalar.pack_forget()
        _q.put(("status", ("⬇️", "Baixando atualização...", "Aguarde, não feche a janela.", AMA)))
        _q.put(("progresso", 0.0))

        def _run():
            ok = baixar_e_aplicar(
                _info[0],
                progresso_cb=lambda p: _q.put(("progresso", p))
            )
            if ok == "restart":
                _q.put(("status", ("🔄", "Atualização baixada!",
                                   "O sistema fechará em 3s e reabrirá atualizado.", VERDE)))
                _q.put(("progresso", 1.0))
                _q.put(("restart", None))
            elif ok:
                _q.put(("status", ("✅", f"Atualização v{_info[0]['versao']} instalada!",
                                   "Feche e reinicie o sistema para aplicar.", VERDE)))
                _q.put(("progresso", 1.0))
            else:
                _q.put(("status", ("❌", "Falha na atualização.",
                                   "Verifique a conexão e tente novamente.", VERM)))

        threading.Thread(target=_run, daemon=True).start()

    def _verificar():
        def _run():
            status, dado = verificar_atualizacao()
            if status == "nao_configurado":
                _q.put(("status", ("⚙️", "Auto-update não configurado.",
                                   "Adicione GITHUB_REPO ao arquivo .env.", CINZA)))
            elif status == "erro":
                _q.put(("status", ("⚠️", "Não foi possível verificar atualizações.",
                                   f"Erro: {dado}", VERM)))
            elif status == "sem_release":
                _q.put(("status", ("ℹ️", "Nenhuma versão publicada no GitHub.",
                                   "Aguarde a publicação de uma release.", CINZA)))
            elif status == "atualizado":
                _q.put(("status", ("✅", "Você está na versão mais recente!",
                                   f"Versão instalada: v{VERSION}", VERDE)))
            elif status == "disponivel":
                info = dado
                tam  = info["tamanho"] / 1_048_576
                _q.put(("status", ("🆕", f"Nova versão disponível: v{info['versao']}",
                                   f"Tamanho: {tam:.1f} MB", AMA)))
                _q.put(("disponivel", info))

        threading.Thread(target=_run, daemon=True).start()

    _after_id[0] = root.after(150, _poll)
    _verificar()

    root.protocol("WM_DELETE_WINDOW", _fechar)
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.wait_window()
    import gc as _gc; _gc.collect()
