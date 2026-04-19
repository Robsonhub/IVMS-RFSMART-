import logging
import threading
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


def salvar_clip(frames: list, frame_id: str):
    if not frames:
        return
    caminho = PASTA_CLIPS / f"alerta_{frame_id}.mp4"
    h, w = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(caminho), cv2.VideoWriter_fourcc(*"mp4v"), 10, (w, h))
    for f in frames:
        writer.write(f)
    writer.release()
    log.info("Clip salvo: %s (%d frames)", caminho, len(frames))


def exibir_overlay(frame, resultado: dict):
    nivel = resultado.get("nivel_risco", "sem_risco")
    cor = _CORES.get(nivel, (255, 255, 255))
    acao = resultado.get("acao_recomendada", "")
    confianca = resultado.get("confianca", 0)

    cv2.putText(frame, f"RISCO: {nivel.upper()}  conf:{confianca:.0%}",
                (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9, cor, 2)
    cv2.putText(frame, acao[:70], (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)

    for i, comportamento in enumerate(resultado.get("comportamentos_detectados", [])[:4]):
        cv2.putText(frame, f"- {comportamento[:65]}", (20, 115 + i * 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    cv2.imshow("SPARTA AGENTE IA - Monitor Tapete de Ouro", frame)


def enviar_webhook(resultado: dict):
    if not WEBHOOK_URL:
        return

    def _post():
        try:
            requests.post(WEBHOOK_URL, json=resultado, timeout=5)
            log.info("Webhook enviado: nivel=%s", resultado.get("nivel_risco"))
        except Exception as exc:
            log.warning("Falha no webhook: %s", exc)

    threading.Thread(target=_post, daemon=True).start()
