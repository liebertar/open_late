#!/usr/bin/env bash
# Host-native model gateway (MLX on Metal). Docker cannot use the Mac GPU, so models run here.
# OpenAI-compatible endpoint on :8090; containers call http://host.docker.internal:8090.
#
# One model covers text + vision: Qwen3.6-35B-A3B is a native VLM (Apache-2.0, ~20 GB at 4-bit).
# mlx-vlm serves both text and image prompts. JSON-producing nodes must wrap calls with a
# constrained decoder (outlines / xgrammar); the server itself does not enforce schemas.
#
# Port 8080 is taken on this machine by another project's mlx_lm.server (Qwen3-Next-80B).
set -euo pipefail
MODEL="${MODEL:-mlx-community/Qwen3.6-35B-A3B-4bit}"
PORT="${PORT:-8090}"
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  uv venv -q --python 3.12 .venv
  uv pip install -q --python .venv/bin/python "mlx-vlm==0.7.6"
fi
exec .venv/bin/python -m mlx_vlm.server --model "$MODEL" --host 127.0.0.1 --port "$PORT"
