# Design: Sparse Spatial Knowledge Transfer over UGTS

## 1. Problem representation

A fluctuating number of observations is not represented by a fluctuating number
of persistent identities. The model distinguishes:

| Persistent node | Variable record |
|---|---|
| sensor | observation update |
| city, road or building | detected condition |
| spatial cell | membership/change event |
| ontology concept | classification assertion |
| lineage root | ordered transition/novelty record |

The graph therefore has three independent sparse lengths:

```text
N persistent nodes
E typed relations
M time-stamped events
```

No `maximum_points_per_frame` appears in the file format or model API.

## 2. Query-first path

```text
source identity
   ↓
H3/Morton broad-phase support
   ↓
exact local ENU cone/sphere/SDF support
   ↓
relation source/target compatibility
   ↓
student semantic probability
   ↓
deterministic guard + calibrated threshold
   ↓
verified event
   ↓
route + lineage checksum + append-only novelty
```

The H3/Morton phase is conservative candidate selection. Exact metric geometry
is authoritative. A semantic score cannot turn an out-of-support candidate into
a verified event.

## 3. Student model

### Temporal memory

Each event contains:

```text
entity_index, event_type, event_time, value[4]
```

The event encoder computes age features, maps each event to a message, aggregates
mean and maximum per persistent entity, and performs a GRU update. Empty and
irregular streams are legal.

### Heterogeneous graph layer

Each relation has typed attention, message and value parameters. Queries, keys,
values and outputs are type-specific. Attention normalizes over incoming sparse
COO edges per destination. The layer does not materialize an `N×N` matrix.

### Link decoder

A candidate score combines:

- relation-specific diagonal bilinear similarity;
- learned source/target difference and product features;
- relation embedding;
- exact distance and age features.

The decoder emits a logit. Thresholds are selected on the validation region and
stored with the checkpoint.

## 4. Teacher separation

A teacher can contribute two artifacts:

1. Compact node embeddings.
2. Soft probabilities for candidate relations.

Training aligns the student to both while retaining the hard supervised task.
Teacher calls are offline. Runtime does not call an LLM or embedding model.

## 5. Ontology compilation

The runtime ontology is a small GPU schema, not an RDF reasoner. It records:

```text
node_type ID
relation ID
allowed source types
allowed target types
mode bit
sheet
relation guard family
```

External ontology URIs are preserved in the schema for interoperability, while
the hot path uses integer fields.

## 6. Spatial split

The demo does not randomly split nearby rows. Complete geographic anchors form
train, validation and test groups:

```text
train: Almere, Lelystad, Dronten
validation: Emmeloord
holdout test: Urk, Zeewolde
```

Real deployments should also use temporal and ontological holdouts.

## 7. Compression relationship

The sparse graph is a knowledge-transfer layer, not a replacement for KLB37 or
KLSC seed-chain geometry. They can be composed:

```text
KLB/KLSC compressed persistent geometry
      + sparse graph topology
      + irregular event/novelty stream
      + distilled node state
```

Coordinates and guard-critical fields must respect the UGTS event-margin
contract. Semantic vectors may be more aggressively compressed because they
propose candidates rather than deciding geometric truth.
