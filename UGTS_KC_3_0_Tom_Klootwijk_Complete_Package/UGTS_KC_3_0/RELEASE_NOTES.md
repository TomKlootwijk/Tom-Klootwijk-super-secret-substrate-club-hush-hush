# UGTS-KC 3.0 release notes

Release date: 16 August 2026

## 3.0 scope

UGTS-KC 3.0 turns the 2.0 pattern-and-kinematics layer into a more complete hybrid geometric dynamics package. The canonical support/compatibility/event/transition architecture is unchanged; the expansion adds the mathematics and contracts needed to handle higher-order motion, constraints, contact, certified event ordering, topology-changing observables, multiscale patterns, structured dynamics and reproducible replay.

## New catalog range: M258-M360

### Jet, differential and Lie kinematics

Typed derivative towers through snap; material and covariant derivative contracts; Lie brackets; SE(3) adjoint, Jacobian and logarithm; dual quaternions; geodesic/retraction updates; curvature, torsion and transported-frame holonomy; limit-aware time scaling and differential-flatness reconstruction.

### Constraints and contact

Holonomic and nonholonomic constraints; constraint Jacobians; Baumgarte, SHAKE and RATTLE stabilization; multiplier and null-space solves; unilateral gaps; complementarity; impact and restitution; Coulomb friction and friction pyramids; contact-manifold reduction and warm starts.

### Certified hybrid events

Crossing-direction and tangency classification; grazing markers; simultaneous-event equivalence classes; priority partial orders; deterministic tie-breaks; Zeno detection; dwell timers; interval event enclosures; Lipschitz exclusion; interval Newton; Sturm root counts; rollback-safe atomic batches.

### Persistent topology

Oriented simplices and chain consistency; Betti vectors; H0 persistence; barcodes and diagram distances; Vietoris-Rips, alpha and cubical filtrations; discrete Hodge Laplacian; harmonic-cycle, winding/linking, fundamental-group and covering-monodromy contracts; topology-change events.

### Patterns and multiscale structure

Wallpaper and frieze symmetries; Penrose and Ammann-Beenker substitutions; cut-and-project quasicrystals; Voronoi/Delaunay, Lloyd relaxation, Poisson disk and blue-noise diagnostics; Hilbert and Morton indexing; Haar wavelets, Laplacian pyramids and graph spectral patterns.

### Dynamics, uncertainty and runtime

Hamiltonian, Euler-Lagrange and variational formulations; implicit midpoint, Stormer-Verlet, Lie-group and projected symplectic updates; semi-Lagrangian advection, implicit diffusion, wave leapfrog, reaction-diffusion and phase-field steps; eikonal update; intervals, affine forms, covariance and unscented propagation; deterministic sampling/reduction; canonical hashes, Merkle event chains and checkpoints; error budgets; jet/contact ABI and event-compaction contracts; capability-driven fallbacks.

## Validation

- 182 unit and integrity tests pass.
- The JSON Schema validates under Draft 2020-12.
- The example world validates against the schema.
- Five executable examples complete successfully.
- The reference benchmark records the Python version, platform and checksums and is labeled as a CPU-only reference measurement.

## Compatibility

3.0 retains the M001-M257 identifiers. New mechanisms only append identifiers. Schema version 3.0 introduces explicit jet fields, numeric policy, constraints, dynamics, topology descriptors, capability manifests and simultaneous-event policy.
