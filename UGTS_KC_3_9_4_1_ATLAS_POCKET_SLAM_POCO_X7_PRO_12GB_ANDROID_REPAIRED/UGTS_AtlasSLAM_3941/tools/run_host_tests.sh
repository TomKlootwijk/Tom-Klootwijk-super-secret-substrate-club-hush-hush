#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$ROOT/.host-test-build"
trap 'rm -rf "$BUILD"' EXIT
rm -rf "$BUILD"
mkdir -p "$BUILD/classes"
find "$ROOT/core/src/main/java" -name '*.java' -print0 \
  | xargs -0 javac --release 17 -encoding UTF-8 -Xlint:all -Xlint:-serial -d "$BUILD/classes"
javac --release 17 -encoding UTF-8 -Xlint:all -Xlint:-serial \
  -cp "$BUILD/classes" -d "$BUILD/classes" \
  "$ROOT/tools/host_tests/CoreSelfTest.java"
java -ea -cp "$BUILD/classes" CoreSelfTest
