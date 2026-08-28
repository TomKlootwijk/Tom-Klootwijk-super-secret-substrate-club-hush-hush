#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
mkdir -p results/no_download
python -m ugts_spatial inspect-graph data/flevoland_pilot.ugkg > results/no_download/graph.json
python -m ugts_spatial validate-novelty data/flevoland_pilot.ugnl > results/no_download/novelty.json
python -m ugts_spatial inspect-teacher examples/teacher_edges_smoke.ugte > results/no_download/teacher.json
python -m ugts_spatial query data/flevoland_pilot.ugkg \
  --model models/gsp4_flevoland_student_smoke.pt \
  --source sensor:1:1:air --relation near --radius 10000 --epsilon 25 \
  --max-events 32 --device cpu --precision float32 \
  --output results/no_download/query.json > results/no_download/query_console.json
python -m ugts_spatial validate-package data/gsp4_flevoland_smoke.ugdeploy \
  > results/no_download/deployment.json
python -m pytest -q | tee results/no_download/tests.txt
printf 'GSP4 no-download validation complete: %s\n' "$ROOT/results/no_download"
