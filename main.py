import logging
import os
import sys
from pathlib import Path

# Força ffmpeg do OpenCV a usar TCP no RTSP e decode single-thread —
# evita crashes de libavcodec (async_lock / GIL) com streams H.264/H.265.
# Deve ser definido ANTES do primeiro import de cv2.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|threads;1",
)

# Suprime crash do GC ao coletar StringVar/BooleanVar fora do loop Tkinter
try:
    import tkinter as _tk
    _orig_var_del = _tk.Variable.__del__
    def _safe_var_del(self, _f=_orig_var_del):
        try:
            _f(self)
        except RuntimeError:
            pass
    _tk.Variable.__del__ = _safe_var_del
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            (Path(sys.executable).parent if getattr(sys, "frozen", False) else Path("."))
            / "monitor.log",
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("main")

_ENV_PATH = (
    Path(sys.executable).parent / ".env"
    if getattr(sys, "frozen", False)
    else Path(".env")
)


def _env_existe() -> bool:
    if not _ENV_PATH.exists():
        return False
    return "CLAUDE_API_KEY" in _ENV_PATH.read_text(encoding="utf-8")


def _carregar_config():
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH, override=True)
    import importlib
    import config as cfg
    importlib.reload(cfg)
    return cfg


def _pedir_config() -> bool:
    from setup_config import abrir_configuracao
    salvo = []
    abrir_configuracao(ao_salvar=lambda: salvo.append(True))
    return bool(salvo)


def _garantir_instancia_unica():
    import socket
    lock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        lock.bind(("localhost", 47321))
        return lock
    except OSError:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(
            "SPARTA AGENTE IA",
            "O sistema ja esta em execucao.\nVerifique a barra de tarefas."
        )
        r.destroy()
        sys.exit(0)


def main():
    _lock = _garantir_instancia_unica()

    import auth
    auth.inicializar()

    # Garante que a chave de API existe antes de abrir o mosaico
    if not _env_existe():
        log.info("Configuracao nao encontrada - abrindo assistente.")
        if not _pedir_config():
            log.info("Configuracao cancelada. Encerrando.")
            return

    from login import abrir_login
    sessao = abrir_login()
    log.info("Login: %s (%s)", sessao["nome"], sessao["grupo"])

    cfg = _carregar_config()

    # Health monitor (heartbeat para watchdog)
    import health_monitor
    db_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(".")
    health_monitor.iniciar(hb_dir=db_dir, intervalo_segundos=30)

    # Backup automático do banco de dados
    import backup_manager
    import db as _db
    backup_manager.iniciar(
        db_path=_db.DB_PATH,
        intervalo_horas=6.0,
        max_backups=14,
    )

    # Backup avançado (painel admin) — inicia agendamento se configurado
    import backup_panel
    backup_panel.iniciar_automatico()

    import gc; gc.collect()

    log.info("Iniciando mosaico...")
    from mosaic import rodar_mosaico
    rodar_mosaico(cfg, sessao)

    health_monitor.parar()
    backup_manager.parar()
    backup_panel.parar_automatico()


if __name__ == "__main__":
    main()
