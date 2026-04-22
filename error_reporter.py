"""Coleta e envia relatórios de erros/bugs para o repositório GitHub.

Fluxo:
  1. Coleta logs + info do sistema + config de câmeras (senhas removidas)
  2. Empacota em zip
  3. Envia como asset da release "bug-reports" no GitHub
  4. Rotaciona assets antigos quando total > LIMITE_GB

GITHUB_TOKEN deve estar no .env com permissão repo (ou public_repo para repo público).
"""
import json
import logging
import os
import platform
import re
import socket
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import requests

from version import VERSION

log = logging.getLogger(__name__)

_LIMITE_GB    = 10          # dispara limpeza quando total ultrapassa esse valor
_ALVO_GB      = 7           # limpa até esse patamar, deixando ~3 GB de buffer livre
_LIMITE_BYTES = _LIMITE_GB * 1024 ** 3
_ALVO_BYTES   = _ALVO_GB   * 1024 ** 3
_TAG_RELEASE  = "bug-reports"
_TIMEOUT      = 30


def _github_token() -> str:
    from config import GITHUB_TOKEN
    return GITHUB_TOKEN


def _github_repo() -> str:
    from config import GITHUB_REPO
    return GITHUB_REPO


def _sanitizar_uri(uri: str) -> str:
    return re.sub(r"(rtsp://[^:]+:)[^@]+(@)", r"\1***\2", uri)


def _coletar_cameras() -> list:
    try:
        p = Path(__file__).parent / "cameras.json"
        if not p.exists():
            return []
        cams = json.loads(p.read_text(encoding="utf-8"))
        for c in cams:
            c.pop("senha", None)
            for k in ("rtsp_uri", "rtsp_uri_sub"):
                if k in c:
                    c[k] = _sanitizar_uri(c[k])
        return cams
    except Exception:
        return []


def _info_sistema() -> dict:
    try:
        hostname = socket.gethostname()
    except Exception:
        hostname = "desconhecido"
    return {
        "versao_app": VERSION,
        "os":         platform.platform(),
        "hostname":   hostname,
        "timestamp":  datetime.now().isoformat(),
    }


def gerar_zip_relatorio(motivo: str = "manual", extra: dict | None = None) -> Path:
    """Empacota log + info em um zip temporário e retorna o caminho."""
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    nome = f"sparta_relatorio_{ts}.zip"
    tmp  = Path(tempfile.gettempdir()) / nome

    info = {
        "motivo":   motivo,
        "sistema":  _info_sistema(),
        "cameras":  _coletar_cameras(),
        **(extra or {}),
    }

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("info.json", json.dumps(info, indent=2, ensure_ascii=False))
        log_path = Path(__file__).parent / "monitor.log"
        if log_path.exists():
            zf.write(log_path, "monitor.log")

    return tmp


def exportar_relatorio(destino: Path | None = None) -> Path | None:
    """Gera zip e salva em *destino* (ou na Área de Trabalho). Retorna caminho ou None."""
    try:
        zip_tmp = gerar_zip_relatorio("exportacao_manual")
        if destino is None:
            desktop = Path.home() / "Desktop"
            desktop.mkdir(exist_ok=True)
            destino = desktop / zip_tmp.name
        import shutil
        shutil.move(str(zip_tmp), str(destino))
        log.info("Relatório exportado: %s", destino)
        return destino
    except Exception as exc:
        log.error("Falha ao exportar relatório: %s", exc)
        return None


# ── GitHub ────────────────────────────────────────────────────────────────────

