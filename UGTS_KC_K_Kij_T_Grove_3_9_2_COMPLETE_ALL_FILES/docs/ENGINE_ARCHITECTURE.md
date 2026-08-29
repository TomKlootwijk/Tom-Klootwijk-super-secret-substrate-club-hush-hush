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

Authoring context is selection-owned. Selecting a bound 2D entity, Mobile 3D node or World Logic
entry resolves only that owner's graph; the editor never borrows an unrelated project graph as a
fallback. An unbound object receives a transient blank `VisualGraph` that is absent from serialized
project data. Its first meaningful edit stores the graph and owner binding together, and the same
Undo command restores the exact unbound state. Ordered multi-bindings are exposed through an explicit
graph chooser. A Mobile 3D node with `scatter_population` cannot cross that transition: Populate Area
must be removed before the prototype can own a graph.

The vocabulary covers lifecycle/input events, branches, values, arithmetic, comparisons, world
state, components, portable nearest-tag sensing, emitted events, forces, activation and despawn.
It also includes a bounded world-axis radial/angular sensing query.
Arbitrary Python or native code is not embedded in a learner project.

Android exports an optional `visual_graphs.kcvg` (`KCVG001`) asset. Its native VM supports the full
current 24-block Mobile 3D authoring vocabulary, including sparse node bindings, world bindings,
2D-XZ or 3D-XYZ Apply Force, and Trigger Enter/Exit. Ready/tick/input/trigger roots, branches, values,
state/components, scalar math/comparisons, bounded event logging, activation and despawn retain the
same step/lifecycle rules as desktop. It still deliberately rejects mapping/nonempty event payloads,
connected event records, unmapped input names and component paths outside the native NodeData
whitelist rather than changing their meaning. Opcode 21 is the append-only **Repeatable Random
Number** value block: World number and Pick number are first canonicalized to binary32, then must be
whole numbers from 0 through 65,535,
Smallest/Largest and the result use binary32, and linked inputs follow the same checks as literals.
It has no clock, tick dependency or mutable random state. A fixed Logic Block namespace and the
existing SplitMix64 compatibility primitives therefore give desktop, browser and native Android the
same result bits for the same four inputs.

Opcode 22 is the append-only **Find Nearby Object** sensing block (`query.nearest_tag`). **Origin**
may use the graph's bound object or name another project object; a world graph must supply an explicit
origin because it has no owner entity. **Tag** is restricted to `player`, `collectible`, `goal`,
`decorative` or `hazard`, and **Radius** is a finite non-negative binary32 value whose boundary is
inclusive. The origin is excluded, as are dead, inactive, untagged or positionless candidates. The
VM returns the nearest remaining object using the shared binary32 distance schedule and breaks an
exact distance tie by UTF-8 object ID, plus `found`, nullable `entity` and nullable `distance`
outputs. Desktop, browser and native implementations share those rules; Mobile 3D itself still has
no browser player.

Opcode 23 is the append-only **When Timer Rings** event root (`event.timer`). Its **Seconds** and
**Repeat** settings are packed literals rather than dynamic ports. Seconds is canonical finite
positive binary32 through 86,400 and defaults to 1; Repeat is boolean and defaults to true. The
period is a whole number of fixed updates, rounded up so a timer never rings early. Each graph
binding owns one active-step counter. World bindings advance with the world, while an inactive or
dead entity owner pauses only that entity binding. Ready and restart reset the counter. A repeating
or one-shot timer emits at most one flow per update and reports binary32 `count`, `remaining` and the
bound `entity`; it does not catch up with a burst. The counter is runtime lifecycle state derived
from active updates—not a serialized clock, suspended graph, continuation or new project-schema
field. Editor authoring/save-load, desktop Preview, retained browser VM, KCVG packing and native C++
share validation and execution fixtures.

