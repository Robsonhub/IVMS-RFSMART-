# SPARTA AGENTE IA — Contexto do Projeto

> Este arquivo é lido automaticamente pelo Claude Code ao iniciar uma sessão.
> Quando o usuário disser **"salvar o projeto"**, atualize este arquivo com o estado atual.

---

## Visão Geral

Sistema de vigilância inteligente com IA (Claude + YOLOv8) para monitoramento de câmeras RTSP.
Detecta comportamentos suspeitos, gera alertas com clipes de vídeo, aprende com feedback do operador.

**Stack:** Python, OpenCV, tkinter, PyInstaller (Windows), SQLite, Anthropic API

---

## Versão Atual

| Item | Valor |
|---|---|
| Versão publicada | **v1.3.1** |
| Servidor update | `https://138.186.129.103:8443` |
| Servidor interno | `https://12.0.0.187` (porta 443 nginx) |
| SSH servidor | `ssh -p 4522 root@12.0.0.187 -i ~/.ssh/sparta_vm` |

---

## Arquitetura do Sistema

```
SPARTA (Windows cliente)
  ├── entry.py           → ponto de entrada (watchdog + main)
  ├── main.py            → logging, .env, inicia mosaic
  ├── mosaic.py          → loop principal OpenCV + tkinter
  ├── vision_engine.py   → YOLOv8 (GPU/CPU)
  ├── analyzer.py        → Claude API (Haiku + Opus)
  ├── auto_updater.py    → atualização automática (HTTPS + cert pinning)
  ├── error_reporter.py  → relatórios de erro para servidor local
  ├── knowledge_sync.py  → sync de aprendizado (exemplos few-shot)
  ├── training_tab.py    → painel de treinamento/feedback
  ├── db.py              → SQLite (analises, exemplos_fewshot, etc.)
  └── version.py         → VERSION = "1.3.1"

Servidor Linux (12.0.0.187 / Ubuntu)
  ├── nginx (porta 443)
  │   ├── GET  /latest.json          → manifesto de versão
  │   ├── GET  /releases/vX.Y.Z/*.zip → download do build
  │   ├── GET  /knowledge/*.zip/json  → knowledge sync download
  │   ├── POST /relatorios/upload    → proxy → upload_server:5001
  │   ├── POST /knowledge/upload     → proxy → upload_server:5001
  │   └── GET  /knowledge/status    → proxy → upload_server:5001
  ├── sparta-upload.service (systemd)
  │   └── /opt/sparta/upload_server.py (porta 5001)
  │       ├── POST /relatorios/upload  → salva em /relatorios/
  │       └── POST /knowledge/upload  → mescla em /knowledge/knowledge.zip
  └── /var/www/sparta-updates/
      ├── latest.json
      ├── releases/vX.Y.Z/*.zip
      ├── relatorios/*.zip
      └── knowledge/knowledge.zip

MikroTik (IP WAN: 138.186.129.103)
  ├── NAT: 138.186.129.103:8443 → 12.0.0.187:443
  ├── NAT: 138.186.129.103:4522 → 12.0.0.187:22
  └── forward chain: ACCEPT dst=12.0.0.187 dst-port=443 (posição 0)
```

---

## Build Pipeline

```powershell
# 1. Build
python -m PyInstaller monitor_tapete.spec --noconfirm

# 2. Criar .env no dist (para máquinas externas)
# Conteúdo:
#   UPDATE_SERVER_URL=https://138.186.129.103:8443/latest.json
#   REPORT_SERVER_URL=https://138.186.129.103:8443/relatorios/upload
#   REPORT_SERVER_TOKEN=2b3dfe2e842a83538693a663f37a862f7f5c24f4dd4889d62e48451e78d0f80e

# 3. Zip
python -c "import zipfile,pathlib; ..."  # ver PUBLICAR_RELEASE.bat

# 4. Upload
python scripts/upload_to_vm.py dist/SPARTA_AgentIA_vX.Y.Z.zip X.Y.Z
```

**Regras do build:**
- Nunca chamar Inno Setup — não está instalado
- O `upload_to_vm.py` lê `scripts/.env.publish` (VM_HOST=12.0.0.187 para upload local)
- `VM_PUBLIC_URL_BASE=https://138.186.129.103:8443` no .env.publish

---

## Configuração das Máquinas Cliente

### Máquinas na rede local (12.0.0.0/24)
```
UPDATE_SERVER_URL=https://12.0.0.187/latest.json
REPORT_SERVER_URL=https://12.0.0.187/relatorios/upload
REPORT_SERVER_TOKEN=2b3dfe2e842a83538693a663f37a862f7f5c24f4dd4889d62e48451e78d0f80e
```

### Máquinas externas
```
UPDATE_SERVER_URL=https://138.186.129.103:8443/latest.json
REPORT_SERVER_URL=https://138.186.129.103:8443/relatorios/upload
REPORT_SERVER_TOKEN=2b3dfe2e842a83538693a663f37a862f7f5c24f4dd4889d62e48451e78d0f80e
```

