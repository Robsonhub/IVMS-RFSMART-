"""Autenticação e gerenciamento de usuários — SPARTA AGENTE IA."""
import hashlib
import logging
import sqlite3
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

_DB_DIR  = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(".")
_DB_PATH = _DB_DIR / "sparta_analytics.db"

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()

_SENHA_PADRAO = "admin123"

_DDL = """
CREATE TABLE IF NOT EXISTS usuarios (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nome            TEXT    NOT NULL UNIQUE,
    senha_hash      TEXT    NOT NULL,
    grupo           TEXT    NOT NULL DEFAULT 'usuario',
    ativo           INTEGER NOT NULL DEFAULT 1,
    trocar_senha    INTEGER NOT NULL DEFAULT 0,
    email           TEXT,
    telefone        TEXT,
    created_at      TEXT    DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS login_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id  INTEGER,
    nome        TEXT NOT NULL,
    sucesso     INTEGER NOT NULL,
    ip          TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_audit_usuario ON login_audit(usuario_id);
CREATE INDEX IF NOT EXISTS idx_audit_data    ON login_audit(created_at);
"""

sessao_atual: dict | None = None


def _hash(senha: str) -> str:
    return hashlib.sha256(senha.encode("utf-8")).hexdigest()


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
    return _conn


def inicializar():
    with _lock:
        conn = _get_conn()
        conn.executescript(_DDL)
        # Migração segura para bancos existentes
        for col_def in [
            ("email",       "TEXT"),
            ("telefone",    "TEXT"),
            ("trocar_senha","INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE usuarios ADD COLUMN {col_def[0]} {col_def[1]}")
                conn.commit()
            except sqlite3.OperationalError:
                pass
        total = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
        if total == 0:
            conn.execute(
                "INSERT INTO usuarios (nome, senha_hash, grupo, trocar_senha) VALUES (?,?,?,?)",
                ("admin", _hash(_SENHA_PADRAO), "administrador", 1),
            )
            conn.commit()
            log.info("Usuário padrão criado: admin / admin123 (troca obrigatória)")


# ── Autenticação ───────────────────────────────────────────────────────────────

def autenticar(nome: str, senha: str) -> dict | None:
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM usuarios WHERE nome=? AND senha_hash=? AND ativo=1",
            (nome, _hash(senha)),
        ).fetchone()
    return dict(row) if row else None


def registrar_login(nome: str, sucesso: bool, usuario_id: int | None = None):
    """Registra tentativa de login na tabela de auditoria."""
    with _lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO login_audit (usuario_id, nome, sucesso) VALUES (?,?,?)",
            (usuario_id, nome, 1 if sucesso else 0)
        )
        conn.commit()


def precisa_trocar_senha(usuario_id: int) -> bool:
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT trocar_senha FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()
    return bool(row and row["trocar_senha"])


def marcar_senha_trocada(usuario_id: int):
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE usuarios SET trocar_senha=0 WHERE id=?", (usuario_id,))
        conn.commit()


# ── CRUD ───────────────────────────────────────────────────────────────────────

def buscar_por_id(usuario_id: int) -> dict | None:
    with _lock:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    return dict(row) if row else None


def buscar_por_email(email: str) -> dict | None:
    if not email:
        return None
    with _lock:
        conn = _get_conn()
        row = conn.execute(
            "SELECT * FROM usuarios WHERE email=? AND ativo=1", (email.strip(),)
        ).fetchone()
    return dict(row) if row else None


def buscar_por_telefone(telefone: str) -> dict | None:
    if not telefone:
        return None
    tel = telefone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM usuarios WHERE telefone IS NOT NULL AND ativo=1"
        ).fetchall()
    for row in rows:
        t = (row["telefone"] or "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
        if t == tel:
            return dict(row)
    return None


def listar_usuarios() -> list:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT id, nome, grupo, ativo, email, telefone, created_at FROM usuarios ORDER BY nome"
        ).fetchall()
    return [dict(r) for r in rows]


def criar_usuario(nome: str, senha: str, grupo: str) -> int:
    with _lock:
        conn = _get_conn()
        cur = conn.execute(
            "INSERT INTO usuarios (nome, senha_hash, grupo) VALUES (?,?,?)",
            (nome, _hash(senha), grupo),
        )
        conn.commit()
        return cur.lastrowid


def atualizar_perfil(usuario_id: int, nome: str = None,
                     email: str = None, telefone: str = None):
    campos, params = [], []
    if nome is not None:
        campos.append("nome=?"); params.append(nome.strip())
    if email is not None:
        campos.append("email=?"); params.append(email.strip() or None)
    if telefone is not None:
        campos.append("telefone=?"); params.append(telefone.strip() or None)
    if not campos:
        return
    params.append(usuario_id)
    with _lock:
        conn = _get_conn()
        conn.execute(f"UPDATE usuarios SET {', '.join(campos)} WHERE id=?", params)
        conn.commit()


def alterar_senha(usuario_id: int, nova_senha: str):
    with _lock:
        conn = _get_conn()
        conn.execute(
            "UPDATE usuarios SET senha_hash=?, trocar_senha=0 WHERE id=?",
            (_hash(nova_senha), usuario_id),
        )
        conn.commit()


def remover_usuario(usuario_id: int):
    with _lock:
        conn = _get_conn()
        conn.execute("DELETE FROM usuarios WHERE id=?", (usuario_id,))
        conn.commit()


def alterar_grupo(usuario_id: int, grupo: str):
    with _lock:
        conn = _get_conn()
        conn.execute("UPDATE usuarios SET grupo=? WHERE id=?", (grupo, usuario_id))
        conn.commit()


def eh_admin(sessao: dict | None) -> bool:
    return bool(sessao and sessao.get("grupo") == "administrador")


# ── Auditoria ──────────────────────────────────────────────────────────────────

def buscar_auditoria(limite: int = 100) -> list:
    with _lock:
        conn = _get_conn()
        rows = conn.execute(
            """SELECT la.*, u.grupo FROM login_audit la
               LEFT JOIN usuarios u ON u.id = la.usuario_id
               ORDER BY la.created_at DESC LIMIT ?""",
            (limite,)
        ).fetchall()
    return [dict(r) for r in rows]
