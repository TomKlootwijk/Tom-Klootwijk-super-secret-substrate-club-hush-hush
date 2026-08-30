# UGTS-KC 3.9.2 — Native Android Source

This is a dependency-free `NativeActivity` project. The game loop, scene loader, GLES 3.0 renderer,
dynamic-resolution framebuffer, fixed-step gameplay, device tier selection, touch/gamepad input and
adaptive thermal/FPS quality logic, Grove juice events, particles and optional post-processing are
implemented in C++.

## Build

Open this directory in Android Studio, or use the checked, pinned Gradle 8.13 wrapper with Android
SDK 36, Android Gradle Plugin 8.13.2, CMake 3.22.1 and Android NDK r29 (`29.0.14206865`):

```powershell
.\gradlew.bat assemblePocoX7ProDebug
```

Common variants:

- `pocoX7ProDebug`: ARM64-only, explicit POCO X7 Pro 12 GB profile.
- `universalDebug`: ARM64, ARMv7 and x86_64 with runtime profile selection.
- Release variants are source-ready but require your own signing configuration.

The wrapper is copied from the verified UGTS 4.1.1 parent package and pins the distribution SHA-256.
The project intentionally includes no private signing key; use debug builds for direct learning and
device testing, then configure a private release key only when publishing.

## Controls

- Left side drag: movement; left-side tap: jump. The movement thumb remains active while another finger acts.
- Right side drag: orbit camera; right-side tap: dash. Touch roles follow pointer IDs, so finger ordering is safe.
- Two-finger spacing: camera distance.
- Gamepad left/right sticks: movement/look; A: jump; B: dash.
- Keyboard: WASD/arrows move; J jumps; Enter/Shift dash; Space triggers both beginner jump and dash actions.

The runtime currently uses OpenGL ES 3.0. Vulkan is declared optional and reserved as a future backend.

## Compact PBR-lite materials

The scene shader consumes the existing KC3D392 base colour, metallic, roughness, emissive and
double-sided fields. It uses a bounded multiply-heavy PBR-lite highlight/Fresnel/rim response and an
explicit zero-half-vector fallback; it does not add textures, IBL, GGX tables or a larger material
record. The renderer uploads the same fields for ordinary and instanced population draws. Emissive
retains Grove's presentation-only pulse, while saved scene/ECS state stays unchanged.

## Visual graph boundary

When the source project contains bound visual graphs, export adds the compact `visual_graphs.kcvg`
asset. The C++20 VM's append-only vocabulary currently contains 25 block types: Ready, Tick, When
Timer Rings, Input Pressed, Trigger Enter/Exit, Branch, constants/state/NodeData component reads,
Repeatable Random Number, Find Nearby Object, Find Object Ahead, scalar math/comparisons, Set State,
Set Component, Send a Game Message, When Message Heard, Apply Force, Set Active and Despawn.

`KCVG001` opcode 22 is **Find Nearby Object**. It searches from an explicit object—or from the bound
owner when available—for the nearest active, alive entity with one portable tag: `player`,
`collectible`, `goal`, `decorative` or `hazard`. The radius is finite, non-negative and inclusive;
the origin excludes itself, 2D entities use Z=0, and equal-distance results use UTF-8 entity-id order
so desktop, web and native Android agree. World Logic has no owner and must name its origin.

`KCVG001` opcode 23 is **When Timer Rings**. Its Seconds and Repeat settings are packed literals:
Seconds is finite positive binary32 through 86,400 and defaults to 1, while Repeat is boolean and
defaults to true. Each sparse graph binding owns an active fixed-step count. Inactive entity owners
pause only their binding; world logic continues, and Ready/restart resets the count. One-shot and
repeating timers emit at most one ring per update and expose count, remaining fixed-step seconds and
bound entity. The runtime derives this lifecycle without serialized timer clocks, suspended graphs
or continuations.

`KCVG001` opcode 24 is **Find Object Ahead**. It keeps the portable tag, inclusive radius,
self-exclusion, nullable outputs and UTF-8 entity-id tie-break from **Find Nearby Object**, then adds
a source-aligned three-dimensional cone with a saved forward-axis and width. Desktop, browser and
native use the same binary32 boundary fixtures, so an object exactly on the cone edge is included.

`KCVG001` opcode 25 is **When Message Heard**. **Send a Game Message** still records the ordinary
world event, and also appends its empty-payload graph message to a transient FIFO. Exact-name
receivers run only after every Ready, tick or trigger sender in the current outer batch finishes;
nested sends are breadth-first and non-reentrant. Recipients use scene insertion order, then graph
id, with World Logic last. A target reaches World Logic plus active bindings owned by that target.
The queue is never serialized and is bounded to 64 sends and 16,384 total graph-node steps per
outer batch.

NodeData paths are transform position/translation/scale/rotation (and numeric fields), velocity,
angular velocity, alive and active. Event payloads must currently be empty; ordinary events are
recorded by the world and Android log, while opcode-25 messages use the separate bounded graph FIFO.
Their Python event-record output cannot be linked. Mapping literals, dynamic configuration ports and
other component paths fail export with an explicit error instead of being ignored. Both per-node
graph bindings and sparse project-level `world_graphs` bindings run in the native VM.

## Packed polar ECS boundary

Nodes may opt into a sparse two-word `packed_kinematic` component in authoring metadata. Export then
adds `packed_kinematics.kcpk`; projects without such nodes add neither an asset nor component records.
Named profiles come from `project.metadata["packed_kinematic_profiles"]` and share one scaled UGLUT2
binary16 table apiece. At each fixed tick the native runtime advances the quantized log-radius/angle
motion, writes X/Z and heading-as-Y-yaw into that node's existing `NodeData`, and only then runs visual
graphs and gameplay physics. Authored Y, scale, velocity, collider and material stay untouched. The
runtime bounds profile/component/LUT counts and rejects truncated packs, unknown references,
noncanonical signed motion lanes, invalid samples and trailing bytes before starting content.

## Packed static population boundary

A static decorative prototype may carry one bounded **Populate Area** recipe. Export stores each
group in the optional `scatter_populations.kcsp` (`KCSP392`) sidecar and native GLES draws its
deterministic binary32 transforms with instancing. Counts are capped at 2–256 objects per group,
64 groups and 1,024 population objects per project; increasing a count preserves the existing
SplitMix64-derived prefix.

Population copies are render-only, not independent gameplay entities. Validation therefore rejects
prototypes that are dynamic or moving, use a collider, Trigger Area, gameplay tag, Logic Blocks or a
Movement Pattern. Projects without a population emit no KCSP asset.
