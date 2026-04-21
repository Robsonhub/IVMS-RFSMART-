#!/usr/bin/env bash
#
# SPARTA AGENTE IA — Provisionamento da VM Ubuntu para hosting de releases
# ---------------------------------------------------------------------------
# Uso:
#   sudo bash provisionar_vm.sh
#
# Efeitos:
#   - Instala nginx, openssl, ufw, fail2ban
#   - Gera certificado TLS self-signed (4096 bits, validade 10 anos)
#   - Configura nginx em 443/TCP com rate limit e cabeçalhos de segurança
#   - Abre 443 no firewall; SSH só pela rede local
#   - Ativa fail2ban para bloqueio de IPs abusivos
#   - Cria /var/www/sparta-updates/ (destino do SCP de releases)
#
# Ao final imprime:
#   - IP público detectado
#   - Fingerprint SHA-256 do certificado
#   - Caminho do .crt para baixar via SCP e embarcar no cliente
# ---------------------------------------------------------------------------
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "[ERRO] Execute como root: sudo bash $0" >&2
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════"
echo "  SPARTA AGENTE IA — Provisionamento do servidor de updates"
echo "═══════════════════════════════════════════════════════════════"
echo

# --- Detecta IP público ------------------------------------------------------
echo "[1/8] Detectando IP público..."
IP_PUBLICO="$(curl -s --max-time 5 https://api.ipify.org || true)"
if [[ -z "$IP_PUBLICO" ]]; then
    IP_PUBLICO="$(curl -s --max-time 5 https://ifconfig.me || true)"
fi
if [[ -z "$IP_PUBLICO" ]]; then
    echo "[AVISO] Não consegui detectar IP público automaticamente."
    read -r -p "Digite o IP público da VM (ex.: 200.100.50.1): " IP_PUBLICO
fi
echo "     IP público: $IP_PUBLICO"

# Rede local (para liberar SSH apenas nela) — deduz da interface padrão
REDE_LOCAL="$(ip -4 route show default | awk '{print $3}' | head -1 | sed 's#\.[0-9]*$#.0/24#')"
echo "     Rede local: $REDE_LOCAL"
echo

# --- Instala pacotes ---------------------------------------------------------
echo "[2/8] Instalando nginx, openssl, ufw, fail2ban..."
apt update -qq
DEBIAN_FRONTEND=noninteractive apt install -y -qq \
    nginx openssl ufw fail2ban curl ca-certificates
echo "     [OK]"
echo

# --- Gera certificado TLS self-signed ---------------------------------------
echo "[3/8] Gerando certificado TLS self-signed (4096 bits, 10 anos)..."
mkdir -p /etc/ssl/sparta
chmod 750 /etc/ssl/sparta

cat > /etc/ssl/sparta/openssl.cnf <<EOF
[req]
default_bits       = 4096
prompt             = no
default_md         = sha256
distinguished_name = dn
req_extensions     = req_ext
x509_extensions    = req_ext

[dn]
C  = BR
ST = SP
L  = Jau
O  = SPARTA AGENTE IA
CN = $IP_PUBLICO

[req_ext]
subjectAltName = @alt_names
basicConstraints = CA:FALSE
keyUsage         = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth

[alt_names]
IP.1  = $IP_PUBLICO
EOF

openssl req -x509 -nodes -newkey rsa:4096 \
    -days 3650 \
    -config /etc/ssl/sparta/openssl.cnf \
    -keyout /etc/ssl/sparta/server.key \
    -out /etc/ssl/sparta/server.crt \
    2>/dev/null

chmod 640 /etc/ssl/sparta/server.key
chmod 644 /etc/ssl/sparta/server.crt
chown root:www-data /etc/ssl/sparta/server.key

# Stage do .crt para o dev baixar via SCP
cp /etc/ssl/sparta/server.crt /tmp/update_server.crt
chmod 644 /tmp/update_server.crt

FINGERPRINT="$(openssl x509 -in /etc/ssl/sparta/server.crt -noout -fingerprint -sha256 | sed 's/SHA256 Fingerprint=//')"
echo "     [OK]"
echo

# --- nginx ------------------------------------------------------------------
echo "[4/8] Configurando nginx..."
mkdir -p /var/www/sparta-updates/releases
chown -R www-data:www-data /var/www/sparta-updates

cat > /etc/nginx/conf.d/sparta-rate-limit.conf <<'EOF'
# Rate limit por IP: JSON = 20 req/min, download = 2 req/min
limit_req_zone $binary_remote_addr zone=sparta_json:10m rate=20r/m;
limit_req_zone $binary_remote_addr zone=sparta_zip:10m  rate=2r/m;
EOF

