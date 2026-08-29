#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
rm -rf "$ROOT/cpp/build/host-release"
pushd "$ROOT/cpp" >/dev/null
cmake --preset host-release
cmake --build --preset host-release -j "${JOBS:-2}"
ctest --preset host-release --output-on-failure
popd >/dev/null
cd "$ROOT"
UGTS_GPU_HOST_EXE="$ROOT/cpp/build/host-release/ugts-chess-gpu" PYTHONPATH=src \
  python -m unittest discover -s tests -v
cpp/build/host-release/ugts-chess2 selftest
cpp/build/host-release/ugts-chess-gpu self-test
