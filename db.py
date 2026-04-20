"""
Módulo SQLite — SPARTA AGENTE IA
Persistência de analytics de vigilância, feedbacks e exemplos few-shot.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

import sys
_DB_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(".")
DB_PATH = _DB_DIR / "sparta_analytics.db"

_conn: Optional[sqlite3.Connection] = None
_lock = threading.Lock()

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS analises (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    frame_id                TEXT NOT NULL,
    camera_id               TEXT NOT NULL,
    timestamp_analise       TEXT NOT NULL,
    alerta                  INTEGER NOT NULL,
    nivel_risco             TEXT NOT NULL,
    confianca               REAL NOT NULL,
    comportamentos          TEXT NOT NULL,
    acao_recomendada        TEXT,
    revisar_clip            INTEGER,
    janela_revisao_segundos INTEGER,
    tokens_entrada          INTEGER,
    tokens_saida            INTEGER,
    clip_path               TEXT,
    fase_processo           TEXT,
    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_analises_camera    ON analises(camera_id);
CREATE INDEX IF NOT EXISTS idx_analises_nivel     ON analises(nivel_risco);
CREATE INDEX IF NOT EXISTS idx_analises_timestamp ON analises(timestamp_analise);
CREATE INDEX IF NOT EXISTS idx_analises_alerta    ON analises(alerta);

CREATE TABLE IF NOT EXISTS feedbacks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analise_id      INTEGER NOT NULL REFERENCES analises(id) ON DELETE CASCADE,
    rotulo          TEXT NOT NULL,
    observacao      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_feedbacks_analise ON feedbacks(analise_id);

CREATE TABLE IF NOT EXISTS perguntas_ia (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analise_id      INTEGER NOT NULL REFERENCES analises(id) ON DELETE CASCADE,
    pergunta        TEXT NOT NULL,
    resposta        TEXT,
    opcoes          TEXT,
    respondido_em   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_perguntas_pendente ON perguntas_ia(resposta);

CREATE TABLE IF NOT EXISTS exemplos_fewshot (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    analise_id      INTEGER NOT NULL REFERENCES analises(id),
    nivel_risco     TEXT NOT NULL,
    comportamentos  TEXT NOT NULL,
    rotulo          TEXT NOT NULL,
    descricao       TEXT,
    peso            REAL DEFAULT 1.0,
    ativo           INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_fewshot_nivel ON exemplos_fewshot(nivel_risco);
CREATE INDEX IF NOT EXISTS idx_fewshot_ativo ON exemplos_fewshot(ativo);
"""


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.executescript(_DDL)
        _conn.commit()
        log.info("Banco de dados iniciado: %s", DB_PATH)
    return _conn


# ── Escrita ────────────────────────────────────────────────────────────────────

