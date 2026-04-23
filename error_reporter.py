"""Coleta e envia relatórios de erros/bugs para o servidor local SPARTA.

Fluxo:
  1. Coleta logs + info do sistema + config de câmeras (senhas removidas)
  2. Empacota em zip
  3. POST para https://<servidor>/relatorios/upload (cert pinning)
  4. Salva cópia local em Documents/SPARTA_Relatorios

REPORT_SERVER_URL e REPORT_SERVER_TOKEN devem estar no .env.
"""
import json
import logging
import os
import platform
import re
import socket
import sys
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path

import requests

from version import VERSION

log = logging.getLogger(__name__)

_TIMEOUT = 30

_REPORT_URL_DEFAULT   = "https://138.186.129.103:8443/relatorios/upload"
_REPORT_TOKEN_DEFAULT = ""


def _report_url() -> str:
    return os.getenv("REPORT_SERVER_URL", _REPORT_URL_DEFAULT)


def _report_token() -> str:
    return os.getenv("REPORT_SERVER_TOKEN", _REPORT_TOKEN_DEFAULT)


def _cert_path() -> str | None:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).parent
    cert = base / "assets" / "update_server.crt"
    return str(cert) if cert.exists() else None


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

    # Localiza monitor.log corretamente em modo frozen e dev
    if getattr(sys, "frozen", False):
        log_path = Path(sys.executable).parent / "monitor.log"
    else:
        log_path = Path(__file__).parent / "monitor.log"

    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("info.json", json.dumps(info, indent=2, ensure_ascii=False))
        if log_path.exists():
            # Inclui apenas os últimos 500 KB para evitar travar em logs grandes
            tamanho = log_path.stat().st_size
            limite  = 500 * 1024
            with log_path.open("rb") as f:
                if tamanho > limite:
                    f.seek(-limite, 2)
                conteudo = f.read()
            zf.writestr("monitor.log", conteudo)

    return tmp


def exportar_relatorio(destino: Path | None = None) -> Path | None:
    """Gera zip e salva em *destino* (ou em Documents/SPARTA_Relatorios). Retorna caminho ou None."""
    try:
        zip_tmp = gerar_zip_relatorio("exportacao_manual")
        if destino is None:
            pasta   = Path.home() / "Documents" / "SPARTA_Relatorios"
            pasta.mkdir(parents=True, exist_ok=True)
            destino = pasta / zip_tmp.name
        import shutil
        shutil.move(str(zip_tmp), str(destino))
        log.info("Relatório exportado: %s", destino)
        return destino
    except Exception as exc:
        log.error("Falha ao exportar relatório: %s", exc)
        return None


# ── Servidor local ────────────────────────────────────────────────────────────

def enviar_relatorio_servidor(zip_path: Path, motivo: str = "auto") -> bool:
    """POST do zip para o servidor SPARTA via HTTPS com cert pinning."""
    url   = _report_url()
    token = _report_token()
    cert  = _cert_path()

    if not token:
        log.warning("REPORT_SERVER_TOKEN não configurado — relatório não enviado.")
        return False
    if not cert:
        log.warning("Certificado update_server.crt ausente — relatório não enviado.")
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type":  "application/zip",
    }
    try:
        with zip_path.open("rb") as f:
            r = requests.post(url, headers=headers, data=f,
                              timeout=_TIMEOUT, verify=cert)
        r.raise_for_status()
        log.info("Relatório enviado ao servidor: %s (motivo=%s)", zip_path.name, motivo)
        return True
    except Exception as exc:
        log.warning("Falha ao enviar relatório ao servidor: %s", exc)
        return False


def relatar_automatico(motivo: str, extra: dict | None = None) -> None:
    """Gera e envia relatório em background sem bloquear a UI."""
    def _run():
        zip_path = None
        try:
            zip_path = gerar_zip_relatorio(motivo, extra)
            enviar_relatorio_servidor(zip_path, motivo)
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

def _pasta_relatorios() -> Path:
    """Pasta fixa onde os relatórios exportados são salvos."""
    p = Path.home() / "Documents" / "SPARTA_Relatorios"
    p.mkdir(parents=True, exist_ok=True)
    return p


