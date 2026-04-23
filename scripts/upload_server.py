"""SPARTA — Servidor de upload: relatórios e knowledge sync.

Endpoints:
  POST /relatorios/upload  — recebe zip de relatório de erro
  POST /knowledge/upload   — recebe knowledge.zip, mescla com central
  GET  /knowledge/status   — retorna metadados do knowledge central

Execução:
    REPORT_TOKEN=xxx python3 upload_server.py
"""
import hashlib
import http.server
import io
import json
import logging
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("upload_server")

TOKEN        = os.environ.get("REPORT_TOKEN", "")
UPLOAD_DIR   = Path(os.environ.get("UPLOAD_DIR",    "/var/www/sparta-updates/relatorios"))
KNOW_DIR     = Path(os.environ.get("KNOW_DIR",      "/var/www/sparta-updates/knowledge"))
MAX_RELAT    = 50  * 1024 * 1024   # 50 MB
MAX_KNOW     = 10  * 1024 * 1024   # 10 MB
PORT         = int(os.environ.get("UPLOAD_PORT", "5001"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auth_ok(headers) -> bool:
    return not TOKEN or headers.get("Authorization", "") == f"Bearer {TOKEN}"


def _content_hash(nivel: str, comportamentos: str, rotulo: str) -> str:
    raw = f"{nivel}|{comportamentos}|{rotulo}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _ler_knowledge_central() -> list:
    """Lê exemplos do knowledge.zip central. Retorna lista vazia se não existir."""
    kzip = KNOW_DIR / "knowledge.zip"
    if not kzip.exists():
        return []
    try:
        with zipfile.ZipFile(kzip, "r") as zf:
            dados = json.loads(zf.read("knowledge.json").decode("utf-8"))
        return dados.get("examples", [])
    except Exception as exc:
        log.warning("Falha ao ler knowledge central: %s", exc)
        return []


def _salvar_knowledge_central(exemplos: list) -> None:
    """Salva lista de exemplos no knowledge.zip central e atualiza knowledge.json."""
    KNOW_DIR.mkdir(parents=True, exist_ok=True)

    meta_know = {
        "version":     "1.0",
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "machine_id":  "servidor",
        "total":       len(exemplos),
        "examples":    exemplos,
    }
    kzip = KNOW_DIR / "knowledge.zip"
    with zipfile.ZipFile(kzip, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr("knowledge.json",
                    json.dumps(meta_know, ensure_ascii=False, indent=2))

    sha = hashlib.sha256(kzip.read_bytes()).hexdigest()
    meta_json = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "total":      len(exemplos),
        "size":       kzip.stat().st_size,
        "sha256":     sha,
    }
    (KNOW_DIR / "knowledge.json").write_text(
        json.dumps(meta_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("Knowledge central atualizado: %d exemplos", len(exemplos))


def _mesclar_knowledge(dados_novos: bytes, origem: str) -> dict:
    """Mescla exemplos recebidos com o knowledge central. Retorna estatísticas."""
    try:
        with zipfile.ZipFile(io.BytesIO(dados_novos), "r") as zf:
            novo = json.loads(zf.read("knowledge.json").decode("utf-8"))
        exemplos_novos = novo.get("examples", [])
    except Exception as exc:
        raise ValueError(f"ZIP de knowledge inválido: {exc}") from exc

    exemplos_central = _ler_knowledge_central()

    # Índice de hashes existentes
    hashes_existentes = set()
    for ex in exemplos_central:
        h = ex.get("hash") or _content_hash(
            ex["nivel_risco"], ex["comportamentos"], ex["rotulo"]
        )
        hashes_existentes.add(h)

    novos_inseridos = 0
    for ex in exemplos_novos:
        h = ex.get("hash") or _content_hash(
            ex["nivel_risco"], ex["comportamentos"], ex["rotulo"]
        )
        if h not in hashes_existentes:
            exemplos_central.append(ex)
            hashes_existentes.add(h)
            novos_inseridos += 1

    _salvar_knowledge_central(exemplos_central)
    log.info("Knowledge de %s: %d novo(s), %d já existiam",
             origem, novos_inseridos, len(exemplos_novos) - novos_inseridos)
    return {"novos": novos_inseridos, "total": len(exemplos_central)}


# ── HTTP Handler ──────────────────────────────────────────────────────────────

class _Handler(http.server.BaseHTTPRequestHandler):

    def do_POST(self):
        if self.path == "/relatorios/upload":
            self._handle_relatorio()
        elif self.path == "/knowledge/upload":
            self._handle_knowledge()
        else:
            self._resp(404, {"erro": "Rota não encontrada"})

    def do_GET(self):
        if self.path == "/knowledge/status":
            self._handle_knowledge_status()
        else:
            self._resp(404, {"erro": "Rota não encontrada"})

    def _handle_relatorio(self):
        if not _auth_ok(self.headers):
            log.warning("Relatório rejeitado — token inválido de %s", self.client_address[0])
            self._resp(401, {"erro": "Não autorizado"})
            return

        data, err = self._ler_body(MAX_RELAT)
        if err:
            self._resp(err[0], {"erro": err[1]})
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = f"relatorio_{ts}_{self.client_address[0].replace('.', '_')}.zip"
        (UPLOAD_DIR / nome).write_bytes(data)

        log.info("Relatório recebido: %s (%.1f KB) de %s",
                 nome, len(data) / 1024, self.client_address[0])
        self._resp(200, {"ok": True, "arquivo": nome})

    def _handle_knowledge(self):
        if not _auth_ok(self.headers):
            log.warning("Knowledge rejeitado — token inválido de %s", self.client_address[0])
            self._resp(401, {"erro": "Não autorizado"})
            return

        data, err = self._ler_body(MAX_KNOW)
        if err:
            self._resp(err[0], {"erro": err[1]})
            return

        try:
            stats = _mesclar_knowledge(data, self.client_address[0])
            self._resp(200, {"ok": True, **stats})
        except ValueError as exc:
            self._resp(400, {"erro": str(exc)})
        except Exception as exc:
            log.error("Erro ao mesclar knowledge: %s", exc)
            self._resp(500, {"erro": "Erro interno ao mesclar knowledge"})

    def _handle_knowledge_status(self):
        meta = KNOW_DIR / "knowledge.json"
        if meta.exists():
            self._resp(200, json.loads(meta.read_text(encoding="utf-8")))
        else:
            self._resp(200, {"total": 0, "updated_at": None})

    def _ler_body(self, max_size: int):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None, (400, "Content-Length inválido")
        if length > max_size:
            return None, (413, f"Arquivo muito grande (máx {max_size // 1024**2} MB)")
        return self.rfile.read(length), None

    def _resp(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        log.error("REPORT_TOKEN não definido — defina a variável de ambiente.")
        sys.exit(1)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    KNOW_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.HTTPServer(("127.0.0.1", PORT), _Handler)
    log.info("Upload server ouvindo em 127.0.0.1:%d", PORT)
    log.info("  Relatórios → %s", UPLOAD_DIR)
    log.info("  Knowledge  → %s", KNOW_DIR)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Servidor encerrado.")
