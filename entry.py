"""
Entry point do executável empacotado (PyInstaller).

Sem argumentos → roda o watchdog, que relança o próprio .exe como filho
com --child. Se o filho crashar (bug do libavcodec/ffmpeg etc.), o
watchdog detecta via heartbeat e reinicia o processo transparentemente.

Com --child → executa o app principal.

Em desenvolvimento, basta rodar `python main.py` direto (este arquivo
é usado apenas no build PyInstaller).
"""
import sys


def _run_child():
    from main import main as _main
    _main()


def _run_watchdog():
    import watchdog as _wd
    _wd.rodar()


if __name__ == "__main__":
    if "--child" in sys.argv:
        _run_child()
    else:
        _run_watchdog()
