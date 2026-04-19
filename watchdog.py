"""
Watchdog externo — reinicia o SPARTA AGENTE IA se o heartbeat parar.
Execute separadamente: python watchdog.py
"""
import subprocess
import sys
import time
from pathlib import Path

HB_FILE   = Path(__file__).parent / "sparta_heartbeat.txt"
TIMEOUT   = 120   # segundos sem heartbeat → reinicia
INTERVALO = 30    # intervalo de checagem
MAIN      = Path(__file__).parent / "main.py"

processo = None


def iniciar_processo():
    global processo
    processo = subprocess.Popen([sys.executable, str(MAIN)])
    print(f"[Watchdog] Iniciado: PID {processo.pid}")


def checar():
    if not HB_FILE.exists():
        return False
    try:
        ts = float(HB_FILE.read_text())
        return (time.time() - ts) < TIMEOUT
    except Exception:
        return False


if __name__ == "__main__":
    print("[Watchdog] Monitorando SPARTA AGENTE IA...")
    iniciar_processo()

    while True:
        time.sleep(INTERVALO)

        # Verifica se processo ainda existe
        saiu = processo.poll() is not None
        hb_ok = checar()

        if saiu or not hb_ok:
            motivo = "processo encerrado" if saiu else "heartbeat perdido"
            print(f"[Watchdog] {motivo} — reiniciando...")
            try:
                processo.kill()
            except Exception:
                pass
            time.sleep(3)
            iniciar_processo()
        else:
            print(f"[Watchdog] OK (PID {processo.pid})")
