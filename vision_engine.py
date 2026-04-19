"""Motor de visão adaptativo — YOLOv8 + DeepSORT + detecção automática de hardware.

Hierarquia de modelos por tier de GPU:
  Tier 0 — CPU only      → yolov8n.pt  (~6 MB)
  Tier 1 — GPU < 4 GB   → yolov8s.pt  (~22 MB)
  Tier 2 — GPU 4-8 GB   → yolov8m.pt  (~52 MB)
  Tier 3 — GPU > 8 GB   → yolov8l.pt  (~87 MB)

Se models/yolo_tapete_ouro.pt existir (fine-tune local), tem prioridade sobre qualquer tier.
"""
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

_ZONA_TAPETE_PADRAO = (0.05, 0.50, 0.95, 0.98)
_FRAMES_PARADO_ALERTA  = 150
_DESLOCAMENTO_PARADO_PX = 20
_MODELO_CUSTOM = Path("models/yolo_tapete_ouro.pt")

MAX_CAMERAS_GPU = {0: 999, 1: 4, 2: 10, 3: 24}


# ── Hardware ───────────────────────────────────────────────────────────────────

class HardwareDetector:
    @staticmethod
    def detectar() -> dict:
        info = {"device": "cpu", "vram_gb": 0.0, "tier": 0, "modelo_yolo": "yolov8n.pt"}
        try:
            import torch
            if torch.cuda.is_available():
                props  = torch.cuda.get_device_properties(0)
                vram   = props.total_memory / (1024 ** 3)
                info.update(device="cuda", vram_gb=round(vram, 1))
                if vram >= 8:
                    info.update(tier=3, modelo_yolo="yolov8l.pt")
                elif vram >= 4:
                    info.update(tier=2, modelo_yolo="yolov8m.pt")
                else:
                    info.update(tier=1, modelo_yolo="yolov8s.pt")
                log.info("GPU: %s (%.1f GB VRAM) — Tier %d, %s",
                         props.name, vram, info["tier"], info["modelo_yolo"])
            else:
                log.info("CUDA indisponível — CPU + YOLOv8n")
        except ImportError:
            log.info("torch não instalado — CPU + YOLOv8n")
        except Exception as exc:
            log.warning("Falha ao detectar hardware (%s) — CPU fallback", exc)
        return info


# ── YOLOv8 ────────────────────────────────────────────────────────────────────

class YOLOv8Engine:
    def __init__(self, hw: dict):
        from ultralytics import YOLO
        modelo = str(_MODELO_CUSTOM) if _MODELO_CUSTOM.exists() else hw["modelo_yolo"]
        self._device = hw["device"]
        self._half   = hw["device"] == "cuda"
        self._model  = YOLO(modelo)
        log.info("YOLOv8 carregado: %s em %s%s",
                 modelo, self._device, " (fp16)" if self._half else "")

    def detectar(self, frame: np.ndarray) -> list:
        try:
            results = self._model(
                frame,
                classes=[0],
                conf=0.45,
                verbose=False,
                device=self._device,
                half=self._half,
            )
            saida = []
            for box in results[0].boxes:
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                saida.append({"bbox": [x1, y1, x2, y2], "conf": float(box.conf[0])})
            return saida
        except Exception as exc:
            log.debug("YOLOv8 falha na inferência: %s", exc)
            return []


# ── DeepSORT ──────────────────────────────────────────────────────────────────

class _TrackInfo:
    def __init__(self, tid: int, cx: int, cy: int):
        self.track_id      = tid
        self.frames_visivel = 1
        self._posicoes     = [(cx, cy)]

    def atualizar(self, cx: int, cy: int):
        self.frames_visivel += 1
        self._posicoes.append((cx, cy))
        if len(self._posicoes) > 30:
            self._posicoes.pop(0)

    @property
    def deslocamento_medio(self) -> float:
        pts = self._posicoes
        if len(pts) < 2:
            return 0.0
        deltas = [
            ((pts[i][0]-pts[i-1][0])**2 + (pts[i][1]-pts[i-1][1])**2) ** 0.5
            for i in range(1, len(pts))
        ]
        return float(sum(deltas) / len(deltas))


