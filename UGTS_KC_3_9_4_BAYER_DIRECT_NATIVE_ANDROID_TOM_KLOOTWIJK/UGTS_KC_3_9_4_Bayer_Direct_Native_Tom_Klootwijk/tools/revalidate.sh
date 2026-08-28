#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python -m unittest discover -s tests -v
python tools/apk_v2_verify.py dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk
jarsigner -verify dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk
unzip -t dist/UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk
