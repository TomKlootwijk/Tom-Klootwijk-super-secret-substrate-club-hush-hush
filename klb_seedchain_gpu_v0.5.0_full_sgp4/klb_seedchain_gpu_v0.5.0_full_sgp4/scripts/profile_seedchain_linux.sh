#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-${ROOT}/build}"
DATA="${1:-${ROOT}/data/procedural_65536_240f.klsc}"
REPORT="${2:-klb_seedchain_direct_query}"
FRAME="${3:-239}"

ncu --set full --target-processes all -o "${REPORT}" \
  "${BUILD_DIR}/klb_seedchain_bench" "${DATA}" \
  --frame "${FRAME}" --mode seed --warmup 0 --repeats 1 --verify 0
