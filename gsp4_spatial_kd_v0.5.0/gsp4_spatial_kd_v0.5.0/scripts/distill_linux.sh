#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source .venv/bin/activate
GRAPH="${1:-data/flevoland_pilot.ugkg}"
OUT="${2:-results/distillation}"
mkdir -p "$OUT"
python -m ugts_spatial embed "$GRAPH" "$OUT/semantic.ugkg" \
  --backend http --base-url http://127.0.0.1:8080/v1 \
  --model Qwen3-Embedding --dimensions 256 --batch-size 32
python -m ugts_spatial teacher-candidates "$OUT/semantic.ugkg" "$OUT/candidates.jsonl" \
  --max-distance 12000 --concepts-per-source 4 --spatial-per-source 6 --max-candidates 2000
python -m ugts_spatial teacher-label "$OUT/candidates.jsonl" "$OUT/labels.jsonl" \
  --base-url http://127.0.0.1:8081/v1 --model Qwen3-4B --limit 2000 --progress
python -m ugts_spatial labels-to-edges "$OUT/semantic.ugkg" "$OUT/labels.jsonl" \
  "$OUT/relation_teacher.ugte" --teacher-name qwen3-4b-local
python -m ugts_spatial train "$OUT/semantic.ugkg" "$OUT/student.pt" \
  --teacher-edges "$OUT/relation_teacher.ugte" --metrics "$OUT/training.json" \
  --hidden-dim 128 --heads 8 --layers 4 --epochs 30 --device auto --precision float16
