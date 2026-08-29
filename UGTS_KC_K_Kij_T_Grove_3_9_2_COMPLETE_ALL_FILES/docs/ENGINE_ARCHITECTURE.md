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
              /                 |                  \
     desktop ECS play      HTML5 graph VM       compact build data
                                                     |
                                        KC3D392 + graph bytecode
                                                     |
                                         Android C++ / GLES 3 player
```

The editor is not runtime authority. It writes the same records consumed by headless simulation and
export. This keeps projects recoverable and allows every important build step to run without the GUI.

## ECS composition

The 2D runtime uses entities, serializable components, typed queries and ordered system phases. The
desktop 3D oracle exposes the same transform/body/collider/render query and system facade while
retaining its compatible entity records. Visual graphs attach as ordinary systems. Packed polar motion also attaches as an
ordinary pre-physics system; neither receives a hidden privileged loop.

The Android graph VM operates on sparse graph bindings and explicit NodeData components, but inherited
Grove gameplay still contains tag-specific C++ paths. Calling that side a complete general ECS today
would be inaccurate.

## Compact kinematic representation

`PackedKinematicComponent` stores two unsigned 64-bit words:

- pose: 20-bit log radius, 18-bit angle, 14-bit tick and 12-bit heading;
- motion: four signed 16-bit fields for radial/angular velocity and acceleration.

The layout retains the bounded log-polar idea from UGTS SCLP 3.6.2 while giving it an explicit game
component contract. Position, Cartesian velocity and Cartesian acceleration use the chart Jacobian
and polar kinematic terms. Clamping and quantization domains are explicit.

`PolarLookupTable` can share 256 binary16 sine, cosine and scaled exponential-radius samples in 1,584
bytes. UGLUT2 stores one shared radius scale so the default `rho_max=12` range remains representable.
Linear interpolation is used for previews and compact deterministic adapters. Direct `sin`, `cos` and
`exp` remain available. The parent GPU evidence found that smaller records were valuable but that the
LUT itself was not universally faster, so selection must be measured on the target GPU.

`UGECS1` stores canonical ECS/project/graph JSON behind a length, CRC-32 and DEFLATE payload. Authored
JSON stays readable; a build can carry the smaller checked form.

Mobile 3D nodes can opt into the same component through metadata. Export emits a sparse optional
`packed_kinematics.kcpk` (`KCPK392`) asset containing only referenced node indices, two 64-bit words
per component and one shared UGLUT2 per profile. The desktop preview composes the exact binary16-
roundtripped LUT before Ready graphs and advances it as an ordinary priority -100 pre-physics system;
the native C++ runtime follows the same polar -> graph -> gameplay order. Dynamic nodes are rejected
because two competing transform authorities would be ambiguous. Projects with no packed nodes emit
no polar asset or sparse records.

## Visual graphs

Graph records are immutable data with typed flow/data ports, stable canonical hashes and a registry
of executable node definitions. Data dependencies use deterministic topological ordering derived from
the UGTS 4.2 ordering work. Runtime execution is traced and bounded.

The first vocabulary covers lifecycle/input events, branches, values, arithmetic, comparisons, world
state, components, emitted events, forces, activation and despawn. Arbitrary Python or native code is
not embedded in a learner project.

Android exports an optional `visual_graphs.kcvg` (`KCVG001`) asset. Its native VM supports the full
current 18-block authoring vocabulary, including sparse node bindings, world bindings and 2D-XZ or
3D-XYZ Apply Force. Ready/tick/input, branches, values, state/components, scalar math/comparisons,
bounded event logging, activation and despawn retain the same step/lifecycle rules as desktop. It
still deliberately rejects mapping/nonempty event payloads, connected event records, unmapped input
names and component paths outside the native NodeData whitelist rather than changing their meaning.

HTML5 exports precompile graph plans too. The browser VM also executes all 18 current built-ins, preserves
entity/world binding ownership, sorts flow deterministically and enforces a 1,024-step ceiling. Browser
exports therefore fail at build time if a future custom block has no browser implementation; logic is
never silently dropped.

## Rendering and the “AAA” boundary

Compact AAA-style presentation means good lighting/material choices, stable frame pacing, adaptive
resolution, careful effects, asset reuse and measured visibility—not enormous source files. Grove
currently provides GLES 3 depth/culling, a scaled framebuffer, post effects, particles, camera shake,
adaptive quality tiers and Poco-specific ARM64 policy.

OBJ mesh import is now a bounded authoring-to-native-pack path, but Grove does **not** yet provide a
full AAA asset pipeline: skeletal animation, texture compression,
streaming LOD, occlusion, instancing/batching, production physics and a Vulkan renderer remain work.
Those gaps are tracked rather than hidden behind marketing language.

## Android target

Generated projects pin Gradle 8.13 by wrapper checksum, SDK/target 36, minimum SDK 26, NDK r29 and
CMake 3.22.1. The Poco X7 Pro flavor is ARM64 and selects the Mali-oriented adaptive profile. A
universal flavor retains ARM64, ARMv7 and x86_64 fallback profiles.

Model names and RAM are only hints. Sustainable 60/90/120 Hz behavior must be profiled on the physical
phone under thermal load. The local toolchain compiles the Poco ARM64 APK, but no current source
artifact proves physical-phone profiling has happened.
