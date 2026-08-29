# UGTS Grove Engine Architecture

## Product rule

Ease of learning is the first design constraint. Runtime and project size come second. Performance
work is accepted when it preserves predictable behavior and editor clarity. A feature does not enter
the beginner surface merely because the substrate can represent it.

## Data flow

```text
editable project + scene objects + visual graphs
                     |
                     v
          validation and deterministic ordering
              /                         \
     desktop ECS play                compact build data
                                          |
                             KC3D392 + graph bytecode
                                          |
                              Android C++ / GLES 3 player
```

The editor is not runtime authority. It writes the same records consumed by headless simulation and
export. This keeps projects recoverable and allows every important build step to run without the GUI.

## ECS composition

The 2D runtime already uses entities, serializable components, typed queries and ordered system
phases. Visual graphs attach as ordinary update systems. Packed polar motion also attaches as an
ordinary pre-physics system; neither receives a hidden privileged loop.

The current Android player is moving toward the same model, but its inherited Grove gameplay still
contains tag-specific C++ paths. Calling that side a complete general ECS today would be inaccurate.

## Compact kinematic representation

`PackedKinematicComponent` stores two unsigned 64-bit words:

- pose: 20-bit log radius, 18-bit angle, 14-bit tick and 12-bit heading;
- motion: four signed 16-bit fields for radial/angular velocity and acceleration.

The layout retains the bounded log-polar idea from UGTS SCLP 3.6.2 while giving it an explicit game
component contract. Position, Cartesian velocity and Cartesian acceleration use the chart Jacobian
and polar kinematic terms. Clamping and quantization domains are explicit.

`PolarLookupTable` can share 256 binary16 sine, cosine and exponential-radius samples in under 1.7 KB.
Linear interpolation is used for previews and compact deterministic adapters. Direct `sin`, `cos` and
`exp` remain available. The parent GPU evidence found that smaller records were valuable but that the
LUT itself was not universally faster, so selection must be measured on the target GPU.

`UGECS1` stores canonical ECS/project/graph JSON behind a length, CRC-32 and DEFLATE payload. Authored
JSON stays readable; a build can carry the smaller checked form.

## Visual graphs

Graph records are immutable data with typed flow/data ports, stable canonical hashes and a registry
of executable node definitions. Data dependencies use deterministic topological ordering derived from
the UGTS 4.2 ordering work. Runtime execution is traced and bounded.

The first vocabulary covers lifecycle/input events, branches, values, arithmetic, comparisons, world
state, components, emitted events, forces, activation and despawn. Arbitrary Python or native code is
not embedded in a learner project.

## Rendering and the “AAA” boundary

Compact AAA-style presentation means good lighting/material choices, stable frame pacing, adaptive
resolution, careful effects, asset reuse and measured visibility—not enormous source files. Grove
currently provides GLES 3 depth/culling, a scaled framebuffer, post effects, particles, camera shake,
adaptive quality tiers and Poco-specific ARM64 policy.

It does **not** yet provide a full AAA asset pipeline: skeletal animation, texture compression,
streaming LOD, occlusion, instancing/batching, production physics and a Vulkan renderer remain work.
Those gaps are tracked rather than hidden behind marketing language.

## Android target

Generated projects pin Gradle 8.13 by wrapper checksum, SDK/target 36, minimum SDK 26, NDK r29 and
CMake 3.22.1. The Poco X7 Pro flavor is ARM64 and selects the Mali-oriented adaptive profile. A
universal flavor retains ARM64, ARMv7 and x86_64 fallback profiles.

Model names and RAM are only hints. Sustainable 60/90/120 Hz behavior must be profiled on the physical
phone under thermal load. No current source artifact proves that profiling has happened.

