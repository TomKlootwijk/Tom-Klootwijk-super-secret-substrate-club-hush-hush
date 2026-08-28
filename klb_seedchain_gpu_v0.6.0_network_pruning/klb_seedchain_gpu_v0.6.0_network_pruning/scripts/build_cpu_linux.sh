#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${1:-${ROOT}/build-cpu}"

cmake -S "${ROOT}" -B "${BUILD_DIR}" \
  -DCMAKE_BUILD_TYPE=Release \
  -DKLB_BUILD_CUDA=OFF
cmake --build "${BUILD_DIR}" -j
ctest --test-dir "${BUILD_DIR}" --output-on-failure
