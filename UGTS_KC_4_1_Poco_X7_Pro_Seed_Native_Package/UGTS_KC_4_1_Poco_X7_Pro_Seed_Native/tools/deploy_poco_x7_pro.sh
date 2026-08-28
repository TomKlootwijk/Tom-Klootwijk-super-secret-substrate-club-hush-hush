#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADB="${ADB:-adb}"
APK="${1:-$ROOT/android_project/app/build/outputs/apk/pocoX7Pro/release/app-pocoX7Pro-release.apk}"
APP_ID="nl.tomklootwijk.ugtskc.spatial.poco"
command -v "$ADB" >/dev/null || { echo "adb not found" >&2; exit 2; }
[[ -f "$APK" ]] || { echo "APK not found: $APK" >&2; exit 3; }
MODEL="$($ADB shell getprop ro.product.model | tr -d '\r')"
DEVICE="$($ADB shell getprop ro.product.device | tr -d '\r')"
ABIS="$($ADB shell getprop ro.product.cpu.abilist | tr -d '\r')"
printf 'Connected model: %s\nDevice: %s\nABIs: %s\n' "$MODEL" "$DEVICE" "$ABIS"
[[ "$ABIS" == *arm64-v8a* ]] || { echo "Connected device lacks arm64-v8a" >&2; exit 4; }
case "${MODEL,,} ${DEVICE,,}" in
  *poco*x7*pro*|*rodin*|*2412dpc0*) ;;
  *)
    echo "Connected device does not match known POCO X7 Pro hints." >&2
    read -r -p "Continue anyway? [y/N] " answer
    [[ "${answer,,}" == y ]] || exit 5
    ;;
esac
"$ADB" install -r "$APK"
"$ADB" shell pm grant "$APP_ID" android.permission.CAMERA || true
"$ADB" shell am start -n "$APP_ID/android.app.NativeActivity"
echo "Launched $APP_ID"
