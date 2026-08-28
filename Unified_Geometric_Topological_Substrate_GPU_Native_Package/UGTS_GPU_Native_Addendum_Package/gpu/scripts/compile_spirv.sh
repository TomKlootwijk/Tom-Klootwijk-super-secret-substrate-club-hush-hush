#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/build/spirv}"
mkdir -p "$OUT"
: "${GLSLANG_VALIDATOR:=glslangValidator}"
for shader in "$ROOT"/shaders/vulkan/ugts_eval_*.comp; do
  stem="$(basename "$shader" .comp)"
  profile="${stem#ugts_eval_}"
  for counters in 0 1; do
    mode="evaluate"
    [[ "$counters" == 1 ]] && mode="evaluate_commit"
    target="$OUT/ugts_${profile}_${mode}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DENABLE_COUNTERS="$counters" "$shader" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_${profile}_${mode}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
done
COMPACT_SHADER="$ROOT/shaders/vulkan/ugts_compact_g32.comp"
if [[ -f "$COMPACT_SHADER" ]]; then
  for full_counters in 0 1; do
    mode="append"
    [[ "$full_counters" == 1 ]] && mode="append_counts"
    target="$OUT/ugts_g32_compact_${mode}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DENABLE_FULL_COUNTERS="$full_counters" "$COMPACT_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_g32_compact_${mode}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
fi
SUBGROUP_COMPACT_SHADER="$ROOT/shaders/vulkan/ugts_compact_g32_subgroup.comp"
if [[ -f "$SUBGROUP_COMPACT_SHADER" ]]; then
  for full_counters in 0 1; do
    mode="append"
    [[ "$full_counters" == 1 ]] && mode="append_counts"
    target="$OUT/ugts_g32_compact_subgroup_${mode}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DENABLE_FULL_COUNTERS="$full_counters" "$SUBGROUP_COMPACT_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_g32_compact_subgroup_${mode}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
fi
PRETHRESHOLD_COMPACT_SHADER="$ROOT/shaders/vulkan/ugts_compact_g32_prethreshold_subgroup.comp"
if [[ -f "$PRETHRESHOLD_COMPACT_SHADER" ]]; then
  for full_counters in 0 1; do
    mode="append"
    [[ "$full_counters" == 1 ]] && mode="append_counts"
    target="$OUT/ugts_g32_prethreshold_subgroup_compact_${mode}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DENABLE_FULL_COUNTERS="$full_counters" "$PRETHRESHOLD_COMPACT_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_g32_prethreshold_subgroup_compact_${mode}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
fi
HOT_LOG_COMPACT_SHADER="$ROOT/shaders/vulkan/ugts_compact_g24_logthreshold_subgroup.comp"
if [[ -f "$HOT_LOG_COMPACT_SHADER" ]]; then
  for full_counters in 0 1; do
    mode="append"
    [[ "$full_counters" == 1 ]] && mode="append_counts"
    target="$OUT/ugts_g24_logthreshold_subgroup_compact_${mode}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DENABLE_FULL_COUNTERS="$full_counters" -DUSE_THRESHOLD_LUT=1 "$HOT_LOG_COMPACT_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_g24_logthreshold_subgroup_compact_${mode}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
  for full_counters in 0 1; do
    mode="append"
    [[ "$full_counters" == 1 ]] && mode="append_counts"
    target="$OUT/ugts_g24_logthreshold_direct_subgroup_compact_${mode}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DENABLE_FULL_COUNTERS="$full_counters" -DUSE_THRESHOLD_LUT=0 "$HOT_LOG_COMPACT_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_g24_logthreshold_direct_subgroup_compact_${mode}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
fi
COLD_LINEAGE_COMPACT_SHADER="$ROOT/shaders/vulkan/ugts_compact_g20_cold_lineage_subgroup.comp"
if [[ -f "$COLD_LINEAGE_COMPACT_SHADER" ]]; then
  for full_counters in 0 1; do
    mode="append"
    [[ "$full_counters" == 1 ]] && mode="append_counts"
    target="$OUT/ugts_g20_cold_lineage_subgroup_compact_${mode}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DENABLE_FULL_COUNTERS="$full_counters" "$COLD_LINEAGE_COMPACT_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_g20_cold_lineage_subgroup_compact_${mode}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
fi
LUT_SHADER="$ROOT/shaders/vulkan/ugts_log_lut_probe.comp"
if [[ -f "$LUT_SHADER" ]]; then
  for random_access in 0 1; do
    access="sequential"
    [[ "$random_access" == 1 ]] && access="random"
    target="$OUT/ugts_log_lut_${access}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DRANDOM_ACCESS="$random_access" "$LUT_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_log_lut_${access}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
fi
SSBO_LUT_SHADER="$ROOT/shaders/vulkan/ugts_log_ssbo_probe.comp"
if [[ -f "$SSBO_LUT_SHADER" ]]; then
  for random_access in 0 1; do
    access="sequential"
    [[ "$random_access" == 1 ]] && access="random"
    target="$OUT/ugts_log_ssbo_${access}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DRANDOM_ACCESS="$random_access" "$SSBO_LUT_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_log_ssbo_${access}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
fi
L2_LATENCY_SHADER="$ROOT/shaders/vulkan/ugts_l2_latency_probe.comp"
if [[ -f "$L2_LATENCY_SHADER" ]]; then
  for chase_steps in 0 512; do
    mode="control"
    [[ "$chase_steps" == 512 ]] && mode="chase512"
    target="$OUT/ugts_l2_latency_${mode}.spv"
    "$GLSLANG_VALIDATOR" -V --target-env vulkan1.2 -DCHASE_STEPS="$chase_steps" "$L2_LATENCY_SHADER" -o "$target"
    if command -v spirv-opt >/dev/null 2>&1; then
      spirv-opt -O "$target" -o "$OUT/ugts_l2_latency_${mode}.opt.spv"
    fi
    if command -v spirv-val >/dev/null 2>&1; then
      spirv-val --target-env vulkan1.2 "$target"
    fi
  done
fi
"$ROOT/tools/inspect_spirv.py" "$OUT"/*.spv -o "$OUT/spirv_manifest.json"
echo "SPIR-V outputs written to $OUT"
