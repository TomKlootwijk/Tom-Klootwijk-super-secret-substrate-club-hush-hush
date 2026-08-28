#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${1:-${ROOT}/build}"
PRESET="${2:-smoke}"
DATA="${ROOT}/data/sgp4/gps_ops_2026-08-16_7d_1s.ksgp"
RESULTS="${ROOT}/sgp4_${PRESET}_results.csv"
EXPECTED="${ROOT}/data/sgp4/gps_ops_2026-08-16_52N_5E_full_sgp4_pass_events.csv"

"${BUILD_DIR}/klb_sgp4" inspect "${DATA}"
"${BUILD_DIR}/klb_sgp4" verify "${DATA}"

ARGS=("${DATA}" --preset "${PRESET}" --repeats 7 --min-ms 150 --csv "${RESULTS}")
if [[ "${PRESET}" == "smoke" ]]; then
  ARGS+=(--validation-only)
elif [[ "${PRESET}" == "file" ]]; then
  ARGS+=(--expected-events "${EXPECTED}")
fi
"${BUILD_DIR}/klb_sgp4_bench" "${ARGS[@]}"
echo "Results: ${RESULTS}"
