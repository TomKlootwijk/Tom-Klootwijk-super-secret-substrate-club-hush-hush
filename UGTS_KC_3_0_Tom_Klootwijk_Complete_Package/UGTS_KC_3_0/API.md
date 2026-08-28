# UGTS-KC 3.0 reference API

The Python package is intentionally small and dependency-free. It is an executable mathematical reference, not a production physics engine.

## Primary modules

- `kinematics.py`: jet state, rigid transforms, quaternions, dual quaternions, SE(2)/SE(3), moving frames and derivative helpers.
- `constraints.py`: holonomic/nonholonomic constraints, projection, multiplier solves, impact and friction helpers.
- `events.py`: crossing classification, simultaneous event clustering, priorities, Zeno detector, interval Newton and Sturm utilities.
- `topology.py`: simplicial complexes, H0 persistence, filtration helpers, Hodge Laplacian, linking, group presentation and monodromy.
- `patterns.py`: parametric pattern and surface functions carried forward from 2.0.
- `fields.py`: implicit primitives, field algebra, gradients and periodic minimal surfaces.
- `multiscale.py`: symmetries, substitutions, spatial partitions, sample sets, indices and transforms.
- `dynamics.py`: bounded geometric and field-dynamics steps.
- `uncertainty.py`: intervals, affine forms, covariance, unscented propagation, deterministic reductions, hashes, checkpoints and error budgets.
- `world.py`: compact query-first world used by the examples.
- `io.py`: schema-adjacent validation, JSON I/O and capability manifests.

## Minimal use

```python
from ugts_kc3.world import QueryWorld

world = QueryWorld.from_json_file("schema/example_world_v3.json")
state = world.state_at("traveler_A", 1.25)
event = world.next_event("traveler_A", 0.0, 5.0)
record = world.process_next_event("traveler_A", 0.0, 5.0)
```

## Important contracts

- Functions validate dimensions and obvious parameter bounds.
- Returned tuples are immutable where practical.
- Numerical policies must be explicit at exchange boundaries.
- Generic calculations are not automatically certified.
- Compact hashes are integrity checks, not identities.
- Topology names are accepted only as explicit combinatorial or gluing data.