def _headers() -> dict:
    return {
        "Authorization":        f"Bearer {_github_token()}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _garantir_release(api: str) -> int | None:
    """Retorna ID da release 'bug-reports', criando se não existir."""
    hdrs = _headers()
    try:
        r = requests.get(f"{api}/releases/tags/{_TAG_RELEASE}", headers=hdrs, timeout=_TIMEOUT)
        if r.status_code == 200:
            return r.json()["id"]
        if r.status_code == 404:
            body = {
                "tag_name":   _TAG_RELEASE,
                "name":       "Bug Reports — SPARTA AGENTE IA",
                "body":       "Relatórios de erros enviados automaticamente pelo app.",
                "draft":      False,
                "prerelease": True,
            }
            r2 = requests.post(f"{api}/releases", headers=hdrs, json=body, timeout=_TIMEOUT)
            r2.raise_for_status()
            return r2.json()["id"]
    except Exception as exc:
        log.warning("Falha ao garantir release bug-reports: %s", exc)
    return None


def _rotacionar_assets(api: str, release_id: int) -> None:
    """Remove assets mais antigos quando total ultrapassa LIMITE_GB.

    Ao limpar, vai até ALVO_GB (não apenas até o limite), garantindo
    buffer de ~3 GB para novas entradas sem lotar imediatamente.
    """
    hdrs = _headers()
    try:
        r = requests.get(f"{api}/releases/{release_id}/assets",
                         headers=hdrs, timeout=_TIMEOUT)
        r.raise_for_status()
        assets = sorted(r.json(), key=lambda a: a["created_at"])
        total  = sum(a["size"] for a in assets)
        if total <= _LIMITE_BYTES:
            return  # dentro do limite, nada a fazer
        log.info("Relatórios: %.1f GB > limite %d GB — limpando até %d GB (buffer livre ~%d GB)",
                 total / 1024**3, _LIMITE_GB, _ALVO_GB, _LIMITE_GB - _ALVO_GB)
        removidos = 0
        while total > _ALVO_BYTES and assets:
            a = assets.pop(0)
            requests.delete(f"{api}/releases/assets/{a['id']}",
                            headers=hdrs, timeout=_TIMEOUT)
            total -= a["size"]
            removidos += 1
            log.info("  Removido: %s (%.1f MB) — restante: %.1f GB",
                     a["name"], a["size"] / 1e6, total / 1024**3)
        log.info("Rotação concluída: %d relatório(s) removido(s). Total atual: %.1f GB",
                 removidos, total / 1024**3)
    except Exception as exc:
        log.warning("Falha na rotação de assets: %s", exc)


def enviar_relatorio_github(zip_path: Path, motivo: str = "auto") -> bool:
    """Faz upload do zip como asset da release 'bug-reports' no GitHub."""
    token = _github_token()
    repo  = _github_repo()
    if not token:
        log.warning("GITHUB_TOKEN não configurado — relatório não enviado.")
        return False
    if not repo:
        log.warning("GITHUB_REPO não configurado — relatório não enviado.")
        return False

    api = f"https://api.github.com/repos/{repo}"
    release_id = _garantir_release(api)
    if not release_id:
        return False

    _rotacionar_assets(api, release_id)

    upload_url = (
        f"https://uploads.github.com/repos/{repo}/releases/{release_id}"
        f"/assets?name={zip_path.name}"
    )
    try:
        with zip_path.open("rb") as f:
            r = requests.post(
                upload_url,
                headers={**_headers(), "Content-Type": "application/zip"},
                data=f,
                timeout=120,
            )
        r.raise_for_status()
        log.info("Relatório enviado ao GitHub: %s (motivo=%s)", zip_path.name, motivo)
        return True
    except Exception as exc:
        log.warning("Falha ao enviar relatório ao GitHub: %s", exc)
        return False


def relatar_automatico(motivo: str, extra: dict | None = None) -> None:
    """Gera e envia relatório em background sem bloquear a UI."""
    def _run():
        zip_path = None
        try:
            zip_path = gerar_zip_relatorio(motivo, extra)
            enviar_relatorio_github(zip_path, motivo)
        except Exception as exc:
            log.warning("Erro no envio automático de relatório: %s", exc)
        finally:
            if zip_path and zip_path.exists():
                try:
                    zip_path.unlink()
                except Exception:
                    pass

    threading.Thread(target=_run, daemon=True).start()


# ── Painel Tkinter ────────────────────────────────────────────────────────────

def abrir_painel_relatorio(parent_tk=None):
    """Janela para envio manual e exportação de relatórios."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    from version import APP_NAME

    BG    = "#0F0F0F"
    AMA   = "#FFD000"
    VERDE = "#3DCC7E"
    VERM  = "#FF4444"
    CINZA = "#888888"
    BCOR  = "#F0F0F0"

    root = tk.Toplevel(parent_tk) if parent_tk else tk.Tk()
    root.title(f"{APP_NAME} — Relatório de Erros")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.grab_set()

    cab = tk.Frame(root, bg=AMA, padx=16, pady=8)
    cab.pack(fill="x")
    tk.Label(cab, text="Relatório de Erros / Bugs",
             font=("Segoe UI", 11, "bold"), bg=AMA, fg=BG).pack(side="left")
    tk.Label(cab, text=f"v{VERSION}",
             font=("Segoe UI", 9), bg=AMA, fg="#666600").pack(side="right")

    corpo = tk.Frame(root, bg=BG, padx=24, pady=16)
    corpo.pack(fill="both")

    sv_status = tk.StringVar(value="")
    sv_token  = tk.StringVar(value=_github_token() or "")

    # ── Token ──────────────────────────────────────────────────────────────
    tk.Label(corpo, text="GitHub Token (opcional para envio ao repositório):",
             font=("Segoe UI", 8), bg=BG, fg=CINZA, anchor="w").pack(fill="x")
    ent_token = tk.Entry(corpo, textvariable=sv_token, font=("Consolas", 9),
                         bg="#1A1A1A", fg=BCOR, insertbackground=BCOR,
                         relief="flat", show="*")
    ent_token.pack(fill="x", pady=(2, 12))

    # ── Descrição ──────────────────────────────────────────────────────────
    tk.Label(corpo, text="Descrição do problema (opcional):",
             font=("Segoe UI", 8), bg=BG, fg=CINZA, anchor="w").pack(fill="x")
    txt_desc = tk.Text(corpo, height=4, font=("Segoe UI", 9),
                       bg="#1A1A1A", fg=BCOR, insertbackground=BCOR,
                       relief="flat", wrap="word")
    txt_desc.pack(fill="x", pady=(2, 12))

    # ── Status ─────────────────────────────────────────────────────────────
    lbl_status = tk.Label(corpo, textvariable=sv_status,
                          font=("Segoe UI", 9), bg=BG, fg=VERDE,
                          wraplength=380, justify="left")
    lbl_status.pack(fill="x", pady=(0, 8))

    def _set_status(msg: str, cor: str = VERDE):
        sv_status.set(msg)
        lbl_status.config(fg=cor)

    def _extra() -> dict:
        desc = txt_desc.get("1.0", "end").strip()
        return {"descricao_usuario": desc} if desc else {}

    def _enviar():
        token_ui = sv_token.get().strip()
        if token_ui:
            os.environ["GITHUB_TOKEN"] = token_ui
        _set_status("Gerando relatório...", AMA)
        root.update()

        def _run():
            zip_path = None
            try:
                zip_path = gerar_zip_relatorio("envio_manual", _extra())
                ok = enviar_relatorio_github(zip_path, "envio_manual")
                if ok:
                    root.after(0, lambda: _set_status(
                        "✔ Relatório enviado ao repositório GitHub.", VERDE))
                else:
                    root.after(0, lambda: _set_status(
                        "✘ Falha no envio. Verifique o Token e a conexão.\n"
                        "Use 'Exportar' para salvar localmente.", VERM))
            except Exception as exc:
                root.after(0, lambda: _set_status(f"✘ Erro: {exc}", VERM))
            finally:
                if zip_path and zip_path.exists():
                    try:
                        zip_path.unlink()
                    except Exception:
                        pass

        threading.Thread(target=_run, daemon=True).start()

    def _exportar():
        destino_str = filedialog.asksaveasfilename(
            parent=root,
            title="Salvar relatório como",
            defaultextension=".zip",
            filetypes=[("ZIP", "*.zip")],
            initialfile=f"sparta_relatorio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip",
        )
        if not destino_str:
            return
        _set_status("Exportando...", AMA)
        root.update()
        destino = exportar_relatorio(Path(destino_str))
        if destino:
            _set_status(f"✔ Relatório salvo em:\n{destino}", VERDE)
        else:
            _set_status("✘ Falha ao exportar.", VERM)

    frm_btns = tk.Frame(corpo, bg=BG)
    frm_btns.pack(fill="x", pady=(4, 0))

    def _btn(parent, txt, cor, cmd):
        b = tk.Label(parent, text=txt, font=("Segoe UI", 10, "bold"),
                     bg=cor, fg=BG, padx=12, pady=8, cursor="hand2")
        esc = "#2EAA66" if cor == VERDE else "#CC3333" if cor == VERM else "#BB9900"
        b.bind("<Enter>", lambda _: b.config(bg=esc))
        b.bind("<Leave>", lambda _: b.config(bg=cor))
        b.bind("<Button-1>", lambda _: cmd())
        b.pack(side="left", padx=(0, 8))
        return b

    _btn(frm_btns, "  Enviar ao GitHub  ", VERDE, _enviar)
    _btn(frm_btns, "  Exportar ZIP  ",     AMA,   _exportar)
    _btn(frm_btns, "  Fechar  ",           "#444444", root.destroy)

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{max(w, 420)}x{h}+{(sw - max(w, 420)) // 2}+{(sh - h) // 2}")
    root.wait_window()
