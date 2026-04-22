import base64
import json
import logging
from datetime import datetime, timezone

import anthropic
import cv2
import httpx

from config import CLAUDE_API_KEY, CAMERA_ID, FASE_PROCESSO
from prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

log = logging.getLogger(__name__)

_client = anthropic.Anthropic(
    api_key=CLAUDE_API_KEY,
    http_client=httpx.Client(
        timeout=httpx.Timeout(60.0, connect=10.0),
    ),
)

_ANALISE_W = 640
_ANALISE_H = 360

_PROMPT_TRIAGEM = (
    "Há alguma pessoa ou ser humano visível nesta imagem de câmera de segurança? "
    "Responda APENAS com JSON válido, sem texto fora dele:\n"
    "{\"pessoa_detectada\": true ou false, \"confianca\": valor 0.0 a 1.0}"
)

# Schema mínimo obrigatório na resposta do Opus
_CAMPOS_OBRIGATORIOS = {
    "alerta": bool,
    "nivel_risco": str,
    "comportamentos_detectados": list,
    "confianca": float,
    "acao_recomendada": str,
    "objetos_detectados": list,
}
_NIVEIS_VALIDOS = {"sem_risco", "atencao", "suspeito", "critico"}

# Cache do system prompt construído (invalida quando fewshot muda)
_system_cache: str | None = None
_system_cache_ts: float = 0.0
_SYSTEM_TTL = 300.0  # recarrega fewshot a cada 5 min


def _frame_para_base64(frame, largura: int = _ANALISE_W, altura: int = _ANALISE_H) -> str:
    if frame.shape[1] != largura or frame.shape[0] != altura:
        frame = cv2.resize(frame, (largura, altura), interpolation=cv2.INTER_AREA)
    _, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return base64.standard_b64encode(buffer).decode("utf-8")


def _system_com_fewshot() -> str:
    global _system_cache, _system_cache_ts
    import time
    agora = time.monotonic()
    if _system_cache is not None and (agora - _system_cache_ts) < _SYSTEM_TTL:
        return _system_cache
    try:
        from db import buscar_exemplos_fewshot_balanceados
        exemplos = buscar_exemplos_fewshot_balanceados(limite=4)
    except Exception:
        exemplos = []

    if not exemplos:
        _system_cache = SYSTEM_PROMPT
    else:
        secao = "\n\n## Historico de calibracao (exemplos reais desta instalacao)\n"
        secao += "Use os exemplos abaixo para calibrar sua sensibilidade:\n\n"
        for i, ex in enumerate(exemplos, 1):
            label = "VERDADEIRO ALERTA" if ex["rotulo"] == "verdadeiro_positivo" else "FALSO POSITIVO (nao era furto)"
            secao += (
                f"Exemplo {i} [{label}]:\n"
                f"  Nivel classificado: {ex['nivel_risco']}\n"
                f"  Descricao: {ex['descricao']}\n\n"
            )
        _system_cache = SYSTEM_PROMPT + secao

    _system_cache_ts = agora
    return _system_cache


def _validar_resultado(resultado: dict, frame_id: str) -> dict:
    """Valida e normaliza campos do JSON retornado pela IA."""
    _DEFAULTS = {bool: False, float: 0.0, str: "", list: []}
    campos_ausentes = []

    for campo, tipo in _CAMPOS_OBRIGATORIOS.items():
        if campo not in resultado:
            campos_ausentes.append(campo)
            resultado[campo] = _DEFAULTS[tipo]

    if campos_ausentes:
        log.error(
            "[%s] Resposta IA incompleta — campos ausentes: %s. "
            "Análise registrada com valores padrão (pode ser falso negativo).",
            frame_id, campos_ausentes
        )

    nivel = resultado.get("nivel_risco", "sem_risco")
    if nivel not in _NIVEIS_VALIDOS:
        log.error("[%s] nivel_risco inválido '%s' — forçando 'sem_risco'", frame_id, nivel)
        resultado["nivel_risco"] = "sem_risco"

    conf = resultado.get("confianca", 0.0)
    resultado["confianca"] = max(0.0, min(1.0, float(conf)))

    for obj in resultado.get("objetos_detectados", []):
        bb = obj.get("bbox_norm", [])
        if len(bb) == 4:
            obj["bbox_norm"] = [max(0.0, min(1.0, float(v))) for v in bb]
        else:
            obj["bbox_norm"] = [0.0, 0.0, 1.0, 1.0]

    resultado.setdefault("frame_id", frame_id)
    resultado.setdefault("revisar_clip", False)
    resultado.setdefault("janela_revisao_segundos", 0)
    resultado.setdefault("posicao_na_cena", "")
    resultado.setdefault("timestamp_analise", datetime.now(timezone.utc).isoformat())
    return resultado


