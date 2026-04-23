"""Auto-update — SPARTA AGENTE IA.

Provedor primário: servidor self-hosted (latest.json + .zip via HTTPS com
certificate pinning). Fallback durante a release-ponte v1.1.5: GitHub Releases.
"""
import hashlib
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


_UPDATE_URL_DEFAULT = "https://138.186.129.103:8443/latest.json"
_GITHUB_REPO_DEFAULT = "Robsonhub/IVMS-RFSMART-"


def _update_url() -> str:
    return os.getenv("UPDATE_SERVER_URL", _UPDATE_URL_DEFAULT)


def _github_repo() -> str:
    return os.getenv("GITHUB_REPO", _GITHUB_REPO_DEFAULT)


def _api_url() -> str:
    return f"https://api.github.com/repos/{_github_repo()}/releases/latest"


def _cert_path() -> str | None:
    """Localiza o certificado embarcado para pinning. Retorna None se ausente."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).parent
    cert = base / "assets" / "update_server.crt"
    return str(cert) if cert.exists() else None


def _rebase_url(download_url: str) -> str:
    """Substitui host/porta da URL de download pelo servidor configurado em UPDATE_SERVER_URL.

    Garante que máquinas com IP interno usem o servidor interno para baixar
    o zip, mesmo que o latest.json tenha o IP público.
    """
    from urllib.parse import urlparse, urlunparse
    base   = urlparse(_update_url())
    target = urlparse(download_url)
    return urlunparse((base.scheme, base.netloc,
                       target.path, target.params,
                       target.query, target.fragment))


def _versao_para_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in v.lstrip("v").split("."))
    except Exception:
        return (0,)


def _verificar_servidor_local() -> tuple[str, dict | str | None]:
    """Consulta latest.json no servidor self-hosted (com cert pinning)."""
    url  = _update_url()
    cert = _cert_path()
    if not cert:
        return ("erro", "Certificado update_server.crt ausente em assets/")

    try:
        resp = requests.get(url, timeout=_TIMEOUT, verify=cert)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("Servidor local falhou: %s", exc)
        return ("erro", str(exc))

    versao_remota = str(data.get("version", "")).lstrip("v")
    url_download  = data.get("url", "")
    sha256        = data.get("sha256", "")

    if not versao_remota or versao_remota == "0.0.0" or not url_download:
        return ("sem_release", None)

    if _versao_para_tuple(versao_remota) <= _versao_para_tuple(VERSION):
        return ("atualizado", None)

    return ("disponivel", {
        "versao":       versao_remota,
        "url_download": _rebase_url(url_download),
        "notas":        str(data.get("notes", ""))[:500],
        "tamanho":      int(data.get("size", 0)),
        "sha256":       sha256,
        "fonte":        "servidor",
    })


def _verificar_github() -> tuple[str, dict | str | None]:
    """Fallback: API do GitHub Releases."""
    repo = _github_repo()
    if not repo:
        return ("nao_configurado", None)

    try:
        resp = requests.get(_api_url(), timeout=_TIMEOUT,
                            headers={"Accept": "application/vnd.github+json"})
        if resp.status_code == 404:
            return ("sem_release", None)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("GitHub fallback falhou: %s", exc)
        return ("erro", str(exc))

    versao_remota = data.get("tag_name", "").lstrip("v")
    if not versao_remota:
        return ("sem_release", None)

    if _versao_para_tuple(versao_remota) <= _versao_para_tuple(VERSION):
        return ("atualizado", None)

    url_download = None
    tamanho = 0
    for asset in data.get("assets", []):
        if asset["name"].endswith(".zip"):
            url_download = asset["browser_download_url"]
            tamanho = asset.get("size", 0)
            break

    if not url_download:
        return ("sem_release", None)

    return ("disponivel", {
        "versao":       versao_remota,
        "url_download": url_download,
        "notas":        data.get("body", "")[:500],
        "tamanho":      tamanho,
        "sha256":       "",
        "fonte":        "github",
    })


def verificar_atualizacao() -> tuple[str, dict | str | None]:
    """
    Tenta o servidor self-hosted primeiro; em qualquer falha ou sem-release,
    cai para a API do GitHub. Mantém o contrato:
      ("nao_configurado", None)  — sem provedores válidos
      ("erro", msg)              — todos provedores falharam
      ("sem_release", None)      — nenhum provedor tem release publicada
      ("atualizado", None)       — versão local já é a mais recente
      ("disponivel", dict)       — nova versão disponível
    """
    status, dado = _verificar_servidor_local()
    if status == "disponivel":
        log.info("Update v%s encontrado no servidor local", dado["versao"])
        return (status, dado)
    if status == "atualizado":
        log.info("Servidor local confirma versão atual (%s).", VERSION)
        return (status, dado)

    log.info("Servidor local indisponível (%s). Tentando GitHub...", status)
    return _verificar_github()


def _lançar_bat_updater(zip_path: str, app_dir: Path, versao: str) -> bool:
    """Escreve bat no temp e o lança como processo independente para extrair após o app fechar."""
    exe      = str(Path(sys.executable))
    exe_name = Path(exe).name
    bat_path = Path(tempfile.gettempdir()) / "sparta_updater.bat"
    log_path = Path(tempfile.gettempdir()) / "sparta_updater.log"

    # Usa variáveis de bat para evitar problemas com aspas em caminhos com espaço
    conteudo = (
        "@echo off\n"
        f"set ZIP={zip_path}\n"
        f"set DST={app_dir}\n"
        f"set EXE={exe}\n"
        f"set LOG={log_path}\n"
        f"set ENV_FILE={app_dir}\\.env\n"
        f"set ENV_BAK={app_dir}\\.env.bak\n"
        "echo [%DATE% %TIME%] Updater iniciado > \"%LOG%\"\n"
        "timeout /t 4 /nobreak >nul\n"
        f"taskkill /F /IM \"{exe_name}\" /T >> \"%LOG%\" 2>&1\n"
        "timeout /t 3 /nobreak >nul\n"
        ":: Preserva .env existente (contém credenciais de câmera do cliente)\n"
        "if exist \"%ENV_FILE%\" (\n"
        "  copy /y \"%ENV_FILE%\" \"%ENV_BAK%\" >> \"%LOG%\" 2>&1\n"
        "  echo [%DATE% %TIME%] .env salvo em backup >> \"%LOG%\"\n"
        ")\n"
        "echo [%DATE% %TIME%] Extraindo zip >> \"%LOG%\"\n"
        "powershell -NoProfile -ExecutionPolicy Bypass -Command "
        "\"try { Expand-Archive -LiteralPath $env:ZIP -DestinationPath $env:DST -Force;"
        " Write-Host OK } catch { Write-Host $_.Exception.Message; exit 1 }\""
        " >> \"%LOG%\" 2>&1\n"
        "if %errorlevel% neq 0 (\n"
        "  echo [%DATE% %TIME%] ERRO na extracao - abortando >> \"%LOG%\"\n"
        "  if exist \"%ENV_BAK%\" copy /y \"%ENV_BAK%\" \"%ENV_FILE%\" >nul\n"
        "  exit /b 1\n"
        ")\n"
        "echo [%DATE% %TIME%] Extracao OK >> \"%LOG%\"\n"
        ":: Restaura .env do cliente por cima do .env padrão do zip\n"
        "if exist \"%ENV_BAK%\" (\n"
        "  copy /y \"%ENV_BAK%\" \"%ENV_FILE%\" >> \"%LOG%\" 2>&1\n"
        "  del \"%ENV_BAK%\"\n"
        "  echo [%DATE% %TIME%] .env restaurado >> \"%LOG%\"\n"
        ")\n"
        ":: Garante UPDATE_SERVER_URL no .env restaurado\n"
        "findstr /i \"UPDATE_SERVER_URL\" \"%ENV_FILE%\" >nul 2>&1\n"
        "if errorlevel 1 (\n"
        "  echo.>> \"%ENV_FILE%\"\n"
        "  echo UPDATE_SERVER_URL=https://138.186.129.103:4543/latest.json>> \"%ENV_FILE%\"\n"
        "  echo [%DATE% %TIME%] UPDATE_SERVER_URL adicionado ao .env >> \"%LOG%\"\n"
        ")\n"
        "del \"%ZIP%\"\n"
        "start \"\" \"%EXE%\"\n"
        "del \"%~f0\"\n"
    )
    try:
        bat_path.write_text(conteudo, encoding="cp1252")  # cmd.exe usa cp1252 no Windows
        subprocess.Popen(
            ["cmd", "/c", str(bat_path)],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        log.info("Atualizador lançado — app encerrará para aplicar v%s (log: %s)",
                 versao, log_path)
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
    url        = info["url_download"]
    versao     = info["versao"]
    sha_esp    = (info.get("sha256") or "").lower().strip()
    fonte      = info.get("fonte", "servidor")
    frozen     = getattr(sys, "frozen", False)
    app_dir    = Path(sys.executable).parent if frozen else Path(".")

    # Servidor self-hosted: usa cert pinning. GitHub: cadeia padrão (CA pública).
    verify_arg = _cert_path() if fonte == "servidor" else True

    log.info("Baixando atualização %s de %s (fonte=%s)", versao, url, fonte)
    try:
        sha = hashlib.sha256()
        with requests.get(url, stream=True, timeout=60, verify=verify_arg) as r:
            r.raise_for_status()
            total    = int(r.headers.get("content-length", 0)) or info.get("tamanho", 1)
            baixado  = 0
            tmp      = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
            for chunk in r.iter_content(chunk_size=65536):
                tmp.write(chunk)
                sha.update(chunk)
                baixado += len(chunk)
                if progresso_cb and total:
                    progresso_cb(min(baixado / total, 1.0))
            tmp.close()
    except Exception as exc:
        log.error("Falha no download: %s", exc)
        return False

    # Valida integridade quando o manifesto declarou SHA-256 (servidor local).
    if sha_esp:
        sha_obtido = sha.hexdigest().lower()
        if sha_obtido != sha_esp:
            log.error("SHA-256 divergente! esperado=%s obtido=%s", sha_esp, sha_obtido)
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
            return False
        log.info("SHA-256 do .zip validado (%s).", sha_obtido[:16] + "...")

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
    AMA   = "#2D7A6E"
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
             font=("Segoe UI", 9), bg=AMA, fg="#FFE0A0").pack(side="right")

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
                                   "Adicione UPDATE_SERVER_URL ao arquivo .env.", CINZA)))
            elif status == "erro":
                _q.put(("status", ("⚠️", "Não foi possível verificar atualizações.",
                                   f"Erro: {dado}", VERM)))
            elif status == "sem_release":
                _q.put(("status", ("ℹ️", "Nenhuma versão publicada.",
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
