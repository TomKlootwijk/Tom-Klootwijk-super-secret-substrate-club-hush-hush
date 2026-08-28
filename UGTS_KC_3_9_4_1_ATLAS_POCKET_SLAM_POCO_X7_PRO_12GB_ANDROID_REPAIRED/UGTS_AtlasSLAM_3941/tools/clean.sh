#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
find "$ROOT" -type d \( -name build -o -name .gradle -o -name .cxx -o -name __pycache__ \) -prune -exec rm -rf {} +
find "$ROOT" -type f \( -name '*.pyc' -o -name '*.class' \) -delete
