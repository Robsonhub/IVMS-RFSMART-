"""
Sincronização de aprendizado da IA — SPARTA AGENTE IA

Exporta exemplos_fewshot (o conhecimento curado pelos operadores) para um ZIP
standalone, faz upload ao servidor local via SCP, e permite que qualquer
máquina baixe e importe o conhecimento via HTTPS com certificate pinning.
"""
import hashlib
import json
import logging
import os
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

# ── Caminhos base ─────────────────────────────────────────────────────────────
_BASE = (Path(sys.executable).parent if getattr(sys, "frozen", False)
         else Path(__file__).parent)
_ENV_PATH   = _BASE / ".env"
_ASSETS_DIR = (_BASE / "assets"
               if getattr(sys, "frozen", False)
               else Path(__file__).parent / "assets")

# ── Servidor ──────────────────────────────────────────────────────────────────
_URL_DEFAULT = "https://138.186.129.103:4543"
_KNOWLEDGE_ENDPOINT = "/knowledge/knowledge.zip"
_META_ENDPOINT      = "/knowledge/knowledge.json"

# SSH padrão (upload) — lê do .env.publish ou fallback
_SSH_KEY_DEFAULT  = "~/.ssh/sparta_vm"
_SSH_HOST_DEFAULT = "138.186.129.103"
_SSH_PORT_DEFAULT = "4522"
_SSH_USER_DEFAULT = "root"
_REMOTE_DIR       = "/var/www/sparta-updates/knowledge"


def _lenv(chave: str, padrao: str = "") -> str:
    if _ENV_PATH.exists():
        for linha in _ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.startswith("#"):
                k, _, v = linha.partition("=")
                if k.strip() == chave:
                    return v.strip()
    return os.getenv(chave, padrao)


def _cert_path() -> str:
    p = _ASSETS_DIR / "update_server.crt"
    return str(p) if p.exists() else True  # type: ignore[return-value]


def _base_url() -> str:
    url = _lenv("UPDATE_SERVER_URL", "")
    if url:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    return _URL_DEFAULT


# ── SSH helpers ───────────────────────────────────────────────────────────────
def _publish_env() -> dict:
    """Lê scripts/.env.publish se disponível, senão usa defaults."""
    env_pub = Path(__file__).parent / "scripts" / ".env.publish"
    dados: dict[str, str] = {}
    if env_pub.exists():
        for linha in env_pub.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if "=" in linha and not linha.startswith("#"):
                k, v = linha.split("=", 1)
                dados[k.strip()] = v.strip().strip('"').strip("'")
    return dados


def _ssh_cmd(env: dict) -> list[str]:
    args = []
    key = env.get("VM_SSH_KEY", _SSH_KEY_DEFAULT).strip()
    if key:
        args += ["-i", os.path.expanduser(key)]
    args += ["-o", "StrictHostKeyChecking=accept-new"]
    return args


# ── Hash de conteúdo ──────────────────────────────────────────────────────────
def _content_hash(nivel_risco: str, comportamentos: str, rotulo: str) -> str:
    raw = f"{nivel_risco}|{comportamentos}|{rotulo}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Export ────────────────────────────────────────────────────────────────────
