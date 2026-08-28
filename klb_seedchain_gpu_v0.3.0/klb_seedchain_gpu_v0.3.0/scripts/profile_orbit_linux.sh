#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${1:-${ROOT}/build}"
DATA="${ROOT}/data/orbit/gps_ops_2026-08-16_7d_1s.kloc"
OUT="${ROOT}/orbit_seed_profile"

ncu --target-processes all --set full --force-overwrite \
  --export "${OUT}" \
  "${BUILD_DIR}/klb_orbit_bench" "${DATA}" \
  --preset laptop --query crossing --mode seed \
  --samples 1 --min-sample-ms 1 --warmup 0 --verify-epochs 0

echo "Nsight Compute report: ${OUT}.ncu-rep"