cat > /etc/nginx/sites-available/sparta-updates <<EOF
server {
    listen 443 ssl http2;
    server_name _;

    ssl_certificate     /etc/ssl/sparta/server.crt;
    ssl_certificate_key /etc/ssl/sparta/server.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Cabeçalhos de segurança
    add_header X-Content-Type-Options "nosniff"            always;
    add_header X-Frame-Options        "DENY"               always;
    add_header Referrer-Policy        "no-referrer"        always;
    add_header Strict-Transport-Security "max-age=63072000" always;

    root  /var/www/sparta-updates;
    index latest.json;

    # Apenas GET/HEAD são aceitos
    if (\$request_method !~ ^(GET|HEAD)\$) {
        return 405;
    }

    # Manifesto — rate limit mais generoso
    location = /latest.json {
        limit_req zone=sparta_json burst=5 nodelay;
        default_type application/json;
        add_header Cache-Control "no-cache";
        try_files \$uri =404;
    }

    # Downloads grandes — rate limit apertado
    location /releases/ {
        limit_req zone=sparta_zip burst=1 nodelay;
        autoindex off;
    }

    # Tudo mais: 404
    location / {
        return 404;
    }

    # Logs (acompanhados por fail2ban)
    access_log /var/log/nginx/sparta-access.log;
    error_log  /var/log/nginx/sparta-error.log;
}

# Redireciona HTTP/80 para HTTPS (apenas para mensagem amigável; o cliente usa 443 direto)
server {
    listen 80 default_server;
    server_name _;
    return 301 https://\$host\$request_uri;
}
EOF

# Desativa o site default do nginx (não queremos expor "Welcome to nginx!")
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/sparta-updates /etc/nginx/sites-enabled/sparta-updates

nginx -t >/dev/null 2>&1
systemctl enable --now nginx >/dev/null 2>&1
systemctl reload nginx
echo "     [OK]"
echo

# --- UFW --------------------------------------------------------------------
echo "[5/8] Configurando firewall (UFW)..."
ufw --force reset >/dev/null
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow 443/tcp comment 'SPARTA updates HTTPS' >/dev/null
ufw allow from "$REDE_LOCAL" to any port 22 proto tcp comment 'SSH rede local' >/dev/null
ufw --force enable >/dev/null
echo "     [OK] 443/tcp aberto | SSH restrito a $REDE_LOCAL"
echo

# --- fail2ban ---------------------------------------------------------------
echo "[6/8] Configurando fail2ban..."
cat > /etc/fail2ban/jail.d/sparta-nginx.conf <<'EOF'
[nginx-sparta-4xx]
enabled  = true
port     = https,http
filter   = nginx-sparta-4xx
logpath  = /var/log/nginx/sparta-access.log
maxretry = 20
findtime = 60
bantime  = 600
EOF

cat > /etc/fail2ban/filter.d/nginx-sparta-4xx.conf <<'EOF'
[Definition]
failregex = ^<HOST> .* "(GET|POST|PUT|DELETE|HEAD).*" (4\d{2}|5\d{2}) .*$
ignoreregex =
EOF

systemctl enable --now fail2ban >/dev/null 2>&1
systemctl restart fail2ban
echo "     [OK] ban de 10 min após 20 requisições 4xx/5xx em 60s"
echo

# --- Manifesto vazio inicial -----------------------------------------------
echo "[7/8] Criando manifesto inicial (sem releases publicadas)..."
cat > /var/www/sparta-updates/latest.json <<'EOF'
{
  "version": "0.0.0",
  "url": "",
  "size": 0,
  "sha256": "",
  "notes": "Nenhuma release publicada ainda."
}
EOF
chown www-data:www-data /var/www/sparta-updates/latest.json
echo "     [OK]"
echo

# --- Resumo final -----------------------------------------------------------
echo "[8/8] Pronto!"
echo
echo "═══════════════════════════════════════════════════════════════"
echo "  SERVIDOR SPARTA UPDATES PROVISIONADO"
echo "═══════════════════════════════════════════════════════════════"
echo
echo "  IP público:        $IP_PUBLICO"
echo "  Endpoint:          https://$IP_PUBLICO/latest.json"
echo "  Diretório releases: /var/www/sparta-updates/releases/"
echo
echo "  Certificado SHA-256:"
echo "    $FINGERPRINT"
echo
echo "  O certificado foi copiado para /tmp/update_server.crt"
echo "  Baixe-o para a máquina dev com:"
echo
echo "    scp ubuntu@$IP_PUBLICO:/tmp/update_server.crt ."
echo
echo "  Depois coloque em: assets/update_server.crt do projeto Windows"
echo
echo "  IMPORTANTE: abra a porta 443/TCP no roteador (port forwarding)"
echo "  apontando para o IP desta VM."
echo
echo "  Teste rápido (da internet):"
echo "    curl -k https://$IP_PUBLICO/latest.json"
echo
echo "═══════════════════════════════════════════════════════════════"
