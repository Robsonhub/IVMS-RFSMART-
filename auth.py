"""Autenticação e gerenciamento de usuários — SPARTA AGENTE IA."""
import hashlib
import logging
import threading

import bcrypt

import db as _db

log = logging.getLogger(__name__)

_lock = threading.Lock()

_SENHA_PADRAO = "admin123"

sessao_atual: dict | None = None


# ── Hashing ────────────────────────────────────────────────────────────────────

def _hash(senha: str) -> str:
    """Gera hash bcrypt com salt aleatório."""
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verificar(senha: str, hash_armazenado: str) -> bool:
    """Verifica senha contra hash bcrypt (atual) ou SHA256 (legado)."""
    if hash_armazenado.startswith(("$2b$", "$2a$", "$2y$")):
        return bcrypt.checkpw(senha.encode("utf-8"), hash_armazenado.encode("utf-8"))
    # Legado: SHA256 sem salt
    return hashlib.sha256(senha.encode("utf-8")).hexdigest() == hash_armazenado


def _migrar_para_bcrypt(usuario_id: int, senha: str):
    """Atualiza hash SHA256 legado para bcrypt transparentemente no login."""
    novo_hash = _hash(senha)
    with _lock:
        conn = _db.get_connection()
        conn.execute("UPDATE usuarios SET senha_hash=? WHERE id=?", (novo_hash, usuario_id))
        conn.commit()
    log.info("Senha do usuário id=%d migrada de SHA256 para bcrypt", usuario_id)


# ── Inicialização ──────────────────────────────────────────────────────────────

def inicializar():
    """Garante tabelas e usuário admin padrão. Chama db.get_connection() para inicializar o banco."""
    conn = _db.get_connection()
    # Garante colunas ausentes em bancos legados
    _db._migrar_colunas_usuarios()
    with _lock:
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
        conn = _db.get_connection()
        row = conn.execute(
            "SELECT * FROM usuarios WHERE nome=? AND ativo=1", (nome,)
        ).fetchone()

    if not row:
        return None

    hash_armazenado = row["senha_hash"]
    if not _verificar(senha, hash_armazenado):
        return None

    # Migração transparente: SHA256 → bcrypt
    if not hash_armazenado.startswith(("$2b$", "$2a$", "$2y$")):
        _migrar_para_bcrypt(row["id"], senha)

    return dict(row)


def registrar_login(nome: str, sucesso: bool, usuario_id: int | None = None):
    """Registra tentativa de login na tabela de auditoria."""
    with _lock:
        conn = _db.get_connection()
        conn.execute(
            "INSERT INTO login_audit (usuario_id, nome, sucesso) VALUES (?,?,?)",
            (usuario_id, nome, 1 if sucesso else 0)
        )
        conn.commit()


def precisa_trocar_senha(usuario_id: int) -> bool:
    with _lock:
        conn = _db.get_connection()
        row = conn.execute(
            "SELECT trocar_senha FROM usuarios WHERE id=?", (usuario_id,)
        ).fetchone()
    return bool(row and row["trocar_senha"])


def marcar_senha_trocada(usuario_id: int):
    with _lock:
        conn = _db.get_connection()
        conn.execute("UPDATE usuarios SET trocar_senha=0 WHERE id=?", (usuario_id,))
        conn.commit()


# ── CRUD ───────────────────────────────────────────────────────────────────────

def buscar_por_id(usuario_id: int) -> dict | None:
    with _lock:
        conn = _db.get_connection()
        row = conn.execute("SELECT * FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    return dict(row) if row else None


def buscar_por_email(email: str) -> dict | None:
    if not email:
        return None
    with _lock:
        conn = _db.get_connection()
        row = conn.execute(
            "SELECT * FROM usuarios WHERE email=? AND ativo=1", (email.strip(),)
        ).fetchone()
    return dict(row) if row else None


def buscar_por_telefone(telefone: str) -> dict | None:
    if not telefone:
        return None
    tel = telefone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    with _lock:
        conn = _db.get_connection()
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
        conn = _db.get_connection()
        rows = conn.execute(
            "SELECT id, nome, grupo, ativo, email, telefone, created_at FROM usuarios ORDER BY nome"
        ).fetchall()
    return [dict(r) for r in rows]


def criar_usuario(nome: str, senha: str, grupo: str) -> int:
    with _lock:
        conn = _db.get_connection()
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
        conn = _db.get_connection()
        conn.execute(f"UPDATE usuarios SET {', '.join(campos)} WHERE id=?", params)
        conn.commit()


def alterar_senha(usuario_id: int, nova_senha: str):
    with _lock:
        conn = _db.get_connection()
        conn.execute(
            "UPDATE usuarios SET senha_hash=?, trocar_senha=0 WHERE id=?",
            (_hash(nova_senha), usuario_id),
        )
        conn.commit()


def remover_usuario(usuario_id: int):
    with _lock:
        conn = _db.get_connection()
        conn.execute("DELETE FROM usuarios WHERE id=?", (usuario_id,))
        conn.commit()


def alterar_grupo(usuario_id: int, grupo: str):
    with _lock:
        conn = _db.get_connection()
        conn.execute("UPDATE usuarios SET grupo=? WHERE id=?", (grupo, usuario_id))
        conn.commit()


def eh_admin(sessao: dict | None) -> bool:
    return bool(sessao and sessao.get("grupo") == "administrador")


# ── Auditoria ──────────────────────────────────────────────────────────────────

def buscar_auditoria(limite: int = 100) -> list:
    with _lock:
        conn = _db.get_connection()
        rows = conn.execute(
            """SELECT la.*, u.grupo FROM login_audit la
               LEFT JOIN usuarios u ON u.id = la.usuario_id
               ORDER BY la.created_at DESC LIMIT ?""",
            (limite,)
        ).fetchall()
    return [dict(r) for r in rows]
