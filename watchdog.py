"""
Watchdog — reinicia o SPARTA AGENTE IA se o heartbeat parar ou o
processo filho crashar (ex.: bug do libavcodec/ffmpeg em streams RTSP).

Uso em dev:        python watchdog.py
Uso empacotado:    entry.py chama rodar() quando o .exe é aberto sem
                   argumentos; watchdog relança o próprio .exe com
                   --child.
"""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

_BASE_DIR = (Path(sys.executable).parent
             if getattr(sys, "frozen", False)
             else Path(__file__).parent)

HB_FILE   = _BASE_DIR / "sparta_heartbeat.txt"
TIMEOUT   = 120   # segundos sem heartbeat → reinicia
INTERVALO = 30    # intervalo de checagem

_MAIN_PY  = Path(__file__).parent / "main.py"


def _comando_filho() -> list[str]:
    """Monta o comando para iniciar o processo filho.

    - No .exe empacotado → relança o próprio executável com --child
    - Em dev             → python main.py --child
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--child"]
    return [sys.executable, str(_MAIN_PY), "--child"]


def _iniciar_processo() -> subprocess.Popen:
    cmd = _comando_filho()
    proc = subprocess.Popen(cmd)
    log.info("[Watchdog] Filho iniciado: PID %d", proc.pid)
    # Zera o heartbeat para dar carência ao processo subir
    try:
        HB_FILE.write_text(str(time.time()))
    except Exception:
        pass
    return proc


def _heartbeat_ok() -> bool:
    if not HB_FILE.exists():
        return False
    try:
        ts = float(HB_FILE.read_text())
        return (time.time() - ts) < TIMEOUT
    except Exception:
        return False


def rodar():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] watchdog - %(message)s",
        datefmt="%H:%M:%S",
    )
    log.info("Monitorando SPARTA AGENTE IA (timeout=%ds)", TIMEOUT)

    processo = _iniciar_processo()
    carencia = time.time() + 60  # 60s de carência para o app subir

    try:
        while True:
            time.sleep(INTERVALO)

            saiu  = processo.poll() is not None
            hb_ok = _heartbeat_ok() or time.time() < carencia

            if saiu or not hb_ok:
                motivo = "processo encerrado" if saiu else "heartbeat perdido"
                log.warning("%s — reiniciando...", motivo)
                try:
                    processo.kill()
                except Exception:
                    pass
                time.sleep(3)
                processo = _iniciar_processo()
                carencia = time.time() + 60
            else:
                log.info("OK (PID %d)", processo.pid)
    except KeyboardInterrupt:
        log.info("Watchdog encerrado pelo usuário.")
        try:
            processo.terminate()
        except Exception:
            pass


if __name__ == "__main__":
    rodar()
