# UGTS-KC Two Hands 3.0 - Production Release Definition

The 3.0 companion extends the 2.0 mathematical substrate with downstream production layers while preserving the canonical authority path.

```text
UGTS-KC2 = (G, P, F, K, D, R, S, C, T, I, L)
UGTS-KC3 = UGTS-KC2 + (A, X, M, V, H, N, E)
```

- `A`: assets, instances, scene layers and schema migration.
- `X`: bounds, BVH, culling, streaming and interest sets.
- `M`: curve/field-to-mesh compilation and error contracts.
- `V`: materials, color, rendering and presentation exports.
- `H`: typed left/right hand state and bimanual interaction.
- `N`: event sequence, checkpoint, rollback and divergence detection.
- `E`: diagnostics, editor inspection and validation gates.

The canonical shorthand remains:

```text
pattern/field + kinematic state
-> spatial/support pruning
-> compatibility
-> guard classification
-> verified event proposal
-> deterministic commit
-> scene/topology/dynamic patch
-> lineage + novelty/replay log
-> optional render/export
```

## Implemented in the reference package

- Dependency-free scene, asset and instance model.
- Adaptive curve flattening, path strokes, swept tubes and marching tetrahedra.
- AABB, BVH, frustum/ray queries, streaming cells and interest sets.
- Typed PBR preview materials, color conversion and a small material graph.
- Left/right hand state, pinch hysteresis, bimanual transform and handover state machine.
- Fixed-step runtime, deterministic proposal commit, snapshots, replay and divergence checks.
- Self-contained glTF 2.0 JSON, USDA and deterministic SVG output.
- A runnable two-hand sandbox vertical slice.

## Specified but not claimed as implemented

- Full Vulkan render graph and compiled physical-GPU renderer.
- Production WebGPU execution environment.
- OpenXR runtime binding.
- OpenUSD composition engine integration.
- MaterialX/OCIO runtime integration.
- Skeletal character system, rigid-body solver and character controller.
- Multiplayer transport, server infrastructure and cross-vendor deterministic certification.

These remain adapter or production work, not hidden claims of this reference companion.
