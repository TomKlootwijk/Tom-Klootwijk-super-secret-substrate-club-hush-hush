#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
OUT_DIR="${OUT_DIR:-$ROOT/../benchmarks/vulkan_native_run}"
SPIRV_DIR="${SPIRV_DIR:-$ROOT/spirv}"
# For the bundled reproducibility run, point this at SwiftShader. On a physical
# Vulkan system, unset VK_ICD_FILENAMES or select the vendor ICD explicitly.
export VK_ICD_FILENAMES="${VK_ICD_FILENAMES:-/usr/lib/chromium/vk_swiftshader_icd.json}"
"$ROOT/scripts/build_swiftshader.sh"
"$BUILD_DIR/ugts_vulkan_bench" \
  --spirv-dir "$SPIRV_DIR" \
  --out-dir "$OUT_DIR" \
  --sizes "${UGTS_SIZES:-1024,16384,262144,1048576}" \
  --warmup "${UGTS_WARMUP:-3}" \
  --iterations "${UGTS_ITERATIONS:-12}"
"$ROOT/tools/summarize_bench.py" \
  "$OUT_DIR/vulkan_benchmark_results.json" \
  "$ROOT/../benchmarks" \
  --bootstrap-json "$ROOT/../benchmarks/latest_run/benchmark_results.json"