class DeepSORTTracker:
    def __init__(self, camera_id: str):
        from deep_sort_realtime.deepsort_tracker import DeepSort
        self._cam_id  = camera_id
        self._tracker = DeepSort(max_age=30, n_init=2, nms_max_overlap=0.7)
        self._infos: dict[int, _TrackInfo] = {}

    def atualizar(self, deteccoes: list, frame: np.ndarray) -> list:
        raw = [([d["bbox"][0], d["bbox"][1],
                 d["bbox"][2]-d["bbox"][0], d["bbox"][3]-d["bbox"][1]],
                d["conf"], 0)
               for d in deteccoes]
        try:
            tracks = self._tracker.update_tracks(raw, frame=frame)
        except Exception as exc:
            log.debug("[%s] DeepSORT erro: %s", self._cam_id, exc)
            return []

        resultado  = []
        ids_ativos = set()
        for track in tracks:
            if not track.is_confirmed():
                continue
            tid = track.track_id
            ids_ativos.add(tid)
            try:
                x1, y1, x2, y2 = (int(v) for v in track.to_ltrb())
            except Exception:
                continue
            cx, cy = (x1+x2)//2, (y1+y2)//2
            if tid not in self._infos:
                self._infos[tid] = _TrackInfo(tid, cx, cy)
            else:
                self._infos[tid].atualizar(cx, cy)
            info = self._infos[tid]
            resultado.append({
                "track_id":       tid,
                "bbox":           [x1, y1, x2, y2],
                "conf":           track.get_det_conf() or 0.5,
                "frames_visivel": info.frames_visivel,
                "deslocamento":   info.deslocamento_medio,
                "cx": cx, "cy": cy,
            })

        # Limpa tracks muito antigos e inativos
        for tid in list(self._infos):
            if tid not in ids_ativos and self._infos[tid].frames_visivel > 300:
                del self._infos[tid]
        return resultado


# ── VisionEngine (singleton) ───────────────────────────────────────────────────

