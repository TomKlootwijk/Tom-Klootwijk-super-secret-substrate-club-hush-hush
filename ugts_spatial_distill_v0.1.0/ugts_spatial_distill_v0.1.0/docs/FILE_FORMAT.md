# UGTS Sparse Temporal Graph Directory Format

Format identifier:

```text
UGTS-SPARSE-TEMPORAL-GRAPH-1
```

Each field is stored as an independent `.npy` array so it can be memory-mapped.
The format intentionally has no frame axis.

## Node arrays

| File | Shape | Meaning |
|---|---:|---|
| `node_ids.npy` | `[N] uint64` | stable namespaced identities |
| `node_types.npy` | `[N] int16` | ontology node type |
| `node_coords.npy` | `[N,3] float64` | latitude, longitude, altitude attributes |
| `node_features.npy` | `[N,F] float32` | compact student input features |
| `lineage_seed.npy` | `[N] uint32` | hot-path checksum seed |
| `texts.jsonl` | `N` lines | semantic source text keyed by ID |

## Sparse relations

| File | Shape | Meaning |
|---|---:|---|
| `edge_src.npy` | `[E] int64` | source node index |
| `edge_dst.npy` | `[E] int64` | destination node index |
| `edge_type.npy` | `[E] int16` | relation ID |
| `edge_time.npy` | `[E] float64` | edge assertion/update time |
| `edge_weight.npy` | `[E] float32` | bounded message weight |
| `edge_flags.npy` | `[E] uint16` | schema-defined flags |

## Irregular event stream

| File | Shape | Meaning |
|---|---:|---|
| `event_entity.npy` | `[M] int64` | persistent entity index |
| `event_time.npy` | `[M] float64` | event time |
| `event_type.npy` | `[M] int16` | event type |
| `event_value.npy` | `[M,4] float32` | typed compact values |
| `event_flags.npy` | `[M] uint16` | event flags |

## Distillation examples

| File | Shape | Meaning |
|---|---:|---|
| `ex_src.npy` | `[Q] int64` | source node |
| `ex_dst.npy` | `[Q] int64` | target node |
| `ex_relation.npy` | `[Q] int16` | candidate relation |
| `ex_label.npy` | `[Q] float32` | hard target |
| `ex_teacher_prob.npy` | `[Q] float32` | soft teacher target |
| `ex_time.npy` | `[Q] float64` | candidate time |
| `ex_distance_m.npy` | `[Q] float32` | exact/precomputed distance |
| `ex_split.npy` | `[Q] uint8` | 0 train, 1 validation, 2 test |

## Teacher vectors

Optional:

```text
teacher_embeddings.npy [N,D] float16
teacher_mask.npy       [N] bool
```

The model identifier, source dimension, projection and timestamp live in
`manifest.json` metadata.

## Integrity

`manifest.json` records every array's SHA-256, shape and dtype. Loading with
`verify_hashes=True` rejects any changed field. This is file integrity, not a
cryptographic proof of semantic correctness.
