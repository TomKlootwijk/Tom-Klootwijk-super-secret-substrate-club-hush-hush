#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${1:-${ROOT}/external_data}"
mkdir -p "${OUT_DIR}"
curl -L --fail --output "${OUT_DIR}/bunny.tar.gz" \
  "https://graphics.stanford.edu/pub/3Dscanrep/bunny.tar.gz"
tar -xzf "${OUT_DIR}/bunny.tar.gz" -C "${OUT_DIR}"
echo "PLY: ${OUT_DIR}/bunny/reconstruction/bun_zipper.ply"
echo "Review Stanford's attribution and use terms before use beyond testing."
