# Android authority contract 4.1.1

A camera, sensor, feature detector, matcher, motion estimator, learned model or GPU kernel may emit a `SpatialProposal`. None may mutate the authoritative map directly.

The verifier evaluates, in order:

1. Identifier validity.
2. Local support.
3. Semantic/topological compatibility.
4. Accepted guard class.
5. Confidence floor.
6. Numeric error within event margin.
7. Uncertainty within policy.
8. Metric availability when metric meaning is required.

A rejected proposal leaves the state hash unchanged and receives a reason code. An accepted proposal receives a monotonic sequence, canonical proposal SHA-256, pre-state SHA-256, post-state SHA-256 and effect fields.

Stable identity is seed-derived and separate from coordinates. Synthetic proposals carry tag bit 31. Bayer or camera previews are downstream and cannot commit map changes.
