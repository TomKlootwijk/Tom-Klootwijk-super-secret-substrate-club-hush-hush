#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/.bootstrap-build"
rm -rf "$BUILD"
mkdir -p "$BUILD/classes"
javac --release 8 -encoding UTF-8 -d "$BUILD/classes" \
  "$ROOT/tools/bootstrap-src/org/gradle/wrapper/GradleWrapperMain.java"
jar --create --file "$ROOT/gradle/wrapper/gradle-wrapper.jar" -C "$BUILD/classes" .
rm -rf "$BUILD"
"$ROOT/gradlew" --bootstrap-self-test
