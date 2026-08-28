# GSP4 Architecture

## 1. Problem statement

Geospatial streams have stable spatial identities but irregular activity. A city, road, sensor, or water-management asset persists, while each time window contains a different number of observations and verified events. A rigid frame tensor wastes storage and couples the model to an arbitrary maximum row count.

GSP4 represents the domain as a sparse typed event graph:

```text
persistent nodes       spatial_entity, sensor, spatial_cell, concept, lineage_state
transient nodes        observation, event
sparse edges           typed relations with time, weight, and local geometric attributes
novelty records        append-only exogenous changes and verified events
```

## 2. Authority separation

```text
Teacher model     semantic supervision only, offline
GNN student       proposal, ranking, relation probability
Spatial index     broad-phase candidate support only
UGTS gate         deterministic support/compatibility/guard/event authority
Novelty chain     durable external changes and verified event lineage
Projection        optional downstream consumer
```

The model is intentionally prevented from turning a semantically plausible relation into a physical event when the deterministic support or guard fails.

## 3. Node and relation vocabulary

Seven node classes are encoded:

| ID | Node type | Persistence |
|---:|---|---|
| 0 | `spatial_entity` | persistent |
| 1 | `sensor` | persistent |
| 2 | `observation` | sparse temporal |
| 3 | `spatial_cell` | persistent broad phase |
| 4 | `concept` | persistent ontology |
| 5 | `event` | sparse temporal |
| 6 | `lineage_state` | persistent/versioned |

Sixteen relation IDs are reserved in a 16-bit compatibility mask:

```text
located_in, adjacent_to, near, observes, made_by_sensor, has_property,
instance_of, affects, descends_from, supersedes, compatible_with,
crossed_guard, transitioned_to, same_cell, connected_to, derived_from
```

Every relation has declared source and target node types and flags for symmetry, geometric support, and guard requirements.

## 4. Spatial support

Morton cells are built in and dependency-free. H3 can be selected as an optional broad-phase backend. Neither is treated as exact geometry.

For a query source, candidate cells are selected first. Local east/north/up coordinates are then computed relative to the source, avoiding global-coordinate FP16 loss. The gate evaluates:

```text
distance <= radius + epsilon
cosine_to_axis >= cone threshold
sheet/mode/orientation/relation mask compatibility
inside or finite-shell guard
semantic student confidence >= threshold
```

Only the survivors become verified events.

## 5. HGT-style student

The student uses:

- node-type embeddings;
- relation-specific key, query, value, and message projections;
- typed multi-head attention;
- edge attributes `[distance, sin bearing, cos bearing, |delta time|]`;
- residual normalization and feed-forward blocks;
- relation scoring heads;
- node-type classification heads;
- teacher-vector projection heads.

It is implemented directly in PyTorch to keep the initial environment small and make the execution graph inspectable.

## 6. TGN-style temporal memory

Irregular event edges update a compact node memory. Time deltas are encoded with periodic frequencies, combined with source state and relation identity, and passed through a gated memory update. There is no requirement for equal frame intervals or equal event counts.

The memory is trained from temporal edges such as `made_by_sensor`, `descends_from`, `supersedes`, `crossed_guard`, and `transitioned_to`.

## 7. Knowledge transfer

Two teacher channels are supported:

1. **Node teacher vectors**: semantic embeddings aligned with the student node state by a cosine objective.
2. **Soft teacher edges**: relation probabilities produced by an LLM, ULTRA, or another structural scorer.

A deterministic candidate generator bounds teacher work through type compatibility and distance. The teacher may abstain. Geometric verification is never delegated to the language model.

## 8. Identity and seed-chain persistence

A coordinate is an observation about an entity, not the entity itself. Durable identity is represented by:

```text
persistent uint64 node ID
uint32 lineage seed
schema/version hash
ordered relation and transition history
hash-linked novelty/event records
```

Closed state may be regenerated from stable graph/model/seed state. External measurements, manual corrections, new entities, splits, merges, ontology changes, and verified events enter the novelty log.

## 9. UGTS bridge

The bridge exports candidate state into both substrate profiles:

- G64: 64-byte authoritative state record.
- G32: 32-byte packed state record with FP16 pairs.

The exporter measures packed error and declares whether the maximum position error remains below the requested guard epsilon. Packing is rejected as a correctness substitute when that contract fails.

## 10. Deployment archive

A `.ugdeploy` archive contains:

```text
graph.ugkg
student_model.pt
novelty.ugnl
ontology.json
runtime.json
attribution.json
manifest.json
optional validation and bridge evidence
```

Every member has a SHA-256 and byte count in the manifest. Model and graph schema hashes must match. Novelty-chain validation must reproduce the terminal hash.
