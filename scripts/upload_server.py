"""SPARTA — Servidor de upload de relatórios de erros.

Recebe POSTs em /relatorios/upload e salva os zips em
/var/www/sparta-updates/relatorios/.

Execução:
    REPORT_TOKEN=xxx python3 upload_server.py
"""
import http.server
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("upload_server")

TOKEN      = os.environ.get("REPORT_TOKEN", "")
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/var/www/sparta-updates/relatorios"))
MAX_SIZE   = 50 * 1024 * 1024   # 50 MB
PORT       = int(os.environ.get("UPLOAD_PORT", "5001"))


class _Handler(http.server.BaseHTTPRequestHandler):

    def do_POST(self):
        if self.path != "/relatorios/upload":
            self._resp(404, {"erro": "Rota não encontrada"})
            return

        auth = self.headers.get("Authorization", "")
        if TOKEN and auth != f"Bearer {TOKEN}":
            log.warning("Upload rejeitado — token inválido de %s", self.client_address[0])
            self._resp(401, {"erro": "Não autorizado"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._resp(400, {"erro": "Content-Length inválido"})
            return

        if length > MAX_SIZE:
            self._resp(413, {"erro": f"Arquivo muito grande (máx {MAX_SIZE // 1024**2} MB)"})
            return

        data = self.rfile.read(length)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        nome = f"relatorio_{ts}_{self.client_address[0].replace('.', '_')}.zip"
        dest = UPLOAD_DIR / nome
        dest.write_bytes(data)

        log.info("Relatório recebido: %s (%.1f KB) de %s",
                 nome, len(data) / 1024, self.client_address[0])
        self._resp(200, {"ok": True, "arquivo": nome})

    def _resp(self, code: int, body: dict):
        data = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        pass  # usa o logger próprio


if __name__ == "__main__":
    if not TOKEN:
        log.error("REPORT_TOKEN não definido — defina a variável de ambiente.")
        sys.exit(1)

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.HTTPServer(("127.0.0.1", PORT), _Handler)
    log.info("Upload server ouvindo em 127.0.0.1:%d — uploads em %s", PORT, UPLOAD_DIR)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Servidor encerrado.")