def export_knowledge(db_path: Path) -> Path:
    """
    Extrai exemplos_fewshot ativos + contexto da analise associada.
    Retorna caminho do ZIP gerado em tempdir.
    """
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT
            e.id,
            e.nivel_risco,
            e.comportamentos,
            e.rotulo,
            e.descricao,
            e.peso,
            e.created_at,
            a.camera_id,
            a.acao_recomendada
        FROM exemplos_fewshot e
        JOIN analises a ON a.id = e.analise_id
        WHERE e.ativo = 1
        ORDER BY e.peso DESC, e.created_at DESC
    """).fetchall()
    con.close()

    machine_id = _lenv("CAMERA_ID", "desconhecido")
    exemplos = []
    for r in rows:
        exemplos.append({
            "hash":            _content_hash(r["nivel_risco"], r["comportamentos"], r["rotulo"]),
            "nivel_risco":     r["nivel_risco"],
            "comportamentos":  r["comportamentos"],
            "rotulo":          r["rotulo"],
            "descricao":       r["descricao"] or "",
            "peso":            r["peso"],
            "acao_recomendada": r["acao_recomendada"] or "",
            "camera_origem":   r["camera_id"] or machine_id,
            "created_at":      r["created_at"] or "",
        })

    meta = {
        "version":      "1.0",
        "exported_at":  datetime.now().isoformat(timespec="seconds"),
        "machine_id":   machine_id,
        "total":        len(exemplos),
        "examples":     exemplos,
    }

    tmp = Path(tempfile.mkdtemp())
    zip_path = tmp / "knowledge.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("knowledge.json", json.dumps(meta, ensure_ascii=False, indent=2))

    log.info("Knowledge exportado: %d exemplos → %s", len(exemplos), zip_path)
    return zip_path


# ── Upload ────────────────────────────────────────────────────────────────────
def upload_to_server(zip_path: Path, on_progress=None) -> None:
    """
    Envia knowledge.zip para o servidor via SCP.
    Requer chave SSH (normalmente só na máquina admin).
    Levanta RuntimeError se falhar.
    """
    env = _publish_env()
    host = env.get("VM_HOST", _SSH_HOST_DEFAULT)
    user = env.get("VM_USER", _SSH_USER_DEFAULT)
    port = env.get("VM_SSH_PORT", _SSH_PORT_DEFAULT)
    ssh  = _ssh_cmd(env)

    if on_progress:
        on_progress("Criando diretório no servidor...")

    subprocess.run(
        ["ssh", "-p", str(port), *ssh, f"{user}@{host}",
         f"mkdir -p {_REMOTE_DIR}"],
        check=True, capture_output=True,
    )

    if on_progress:
        on_progress("Enviando knowledge.zip...")

    tmp_remote = "/tmp/sparta_knowledge.zip"
    subprocess.run(
        ["scp", "-P", str(port), *ssh, str(zip_path),
         f"{user}@{host}:{tmp_remote}"],
        check=True,
    )

    if on_progress:
        on_progress("Publicando no servidor...")

    # Gera metadata
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    meta_json = json.dumps({
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "size":       zip_path.stat().st_size,
        "sha256":     sha,
    })

    cmd = (
        f"mv {tmp_remote} {_REMOTE_DIR}/knowledge.zip && "
        f"echo '{meta_json}' > {_REMOTE_DIR}/knowledge.json && "
        f"chmod 644 {_REMOTE_DIR}/knowledge.zip {_REMOTE_DIR}/knowledge.json"
    )
    subprocess.run(
        ["ssh", "-p", str(port), *ssh, f"{user}@{host}", cmd],
        check=True, capture_output=True,
    )

    log.info("Knowledge publicado no servidor: %d bytes", zip_path.stat().st_size)


# ── Download ──────────────────────────────────────────────────────────────────
def download_from_server() -> tuple[Path, dict]:
    """
    Baixa knowledge.zip do servidor via HTTPS com cert pinning.
    Retorna (caminho_zip, metadata).
    """
    import requests

    base = _base_url()
    cert = _cert_path()

    # Lê metadata primeiro
    try:
        r = requests.get(f"{base}{_META_ENDPOINT}", verify=cert, timeout=15)
        r.raise_for_status()
        meta = r.json()
    except Exception as exc:
        raise RuntimeError(f"Erro ao ler metadados do servidor: {exc}") from exc

    # Baixa o ZIP
    try:
        r = requests.get(f"{base}{_KNOWLEDGE_ENDPOINT}", verify=cert,
                         timeout=120, stream=True)
        r.raise_for_status()
    except Exception as exc:
        raise RuntimeError(f"Erro ao baixar knowledge.zip: {exc}") from exc

    tmp = Path(tempfile.mkdtemp())
    zip_path = tmp / "knowledge.zip"
    sha = hashlib.sha256()
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
            sha.update(chunk)

    if "sha256" in meta:
        obtido = sha.hexdigest()
        if obtido != meta["sha256"]:
            zip_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"SHA-256 divergente — arquivo corrompido.\n"
                f"Esperado: {meta['sha256']}\nObtido:   {obtido}"
            )

    log.info("Knowledge baixado: %s (%d bytes)", zip_path, zip_path.stat().st_size)
    return zip_path, meta


def server_metadata() -> dict | None:
    """Retorna metadados do servidor sem baixar o ZIP. None se indisponível."""
    try:
        import requests
        base = _base_url()
        cert = _cert_path()
        r = requests.get(f"{base}{_META_ENDPOINT}", verify=cert, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ── Import / merge ────────────────────────────────────────────────────────────
def import_knowledge(zip_path: Path, db_path: Path) -> tuple[int, int]:
    """
    Importa exemplos do ZIP para o banco local.
    Usa hash de conteúdo para evitar duplicatas.
    Retorna (novos_inseridos, já_existentes).
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        dados = json.loads(zf.read("knowledge.json").decode("utf-8"))

    exemplos = dados.get("examples", [])
    if not exemplos:
        return 0, 0

    con = sqlite3.connect(str(db_path))
    novos = 0
    existentes = 0

    try:
        # Hash de todos os exemplos já no banco (pelo conteúdo)
        rows_bd = con.execute(
            "SELECT nivel_risco, comportamentos, rotulo FROM exemplos_fewshot WHERE ativo=1"
        ).fetchall()
        hashes_locais = {_content_hash(r[0], r[1], r[2]) for r in rows_bd}

        for ex in exemplos:
            h = ex.get("hash") or _content_hash(
                ex["nivel_risco"], ex["comportamentos"], ex["rotulo"]
            )
            if h in hashes_locais:
                existentes += 1
                continue

            # Cria registro sintético em analises para satisfazer FK
            cur = con.execute(
                """INSERT INTO analises
                   (camera_id, nivel_risco, comportamentos, alerta,
                    acao_recomendada, confianca, tokens_in, tokens_out)
                   VALUES (?, ?, ?, 0, ?, 0.9, 0, 0)""",
                (
                    f"KNOWLEDGE:{ex.get('camera_origem', 'importado')}",
                    ex["nivel_risco"],
                    ex["comportamentos"],
                    ex.get("acao_recomendada", ""),
                ),
            )
            analise_id = cur.lastrowid

            con.execute(
                """INSERT INTO exemplos_fewshot
                   (analise_id, nivel_risco, comportamentos, rotulo, descricao, peso)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    analise_id,
                    ex["nivel_risco"],
                    ex["comportamentos"],
                    ex["rotulo"],
                    ex.get("descricao", ""),
                    float(ex.get("peso", 1.0)),
                ),
            )
            hashes_locais.add(h)
            novos += 1

        con.commit()
        log.info("Knowledge importado: %d novos, %d já existentes", novos, existentes)
    finally:
        con.close()

    return novos, existentes
