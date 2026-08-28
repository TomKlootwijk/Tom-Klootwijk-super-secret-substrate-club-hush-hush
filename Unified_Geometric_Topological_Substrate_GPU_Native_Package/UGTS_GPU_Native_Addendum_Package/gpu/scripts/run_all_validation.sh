#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Stage 1: compile GLSL ES through ANGLE, retrieve native program binaries, and
# extract the embedded SPIR-V modules used for the bundled reproducibility set.
"$ROOT/scripts/run_benchmarks.sh"
mkdir -p "$ROOT/spirv"
cp "$ROOT/../benchmarks/latest_run/native_cache/G64_E32_evaluate_module.spv" "$ROOT/spirv/ugts_g64_evaluate.spv"
cp "$ROOT/../benchmarks/latest_run/native_cache/G64_E32_evaluate_commit_module.spv" "$ROOT/spirv/ugts_g64_evaluate_commit.spv"
cp "$ROOT/../benchmarks/latest_run/native_cache/G32_E16_evaluate_module.spv" "$ROOT/spirv/ugts_g32_evaluate.spv"
cp "$ROOT/../benchmarks/latest_run/native_cache/G32_E16_evaluate_commit_module.spv" "$ROOT/spirv/ugts_g32_evaluate_commit.spv"
"$ROOT/tools/inspect_spirv.py" "$ROOT"/spirv/*.spv -o "$ROOT/spirv/spirv_manifest.json"
# Stage 2: execute those modules through the direct Vulkan runtime.
"$ROOT/scripts/run_vulkan_benchmarks.sh"
