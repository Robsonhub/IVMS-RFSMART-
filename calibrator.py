"""
Calibrador de thresholds locais — SPARTA AGENTE IA
Lê o histórico de análises e feedbacks do banco para ajustar os limiares
do AnalisadorLocal de acordo com o comportamento real de cada câmera.
"""
import json
import logging
import sqlite3
from typing import Optional

log = logging.getLogger(__name__)

# Limites de segurança para evitar thresholds absurdos
_LIMITES = {
    "motion_atencao":         (0.01, 0.10),
    "motion_suspeito":        (0.03, 0.20),
    "motion_critico":         (0.06, 0.40),
    "tapete_motion_suspeito": (0.02, 0.15),
    "optical_flow_rapido":    (1.5,  8.0),
    "bbox_agachamento":       (0.8,  2.0),
    "frames_parado_alerta":   (60,   600),
}


def calcular_thresholds(conn: sqlite3.Connection, camera_id: str) -> Optional[dict]:
    """
    Retorna dict com thresholds calibrados para a câmera, ou None se dados
    insuficientes (< 30 análises com feedback).
    """
    try:
        return _calcular(conn, camera_id)
    except Exception as exc:
        log.warning("[calibrator] Falha ao calibrar camera=%s: %s", camera_id, exc)
        return None


def _calcular(conn: sqlite3.Connection, camera_id: str) -> Optional[dict]:
    # ── 1. Taxa de falsos positivos por câmera ─────────────────────────────────
    row = conn.execute(
        """
        SELECT
            COUNT(*)                                             AS total,
            SUM(CASE WHEN f.rotulo='falso_positivo' THEN 1 ELSE 0 END) AS fps,
            SUM(CASE WHEN f.rotulo='correto'        THEN 1 ELSE 0 END) AS vps
        FROM analises a
        JOIN feedbacks f ON f.analise_id = a.id
        WHERE a.camera_id = ?
        """,
        (camera_id,)
    ).fetchone()

    if not row or row[0] < 30:
        return None

    total, fps, vps = row[0], row[1] or 0, row[2] or 0
    if total == 0:
        return None

    taxa_fp = fps / total   # fração de falsos positivos
    taxa_vp = vps / total   # fração de verdadeiros positivos

    # ── 2. Distribuição de confiança nos alertas ───────────────────────────────
    conf_rows = conn.execute(
        """
        SELECT AVG(confianca), MIN(confianca)
        FROM analises
        WHERE camera_id=? AND alerta=1
        """,
        (camera_id,)
    ).fetchone()
    avg_conf = conf_rows[0] or 0.70
    min_conf = conf_rows[1] or 0.50

    # ── 3. Proporção de alertas por nível ─────────────────────────────────────
    niveis = {
        r[0]: r[1]
        for r in conn.execute(
            """
            SELECT nivel_risco, COUNT(*) FROM analises
            WHERE camera_id=? AND alerta=1
            GROUP BY nivel_risco
            """,
            (camera_id,)
        ).fetchall()
    }
    total_alertas = sum(niveis.values()) or 1
    pct_critico = niveis.get("critico", 0) / total_alertas
    pct_suspeito = niveis.get("suspeito", 0) / total_alertas

    # ── 4. Cálculo dos ajustes ────────────────────────────────────────────────
    # Se muitos FPs → elevar thresholds (exigir mais para disparar)
    # Se muitos VPs confirmados → baixar thresholds (mais sensível)
    fator = _fator_ajuste(taxa_fp, taxa_vp, avg_conf)

    from local_analyzer import THRESHOLDS_PADRAO as PAD
    novos = {}

    for key in ("motion_atencao", "motion_suspeito", "motion_critico",
                "tapete_motion_suspeito", "optical_flow_rapido"):
        base = PAD[key]
        ajustado = base * fator
        lo, hi = _LIMITES[key]
        novos[key] = round(max(lo, min(hi, ajustado)), 4)

    # bbox_agachamento: mais FPs → elevar (menos sensível a curvamentos)
    base_bb = PAD["bbox_agachamento"]
    novos["bbox_agachamento"] = round(
        max(_LIMITES["bbox_agachamento"][0],
            min(_LIMITES["bbox_agachamento"][1],
                base_bb * (2 - fator))),   # inverso: FP → menor razão exigida
        3
    )

    # frames_parado: se muitos falsos por imobilidade → aumentar janela
    base_fp_frames = PAD["frames_parado_alerta"]
    novos["frames_parado_alerta"] = int(
        max(_LIMITES["frames_parado_alerta"][0],
            min(_LIMITES["frames_parado_alerta"][1],
                base_fp_frames * fator))
    )

    log.info(
        "[calibrator] camera=%s total=%d fps=%d vps=%d fator=%.3f",
        camera_id, total, fps, vps, fator
    )
    return novos


def _fator_ajuste(taxa_fp: float, taxa_vp: float, avg_conf: float) -> float:
    """
    Retorna fator multiplicativo para os thresholds.
    > 1.0 → thresholds maiores (menos sensível, menos FPs)
    < 1.0 → thresholds menores (mais sensível, pega mais VPs)
    Intervalo: [0.70, 1.50]
    """
    # Base: quanto mais FP, mais elevamos os thresholds
    fator = 1.0 + (taxa_fp - 0.15) * 1.2   # neutro em 15% FP

    # Corrige pela confiança média: confiança alta = sistema certo, mantém
    if avg_conf > 0.75:
        fator *= 0.97
    elif avg_conf < 0.55:
        fator *= 1.05

    # Puxa para baixo se há muitos VPs confirmados (não queremos perder alertas reais)
    fator -= taxa_vp * 0.3

    return round(max(0.70, min(1.50, fator)), 4)


def resumo_calibracao(conn: sqlite3.Connection, camera_id: str) -> dict:
    """Retorna estatísticas legíveis sobre o estado de calibração da câmera."""
    row = conn.execute(
        """
        SELECT COUNT(*) as total,
               SUM(CASE WHEN f.rotulo='falso_positivo' THEN 1 ELSE 0 END) as fps,
               SUM(CASE WHEN f.rotulo='correto' THEN 1 ELSE 0 END) as vps
        FROM analises a LEFT JOIN feedbacks f ON f.analise_id = a.id
        WHERE a.camera_id = ?
        """,
        (camera_id,)
    ).fetchone()

    total = row[0] or 0
    fps   = row[1] or 0
    vps   = row[2] or 0
    com_fb = fps + vps

    return {
        "camera_id":             camera_id,
        "total_analises":        total,
        "com_feedback":          com_fb,
        "falsos_positivos":      fps,
        "verdadeiros_positivos": vps,
        "taxa_falsos_positivos": round(fps / com_fb, 3) if com_fb else None,
        "pronto_para_calibrar":  total >= 30,
    }
