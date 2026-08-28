#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
CUDA=0
FULL=0
TORCH_INDEX_URL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --cuda) CUDA=1; shift ;;
    --full) FULL=1; shift ;;
    --torch-index-url)
      [[ $# -ge 2 ]] || { echo "--torch-index-url requires a value" >&2; exit 2; }
      TORCH_INDEX_URL="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
if [[ "$CUDA" -eq 1 ]]; then
  # Current stable PyTorch publishes its Blackwell-capable CUDA build through
  # the normal package index. Override only for a future/nightly channel or a
  # controlled mirror.
  if [[ -n "$TORCH_INDEX_URL" ]]; then
    python -m pip install torch torchvision torchaudio --index-url "$TORCH_INDEX_URL"
  else
    python -m pip install torch torchvision torchaudio
  fi
else
  python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
fi
if [[ "$FULL" -eq 1 ]]; then
  python -m pip install -e '.[all]'
else
  python -m pip install -e '.[dev]'
fi
python -m ugts_spatial --version
python -m ugts_spatial check-gpu --device auto --precision float16 || true
