"""Backup automático do banco de dados SQLite — SPARTA AGENTE IA."""
import logging
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

_stop = threading.Event()
_thread: threading.Thread | None = None


def _fazer_backup(db_path: Path, backup_dir: Path, max_backups: int) -> Path | None:
    if not db_path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"sparta_backup_{ts}.db"

    # Usa sqlite3.connect + backup() para garantir consistência mesmo com WAL
    src  = sqlite3.connect(str(db_path))
    dst  = sqlite3.connect(str(dest))
    src.backup(dst)
    src.close()
    dst.close()

    log.info("Backup criado: %s", dest.name)

    # Remove backups excedentes (mais antigos primeiro)
    backups = sorted(backup_dir.glob("sparta_backup_*.db"))
    for old in backups[:-max_backups]:
        old.unlink()
        log.debug("Backup antigo removido: %s", old.name)

    return dest


def _loop(db_path: Path, backup_dir: Path, intervalo_s: int, max_backups: int):
    while not _stop.wait(intervalo_s):
        try:
            _fazer_backup(db_path, backup_dir, max_backups)
        except Exception as exc:
            log.error("Falha no backup automático: %s", exc)


def iniciar(db_path: Path, backup_dir: Path | None = None,
            intervalo_horas: float = 6.0, max_backups: int = 14):
    global _thread
    if backup_dir is None:
        backup_dir = db_path.parent / "backups"

    # Backup imediato na inicialização
    try:
        _fazer_backup(db_path, backup_dir, max_backups)
    except Exception as exc:
        log.warning("Backup inicial falhou: %s", exc)

    _stop.clear()
    _thread = threading.Thread(
        target=_loop,
        args=(db_path, backup_dir, int(intervalo_horas * 3600), max_backups),
        daemon=True, name="BackupManager"
    )
    _thread.start()
    log.info("Backup automático iniciado (a cada %.0fh, máx %d arquivos)", intervalo_horas, max_backups)


def parar():
    _stop.set()


def backup_manual(db_path: Path, backup_dir: Path | None = None, max_backups: int = 14) -> Path | None:
    if backup_dir is None:
        backup_dir = db_path.parent / "backups"
    return _fazer_backup(db_path, backup_dir, max_backups)
