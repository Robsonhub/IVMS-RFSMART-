"""Monitor de saúde do processo — escreve heartbeat periódico."""
import logging
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_stop   = threading.Event()
_thread: threading.Thread | None = None
_hb_path: Path | None = None


def _loop(hb_path: Path, intervalo: int):
    while not _stop.wait(intervalo):
        try:
            hb_path.write_text(str(time.time()), encoding="utf-8")
        except Exception:
            pass


def iniciar(hb_dir: Path | None = None, intervalo_segundos: int = 30):
    global _thread, _hb_path
    if hb_dir is None:
        hb_dir = Path(".")
    hb_dir.mkdir(parents=True, exist_ok=True)
    _hb_path = hb_dir / "sparta_heartbeat.txt"

    # Escreve imediatamente
    try:
        _hb_path.write_text(str(time.time()), encoding="utf-8")
    except Exception:
        pass

    _stop.clear()
    _thread = threading.Thread(
        target=_loop,
        args=(_hb_path, intervalo_segundos),
        daemon=True, name="HealthMonitor"
    )
    _thread.start()
    log.info("Health monitor iniciado (heartbeat a cada %ds)", intervalo_segundos)


def parar():
    _stop.set()
    if _hb_path and _hb_path.exists():
        try:
            _hb_path.unlink()
        except Exception:
            pass


def status() -> dict:
    if _hb_path is None or not _hb_path.exists():
        return {"saudavel": False, "delta": None}
    try:
        ts    = float(_hb_path.read_text(encoding="utf-8"))
        delta = time.time() - ts
        return {"saudavel": delta < 120, "delta": round(delta, 1)}
    except Exception:
        return {"saudavel": False, "delta": None}
