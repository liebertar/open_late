#!/usr/bin/env bash
# Host-native render engine for the fitting room (MLX on Metal, :8091).
# Models stay loaded between renders: FLUX.2 klein 4B for try-on (~15 GB) and Z-Image-Turbo for portraits (~31 GB),
# both downloaded once into the HF cache. PORTRAIT_MODEL=klein switches portraits back to klein txt2img.
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  uv venv -q --python 3.12 .venv
  uv pip install -q --python .venv/bin/python "mflux==0.21.0" "fastapi==0.118.0" "uvicorn==0.37.0" "httpx==0.28.1" "Pillow==12.3.0" "numpy==2.5.2" "rembg[cpu]==2.0.67"
fi
exec .venv/bin/python -m uvicorn engine:app --host 127.0.0.1 --port "${PORT:-8091}"
