"""Auto-update via GitHub Releases — SPARTA AGENTE IA."""
import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import requests

from version import VERSION, APP_NAME

log = logging.getLogger(__name__)

# Configure no .env: GITHUB_REPO=usuario/repositorio
_GITHUB_REPO = os.getenv("GITHUB_REPO", "")
_API_URL      = f"https://api.github.com/repos/{_GITHUB_REPO}/releases/latest"
_TIMEOUT      = 10


def _versao_para_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0,)


def verificar_atualizacao() -> dict | None:
    """
    Consulta o GitHub e retorna dict com info da nova versão, ou None se já atualizado.
    dict: {"versao": str, "url_download": str, "notas": str, "tamanho": int}
    """
    if not _GITHUB_REPO:
        log.warning("GITHUB_REPO não configurado no .env — auto-update desabilitado")
        return None
    try:
        resp = requests.get(_API_URL, timeout=_TIMEOUT,
                            headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Falha ao verificar atualizações: %s", exc)
        return None

    versao_remota = data.get("tag_name", "").lstrip("v")
    if not versao_remota:
        return None

    if _versao_para_tuple(versao_remota) <= _versao_para_tuple(VERSION):
        log.info("Versão atual (%s) já é a mais recente.", VERSION)
        return None

    # Procura asset .zip na release
    url_download = None
    tamanho = 0
    for asset in data.get("assets", []):
        if asset["name"].endswith(".zip"):
            url_download = asset["browser_download_url"]
            tamanho = asset.get("size", 0)
            break

    if not url_download:
        log.warning("Release %s sem asset .zip — update ignorado", versao_remota)
        return None

    return {
        "versao":       versao_remota,
        "url_download": url_download,
        "notas":        data.get("body", "")[:500],
        "tamanho":      tamanho,
    }


def baixar_e_aplicar(info: dict, progresso_cb=None) -> bool:
    """
    Baixa o .zip da release e extrai sobre a pasta do projeto.
    progresso_cb(pct: float) chamado durante download (0.0 a 1.0).
    Retorna True se aplicado com sucesso.
    """
    url      = info["url_download"]
    versao   = info["versao"]
    app_dir  = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(".")

    log.info("Baixando atualização %s de %s", versao, url)
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get("content-length", 0)) or info.get("tamanho", 1)
            baixado = 0
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            for chunk in r.iter_content(chunk_size=65536):
                tmp.write(chunk)
                baixado += len(chunk)
                if progresso_cb and total:
                    progresso_cb(min(baixado / total, 1.0))
            tmp.close()
    except Exception as exc:
        log.error("Falha no download: %s", exc)
        return False

    # Backup da pasta atual antes de extrair
    backup_dir = app_dir / f"_backup_pre_update_{VERSION}"
    try:
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        shutil.copytree(app_dir, backup_dir,
                        ignore=shutil.ignore_patterns("*.db", "*.log", "clips", "_backup*"))
        log.info("Backup pré-update salvo em: %s", backup_dir.name)
    except Exception as exc:
        log.warning("Backup pré-update falhou (não crítico): %s", exc)

    # Extrai o zip
    try:
        with zipfile.ZipFile(tmp.name, "r") as zf:
            zf.extractall(app_dir)
        log.info("Update %s aplicado com sucesso.", versao)
    except Exception as exc:
        log.error("Falha ao extrair update: %s", exc)
        return False
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

    return True


def abrir_dialog_update(parent_tk=None):
    """Abre janela Tkinter mostrando status de update. Chama em thread separada."""
    import tkinter as tk
    from tkinter import messagebox

    BG   = "#0F0F0F"
    AMA  = "#FFD000"
    BCOR = "#F0F0F0"
    VERM = "#FF4444"
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

    sv_status = tk.StringVar(value="Verificando atualizações...")
    lbl = tk.Label(corpo, textvariable=sv_status, font=("Segoe UI", 9),
                   bg=BG, fg=BCOR, wraplength=340, justify="left")
    lbl.pack(anchor="w", pady=(0, 10))

    # Barra de progresso simples
    frm_prog = tk.Frame(corpo, bg=BG)
    frm_prog.pack(fill="x", pady=(0, 10))
    canvas_prog = tk.Canvas(frm_prog, bg="#333333", height=8,
                            highlightthickness=0, relief="flat")
    canvas_prog.pack(fill="x")
    barra = canvas_prog.create_rectangle(0, 0, 0, 8, fill=AMA, outline="")

    def _set_progresso(pct: float):
        w = canvas_prog.winfo_width()
        canvas_prog.coords(barra, 0, 0, int(w * pct), 8)
        root.update_idletasks()

    sv_notas = tk.StringVar(value="")
    lbl_notas = tk.Label(corpo, textvariable=sv_notas, font=("Consolas", 8),
                         bg="#1A1A1A", fg="#AAAAAA", wraplength=340,
                         justify="left", padx=8, pady=6)

    btn_atualizar = tk.Label(corpo, text="  Baixar e Instalar  ",
                             font=("Segoe UI", 10, "bold"),
                             bg=VERDE, fg=BG, padx=12, pady=8, cursor="hand2")
    btn_fechar = tk.Label(corpo, text="  Fechar  ",
                          font=("Segoe UI", 9),
                          bg="#333333", fg=BCOR, padx=12, pady=6, cursor="hand2")
    btn_fechar.bind("<Button-1>", lambda _: root.destroy())
    btn_fechar.pack(anchor="e", pady=(8, 0))

    _info = [None]

    def _aplicar():
        btn_atualizar.pack_forget()
        sv_status.set("Baixando atualização...")
        _set_progresso(0)

        def _run():
            ok = baixar_e_aplicar(_info[0], progresso_cb=lambda p: root.after(0, lambda: _set_progresso(p)))
            if ok:
                root.after(0, lambda: sv_status.set(
                    f"Atualização v{_info[0]['versao']} instalada!\nReinicie o sistema para aplicar."))
                root.after(0, lambda: _set_progresso(1.0))
            else:
                root.after(0, lambda: sv_status.set("Falha na atualização. Tente novamente."))

        threading.Thread(target=_run, daemon=True).start()

    def _verificar():
        def _run():
            info = verificar_atualizacao()
            if info is None:
                root.after(0, lambda: sv_status.set(
                    f"Você já está na versão mais recente (v{VERSION})."))
                return
            _info[0] = info
            tam_mb = info['tamanho'] / 1_048_576
            root.after(0, lambda: sv_status.set(
                f"Nova versão disponível: v{info['versao']}  ({tam_mb:.1f} MB)"))
            root.after(0, lambda: sv_notas.set(info["notas"]))
            root.after(0, lambda: lbl_notas.pack(fill="x", pady=(0, 10)))
            root.after(0, lambda: btn_atualizar.pack(fill="x", pady=(4, 0)))
            root.after(0, lambda: btn_atualizar.bind("<Button-1>", lambda _: _aplicar()))

        threading.Thread(target=_run, daemon=True).start()

    _verificar()

    # Centralizar
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")
    root.wait_window()
    import gc as _gc; _gc.collect()
