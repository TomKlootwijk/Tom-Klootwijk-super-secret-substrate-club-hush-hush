#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ANGLE_DIR="${ANGLE_DIR:-/usr/lib/chromium}"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
OUT_DIR="${OUT_DIR:-$ROOT/../benchmarks/latest_run}"
export LD_LIBRARY_PATH="$ANGLE_DIR:${LD_LIBRARY_PATH:-}"
export VK_ICD_FILENAMES="${VK_ICD_FILENAMES:-$ANGLE_DIR/vk_swiftshader_icd.json}"
"$ROOT/scripts/build_swiftshader.sh"
"$BUILD_DIR/ugts_bench" \
  --shader-dir "$ROOT/shaders/es" \
  --out-dir "$OUT_DIR" \
  --sizes "${UGTS_SIZES:-1024,16384,262144,1048576}" \
  --warmup "${UGTS_WARMUP:-3}" \
  --iterations "${UGTS_ITERATIONS:-12}"
