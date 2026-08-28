#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BENCH="${ROOT}/build/klb_bench"
DATA="${1:-${ROOT}/data/procedural_65536.klb}"
REPORT="${2:-klb_packed_report}"

ncu --set full --target-processes all -o "${REPORT}" \
  "${BENCH}" "${DATA}" \
  --mode packed --queries 1048576 --depth 12 \
  --warmup 0 --repeats 1 --verify 0
