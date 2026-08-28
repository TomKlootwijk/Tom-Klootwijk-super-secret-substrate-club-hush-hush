#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cc -O3 -std=c11 -D_POSIX_C_SOURCE=200809L -Wall -Wextra -Wpedantic \
  "$ROOT/tools/host_preview.c" \
  "$ROOT/app/src/main/cpp/bayer_core.c" \
  -o "$ROOT/tools/host_preview"
echo "built $ROOT/tools/host_preview"
