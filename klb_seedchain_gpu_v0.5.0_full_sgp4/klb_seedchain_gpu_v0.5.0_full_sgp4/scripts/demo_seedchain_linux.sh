#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-${ROOT}/build}"
DATA="${1:-${ROOT}/data/procedural_65536_240f.klsc}"
FRAME="${2:-239}"
REPEATS="${3:-20}"

CPU="${BUILD_DIR}/klb_seedchain"
GPU="${BUILD_DIR}/klb_seedchain_bench"

[[ -x "${CPU}" ]] || { echo "Missing ${CPU}; run scripts/build_linux.sh first." >&2; exit 2; }
[[ -x "${GPU}" ]] || { echo "Missing ${GPU}; run scripts/build_linux.sh with CUDA 12.8+ first." >&2; exit 2; }

"${CPU}" inspect "${DATA}"
"${GPU}" "${DATA}" --frame "${FRAME}" --mode all --repeats "${REPEATS}" \
  --csv "${ROOT}/seedchain_results.csv"

echo "Results appended to ${ROOT}/seedchain_results.csv"