def abrir_painel_relatorio(parent_tk=None):
    """Janela de feedback para o operador — simples, sem detalhes técnicos."""
    import tkinter as tk
    import tkinter.messagebox as _msgbox

    from version import APP_NAME

    BG    = "#0F0F0F"
    AMA   = "#2D7A6E"
    VERDE = "#3DCC7E"
    VERM  = "#FF4444"
    CINZA = "#888888"
    BCOR  = "#F0F0F0"

    root = tk.Toplevel(parent_tk) if parent_tk else tk.Tk()
    root.title(f"{APP_NAME} — Relatorio de Erros")
    root.configure(bg=BG)
    root.resizable(False, False)
    root.attributes("-topmost", True)
    root.grab_set()

    cab = tk.Frame(root, bg=AMA, padx=16, pady=8)
    cab.pack(fill="x")
    tk.Label(cab, text="Relatorio de Erros / Melhorias",
             font=("Segoe UI", 11, "bold"), bg=AMA, fg=BG).pack(side="left")
    tk.Label(cab, text=f"v{VERSION}",
             font=("Segoe UI", 9), bg=AMA, fg="#FFE0A0").pack(side="right")

    corpo = tk.Frame(root, bg=BG, padx=24, pady=16)
    corpo.pack(fill="both")

    tk.Label(corpo,
             text="Descreva o que aconteceu ou o que pode ser melhorado:",
             font=("Segoe UI", 9), bg=BG, fg=CINZA, anchor="w").pack(fill="x")
    txt_desc = tk.Text(corpo, height=5, font=("Segoe UI", 10),
                       bg="#1A1A1A", fg=BCOR, insertbackground=BCOR,
                       relief="flat", wrap="word")
    txt_desc.pack(fill="x", pady=(4, 12))
    txt_desc.focus_set()

    sv_status = tk.StringVar(value="")
    lbl_status = tk.Label(corpo, textvariable=sv_status,
                          font=("Segoe UI", 9), bg=BG, fg=VERDE,
                          wraplength=400, justify="left")
    lbl_status.pack(fill="x", pady=(0, 8))

    def _set_status(msg: str, cor: str = VERDE):
        sv_status.set(msg)
        lbl_status.config(fg=cor)

    def _extra() -> dict:
        desc = txt_desc.get("1.0", "end").strip()
        return {"descricao_operador": desc} if desc else {}

    def _enviar():
        _set_status("Gerando relatorio...", AMA)
        root.update()

        def _run():
            zip_path = None
            try:
                extra    = _extra()
                zip_path = gerar_zip_relatorio("envio_operador", extra)
                # Sempre salva cópia local
                pasta  = _pasta_relatorios()
                local  = pasta / zip_path.name
                import shutil
                shutil.copy2(str(zip_path), str(local))
                # Tenta enviar ao servidor se token configurado
                tem_token = bool(_report_token())
                if tem_token:
                    ok = enviar_relatorio_servidor(zip_path, "envio_operador")
                    if ok:
                        msg = "Relatorio enviado com sucesso!\n\nSalvo em:\n" + str(local)
                        root.after(0, lambda: _set_status(
                            "Relatorio enviado e salvo em:\n" + str(local), VERDE))
                        root.after(0, lambda: _msgbox.showinfo(
                            "Relatorio Enviado", msg, parent=root))
                    else:
                        msg = "Enviado localmente (falha no envio remoto).\n\nSalvo em:\n" + str(local)
                        root.after(0, lambda: _set_status(
                            "Enviado localmente (falha no envio remoto):\n" + str(local), AMA))
                        root.after(0, lambda: _msgbox.showwarning(
                            "Envio Parcial", msg, parent=root))
                else:
                    msg = "Relatorio salvo localmente em:\n" + str(local)
                    root.after(0, lambda: _set_status(
                        "Relatorio salvo em:\n" + str(local), VERDE))
                    root.after(0, lambda: _msgbox.showinfo(
                        "Relatorio Salvo", msg, parent=root))
            except Exception as exc:
                root.after(0, lambda: _set_status(f"Erro: {exc}", VERM))
                root.after(0, lambda: _msgbox.showerror(
                    "Erro no Relatorio", str(exc), parent=root))
            finally:
                if zip_path and zip_path.exists():
                    try:
                        zip_path.unlink()
                    except Exception:
                        pass

        threading.Thread(target=_run, daemon=True).start()

    def _exportar():
        _set_status("Exportando...", AMA)
        root.update()
        pasta   = _pasta_relatorios()
        nome    = f"sparta_relatorio_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        destino = exportar_relatorio(pasta / nome)
        if destino:
            _set_status("Relatorio salvo em:\n" + str(destino), VERDE)
        else:
            _set_status("Falha ao exportar.", VERM)

    frm_btns = tk.Frame(corpo, bg=BG)
    frm_btns.pack(fill="x", pady=(4, 0))

    def _btn(parent, txt, cor, cmd):
        esc = {"#3DCC7E": "#2EAA66", "#2D7A6E": "#1F5C52"}.get(cor, "#555555")
        b = tk.Label(parent, text=txt, font=("Segoe UI", 10, "bold"),
                     bg=cor, fg=BG, padx=12, pady=8, cursor="hand2")
        b.bind("<Enter>", lambda _: b.config(bg=esc))
        b.bind("<Leave>", lambda _: b.config(bg=cor))
        b.bind("<Button-1>", lambda _: cmd())
        b.pack(side="left", padx=(0, 8))
        return b

    _btn(frm_btns, "  Enviar Relatorio  ", VERDE,     _enviar)
    _btn(frm_btns, "  Exportar ZIP  ",     AMA,       _exportar)
    _btn(frm_btns, "  Fechar  ",           "#444444",  root.destroy)

    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{max(w, 440)}x{h}+{(sw - max(w, 440)) // 2}+{(sh - h) // 2}")
    root.wait_window()
