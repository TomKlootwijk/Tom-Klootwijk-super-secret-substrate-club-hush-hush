#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/android_project"
: "${ANDROID_SDK_ROOT:=${ANDROID_HOME:-}}"
if [[ -z "${ANDROID_SDK_ROOT}" ]]; then
  echo "Set ANDROID_SDK_ROOT (or ANDROID_HOME) to an Android SDK containing API 36." >&2
  exit 2
fi
if [[ ! -f local.properties ]]; then
  printf 'sdk.dir=%s\n' "$ANDROID_SDK_ROOT" > local.properties
fi
./gradlew --no-daemon clean :app:assemblePocoX7ProRelease
APK="$ROOT/android_project/app/build/outputs/apk/pocoX7Pro/release/app-pocoX7Pro-release.apk"
[[ -f "$APK" ]] || { echo "Expected APK not found: $APK" >&2; exit 3; }
sha256sum "$APK"
echo "$APK"