class VisionEngine:
    _instancia  = None
    _lock_init  = threading.Lock()

    @classmethod
    def obter(cls) -> "VisionEngine":
        if cls._instancia is None:
            with cls._lock_init:
                if cls._instancia is None:
                    cls._instancia = cls()
        return cls._instancia

    def __init__(self):
        self._hw       = HardwareDetector.detectar()
        self._yolo     = YOLOv8Engine(self._hw)
        self._trackers: dict[str, DeepSORTTracker] = {}
        self._lock     = threading.Lock()

    # ── Propriedades de info ────────────────────────────────────────────────

    @property
    def tier(self) -> int:
        return self._hw["tier"]

    @property
    def device(self) -> str:
        return self._hw["device"]

    @property
    def modelo_label(self) -> str:
        m = self._hw["modelo_yolo"].replace("yolov8", "YOLO-").replace(".pt", "")
        suf = "GPU" if self._hw["device"] == "cuda" else "CPU"
        return f"{m} {suf}"

    @property
    def max_cameras(self) -> int:
        return MAX_CAMERAS_GPU[self._hw["tier"]]

    def _tracker(self, camera_id: str) -> DeepSORTTracker:
        with self._lock:
            if camera_id not in self._trackers:
                self._trackers[camera_id] = DeepSORTTracker(camera_id)
            return self._trackers[camera_id]

    # ── Análise principal ─────────────────────────────────────────────────

    def analisar(self, frame: np.ndarray, frame_id: str,
                 camera_id: str = "", slot_idx: int = 0,
                 zona_tapete: tuple = _ZONA_TAPETE_PADRAO) -> dict:
        """Retorna dict compatível com AnalisadorLocal.analisar()."""
        h, w = frame.shape[:2]

        deteccoes = self._yolo.detectar(frame)
        tracks    = self._tracker(camera_id or str(slot_idx)).atualizar(deteccoes, frame)

        n_pessoas = len(tracks)
        eventos   = []
        nivel     = "sem_risco"
        alerta    = False
        confianca = 0.55
        acao      = "Monitoramento normal"
        ORDEM     = ["sem_risco", "atencao", "suspeito", "critico"]

        def _elevar(novo: str, conf: float = 0.0):
            nonlocal nivel, confianca
            if ORDEM.index(novo) > ORDEM.index(nivel):
                nivel = novo
            confianca = min(0.94, confianca + conf)

        # Regra 1 — múltiplas pessoas
        if n_pessoas > 1:
            eventos.append(f"{n_pessoas} pessoas detectadas na area restrita")
            _elevar("critico", 0.30)
            alerta = True
            acao   = "Acionar supervisor — segunda pessoa detectada"

        # Regra 2 — pessoa parada
        parados = [t for t in tracks
                   if t["frames_visivel"] > _FRAMES_PARADO_ALERTA
                   and t["deslocamento"] < _DESLOCAMENTO_PARADO_PX]
        if parados:
            eventos.append("Pessoa parada sem movimentacao por tempo prolongado")
            _elevar("atencao", 0.12)

        # Regra 3 — pessoa na zona do tapete
        tx1, ty1 = int(zona_tapete[0]*w), int(zona_tapete[1]*h)
        tx2, ty2 = int(zona_tapete[2]*w), int(zona_tapete[3]*h)
        for t in tracks:
            bx1, by1, bx2, by2 = t["bbox"]
            if bx1 < tx2 and bx2 > tx1 and by1 < ty2 and by2 > ty1:
                eventos.append("Pessoa detectada na zona do tapete de ouro")
                _elevar("suspeito", 0.18)
                break

        # Regra 4 — movimento brusco (deslocamento alto, track recente)
        rapidos = [t for t in tracks
                   if t["deslocamento"] > 15 and t["frames_visivel"] < 30]
        if rapidos:
            eventos.append("Movimento rapido detectado na cena")
            _elevar("suspeito", 0.10)

        if not eventos:
            eventos.append("Nenhuma pessoa detectada" if n_pessoas == 0
                           else "Cena dentro do padrao esperado")
            confianca = 0.70 if n_pessoas == 0 else 0.65

        if nivel in ("suspeito", "critico"):
            alerta = True
            if acao == "Monitoramento normal":
                acao = "Revisar gravacao — comportamento suspeito detectado"

        objetos = [{
            "tipo":         "pessoa",
            "track_id":     t["track_id"],
            "frames_visivel": t["frames_visivel"],
            "bbox_norm": [
                round(max(0.0, t["bbox"][0]/w), 3),
                round(max(0.0, t["bbox"][1]/h), 3),
                round(min(1.0, t["bbox"][2]/w), 3),
                round(min(1.0, t["bbox"][3]/h), 3),
            ],
            "descricao": f"Track #{t['track_id']} — {t['frames_visivel']} frames",
        } for t in tracks]

        return {
            "alerta":                    alerta,
            "nivel_risco":               nivel,
            "comportamentos_detectados": eventos,
            "posicao_na_cena":           f"{n_pessoas} pessoa(s) rastreada(s)",
            "acao_recomendada":          acao,
            "revisar_clip":              alerta,
            "janela_revisao_segundos":   30 if alerta else 0,
            "confianca":                 round(confianca, 2),
            "timestamp_analise":         datetime.now(timezone.utc).isoformat(),
            "frame_id":                  frame_id,
            "objetos_detectados":        objetos,
            "fonte":                     "yolo-deepsort",
        }

    def __repr__(self) -> str:
        return (f"VisionEngine(tier={self.tier}, device={self.device}, "
                f"modelo={self._hw['modelo_yolo']}, vram={self._hw['vram_gb']}GB)")
