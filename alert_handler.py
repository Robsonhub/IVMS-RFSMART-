"""Alertas, clips de vídeo e webhook — SPARTA AGENTE IA."""
import logging
import threading
import time
from pathlib import Path

import cv2
import requests

from config import PASTA_CLIPS, WEBHOOK_URL

log = logging.getLogger(__name__)

_CORES = {
    "sem_risco": (0, 200, 0),
    "atencao":   (0, 200, 255),
    "suspeito":  (0, 100, 255),
    "critico":   (0, 0, 255),
}

# ── Throttling de alertas ──────────────────────────────────────────────────────
# Impede múltiplos alertas do mesmo nível para a mesma câmera em janela de tempo
_THROTTLE_JANELA: dict[str, float] = {}   # chave: "camera_id:nivel" → timestamp
_THROTTLE_LOCK   = threading.Lock()
_THROTTLE_SEG    = {
    "atencao":  60,    # 1 minuto entre alertas de atenção
    "suspeito": 45,
    "critico":  20,    # crítico alerta mais rápido
}


def _throttle_ok(camera_id: str, nivel: str) -> bool:
    """Retorna True se o alerta pode ser disparado (não foi throttled)."""
    janela = _THROTTLE_SEG.get(nivel, 60)
    chave  = f"{camera_id}:{nivel}"
    agora  = time.monotonic()
    with _THROTTLE_LOCK:
        ultimo = _THROTTLE_JANELA.get(chave, 0.0)
        if agora - ultimo < janela:
            return False
        _THROTTLE_JANELA[chave] = agora
        return True


# ── Clips ──────────────────────────────────────────────────────────────────────

def salvar_clip(frames: list, frame_id: str):
    if not frames:
        return
    caminho = PASTA_CLIPS / f"alerta_{frame_id}.mp4"
    h, w    = frames[0].shape[:2]
    writer  = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    for f in frames:
        writer.write(f)
    writer.release()
    log.info("Clip salvo: %s (%d frames)", caminho, len(frames))


# ── Overlay ────────────────────────────────────────────────────────────────────

def exibir_overlay(frame, resultado: dict):
    nivel    = resultado.get("nivel_risco", "sem_risco")
    cor      = _CORES.get(nivel, (255, 255, 255))
    acao     = resultado.get("acao_recomendada", "")
    confianca = resultado.get("confianca", 0)

    cv2.putText(frame, f"RISCO: {nivel.upper()}  conf:{confianca:.0%}",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, cor, 2)
    cv2.putText(frame, acao[:70], (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    for i, comp in enumerate(resultado.get("comportamentos_detectados", [])[:4]):
        cv2.putText(frame, f"- {comp[:65]}", (20, 115 + i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    cv2.imshow("SPARTA AGENTE IA - Monitor Tapete de Ouro", frame)


# ── Webhook com retry ──────────────────────────────────────────────────────────

def enviar_webhook(resultado: dict, camera_id: str = ""):
    """Envia webhook com throttling e retry exponencial."""
    nivel = resultado.get("nivel_risco", "sem_risco")
    if nivel == "sem_risco":
        return
    if not WEBHOOK_URL:
        return
    if not _throttle_ok(camera_id or resultado.get("camera_id", ""), nivel):
        log.debug("Webhook throttled para %s/%s", camera_id, nivel)
        return

    def _post():
        payload   = {**resultado, "camera_id": camera_id}
        tentativas = 4
        espera     = 2.0
        for i in range(tentativas):
            try:
                r = requests.post(WEBHOOK_URL, json=payload, timeout=8)
                r.raise_for_status()
                log.info("Webhook enviado: nivel=%s camera=%s", nivel, camera_id)
                return
            except Exception as exc:
                if i < tentativas - 1:
                    log.warning("Webhook tentativa %d falhou (%s) — aguardando %.0fs",
                                i + 1, exc, espera)
                    time.sleep(espera)
                    espera *= 2
                else:
                    log.error("Webhook falhou após %d tentativas: %s", tentativas, exc)

    threading.Thread(target=_post, daemon=True).start()
