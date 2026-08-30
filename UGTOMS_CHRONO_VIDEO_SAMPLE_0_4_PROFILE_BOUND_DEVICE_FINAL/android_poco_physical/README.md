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

## Chrono-video runtime boundary

The optional native chrono player has two mutually exclusive, logged modes. In
`AUTHORITATIVE_SOURCE_LUT`, `source_media.mp4` and `source_timeline.ugcvpts1` must both pass the
generated whole-asset ledger and the timeline's own hashes; the source dimensions must match
`UGCVLUT1`. MediaCodec output ordinal and microsecond PTS are checked against the exact source clock,
and GLES applies the LUT with its explicit integer Q8 four-neighbour weights. A declared but corrupt
source set fails closed and is never promoted to a preview.

`DERIVED_POLAR_PREVIEW` instead consumes `polar_preview.mp4` plus
`preview_timeline.ugcvpts1`. Its shader has no LUT binding, so an already-log-polar diagnostic cannot
be transformed twice. Both paths release at most one decoded buffer until the GL thread consumes its
SurfaceTexture callback. Two owned RGBA8 slots keep the selected raster visible while exactly one
verified next ordinal is staged; the render thread swaps the published slot only at its integer
half-open boundary. Ordinal zero is published before the steady clock starts. A missed prefetch keeps
the previous slot, increments an explicit late-boundary counter and logs that physical exact timing
was not achieved. The default is `ONCE_HOLD_LAST`, while looping occurs only when the cache carries
its explicit loop flag; loop epoch detection remains valid even after a stall spanning whole cycles.
MP4 assets are packaged uncompressed because NDK MediaExtractor requires a real descriptor range.

The LUT coordinate/interpolation math is exact. Device MediaCodec YUV-to-RGB conversion is not
claimed byte-identical across phones; logs state that color boundary separately. The shader treats
LUT addresses as canonical top-left pixel indices, converts exact pixel centres to GL coordinates,
then applies Android's SurfaceTexture transform matrix.

## Compact PBR-lite materials

The scene shader consumes the existing KC3D392 base colour, metallic, roughness, emissive and
double-sided fields. It uses a bounded multiply-heavy PBR-lite highlight/Fresnel/rim response and an
explicit zero-half-vector fallback; it does not add textures, IBL, GGX tables or a larger material
record. The renderer uploads the same fields for ordinary and instanced population draws. Emissive
retains Grove's presentation-only pulse, while saved scene/ECS state stays unchanged.

## Sparse transform-animation boundary

An eligible static node may carry up to 16 named clips of whole relative transform poses, with zero
or one clip chosen to autoplay. Export writes the optional `transform_animations.kcan` (`KCAN392`)
asset only when at least one placed node has a clip. Duration is binary32; normalized time is unsigned
16-bit; translation, relative quaternion and scale multiplier are binary16. Each whole-pose key is
24 bytes, and the C++ loader validates the complete file before content starts.

KCAN v1 remains the exact legacy ABI. A project using only the old single-clip
`metadata.transform_animation` form emits the same 24-byte header, 16-byte node bindings and bytes as
before; native code exposes each as an implicit `main` autoplay clip. A project containing any
`metadata.transform_animation_library` uses KCAN v2 for the complete asset. Its header and keys are
unchanged, while each 24-byte clip binding adds the portable unsigned-64 FNV-1a clip hash and an
autoplay flag. Mixed legacy nodes become `main` autoplay bindings in that v2 asset. V2 bindings are
canonical by scene-node index and clip hash; one controller per node tracks the active clip, elapsed
time and playing state.

At each fixed tick the runtime composes packed polar motion first, transform animation second and
visual graphs afterwards. Animation uses the node's authored pose as its base, supports once, loop
and ping-pong plus nine shared easing codes, and uses shortest-path normalized quaternion
interpolation. Export rejects dynamic/Player/packed-motion/population/spinning owners so two systems
cannot write one transform. The native runtime supports named rigid-transform clips and direct graph
Play/Stop; it does not provide GLB animation import, skeletal animation/retargeting, crossfades,
layered blending, animation-state-machine authoring or animated glTF export.

## Visual graph boundary

When the source project contains bound visual graphs, export adds the compact `visual_graphs.kcvg`
asset. The C++20 VM's append-only vocabulary currently contains 27 block types: Ready, Tick, When
Timer Rings, Input Pressed, Trigger Enter/Exit, Branch, constants/state/NodeData component reads,
Repeatable Random Number, Find Nearby Object, Find Object Ahead, scalar math/comparisons, Set State,
Set Component, Send a Game Message, When Message Heard, Play Animation, Stop Animation, Apply Force,
Set Active and Despawn.

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

`KCVG001` opcodes 26 and 27 are **Play Animation** and **Stop Animation**. Play resolves the target
scene node and portable clip hash. Restart true, or changing to another clip, starts at elapsed zero;
Restart false resumes the same paused clip. Stop with Reset false holds its current pose and clock;
Reset true clears the active clip and restores the node's authored base pose. A missing animation
controller or clip reports a bounded graph issue instead of silently continuing. Graph execution
still follows the animation tick, so control changes apply deterministically at the graph step and
the next fixed tick advances the selected clip.

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
