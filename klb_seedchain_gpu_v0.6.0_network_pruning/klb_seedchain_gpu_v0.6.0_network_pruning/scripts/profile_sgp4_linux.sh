#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${1:-${ROOT}/build}"
PRESET="${2:-file}"
DATA="${ROOT}/data/sgp4/gps_ops_2026-08-16_7d_1s.ksgp"
REPORT="${ROOT}/sgp4_${PRESET}_ncu"

ncu --set full --target-processes all --export "${REPORT}" --force-overwrite \
  "${BUILD_DIR}/klb_sgp4_bench" "${DATA}" \
  --preset "${PRESET}" --repeats 1 --min-ms 25 --skip-events
