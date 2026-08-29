# Exactness contract

This file is normative for every optimization performed by Codex or a human
contributor.

## Proof-authoritative data

A transition or proof update is authoritative only when all of these are exact:

- board occupancy;
- player to move;
- consecutive-pass state;
- capture result;
- own-liberty/suicide guard;
- positional-superko membership;
- terminal recognition;
- area score in integer half-points;
- AND/OR role;
- proof and disproof arithmetic with saturation, not wraparound.

## Allowed accelerators

The following may reorder work but may not determine truth:

- policy networks;
- value networks;
- MCTS or rollout estimates;
- pattern priors;
- local tactical solvers whose assumptions are not certified;
- lossy GPU caches;
- probabilistic filters;
- bloom filters;
- 64-bit or 128-bit hashes without equality verification.

A false-positive probabilistic membership test may trigger an exact lookup. It
may not reject a legal move by itself.

## Sound transpositions

A transposition key must include the complete superko context. Acceptable designs
include:

1. exact immutable history values in the key;
2. a collision-checked content-addressed persistent set;
3. a Merkle-rooted history object whose equality is independently verified.

A board hash plus side to move is explicitly forbidden for proof values.

## Sound symmetry

D4 canonicalization is sound only over the complete state. Transforming the
current board while leaving history unchanged is forbidden. When storing a move
inside a canonical entry, store the transform and invert it on retrieval.

## Sound pruning

Allowed after implementation and tests:

- alpha-beta bounds with correct TT flags;
- proof/disproof propagation;
- score interval bounds that enclose all completions;
- unconditional-life/territory certificates;
- exact local decomposition with a separator proof;
- dominance where a formal implication is recorded;
- duplicate D4 action classes.

Not allowed:

- pruning because a move “looks bad”;
- treating neural confidence as a bound;
- assuming two regions are independent without a separator/interface proof;
- dropping ko threats outside a local window;
- terminal scoring before two passes;
- dead-stone adjudication not defined by the rules profile.

## Budget behavior

Every node/time/memory/disk limit must produce `UNKNOWN` unless the root was
already proven or disproven. Checkpoints must preserve that status. Resuming with
more resources may continue the same proof; it must not relabel an unfinished
run.

## Arithmetic

- Komi and score are signed integers in half-point units.
- Proof/disproof sums saturate at a declared `INF`.
- Counters use widths that cannot silently wrap during a campaign.
- Serialized integers include their width and endianness in the schema.

## Claim gate

The words “19×19 Go solved,” “Black wins,” or “White wins” may appear as a result
only when `scripts/claim_gate.py` validates a full certificate and an independent
verifier agrees. Until then, release status is `UNKNOWN`.
