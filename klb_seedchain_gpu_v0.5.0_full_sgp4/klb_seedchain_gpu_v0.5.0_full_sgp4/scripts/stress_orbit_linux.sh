#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${1:-${ROOT}/build}"
PRESET="${2:-laptop}"
case "${PRESET}" in
  smoke|file|laptop|vram) ;;
  *) echo "preset must be smoke, file, laptop, or vram" >&2; exit 2 ;;
esac
DATA="${ROOT}/data/orbit/gps_ops_2026-08-16_7d_1s.kloc"
RESULTS="${ROOT}/orbit_${PRESET}_results.csv"

"${BUILD_DIR}/klb_orbit_bench" "${DATA}" \
  --preset "${PRESET}" --query crossing --mode all --write-events \
  --samples 11 --min-sample-ms 250 --verify-epochs 4096 \
  --csv "${RESULTS}"

echo "Results: ${RESULTS}"
