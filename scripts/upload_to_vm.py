"""
SPARTA AGENTE IA — Upload de release para a VM self-hosted.

Lê configuração de `scripts/.env.publish` (gitignored):

    VM_HOST=200.100.50.1
    VM_USER=ubuntu
    VM_SSH_PORT=22
    VM_RELEASES_DIR=/var/www/sparta-updates
    VM_SUDO=1                        # se www-data precisa de sudo para escrever
    NOTAS="Notas opcionais da release"

Uso:

    python scripts/upload_to_vm.py dist/SPARTA_AgentIA_v1.1.5.zip 1.1.5
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def _ler_env_publish() -> dict[str, str]:
    env_path = Path(__file__).parent / ".env.publish"
    if not env_path.exists():
        print(f"[ERRO] Arquivo {env_path} não encontrado.", file=sys.stderr)
        print("Crie com as variáveis VM_HOST, VM_USER, VM_SSH_PORT.", file=sys.stderr)
        sys.exit(1)

    dados = {}
    for linha in env_path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        k, v = linha.split("=", 1)
        dados[k.strip()] = v.strip().strip('"').strip("'")
    return dados


def _sha256(caminho: Path) -> str:
    h = hashlib.sha256()
    with caminho.open("rb") as fp:
        for bloco in iter(lambda: fp.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _run_ssh(env: dict, cmd: str) -> None:
    host  = f"{env['VM_USER']}@{env['VM_HOST']}"
    porta = env.get("VM_SSH_PORT", "22")
    subprocess.run(
        ["ssh", "-p", str(porta), host, cmd],
        check=True,
    )


def _scp(env: dict, origem: Path, destino_remoto: str) -> None:
    host  = f"{env['VM_USER']}@{env['VM_HOST']}"
    porta = env.get("VM_SSH_PORT", "22")
    subprocess.run(
        ["scp", "-P", str(porta), str(origem), f"{host}:{destino_remoto}"],
        check=True,
    )


def main() -> int:
    if len(sys.argv) < 3:
        print("Uso: python upload_to_vm.py <caminho_do_zip> <versao>", file=sys.stderr)
        return 1

    zip_path = Path(sys.argv[1]).resolve()
    versao   = sys.argv[2].lstrip("v")

    if not zip_path.exists():
        print(f"[ERRO] Zip não encontrado: {zip_path}", file=sys.stderr)
        return 1

    env = _ler_env_publish()
    base_dir = env.get("VM_RELEASES_DIR", "/var/www/sparta-updates")
    sudo     = "sudo " if env.get("VM_SUDO", "0") == "1" else ""
    notas    = env.get("NOTAS", f"Release v{versao}")

    print(f"[1/5] Calculando SHA-256 de {zip_path.name} ({zip_path.stat().st_size / 1048576:.1f} MB)...")
    sha = _sha256(zip_path)
    print(f"      {sha}")

    print(f"[2/5] Gerando latest.json local...")
    manifesto = {
        "version": versao,
        "url":     f"https://{env['VM_HOST']}/releases/v{versao}/{zip_path.name}",
        "size":    zip_path.stat().st_size,
        "sha256":  sha,
        "notes":   notas,
    }
    manifesto_path = zip_path.parent / "latest.json"
    manifesto_path.write_text(json.dumps(manifesto, indent=2), encoding="utf-8")

    print(f"[3/5] Criando diretório remoto {base_dir}/releases/v{versao}/ ...")
    _run_ssh(env, f"{sudo}mkdir -p {base_dir}/releases/v{versao} && "
                  f"{sudo}chown -R www-data:www-data {base_dir}/releases")

    print(f"[4/5] Enviando .zip (pode demorar para arquivos grandes)...")
    tmp_zip = f"/tmp/{zip_path.name}"
    _scp(env, zip_path, tmp_zip)
    _run_ssh(env, f"{sudo}mv {tmp_zip} {base_dir}/releases/v{versao}/ && "
                  f"{sudo}chown www-data:www-data {base_dir}/releases/v{versao}/{zip_path.name}")

    print(f"[5/5] Atualizando latest.json remoto...")
    tmp_json = "/tmp/sparta_latest.json"
    _scp(env, manifesto_path, tmp_json)
    _run_ssh(env, f"{sudo}mv {tmp_json} {base_dir}/latest.json && "
                  f"{sudo}chown www-data:www-data {base_dir}/latest.json")

    print()
    print(f"═══════════════════════════════════════════════════════════════")
    print(f"  RELEASE v{versao} PUBLICADA NO SERVIDOR LOCAL")
    print(f"  https://{env['VM_HOST']}/latest.json")
    print(f"═══════════════════════════════════════════════════════════════")
    return 0


if __name__ == "__main__":
    sys.exit(main())
