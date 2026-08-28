# UGTS-KC Two Hands 3.0
## Interactive Graphics, Game Runtime and Content Substrate

This package turns the UGTS-KC 2.0 pattern/kinematics layer into a runnable production-facing reference vertical slice while preserving the core rule:

```text
local/spatial support -> compatibility -> guard classification
-> verified proposal -> deterministic event commit
-> scene/topology/dynamic patch -> lineage + replay log
-> optional render/export
```

The source-normalized baseline contains 197 mechanisms. KC 2.0 added M198-M257. This companion adds **72 engineering mechanisms, M258-M329**, for an extended total of **329 mechanisms**.

## Delivered implementation

- Self-contained Python 3 reference runtime with no third-party runtime dependency.
- Scene/assets/instances/layers, geometry compilation, AABB/BVH, materials and SVG preview.
- Typed two-hand input, pinch hysteresis, bimanual scale/rotation/translation and handover lineage.
- Deterministic event proposal commit, snapshots, checkpoints, rollback and replay divergence checks.
- glTF 2.0 JSON and USDA export adapters.
- Runnable sandbox output under `examples/output/`.
- **117 passing tests** across retained KC 2.0 and new KC 3.0 functionality.

## Quick start

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python examples/two_hands_sandbox.py
```

## Package layout

- `report/` - companion PDF and editable DOCX source.
- `spec/` - M258-M329 catalog, combined engineering catalog, schema and contracts.
- `src/ugts_kc/` - retained KC 2.0 geometry/topology/kinematics/dynamics oracle.
- `src/ugts_kc3/` - scene, geometry compiler, spatial, material, hand, runtime, replay, render and export modules.
- `tests/` - retained 47 tests plus 70 new tests.
- `examples/` - vertical-slice source, machine-readable definition and generated outputs.
- `shaders/` - WGSL and GLSL layout/preview prototypes.
- `diagrams/` - report figures.
- `validation/` - captured tests, hashes, counts and PDF checks.
- `docs/` - attribution, evidence boundary, references, changelog and roadmap.

## Boundary

The package is a tested reference implementation and specification companion. It does not claim a production Vulkan renderer, physical-GPU benchmark, OpenXR runtime binding, full OpenUSD/MaterialX/OCIO integration, general rigid-body physics or multiplayer service.

## Attribution

Prepared for **Tom Klootwijk**. The supplied identifier and date of birth are recorded as requester-supplied and not independently verified. See `docs/ATTRIBUTION_NOTICE.md`.
