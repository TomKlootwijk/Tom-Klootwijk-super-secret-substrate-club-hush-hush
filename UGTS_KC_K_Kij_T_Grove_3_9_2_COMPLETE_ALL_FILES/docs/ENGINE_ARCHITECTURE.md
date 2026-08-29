# UGTS Grove Engine Architecture

## Product rule

Ease of learning is the first design constraint. Runtime and project size come second. Performance
work is accepted when it preserves predictable behavior and editor clarity. A feature does not enter
the beginner surface merely because the substrate can represent it.

## Data flow

```text
editable project + scene objects + visual graphs + optional population recipes
                     |
                     v
          validation and deterministic ordering
              /                 |                  \
     desktop ECS play    2D HTML5 graph VM      Mobile 3D compact build data
                                                     |
                                  KC3D392 + graph bytecode + KCSP392
                                                     |
                                    Android C++ / GLES 3 instanced player
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

The Mobile 3D Inspector translates **Off**, **Orbit**, **Spiral Out** and **Spiral In** into this same
component data. It keeps the packed words out of the beginner surface, presents radius, turn-speed and
start-angle controls, and records each edit through Undo/Redo. The control is disabled for dynamic
nodes so the editor cannot create two transform authorities.

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
per component and one shared UGLUT2 per profile. Its on-disk component record is exactly 24 bytes:
a 32-bit node index, 16-bit profile index, 16 reserved bits and the two unsigned 64-bit words. The
desktop preview composes the exact binary16-
roundtripped LUT before Ready graphs and advances it as an ordinary priority -100 pre-physics system;
the native C++ runtime follows the same polar -> graph -> gameplay order. Dynamic nodes are rejected
because two competing transform authorities would be ambiguous. Projects with no packed nodes emit
no polar asset or sparse records.

## Visual graphs

Graph records are immutable data with typed flow/data ports, stable canonical hashes and a registry
of executable node definitions. Data dependencies use deterministic topological ordering derived from
the UGTS 4.2 ordering work. Runtime execution is traced and bounded.

Desktop Preview turns that existing runtime trace into a **Logic Trail**. The document keeps immutable
per-graph/per-owner snapshots for the current Preview, and the editor presents their step order,
values, chosen flow and errors in block badges and the **Last Run** list. The Logic tab remains
navigable but read-only during Play; Stop retains the latest trail for inspection. These snapshots are
presentation state, not graph state: they do not set project dirty state, are not serialized, and add
zero bytes to scene, graph, web, glTF or Android output. Starting a new Preview or project clears them.

The first vocabulary covers lifecycle/input events, branches, values, arithmetic, comparisons, world
state, components, emitted events, forces, activation and despawn. Arbitrary Python or native code is
not embedded in a learner project.

Android exports an optional `visual_graphs.kcvg` (`KCVG001`) asset. Its native VM supports the full
current 20-block Mobile 3D authoring vocabulary, including sparse node bindings, world bindings,
2D-XZ or 3D-XYZ Apply Force, and Trigger Enter/Exit. Ready/tick/input/trigger roots, branches, values,
state/components, scalar math/comparisons, bounded event logging, activation and despawn retain the
same step/lifecycle rules as desktop. It still deliberately rejects mapping/nonempty event payloads,
connected event records, unmapped input names and component paths outside the native NodeData
whitelist rather than changing their meaning.

Trigger areas are non-physical sensor colliders. Desktop and native select the first active player,
perform matching scale-aware sphere/box overlap tests, emit exits before enters in deterministic sensor
order, and dispatch each transition to world graphs plus graphs bound to that sensor. The event roots
expose sensor/player/entity context. Both validation and native tracking cap a project at 4,096 active
sensors; the native VM additionally budgets 256 trigger transitions per fixed step. The beginner
surface is data-backed rather than a runtime shortcut: **+ Trigger Area** creates an ordinary static
sensor node, and **Use as Trigger** edits the selected node's Sphere/Radius or Box/Size X/Y/Z collider.
The same replacement command provides Undo/Redo and normal project save/load.

HTML5 exports for retained 2D projects precompile graph plans too. The browser VM executes the full
current 20-block vocabulary, including Trigger Enter/Exit sensor and player context. It preserves
entity/world binding ownership, sorts flow deterministically and enforces a 1,024-step ceiling.
Browser exports fail at build time if a future custom block has no browser implementation; logic is
never silently dropped. There is no browser Mobile 3D player, so Mobile 3D graph execution and
Populate Area currently have desktop/native Android paths, not browser parity.

## Bounded decorative populations

**Populate Area** is a static render-decoration component, not a gameplay spawner. One ordinary
Mobile 3D node remains the authored prototype and stores one `metadata.scatter_population` recipe:
object count, World number, three-dimensional area size, minimum/maximum scale and optional random
yaw. The first-steps template demonstrates the feature with **Crystal Garden**: one saved crystal and
an 18-object deterministic garden.

Validation keeps the ownership model unambiguous. A prototype must be static, render-active and have
zero linear/angular velocity. It cannot have a collider or Trigger Area, a player/collectible/goal/
hazard gameplay tag, Logic Blocks, or a Movement Pattern. The generated copies are display transforms
only; they never become ECS/gameplay entities with independent collider, graph, movement, input or
state semantics.

Counts are bounded to 2–256 objects per group, including the authored prototype, with at most 64
groups and 1,024 population objects across a project. The optional `scatter_populations.kcsp`
(`KCSP392`) sidecar has one 24-byte header and one fixed 36-byte record per group; projects without a
population emit no sidecar. Each generated index uses a random-access SplitMix64-derived lineage and
binary32 transform schedule. The same prototype id, World number and index therefore produce the same
copy, and raising the count preserves every existing copy as a deterministic prefix.

The seed behavior is a local compatibility reimplementation; no parent-repository source file is
vendored into this package. The inspected parent UGTS trees did not expose an explicit license for
their source, so compatibility here must not be read as a license grant for unrelated parent code.

Adapters keep their different jobs explicit:

- The desktop Scene view shows at most 64 generated copies per group and 256 globally, while reporting
  the full generated count.
- glTF output bakes every generated copy as an explicit render-only node.
- Native C++ validates KCSP, regenerates the same matrices, uploads one matrix buffer per group and
  issues GLES `glDrawElementsInstanced` calls. If a quality tier's visible-node budget is exhausted,
  it draws a deterministic prefix rather than reshuffling the garden.

This narrow native instancing path is not a general visibility system or a measured performance
claim. Placement has no spacing or overlap avoidance, and generated copies currently have no
per-copy frustum culling, occlusion selection or LOD. Dense overlapping recipes can still waste fill
rate and geometry work within the safety caps.

## Owner-device deployment

The editor's **Deploy to Phone** operation is a single bounded pipeline, not three unrelated buttons.
It selects exactly one authorized ADB device before generation and retains that serial through build,
install and launch. Generated files stay under the saved project's
`.ugts-studio/deploy/<project-id>-android` path. The build result is paired with Gradle's
`output-metadata.json`; only its validated, flavor-aware `applicationId` is used to launch
`<applicationId>/android.app.NativeActivity`. Phase-aware completion preserves an already-built APK
when install fails and an already-installed APK when launch fails.

## Rendering and the “AAA” boundary

Compact AAA-style presentation means good lighting/material choices, stable frame pacing, adaptive
resolution, careful effects, asset reuse and measured visibility—not enormous source files. Grove
currently provides GLES 3 depth/culling, a scaled framebuffer, post effects, particles, camera shake,
adaptive quality tiers and Poco-specific ARM64 policy.

OBJ mesh import is now a bounded authoring-to-native-pack path, but Grove does **not** yet provide a
full AAA asset pipeline: skeletal animation, texture compression,
streaming LOD, occlusion, general-purpose batching, production physics and a Vulkan renderer remain
work. Populate Area's bounded static GLES instancing is the one narrow exception; it does not close
those broader gaps. Those gaps are tracked rather than hidden behind marketing language.

## Android target

Generated projects pin Gradle 8.13 by wrapper checksum, SDK/target 36, minimum SDK 26, NDK r29 and
CMake 3.22.1. The Poco X7 Pro flavor is ARM64 and selects the Mali-oriented adaptive profile. A
universal flavor retains ARM64, ARMv7 and x86_64 fallback profiles.

Model names and RAM are only hints. An authorized `2412DPC0AG`/`rodin` with Mali-G720 MC7 accepted
and launched a 3.9.2 GUI deployment, but disconnected before a sustained capture. Sustainable
60/90/120 Hz behavior must still be profiled on the physical phone under thermal load.
