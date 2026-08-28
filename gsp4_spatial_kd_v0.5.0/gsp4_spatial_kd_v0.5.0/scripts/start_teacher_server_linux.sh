#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then echo "usage: $0 MODEL.gguf [port] [gpu_layers]" >&2; exit 2; fi
MODEL="$1"; PORT="${2:-8081}"; NGL="${3:-99}"
if command -v llama >/dev/null 2>&1; then
  exec llama serve -m "$MODEL" --host 127.0.0.1 --port "$PORT" -ngl "$NGL" -c 8192
elif command -v llama-server >/dev/null 2>&1; then
  exec llama-server -m "$MODEL" --host 127.0.0.1 --port "$PORT" -ngl "$NGL" -c 8192
else
  echo "llama or llama-server is not on PATH" >&2; exit 3
fi
