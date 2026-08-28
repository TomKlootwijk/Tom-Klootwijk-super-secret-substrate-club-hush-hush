# UGTS-KC 4.0 Spatial Evidence Contract

## Canonical path

```text
capture profile + typed observation
-> local spatial support
-> semantic/topological compatibility
-> relation interval and guard class
-> confidence, uncertainty, metric-scale and provenance gates
-> verified proposal
-> deterministic conflict policy
-> atomic map patch
-> pre/post hashes + evidence + lineage
-> checkpoint/replay/change/export
```

## Observation authority

An observation is a proposal. It cannot mutate a `MapState`. Only `SpatialLedger.commit` may apply a
`MapPatch`, and only after `ProposalVerifier` accepts the proposal.

## Stable identity

Node ID, edge ID, coordinates, semantic labels, evidence IDs and lineage are distinct. A node can move,
change state or receive new evidence without changing its stable ID.

## Uncertainty

A position bound is either an explicit conservative maximum error or the reference `3*||sigma||` bound.
Route clearance uses its lower interval bound; route slope uses its upper interval bound. Movement is
verified only when the lower displacement bound exceeds the movement threshold.

## Replay

Each event stores sequence, patch, pre-state hash and post-state hash. Replay begins from the initial map
or a verified checkpoint and stops at the first sequence or hash divergence.

## Projection boundary

GeoJSON, SVG plan views, meshes and HTML reports are non-authoritative projections unless a separate
application contract promotes them under explicit geometry and topology error budgets.
