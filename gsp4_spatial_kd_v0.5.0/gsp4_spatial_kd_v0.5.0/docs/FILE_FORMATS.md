# GSP4 File Formats

## `.ugkg` — UGKG2 sparse graph

A `.ugkg` file is a ZIP-based portable container written by NumPy and JSON. It stores dense node columns and sparse edge columns, not padded temporal frames.

Principal node arrays:

```text
x                  float32 [N,input_dim]
node_type          int64   [N]
node_id            uint64  [N]
latitude/longitude float64 [N]
elevation          float32 [N]
node_time          float64 [N]
cell_id            uint64  [N]
split              int8    [N]
sheet              uint8   [N]
orientation        uint8   [N]
compatibility_mask uint16  [N]
lineage_seed       uint32  [N]
teacher_x          float32 [N,teacher_dim]
teacher_mask       bool    [N]
keys/texts         JSON rows
```

Principal edge arrays:

```text
edge_index   int64   [2,E]
edge_type    int64   [E]
edge_time    float64 [E]
edge_weight  float32 [E]
edge_attr    float32 [E,4]
```

`edge_attr` is fixed to:

```text
[distance_m, sin_bearing, cos_bearing, abs_delta_time_s]
```

The schema hash covers format, dimensions, node/relation vocabularies, ontology version, coordinate reference, feature schema, and spatial-index contract.

## `.ugnl` — UGNL3 novelty chain

The novelty file begins with a versioned header and contains fixed 72-byte records. Each record includes:

```text
sequence
timestamp
operation ID
relation ID
flags
source uint64 ID
target uint64 ID
value
confidence
lineage hash
parent record hash
self record hash
```

Validation checks monotonically ordered sequence numbers, parent links, every self hash, and the terminal hash. Operations cover observations, node/edge changes, verified events, identity changes, and ontology changes.

## `.ugte` — soft teacher edges

A teacher-edge file stores bounded relation supervision:

```text
source node ID
target node ID
relation ID
probability/confidence
teacher name
schema hash
provenance metadata
```

Graph schema and node IDs must match before training.

## `.ugdeploy` — deployment archive

A deployment is a ZIP archive with `manifest.json`. Every included member has a byte count and SHA-256. It can include graph, student, novelty chain, ontology, runtime contract, attribution, validation, and UGTS bridge evidence.

## UGTS G64/G32 bridge

G64 is the authoritative 64-byte state ABI:

```text
position_time  4 × float32
axis_radius    4 × float32
phase_guard    4 × float32
meta           4 × uint32
```

G32 packs the twelve scalar values into six IEEE binary16 pairs plus topology and lineage words. Export metadata contains maximum position/scalar error and a boolean precision-within-guard verdict.

## JSON/JSONL interchange

- Teacher candidates and labels use JSON Lines for resumable bounded inference.
- Query and benchmark outputs use deterministic JSON.
- Ontology and relation contracts use versioned JSON/JSON-LD.
- ULTRA interchange uses tab-separated triples plus a JSON manifest.
