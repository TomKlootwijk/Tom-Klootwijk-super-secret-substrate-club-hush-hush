# Migration guide: UGTS-KC 2.0 to 3.0

## What remains stable

- Query-first authority.
- Support before compatibility, and compatibility before event solving.
- Explicit relation/guard surfaces.
- Transition records with lineage and novelty.
- Schema-bound one-bit roles.
- Optional projection and hardware endpoints.
- Mechanism identifiers M001-M257.

## Required schema changes

1. Set `schema_version` to `3.0.0`.
2. Replace untyped trajectory derivatives with explicit `position`, `velocity`, `acceleration`, `jerk` and `snap` arrays. Zero-fill unused orders.
3. Add `frame`, `length_unit` and `time_unit` to state records.
4. Add a `numeric_policy` with tolerances, certification mode and deterministic-reduction policy.
5. Declare solver capability and fallbacks in `capabilities`.
6. Move constraint/contact semantics into `constraints` rather than hiding them in a transition callback.
7. Declare `event_policy`, including simultaneous-event tolerance, tie-break policy, Zeno policy, atomic batching and dwell time.
8. Record dynamics and integrator choices under `dynamics` with an explicit error budget.
9. Add topology descriptors only when their ports, maps, generators, relations or filtration policy are declared.

## Event-processing change

2.0 could process the first valid event as a single transition. 3.0 first clusters events within the declared time tolerance, orders the cluster through a priority partial order plus deterministic tie-break, validates the complete transition batch, then commits atomically or rolls back.

## Numerical change

A scalar root estimate is no longer sufficient when certification is requested. Use an interval enclosure and status. Tangency, grazing, coincident roots and Zeno-like accumulation must be returned as classified states rather than silently forced into a crossing.

## Replay change

Canonical JSON hashes, an event-log Merkle chain and checkpoints are available for tamper detection and deterministic rollback. These are integrity mechanisms, not cryptographic identity or authorization.

## Runtime change

Consumers should inspect the capability manifest and route unsupported mechanisms to a declared fallback. A mechanism ID in a world file is not proof that every backend implements it.
