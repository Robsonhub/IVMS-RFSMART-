import os
import sys
from pathlib import Path
from dotenv import load_dotenv

_ENV_PATH = (Path(sys.executable).parent / ".env") if getattr(sys, "frozen", False) else Path(".env")
load_dotenv(_ENV_PATH)

CLAUDE_API_KEY   = os.getenv("CLAUDE_API_KEY", "")
CAMERA_IP        = os.getenv("CAMERA_IP", "")
CAMERA_PORTA     = int(os.getenv("CAMERA_PORTA", "80"))
CAMERA_USUARIO   = os.getenv("CAMERA_USUARIO", "admin")
CAMERA_SENHA     = os.getenv("CAMERA_SENHA", "")
CAMERA_ID        = os.getenv("CAMERA_ID", "CAM-TAPETE-01")
INTERVALO_FRAMES = int(os.getenv("INTERVALO_FRAMES", "3"))
PASTA_CLIPS      = Path(os.getenv("PASTA_CLIPS", "clips_alertas"))
WEBHOOK_URL      = os.getenv("WEBHOOK_URL", "")
FASE_PROCESSO    = os.getenv("FASE_PROCESSO", "manuseio")

PASTA_CLIPS.mkdir(exist_ok=True)

GITHUB_TOKEN     = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPO      = os.getenv("GITHUB_REPO", "Robsonhub/IVMS-RFSMART-")