**Por que duas URLs?** O MikroTik não tem hairpin NAT. Máquinas internas não alcançam
o IP público de dentro da rede. O `_rebase_url()` em `auto_updater.py` substitui
automaticamente o host do download pelo mesmo host do `UPDATE_SERVER_URL`.

---

## Certificado SSL

- Arquivo: `assets/update_server.crt` (cert pinning no cliente)
- Servidor: `/etc/ssl/sparta/server.crt`
- **SANs:** `IP:138.186.129.103` e `IP:12.0.0.187` (ambos funcionam)
- Validade: 10 anos (gerado em 2026-04-23)
- Para regenerar: ver seção de comandos úteis abaixo

---

## Máquina MONITORAMENTO (12.0.0.16)

- Instalação: `C:\Users\MONITORAMENTO\AppData\Local\Programs\SPARTA-AGENTE-IA\`
- Versão: **v1.3.1** (auto-update funcionando via IP interno)
- `.env` configurado com URLs internas (`12.0.0.187`)
- GitHub bloqueado nessa rede — auto-update só via servidor local

---

## Sistema de Relatórios de Erro

- Botão: Menu → Relatório de Erros → Enviar Relatório
- Destino: `POST https://{servidor}/relatorios/upload`
- Auth: Bearer token (REPORT_SERVER_TOKEN)
- Salvo em: `/var/www/sparta-updates/relatorios/` e cópia local em `Documents/SPARTA_Relatorios/`
- Inclui: últimos 500 KB do monitor.log + info do sistema

---

## Sistema de Knowledge Sync (Aprendizado)

- Aba Treinamento → botões **Enviar** / **Receber**
- **Enviar:** exporta `exemplos_fewshot` do SQLite local → POST `/knowledge/upload` → merge automático no servidor
- **Receber:** GET `/knowledge/knowledge.zip` → importa exemplos novos (deduplicação por hash)
- Servidor mescla automaticamente ao receber novos conhecimentos
- Nova instalação: clicar **Receber** para herdar todo aprendizado acumulado

---

## Regras Importantes (não esquecer)

| Regra | Motivo |
|---|---|
| `cv2.putText` — só ASCII puro, nunca acentos | cv2 no Windows não suporta Unicode |
| `_btn(pai, texto, cmd, bg)` — ordem dos params | bg vem DEPOIS de cmd em training_tab.py |
| Porta 4543 não usar — ISP bloqueia inbound | Migrado para 8443 |
| Nunca commitar cameras.json com senhas | Arquivo deve ficar vazio `[]` |
| `.env` com API keys — nunca commitar | Está no .gitignore |

---

## Comandos Úteis

```bash
# Ver versão no servidor
curl -sk https://12.0.0.187/latest.json

# Ver relatórios recebidos
ssh -p 4522 root@12.0.0.187 -i ~/.ssh/sparta_vm "ls -lh /var/www/sparta-updates/relatorios/"

# Ver knowledge central
ssh -p 4522 root@12.0.0.187 -i ~/.ssh/sparta_vm "cat /var/www/sparta-updates/knowledge/knowledge.json"

# Reiniciar upload server
ssh -p 4522 root@12.0.0.187 -i ~/.ssh/sparta_vm "systemctl restart sparta-upload"

# Regenerar certificado SSL (se necessário)
ssh -p 4522 root@12.0.0.187 -i ~/.ssh/sparta_vm \
  "openssl req -x509 -newkey rsa:4096 -keyout /etc/ssl/sparta/server.key \
   -out /etc/ssl/sparta/server.crt -days 3650 -nodes \
   -subj '/C=BR/ST=SP/L=Jau/O=SPARTA AGENTE IA/CN=138.186.129.103' \
   -addext 'subjectAltName=IP:138.186.129.103,IP:12.0.0.187' && systemctl reload nginx"
# Depois: scp novo cert para assets/update_server.crt e rebuildar
```

---

## Histórico Recente (resumo desta sessão)

| Versão | O que mudou |
|---|---|
| v1.2.5 | Primeira versão funcional no servidor self-hosted |
| v1.2.6 | Relatórios de erro → servidor local (não GitHub); endpoint /relatorios/upload |
| v1.2.7 | Certificado SSL com SAN duplo (138.186... + 12.0.0.187) |
| v1.2.8 | `_rebase_url` no auto_updater: download usa mesmo host do UPDATE_SERVER_URL |
| v1.2.9 | Fix log path em frozen mode; limite 500KB no relatório |
| v1.3.0 | Knowledge sync via HTTP; botões Enviar/Receber na aba Treinamento |
| v1.3.1 | Fix ordem de params `_btn` no training_tab |

---

*Última atualização: 2026-04-23*
