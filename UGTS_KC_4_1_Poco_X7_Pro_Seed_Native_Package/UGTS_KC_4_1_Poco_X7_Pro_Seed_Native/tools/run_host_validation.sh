#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="${TMPDIR:-/tmp}/ugts41-host-build"
rm -rf "$BUILD"
cmake -S "$ROOT/native/host_tests" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release
cmake --build "$BUILD" -j2
"$BUILD/ugts41_host_tests"
"$BUILD/ugts41_demo_builder" "$ROOT/examples"
python3 "$ROOT/tools/kseed_inspect.py" "$ROOT/examples/demo_session.kseed" >/dev/null
echo "UGTS-KC 4.1 host validation passed"
