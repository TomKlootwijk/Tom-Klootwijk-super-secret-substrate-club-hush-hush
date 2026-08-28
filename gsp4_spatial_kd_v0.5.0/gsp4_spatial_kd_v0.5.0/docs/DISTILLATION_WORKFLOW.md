# Offline Teacher → GSP4 Student Distillation

## Objective

Transfer semantic and relational knowledge from a model that may be too large or too slow for continuous edge deployment into a compact sparse GNN. The teacher can run locally, with partial GPU offload, on CPU, or through a hosted OpenAI-compatible API.

## A. Semantic embedding transfer

Start a local embedding endpoint and compile teacher vectors into the graph:

```bash
gsp4 embed data/flevoland_pilot.ugkg work/flevoland_semantic.ugkg \
  --backend http \
  --base-url http://127.0.0.1:8080/v1 \
  --model Qwen3-Embedding \
  --dimensions 256 \
  --batch-size 32
```

The HTTP adapter calls `/v1/embeddings`. Returned vectors are normalized and truncated to the requested Matryoshka dimension when the server returns a larger vector.

A 256-dimensional FP16 deployment cache costs 512 bytes per embedded entity before container overhead. The teacher weights do not enter `.ugdeploy`.

## B. Bounded relation labeling

Generate candidates before calling a chat model:

```bash
gsp4 teacher-candidates work/flevoland_semantic.ugkg work/candidates.jsonl \
  --max-distance 12000 \
  --concepts-per-source 4 \
  --spatial-per-source 6 \
  --max-candidates 5000
```

The generator includes only declared relation types and relevant deterministic fields. This prevents unrestricted relation invention and sharply reduces token use.

Label a bounded slice:

```bash
gsp4 teacher-label work/candidates.jsonl work/labels.jsonl \
  --base-url http://127.0.0.1:8081/v1 \
  --model Qwen3-4B \
  --limit 1000 \
  --progress
```

The teacher must return:

```json
{
  "relation": "near",
  "confidence": 0.83,
  "abstain": false,
  "requires_geometric_verification": true,
  "evidence_fields": ["source_text", "target_text"],
  "rationale": "bounded explanation"
}
```

A returned relation outside the candidate's allowed vocabulary is rejected.

Compile the labels:

```bash
gsp4 labels-to-edges work/flevoland_semantic.ugkg work/labels.jsonl \
  work/relation_teacher.ugte --teacher-name qwen3-4b-local
```

## C. Structural transfer with ULTRA or another scorer

Export typed triples:

```bash
gsp4 export-ultra work/flevoland_semantic.ugkg work/ultra
```

Run ULTRA separately, or use any scorer that emits source, relation, target, and probability. Import the scored triples:

```bash
gsp4 import-scores work/flevoland_semantic.ugkg work/ultra_scores.tsv \
  work/ultra_teacher.ugte --teacher-name ultra
```

ULTRA itself is not bundled. The adapter is intentionally tool-agnostic so structural probabilities can come from ULTRA, a hosted knowledge-graph service, or an internal scorer.

## D. Student training

Train with node-vector and soft-edge teachers:

```bash
gsp4 train work/flevoland_semantic.ugkg models/flevoland_student.pt \
  --teacher-edges work/relation_teacher.ugte \
  --metrics results/flevoland_training.json \
  --hidden-dim 128 --heads 8 --layers 4 \
  --epochs 30 --device cuda --precision float16
```

The total objective combines:

```text
observed link discrimination
teacher embedding alignment
soft teacher-edge relation loss
node type prediction
temporal memory/order loss
```

Teacher labels are supervision, not facts. Keep teacher name, model revision, prompt schema, confidence, and input evidence as provenance.

## E. Query-time deployment

The teacher is absent online:

```bash
gsp4 query work/flevoland_semantic.ugkg \
  --model models/flevoland_student.pt \
  --source sensor:1:1:air --relation near \
  --radius 10000 --epsilon 25 \
  --confidence-min 0.55 --device cuda --precision float16 \
  --commit data/live_events.ugnl \
  --output results/query.json
```

The student ranks candidates, but a query can commit only after deterministic support, compatibility, and guard evaluation.

## F. Recommended quality gates

- Hold out complete spatial cells, not random neighboring rows.
- Hold out later time ranges for temporal evaluation.
- Hold out selected ontology types or relations for transfer evaluation.
- Report link MRR/Hits@K, event AUPRC, calibration, lineage mismatches, event-order mismatches, bytes/event, peak VRAM, and candidate rejection gain.
- Compare against rule-only UGTS, R-GCN/GraphSAGE, HGT without teacher transfer, and HGT with each teacher channel.
- Reject a model when quantization changes event ordering or teacher scores bypass deterministic geometry.
