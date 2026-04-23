import os
import sys
from pathlib import Path
from dotenv import load_dotenv

_BASE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent
_ENV_PATH = _BASE_DIR / ".env"
load_dotenv(_ENV_PATH)

CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY", "")
CAMERA_IP        = os.getenv("CAMERA_IP", "")
CAMERA_PORTA     = int(os.getenv("CAMERA_PORTA", "80"))
CAMERA_USUARIO   = os.getenv("CAMERA_USUARIO", "admin")
CAMERA_SENHA     = os.getenv("CAMERA_SENHA", "")
CAMERA_ID        = os.getenv("CAMERA_ID", "CAM-TAPETE-01")
INTERVALO_FRAMES = int(os.getenv("INTERVALO_FRAMES", "3"))
WEBHOOK_URL      = os.getenv("WEBHOOK_URL", "")
FASE_PROCESSO    = os.getenv("FASE_PROCESSO", "manuseio")

_clips_env = os.getenv("PASTA_CLIPS", "clips_alertas")
PASTA_CLIPS = Path(_clips_env) if Path(_clips_env).is_absolute() else _BASE_DIR / _clips_env
PASTA_CLIPS.mkdir(exist_ok=True)

GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO      = os.getenv("GITHUB_REPO", "Robsonhub/IVMS-RFSMART-")
