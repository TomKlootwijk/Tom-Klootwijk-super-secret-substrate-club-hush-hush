#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADB="${ADB:-adb}"
APP_ID="nl.tomklootwijk.ugtskc.spatial.poco"
DEST="${1:-$ROOT/pulled_sessions}"
mkdir -p "$DEST"
"$ADB" exec-out run-as "$APP_ID" sh -c 'cd files && tar cf - sessions' | tar xf - -C "$DEST"
LATEST="$(find "$DEST/sessions" -type f -name '*.kseed' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)"
[[ -n "$LATEST" ]] || { echo "No .kseed session pulled" >&2; exit 2; }
echo "Latest: $LATEST"
python3 "$ROOT/tools/kseed_inspect.py" "$LATEST" --json
