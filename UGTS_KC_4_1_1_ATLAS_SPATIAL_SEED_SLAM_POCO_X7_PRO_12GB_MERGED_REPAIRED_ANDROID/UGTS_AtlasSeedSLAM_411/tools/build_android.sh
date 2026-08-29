#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if ! command -v java >/dev/null 2>&1; then
  echo "Java is missing; install JDK 17." >&2
  exit 2
fi
JAVA_VERSION=$(java -version 2>&1 | head -n1)
echo "$JAVA_VERSION"
./gradlew --bootstrap-self-test
./gradlew :app:clean :app:assembleRelease "$@"
APK="$ROOT/app/build/outputs/apk/release/app-release.apk"
if [[ ! -f "$APK" ]]; then
  echo "Expected APK not found: $APK" >&2
  find "$ROOT/app/build/outputs" -type f -name '*.apk' -print 2>/dev/null || true
  exit 3
fi
sha256sum "$APK"
ls -lh "$APK"
if command -v apksigner >/dev/null 2>&1; then
  apksigner verify --verbose "$APK"
fi
