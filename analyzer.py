import base64
import json
import logging
from datetime import datetime, timezone

import anthropic
import cv2

from config import CLAUDE_API_KEY, CAMERA_ID, FASE_PROCESSO
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

log = logging.getLogger(__name__)

_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)


def _frame_para_base64(frame) -> str:
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.standard_b64encode(buffer).decode("utf-8")


def _system_com_fewshot() -> str:
    """Monta system prompt com exemplos curados do banco, se existirem."""
    try:
        from db import buscar_exemplos_fewshot_balanceados
        exemplos = buscar_exemplos_fewshot_balanceados(limite=4)
    except Exception:
        return SYSTEM_PROMPT

    if not exemplos:
        return SYSTEM_PROMPT

    secao = "\n\n## Historico de calibracao (exemplos reais desta instalacao)\n"
    secao += "Use os exemplos abaixo para calibrar sua sensibilidade:\n\n"
    for i, ex in enumerate(exemplos, 1):
        label = "VERDADEIRO ALERTA" if ex["rotulo"] == "verdadeiro_positivo" else "FALSO POSITIVO (nao era furto)"
        secao += (
            f"Exemplo {i} [{label}]:\n"
            f"  Nivel classificado: {ex['nivel_risco']}\n"
            f"  Descricao: {ex['descricao']}\n\n"
        )
    return SYSTEM_PROMPT + secao


def analisar_frame(
    frame,
    frame_id: str,
    fase: str = FASE_PROCESSO,
    camera_id: str = CAMERA_ID,
) -> tuple:
    """
    Analisa um frame e retorna (resultado_dict, tokens_entrada, tokens_saida).
    Injeta exemplos few-shot no system prompt quando existirem feedbacks confirmados.
    """
    imagem_b64 = _frame_para_base64(frame)
    timestamp = datetime.now(timezone.utc).isoformat()

    user_prompt = USER_PROMPT_TEMPLATE.format(
        CAMERA_ID=camera_id,
        FASE=fase,
        TIMESTAMP=timestamp,
        FRAME_ID=frame_id,
    )

    system = _system_com_fewshot()

    resposta = _client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=system,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": imagem_b64,
                        },
                    },
                    {"type": "text", "text": user_prompt},
                ],
            }
        ],
    )

    tokens_in  = resposta.usage.input_tokens
    tokens_out = resposta.usage.output_tokens

    texto = resposta.content[0].text.strip()

    # Remove blocos markdown caso o modelo os inclua
    if texto.startswith("```"):
        linhas = texto.splitlines()
        texto = "\n".join(linhas[1:-1]) if linhas[-1] == "```" else "\n".join(linhas[1:])

    try:
        resultado = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Resposta fora do formato JSON esperado: {exc}\nTexto recebido: {texto[:300]}")

    return resultado, tokens_in, tokens_out
