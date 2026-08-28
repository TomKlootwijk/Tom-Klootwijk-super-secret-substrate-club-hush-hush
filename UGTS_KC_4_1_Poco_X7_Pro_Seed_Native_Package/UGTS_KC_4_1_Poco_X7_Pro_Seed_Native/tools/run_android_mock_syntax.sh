#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOCK="${ANDROID_MOCK_HEADERS:-/home/oai/share/_android_mock}"
CPP="$ROOT/android_project/app/src/main/cpp"
OUT="$ROOT/validation/android_cpp_mock_syntax_final.txt"
[[ -d "$MOCK" ]] || { echo "Mock headers not present: $MOCK" >&2; exit 2; }
: > "$OUT"
pass=0; total=0
for f in main.cpp engine.cpp camera_ndk.cpp imu_ndk.cpp permissions.cpp thermal_policy.cpp device_profile.cpp renderer_bayer.cpp storage_android.cpp; do
  total=$((total+1)); echo "--- $f" | tee -a "$OUT"
  if g++ -std=c++20 -fsyntax-only -Wno-unused-parameter -I"$MOCK" -I"$CPP" "$CPP/$f" >> "$OUT" 2>&1; then
    echo "PASS: $f" | tee -a "$OUT"; pass=$((pass+1))
  else
    echo "FAIL: $f" | tee -a "$OUT"
  fi
done
echo "TOTAL PASS: $pass/$total" | tee -a "$OUT"
[[ "$pass" -eq "$total" ]]
