"""Converte assets/logo_dark.png.png para assets/sparta.ico (multi-resolucao)."""
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("[convert_icon] Instalando Pillow...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pillow", "--quiet"])
    from PIL import Image

SRC  = Path("assets/logo_dark.png.png")
DEST = Path("assets/sparta.ico")

if not SRC.exists():
    print(f"[ERRO] Arquivo nao encontrado: {SRC}")
    sys.exit(1)

img = Image.open(SRC).convert("RGBA")

sizes = [16, 24, 32, 48, 64, 128, 256]
icons = []
for s in sizes:
    resized = img.resize((s, s), Image.LANCZOS)
    icons.append(resized)

icons[0].save(
    DEST,
    format="ICO",
    sizes=[(s, s) for s in sizes],
    append_images=icons[1:],
)
print(f"[OK] Icone gerado: {DEST}  ({', '.join(str(s) for s in sizes)} px)")
