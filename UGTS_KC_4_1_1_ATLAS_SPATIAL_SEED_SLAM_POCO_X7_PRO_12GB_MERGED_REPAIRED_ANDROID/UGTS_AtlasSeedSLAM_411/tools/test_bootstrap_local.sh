#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/project/gradle/wrapper" "$TMP/dist/gradle-8.13/bin" "$TMP/home"
cp "$ROOT/gradle/wrapper/gradle-wrapper.jar" "$TMP/project/gradle/wrapper/"
cp "$ROOT/gradlew" "$TMP/project/"
cat > "$TMP/dist/gradle-8.13/bin/gradle" <<'SH'
#!/bin/sh
printf 'LOCAL_FAKE_GRADLE_OK:%s\n' "$*"
SH
chmod +x "$TMP/dist/gradle-8.13/bin/gradle"
(
  cd "$TMP/dist"
  python3 - <<'PY'
from pathlib import Path
import zipfile
root=Path('.')
with zipfile.ZipFile('../gradle-8.13-bin.zip','w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted((root/'gradle-8.13').rglob('*')):
        if p.is_file(): z.write(p,p.as_posix())
PY
)
SHA=$(sha256sum "$TMP/gradle-8.13-bin.zip" | awk '{print $1}')
URL=$(python3 - "$TMP/gradle-8.13-bin.zip" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).resolve().as_uri())
PY
)
cat > "$TMP/project/gradle/wrapper/gradle-wrapper.properties" <<PROP
distributionUrl=$URL
distributionSha256Sum=$SHA
networkTimeout=30000
PROP
OUT=$(cd "$TMP/project" && GRADLE_USER_HOME="$TMP/home" ./gradlew alpha beta)
test "$OUT" = "LOCAL_FAKE_GRADLE_OK:alpha beta"
printf 'UGTS local bootstrap download/hash/extract/execute test: PASS\n'
