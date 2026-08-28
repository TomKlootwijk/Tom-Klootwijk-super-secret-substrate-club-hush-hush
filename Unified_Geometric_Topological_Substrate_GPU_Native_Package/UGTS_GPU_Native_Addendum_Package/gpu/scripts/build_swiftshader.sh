#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ANGLE_DIR="${ANGLE_DIR:-/usr/lib/chromium}"
BUILD_DIR="${BUILD_DIR:-$ROOT/build}"
cmake -S "$ROOT" -B "$BUILD_DIR" -G Ninja -DUGTS_ANGLE_DIR="$ANGLE_DIR" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD_DIR"
echo "Built $BUILD_DIR/ugts_bench and $BUILD_DIR/ugts_vulkan_bench"