Opcode 24 is the append-only **Find Object Ahead** sensing block (`query.nearest_in_cone`). It takes
the same **Origin**, portable **Tag** and inclusive binary32 **Radius** as opcode 22, with identical
self/dead/inactive/position filters, nearest-distance selection, UTF-8 tie-break and
found/entity/distance outputs. Its fourth input is one Vector4: explicit world-axis X/Y/Z plus minimum
cosine in the inclusive range [-1, 1]. The runtime canonicalizes and normalizes any finite nonzero
axis using the specified round-after-each-operation binary32 schedule. Candidate direction divides
each displacement component by `max(distance, f32(1e-6))`, then the rounded dot is compared
inclusively with the saved minimum cosine. This is the source-aligned GSP4 cone: a coincident point
has cosine zero, runtime trigonometry is never used, and Origin rotation and scale are deliberately
irrelevant. The editor writes exact world-axis/width presets, but dynamic Vector4 links remain valid.

Trigger areas are non-physical sensor colliders. Desktop and native select the first active player,
perform matching scale-aware sphere/box overlap tests, emit exits before enters in deterministic sensor
order, and dispatch each transition to world graphs plus graphs bound to that sensor. The event roots
expose sensor/player/entity context. Both validation and native tracking cap a project at 4,096 active
sensors; the native VM additionally budgets 256 trigger transitions per fixed step. The beginner
surface is data-backed rather than a runtime shortcut: **+ Trigger Area** creates an ordinary static
sensor node, and **Use as Trigger** edits the selected node's Sphere/Radius or Box/Size X/Y/Z collider.
The same replacement command provides Undo/Redo and normal project save/load.

HTML5 exports for retained 2D projects precompile graph plans too. The browser VM executes the full
current 24-block vocabulary, including Repeatable Random Number, Find Nearby Object, Find Object Ahead, When Timer
Rings and Trigger Enter/Exit sensor/player context. It preserves
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

The population and Repeatable Random Number seed behavior is a local compatibility reimplementation;
no parent-repository source file is vendored into this package. The inspected parent UGTS trees did
not expose an explicit license for their source, so compatibility here must not be read as a license
grant for unrelated parent code.

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

**Check Phone** (`Ctrl+Shift+P`) is a separate bounded observation pipeline. With the deployed game
running and its screen on, the editor profiles it on a worker thread for 30 seconds, leaving editing
responsive. It pins the selected authorized ADB serial, reads SurfaceFlinger frame cadence, process
PSS/RSS, Android thermal status, available GPU/battery temperature and the app's crash buffer.
Studio Output summarizes cadence, PSS, available GPU temperature, crash lines and warnings; CLI JSON
retains the complete available sample. Neither path injects input or changes game/device settings. The
profiler clears only SurfaceFlinger's diagnostic latency history between sample windows.
`profile-android` exposes the
same operation to non-GUI workflows.

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

Model names and RAM are only hints. The canonical opcode-24 Poco APK is locally built and inspected:
1,460,361 bytes, SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`, package
`org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 / `3.9.2-poco-x7-pro`, minimum SDK 26,
target/compile SDK 36, GLES 3.0, ARM64-only, debug-certificate signed and APK Signature Scheme v2
verified. Its embedded KCVG/KCPK/KCSP assets hash-match the current source sidecars. ADB reported zero
devices, so there is no fresh install, launch or profile claim for that build.

The preceding opcode-23 APK is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`; it is not the current source
artifact and has no fresh device claim.

An authorized `2412DPC0AG`/`rodin` with Mali-G720 MC7 previously accepted, launched and hash-matched
the preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk`. Its retained 30-second baseline reported
120.23 effective FPS, 10.118 ms p95, thermal status 0 and no crash lines or warnings; a still earlier
APK retains a separate 64.9-second idle baseline. Interaction-heavy/touch, unplugged and
long-duration thermal runs, explicit 60/90 Hz fallbacks and representative lower-tier devices remain
required; neither historical short baseline is a general performance guarantee or opcode-24 device
evidence.
