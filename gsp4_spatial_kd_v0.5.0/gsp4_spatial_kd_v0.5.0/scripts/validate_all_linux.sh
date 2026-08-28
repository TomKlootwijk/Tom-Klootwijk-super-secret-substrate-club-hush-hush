#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
mkdir -p results/validation_replay
python -m pytest -q | tee results/validation_replay/tests.txt
python -m ugts_spatial inspect-graph data/flevoland_pilot.ugkg > results/validation_replay/graph.json
python -m ugts_spatial validate-novelty data/flevoland_pilot.ugnl > results/validation_replay/novelty.json
python -m ugts_spatial validate-package data/gsp4_flevoland_smoke.ugdeploy > results/validation_replay/deployment.json
python -m compileall -q src scripts/verify_manual_asset.py
python -m build
sha256sum dist/* > results/validation_replay/dist.sha256
