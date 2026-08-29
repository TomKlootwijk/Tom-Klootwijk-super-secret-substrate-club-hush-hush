# Full 19×19 proof-certificate design

The delivered tiny certificates are recomputation records. This document defines
the intended stronger certificate needed for a publishable 19×19 threshold
result.

## Root envelope

The certificate begins with canonical encodings and digests for:

- rules profile;
- initial empty state;
- threshold in half-points;
- move/point ordering;
- state and history serialization versions;
- proof arithmetic and infinity value;
- certificate format version.

## DAG node kinds

### Terminal

Contains exact board/history references, two-pass witness, full area partition,
Black/White area, komi, score2, and threshold truth.

### OR proof

For a proven Black-to-play node, contains one legal child proof. For a disproven
Black-to-play node, contains every distinct legal child disproof after certified
symmetry/dominance reductions.

### AND proof

For a proven White-to-play node, contains every distinct legal child proof. For
a disproven White-to-play node, contains one legal child disproof.

### Reduction witness

Identifies the reduction type, assumptions, transformed/removed children, and an
independently checkable implication. Examples are full-history D4 equivalence or
certified unconditional territory.

### Transposition link

References a node with collision-safe complete-state identity. The verifier must
check the board, player, pass count, full repetition context, and profile—not
only a digest.

## Legal-child quantification

Whenever “all children” are required, the verifier independently enumerates the
legal action set from the exact state and accounts for every action through one
of:

- an explicit child edge;
- a verified D4-equivalence edge;
- a verified reduction witness.

A principal variation cannot satisfy an all-child obligation.

## Merkle organization

Each canonical node record is hashed. Child hashes are ordered deterministically.
Immutable segment manifests form a Merkle forest whose root is embedded in the
certificate envelope. The verifier streams segments and may discard checked
records, avoiding a requirement to fit the full DAG in memory.

## Independent verifier

The verifier should be a small implementation with no shared search code. It
needs only:

- rules transition and legal-action enumeration;
- exact superko context decoding;
- terminal area scoring;
- reduction-witness checkers;
- content hash and Merkle verification;
- AND/OR quantifier validation.

It does not need move ordering, neural models, transposition heuristics, or GPU
kernels.

## Fault containment

Every segment has length, version, checksum, and SHA-256. References include the
expected object kind. The verifier rejects duplicate/conflicting object IDs,
integer overflow, unknown witness types, missing child obligations, rules/root
mismatch, and any unresolved content collision.
