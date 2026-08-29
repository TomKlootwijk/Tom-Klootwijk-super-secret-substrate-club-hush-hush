#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d -t ugts-seed-host-XXXXXX)"
trap 'rm -rf "$TMP"' EXIT
cmake -S "$ROOT/native/host_tests" -B "$TMP/build" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$TMP/build" --parallel >/dev/null
"$TMP/build/ugts_seed_host_tests"