def _parse_json(texto: str) -> dict:
    texto = texto.strip()
    if texto.startswith("```"):
        linhas = texto.splitlines()
        texto = "\n".join(linhas[1:-1] if linhas[-1].strip() == "```" else linhas[1:])
    return json.loads(texto)


def triagem_haiku(frame, frame_id: str, camera_id: str = CAMERA_ID) -> tuple[bool, float]:
    """
    Triagem rápida com Haiku: há pessoa no frame?
    Retorna (pessoa_detectada: bool, confianca: float).
    Falha aberta → retorna (True, 0.5).
    """
    try:
        imagem_b64 = _frame_para_base64(frame)
        resposta = _client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=64,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": imagem_b64}},
                    {"type": "text", "text": _PROMPT_TRIAGEM},
                ],
            }],
        )
        dados = _parse_json(resposta.content[0].text)
        pessoa = bool(dados.get("pessoa_detectada", True))
        conf   = float(dados.get("confianca", 0.5))
        log.debug("[%s] Haiku triagem: pessoa=%s conf=%.2f", camera_id, pessoa, conf)
        return pessoa, conf
    except Exception as exc:
        log.debug("[%s] Haiku triagem falhou (%s) — passando para análise completa", camera_id, exc)
        return True, 0.5


def analisar_frame(
    frame,
    frame_id: str,
    fase: str = FASE_PROCESSO,
    camera_id: str = CAMERA_ID,
) -> tuple:
    """
    Análise completa com Opus + prompt caching no system prompt.
    Retorna (resultado_dict, tokens_in, tokens_out).
    """
    imagem_b64 = _frame_para_base64(frame)
    timestamp  = datetime.now(timezone.utc).isoformat()

    user_prompt = USER_PROMPT_TEMPLATE.format(
        CAMERA_ID=camera_id,
        FASE=fase,
        TIMESTAMP=timestamp,
        FRAME_ID=frame_id,
    )

    system_text = _system_com_fewshot()

    # Prompt caching: marca system prompt para cache (min 1024 tokens no Opus)
    system_blocks = [
        {
            "type": "text",
            "text": system_text,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    resposta = _client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=system_blocks,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": imagem_b64}},
                {"type": "text", "text": user_prompt},
            ],
        }],
    )

    usage      = resposta.usage
    tokens_in  = usage.input_tokens
    tokens_out = usage.output_tokens
    tokens_cache_read    = getattr(usage, "cache_read_input_tokens", 0) or 0
    tokens_cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0

    if tokens_cache_read:
        log.debug("[%s] Cache hit: %d tokens lidos do cache (economia ~60%%)", camera_id, tokens_cache_read)
    if tokens_cache_created:
        log.debug("[%s] Cache criado: %d tokens armazenados", camera_id, tokens_cache_created)

    try:
        resultado = _parse_json(resposta.content[0].text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Resposta fora do formato JSON esperado: {exc}\n"
            f"Texto recebido: {resposta.content[0].text[:300]}"
        )

    resultado = _validar_resultado(resultado, frame_id)
    return resultado, tokens_in, tokens_out
