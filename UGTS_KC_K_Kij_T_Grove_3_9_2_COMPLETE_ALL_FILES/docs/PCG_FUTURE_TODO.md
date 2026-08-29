# PCG beyond Populate Area — future TODO

Grove 3.9.2 now implements one deliberately narrow procedural feature: **Populate Area** expands a
safe authored static prototype into a bounded deterministic render-only population. The compact
recipe, prefix stability, KCSP sidecar, glTF baking and native GLES instancing are shipped.

It does not yet implement general gameplay PCG. Future work should remain deterministic,
seed-addressable, validation-friendly and replay-safe. Candidate scope includes biome grammar,
room/arena generation, traversal guarantees, encounter placement, overlap constraints and authoring
overrides. None of those broader systems should be inferred from Populate Area.
