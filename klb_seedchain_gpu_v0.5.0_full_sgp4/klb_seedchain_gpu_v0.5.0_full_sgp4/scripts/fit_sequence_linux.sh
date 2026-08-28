#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 frames.txt output.klsc [extra klb_seedchain options...]" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-${ROOT}/build}"
LIST="$1"
OUTPUT="$2"
shift 2
"${BUILD_DIR}/klb_seedchain" fit-sequence "${LIST}" "${OUTPUT}" \
  --checkpoint 16 --residual-threshold 0.002 "$@"
