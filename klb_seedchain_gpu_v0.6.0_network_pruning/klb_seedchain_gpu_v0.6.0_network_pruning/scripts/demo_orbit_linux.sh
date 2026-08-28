#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${1:-${ROOT}/build}"
DATA="${ROOT}/data/orbit/gps_ops_2026-08-16_7d_1s.kloc"
RESULTS="${ROOT}/orbit_file_results.csv"
PASSES="${ROOT}/orbit_pass_events_rebuilt.csv"

"${BUILD_DIR}/klb_orbit" inspect "${DATA}"
"${BUILD_DIR}/klb_orbit" verify "${DATA}"
"${BUILD_DIR}/klb_orbit" passes "${DATA}" \
  --lat 52 --lon 5 --alt-km 0.05 \
  --elevation-deg 10 --crossing-band-deg 0.25 \
  --hours 168 --step-seconds 1 --output "${PASSES}"
"${BUILD_DIR}/klb_orbit_bench" "${DATA}" \
  --preset file --query crossing --mode all --write-events \
  --samples 9 --min-sample-ms 150 --verify-epochs 4096 \
  --csv "${RESULTS}"

echo "Results: ${RESULTS}"
echo "Coarse pass schedule: ${PASSES}"