def salvar_analise(
    resultado: dict,
    frame_id: str,
    camera_id: str,
    fase: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    clip_path: str = None,
) -> int:
    sql = """
        INSERT INTO analises (
            frame_id, camera_id, timestamp_analise, alerta, nivel_risco,
            confianca, comportamentos, acao_recomendada, revisar_clip,
            janela_revisao_segundos, tokens_entrada, tokens_saida,
            clip_path, fase_processo
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    params = (
        frame_id,
        camera_id,
        resultado.get("timestamp_analise", datetime.now(timezone.utc).isoformat()),
        1 if resultado.get("alerta") else 0,
        resultado.get("nivel_risco", "sem_risco"),
        float(resultado.get("confianca", 0.0)),
        json.dumps(resultado.get("comportamentos_detectados", []), ensure_ascii=False),
        resultado.get("acao_recomendada"),
        1 if resultado.get("revisar_clip") else 0,
        resultado.get("janela_revisao_segundos", 0),
        tokens_in,
        tokens_out,
        clip_path,
        fase,
    )
    with _lock:
        conn = get_connection()
        cur = conn.execute(sql, params)
        conn.commit()
        analise_id = cur.lastrowid

    confianca = float(resultado.get("confianca", 1.0))
    nivel = resultado.get("nivel_risco", "sem_risco")
    if confianca < 0.6 and nivel in ("atencao", "suspeito", "critico"):
        _criar_pergunta_automatica(analise_id, resultado)

    return analise_id


def salvar_feedback(analise_id: int, rotulo: str, observacao: str = "") -> int:
    sql = "INSERT INTO feedbacks (analise_id, rotulo, observacao) VALUES (?,?,?)"
    with _lock:
        conn = get_connection()
        cur = conn.execute(sql, (analise_id, rotulo, observacao))
        conn.commit()
        fid = cur.lastrowid

    if rotulo in ("correto", "falso_positivo"):
        _promover_para_fewshot(analise_id, rotulo)

    return fid


def _promover_para_fewshot(analise_id: int, rotulo: str):
    conn = get_connection()
    row = conn.execute(
        "SELECT nivel_risco, comportamentos, acao_recomendada FROM analises WHERE id=?",
        (analise_id,)
    ).fetchone()
    if not row:
        return

    # Busca observação do feedback para enriquecer o exemplo
    fb_row = conn.execute(
        "SELECT observacao FROM feedbacks WHERE analise_id=? ORDER BY created_at DESC LIMIT 1",
        (analise_id,)
    ).fetchone()
    obs = (fb_row["observacao"] or "").strip() if fb_row else ""

    label = "verdadeiro_positivo" if rotulo == "correto" else "falso_positivo"
    comps = row["comportamentos"]
    descricao = (
        f"Nivel: {row['nivel_risco']}. "
        f"Comportamentos: {comps}. "
        f"Acao: {row['acao_recomendada'] or 'N/A'}"
    )
    if obs:
        descricao += f". Contexto real (operador): {obs[:400]}"

    with _lock:
        existente = conn.execute(
            "SELECT id FROM exemplos_fewshot WHERE analise_id=?", (analise_id,)
        ).fetchone()

        if existente:
            conn.execute(
                "UPDATE exemplos_fewshot SET peso=peso+0.5, rotulo=? WHERE id=?",
                (label, existente["id"])
            )
        else:
            conn.execute(
                """INSERT INTO exemplos_fewshot
                   (analise_id, nivel_risco, comportamentos, rotulo, descricao)
                   VALUES (?,?,?,?,?)""",
                (analise_id, row["nivel_risco"], comps, label, descricao)
            )
        conn.commit()


def _criar_pergunta_automatica(analise_id: int, resultado: dict):
    nivel = resultado.get("nivel_risco", "atencao")
    comps = resultado.get("comportamentos_detectados", [])
    desc = "; ".join(comps[:2]) if comps else "comportamento indefinido"

    templates = {
        "atencao": (
            f"Detectado '{desc}' com baixa confianca. "
            "O operador estava trabalhando normalmente ou houve desvio?",
            ["Trabalhando normalmente (falso positivo)", "Comportamento suspeito (confirmar)"]
        ),
        "suspeito": (
            f"Comportamento suspeito detectado: '{desc}'. "
            "O que o operador estava fazendo neste momento?",
            ["Ajustando EPI (falso positivo)", "Manuseio normal do tapete (falso positivo)",
             "Comportamento de furto (confirmar)"]
        ),
        "critico": (
            f"ALERTA CRITICO gerado para: '{desc}'. "
            "Confirme: o operador estava realizando furto?",
            ["Sim, furto confirmado", "Nao, falso alarme"]
        ),
    }

    pergunta, opcoes = templates.get(nivel, templates["atencao"])
    with _lock:
        conn = get_connection()
        conn.execute(
            "INSERT INTO perguntas_ia (analise_id, pergunta, opcoes) VALUES (?,?,?)",
            (analise_id, pergunta, json.dumps(opcoes, ensure_ascii=False))
        )
        conn.commit()


def deletar_clip_analise(analise_id: int):
    """Remove o arquivo .mp4 do disco e zera clip_path no banco."""
    conn = get_connection()
    row = conn.execute(
        "SELECT clip_path FROM analises WHERE id=?", (analise_id,)
    ).fetchone()
    if row and row["clip_path"]:
        try:
            Path(row["clip_path"]).unlink(missing_ok=True)
        except Exception as exc:
            log.warning("Erro ao deletar clip %s: %s", row["clip_path"], exc)
    with _lock:
        conn.execute(
            "UPDATE analises SET clip_path=NULL WHERE id=?", (analise_id,)
        )
        conn.commit()


def responder_pergunta(pergunta_id: int, resposta: str):
    with _lock:
        conn = get_connection()
        conn.execute(
            "UPDATE perguntas_ia SET resposta=?, respondido_em=datetime('now') WHERE id=?",
            (resposta, pergunta_id)
        )
        conn.commit()


# ── Leitura ────────────────────────────────────────────────────────────────────

def buscar_analises(
    nivel_risco: str = None,
    camera_id: str = None,
    apenas_alertas: bool = False,
    limite: int = 200,
) -> list:
    conn = get_connection()
    where, params = [], []

    if nivel_risco and nivel_risco != "todos":
        where.append("nivel_risco = ?")
        params.append(nivel_risco)
    if camera_id and camera_id != "todas":
        where.append("camera_id = ?")
        params.append(camera_id)
    if apenas_alertas:
        where.append("alerta = 1")

    sql = "SELECT * FROM analises"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY timestamp_analise DESC LIMIT ?"
    params.append(limite)

    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def buscar_perguntas_pendentes() -> list:
    conn = get_connection()
    sql = """
        SELECT p.*, a.nivel_risco, a.camera_id, a.timestamp_analise, a.confianca
        FROM perguntas_ia p
        JOIN analises a ON a.id = p.analise_id
        WHERE p.resposta IS NULL
        ORDER BY p.created_at DESC
    """
    return [dict(r) for r in conn.execute(sql).fetchall()]


def buscar_exemplos_fewshot_balanceados(limite: int = 4) -> list:
    conn = get_connection()
    meio = limite // 2

    fps = conn.execute(
        """SELECT * FROM exemplos_fewshot WHERE ativo=1 AND rotulo='falso_positivo'
           ORDER BY peso DESC, created_at DESC LIMIT ?""",
        (meio,)
    ).fetchall()

    vps = conn.execute(
        """SELECT * FROM exemplos_fewshot WHERE ativo=1 AND rotulo='verdadeiro_positivo'
           ORDER BY peso DESC, created_at DESC LIMIT ?""",
        (limite - meio,)
    ).fetchall()

    return [dict(r) for r in list(fps) + list(vps)]


def buscar_analises_filtradas(
    data_inicio: str | None = None,
    data_fim: str | None = None,
    camera_id: str | None = None,
    nivel_risco: str | None = None,
    apenas_alertas: bool = False,
    limite: int = 5000,
) -> list:
    """Busca análises com filtros opcionais de período, câmera e nível."""
    conn = get_connection()
    where, params = [], []

    if data_inicio:
        where.append("timestamp_analise >= ?")
        params.append(data_inicio)
    if data_fim:
        where.append("timestamp_analise <= ?")
        params.append(data_fim + "T23:59:59" if "T" not in data_fim else data_fim)
    if camera_id and camera_id != "todas":
        where.append("camera_id = ?")
        params.append(camera_id)
    if nivel_risco and nivel_risco != "todos":
        where.append("nivel_risco = ?")
        params.append(nivel_risco)
    if apenas_alertas:
        where.append("alerta = 1")

    sql = "SELECT * FROM analises"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY timestamp_analise DESC LIMIT ?"
    params.append(limite)
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def estatisticas_tokens(dias: int = 30) -> dict:
    """Retorna uso de tokens agrupado por dia nos últimos N dias."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT date(timestamp_analise) AS dia,
                  SUM(tokens_entrada) AS tok_in,
                  SUM(tokens_saida)   AS tok_out,
                  COUNT(*)            AS analises
           FROM analises
           WHERE timestamp_analise >= date('now', ?)
           GROUP BY dia ORDER BY dia""",
        (f"-{dias} days",)
    ).fetchall()
    return [dict(r) for r in rows]


def tendencias(dias: int = 7) -> dict:
    """Retorna contagem de alertas por nível e por câmera nos últimos N dias."""
    conn = get_connection()
    por_nivel = conn.execute(
        """SELECT nivel_risco, COUNT(*) AS total
           FROM analises
           WHERE timestamp_analise >= date('now', ?) AND alerta=1
           GROUP BY nivel_risco""",
        (f"-{dias} days",)
    ).fetchall()
    por_camera = conn.execute(
        """SELECT camera_id, COUNT(*) AS alertas
           FROM analises
           WHERE timestamp_analise >= date('now', ?) AND alerta=1
           GROUP BY camera_id ORDER BY alertas DESC""",
        (f"-{dias} days",)
    ).fetchall()
    return {
        "por_nivel":  [dict(r) for r in por_nivel],
        "por_camera": [dict(r) for r in por_camera],
        "dias":       dias,
    }


def buscar_cameras_distintas() -> list:
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT camera_id FROM analises ORDER BY camera_id"
    ).fetchall()
    return [r["camera_id"] for r in rows]


def estatisticas() -> dict:
    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) FROM analises").fetchone()[0]
    alertas = conn.execute("SELECT COUNT(*) FROM analises WHERE alerta=1").fetchone()[0]
    fps = conn.execute(
        "SELECT COUNT(*) FROM feedbacks WHERE rotulo='falso_positivo'"
    ).fetchone()[0]
    corretos = conn.execute(
        "SELECT COUNT(*) FROM feedbacks WHERE rotulo='correto'"
    ).fetchone()[0]
    pendentes = conn.execute(
        "SELECT COUNT(*) FROM perguntas_ia WHERE resposta IS NULL"
    ).fetchone()[0]
    exemplos = conn.execute(
        "SELECT COUNT(*) FROM exemplos_fewshot WHERE ativo=1"
    ).fetchone()[0]

    com_fb = fps + corretos
    taxa = round(fps / com_fb, 3) if com_fb else None

    return {
        "total_analises":       total,
        "total_alertas":        alertas,
        "falsos_positivos":     fps,
        "corretos":             corretos,
        "com_feedback":         com_fb,
        "taxa_falsos_positivos": taxa,
        "perguntas_pendentes":  pendentes,
        "exemplos_fewshot":     exemplos,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    conn = get_connection()
    print("Banco criado com sucesso:", DB_PATH)
    print("Tabelas:", [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()])
