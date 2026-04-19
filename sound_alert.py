"""Alertas sonoros por nível de risco — SPARTA AGENTE IA (Windows)."""
import logging
import threading

log = logging.getLogger(__name__)

_SONS = {
    "critico":  (1000, 600),   # frequência Hz, duração ms
    "suspeito": (750, 400),
    "atencao":  (500, 200),
}

_ultimo_nivel: str = ""
_lock = threading.Lock()


def tocar(nivel: str):
    """Toca beep não-bloqueante conforme o nível de risco."""
    if nivel not in _SONS:
        return
    freq, dur = _SONS[nivel]

    def _beep():
        try:
            import winsound
            repeticoes = 3 if nivel == "critico" else 1
            for _ in range(repeticoes):
                winsound.Beep(freq, dur)
        except Exception as exc:
            log.debug("Alerta sonoro indisponível: %s", exc)

    threading.Thread(target=_beep, daemon=True).start()


def tocar_se_novo(nivel: str):
    """Toca apenas se o nível mudou (evita spam sonoro)."""
    global _ultimo_nivel
    with _lock:
        if nivel == _ultimo_nivel or nivel == "sem_risco":
            return
        _ultimo_nivel = nivel
    tocar(nivel)


def resetar():
    global _ultimo_nivel
    with _lock:
        _ultimo_nivel = ""
