#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 1 ]]; then
  echo "usage: $0 orbit.sp3[.gz] [build-dir]" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SP3="$1"
BUILD="${2:-${ROOT}/build}"
python3 "${ROOT}/tools/compare_sp3.py" \
  --sp3 "${SP3}" \
  --ksgp "${ROOT}/data/network/celestrak_mixed_58obj_7d_60s.ksgp" \
  --klb-sgp4 "${BUILD}/klb_sgp4" \
  --output "${ROOT}/sp3_comparison.csv" \
  --summary "${ROOT}/sp3_comparison.summary.txt"
