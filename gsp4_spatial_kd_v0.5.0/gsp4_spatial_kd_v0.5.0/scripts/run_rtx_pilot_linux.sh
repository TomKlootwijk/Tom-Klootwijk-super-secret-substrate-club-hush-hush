#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
OUT=results/rtx_pilot
mkdir -p "$OUT"
python -m ugts_spatial check-gpu --device cuda --precision float16 --output "$OUT/gpu_environment.json"
python -m ugts_spatial train data/flevoland_pilot.ugkg "$OUT/flevoland_rtx_student.pt" \
  --teacher-edges examples/teacher_edges_smoke.ugte \
  --metrics "$OUT/training_metrics.json" \
  --hidden-dim 128 --heads 8 --layers 4 --epochs 30 \
  --max-edges 8000 --max-encoder-edges 16000 --temporal-edges 2048 \
  --device cuda --precision float16
python -m ugts_spatial query data/flevoland_pilot.ugkg \
  --model "$OUT/flevoland_rtx_student.pt" \
  --source sensor:1:1:air --relation near --radius 10000 --epsilon 25 \
  --confidence-min 0.5 --max-events 32 --device cuda --precision float16 \
  --output "$OUT/query.json"
python -m ugts_spatial benchmark data/flevoland_pilot.ugkg "$OUT/flevoland_rtx_student.pt" \
  --source sensor:1:1:air --relation near --radius 10000 --epsilon 25 \
  --warmup 10 --repeats 50 --device cuda --precision float16 \
  --output "$OUT/benchmark.json"
python -m ugts_spatial package data/flevoland_pilot.ugkg "$OUT/flevoland_rtx.ugdeploy" \
  --model "$OUT/flevoland_rtx_student.pt" --novelty data/flevoland_pilot.ugnl \
  --ontology ontology/gsp4_ontology.json
python -m ugts_spatial validate-package "$OUT/flevoland_rtx.ugdeploy" > "$OUT/deployment_validation.json"
printf 'RTX pilot complete: %s\n' "$ROOT/$OUT"
