#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$(mktemp -d -t ugts-kseed-fixture-XXXXXX)"
trap 'rm -rf "$BUILD"' EXIT
mkdir -p "$BUILD/classes"
find "$ROOT/core/src/main/java" -name '*.java' -print0 \
  | xargs -0 javac --release 17 -encoding UTF-8 -d "$BUILD/classes"
javac --release 17 -encoding UTF-8 -cp "$BUILD/classes" -d "$BUILD/classes" \
  "$ROOT/tools/host_tests/GenerateKSeedFixture.java"
java -cp "$BUILD/classes" GenerateKSeedFixture \
  "$ROOT/samples/atlas_seed_slam_411_fixture.kseed" \
  "$ROOT/samples/atlas_seed_slam_411_fixture_summary.json"
