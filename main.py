import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            (Path(sys.executable).parent if getattr(sys, "frozen", False) else Path("."))
            / "monitor.log",
            encoding="utf-8",
        ),
    ],
)
log = logging.getLogger("main")

_ENV_PATH = (
    Path(sys.executable).parent / ".env"
    if getattr(sys, "frozen", False)
    else Path(".env")
)


def _env_existe() -> bool:
    if not _ENV_PATH.exists():
        return False
    return "CLAUDE_API_KEY" in _ENV_PATH.read_text(encoding="utf-8")


def _carregar_config():
    from dotenv import load_dotenv
    load_dotenv(_ENV_PATH, override=True)
    import importlib
    import config as cfg
    importlib.reload(cfg)
    return cfg


def _pedir_config() -> bool:
    """Abre tela de configuracao. Retorna True se o usuario salvou."""
    from setup_config import abrir_configuracao
    salvo = []
    abrir_configuracao(ao_salvar=lambda: salvo.append(True))
    return bool(salvo)



def _garantir_instancia_unica():
    """Impede que duas cópias do sistema rodem ao mesmo tempo."""
    import socket
    lock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        lock.bind(("localhost", 47321))
        return lock   # mantém o socket aberto enquanto o processo vive
    except OSError:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(
            "SPARTA AGENTE IA",
            "O sistema ja esta em execucao.\nVerifique a barra de tarefas."
        )
        r.destroy()
        sys.exit(0)


def main():
    _lock = _garantir_instancia_unica()   # trava enquanto o processo vive

    from connection_status import StatusConexao

    # Loop linear: config → status → monitorar
    # Sem callbacks recursivos — cada etapa retorna um valor
    while True:

        # 1. Garantir que o .env existe e tem a chave
        if not _env_existe():
            log.info("Configuracao nao encontrada - abrindo assistente.")
            if not _pedir_config():
                log.info("Configuracao cancelada. Encerrando.")
                break

        # 2. Carregar config e tentar conexao ONVIF
        cfg = _carregar_config()
        resultado = StatusConexao().mostrar(cfg)

        if resultado[0] == "ok":
            rtsp_uri = resultado[1]
            log.info("URI descoberta: %s", rtsp_uri.split("@")[-1])
            from mosaic import rodar_mosaico
            rodar_mosaico(cfg, rtsp_uri, cfg.INTERVALO_FRAMES)
            break

        elif resultado[0] == "reconfigurar":
            # Usuario quer corrigir os dados — volta ao inicio do loop
            log.info("Reabrindo configuracao a pedido do usuario.")
            if not _pedir_config():
                log.info("Configuracao cancelada. Encerrando.")
                break
            # Continua o while — tenta conexao novamente com novos dados

        else:
            # Usuario fechou a janela
            log.info("Janela fechada pelo usuario. Encerrando.")
            break


if __name__ == "__main__":
    main()
