import logging
import threading
import time
from collections import deque
from urllib.parse import urlparse, urlunparse

import cv2

log = logging.getLogger(__name__)


def _descobrir_rtsp(ip: str, porta: int, usuario: str, senha: str) -> str:
    """Conecta via ONVIF e retorna a URI RTSP do primeiro perfil disponivel."""
    from onvif import ONVIFCamera

    cam   = ONVIFCamera(ip, int(porta), usuario, senha)
    media = cam.create_media_service()

    perfis = media.GetProfiles()
    if not perfis:
        raise RuntimeError("Nenhum perfil de video encontrado via ONVIF.")

    req = media.create_type("GetStreamUri")
    req.ProfileToken = perfis[0].token
    req.StreamSetup  = {
        "Stream":    "RTP-Unicast",
        "Transport": {"Protocol": "RTSP"},
    }
    uri = media.GetStreamUri(req).Uri

    # Injeta credenciais para autenticacao no OpenCV
    p = urlparse(uri)
    host_porta = f"{p.hostname}:{p.port}" if p.port else p.hostname
    return urlunparse(p._replace(netloc=f"{usuario}:{senha}@{host_porta}"))


class VideoCapture:
    """Captura video a partir de uma URI RTSP em thread separada com buffer circular."""

    def __init__(self, rtsp_uri: str, buffer_segundos: int = 60, fps_padrao: float = 15.0):
        self._uri      = rtsp_uri
        self._fps_pad  = fps_padrao
        self.fps       = fps_padrao

        self._cap          = None
        self._lock         = threading.Lock()
        self._ultimo_frame = None
        self._rodando      = False

        capacidade   = int(fps_padrao * buffer_segundos)
        self._buffer = deque(maxlen=capacidade)
        self._thread = threading.Thread(target=self._loop_captura, daemon=True)

    def iniciar(self):
        self._rodando = True
        self._thread.start()
        for _ in range(100):
            if self._ultimo_frame is not None:
                break
            time.sleep(0.1)

    def parar(self):
        self._rodando = False
        self._thread.join(timeout=5)
        if self._cap:
            self._cap.release()

    def ler_frame(self):
        with self._lock:
            return self._ultimo_frame.copy() if self._ultimo_frame is not None else None

    def get_buffer_slice(self, segundos: int) -> list:
        n = int(self.fps * segundos)
        with self._lock:
            frames = list(self._buffer)
        return frames[-n:] if n <= len(frames) else frames

    def _conectar(self) -> bool:
        if self._cap:
            self._cap.release()
        self._cap = cv2.VideoCapture(self._uri)
        if self._cap.isOpened():
            fps = self._cap.get(cv2.CAP_PROP_FPS)
            self.fps = fps if fps > 0 else self._fps_pad
            log.info("Stream conectado. FPS: %.1f", self.fps)
            return True
        return False

    def _loop_captura(self):
        atraso = 1.0
        while self._rodando:
            if not self._conectar():
                log.warning("Falha no stream RTSP. Tentando em %.0fs...", atraso)
                time.sleep(atraso)
                atraso = min(atraso * 2, 30)
                continue
            atraso = 1.0
            while self._rodando:
                ok, frame = self._cap.read()
                if not ok:
                    log.warning("Stream interrompido — reconectando...")
                    break
                with self._lock:
                    self._ultimo_frame = frame
                    self._buffer.append(frame.copy())
