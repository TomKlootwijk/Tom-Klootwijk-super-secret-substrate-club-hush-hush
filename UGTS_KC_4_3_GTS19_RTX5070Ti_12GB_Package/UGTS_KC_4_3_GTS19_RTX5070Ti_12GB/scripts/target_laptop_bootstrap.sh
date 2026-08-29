#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
mkdir -p evidence
python scripts/hardware_probe.py evidence/target_hardware.json
./codex/acceptance.sh
cmake -S cpp -B build-cuda -DUGTS_ENABLE_CUDA=ON -DCMAKE_BUILD_TYPE=Release -DCMAKE_CUDA_ARCHITECTURES=native
cmake --build build-cuda --config Release
./build-cuda/ugts_go19_gpu_probe | tee evidence/target_cuda_probe.json
echo "Bootstrap complete. Start M1 from codex/TASKS.md."
