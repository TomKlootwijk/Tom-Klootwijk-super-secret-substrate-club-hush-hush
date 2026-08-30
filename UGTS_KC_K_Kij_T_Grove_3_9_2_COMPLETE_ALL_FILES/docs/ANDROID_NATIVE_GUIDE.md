# Native Android Guide — Grove 3.9.2

## Generate the current project

The packaged generator/template is the authority for the current graph, packed-motion, transform-
animation, retained-display-hierarchy and population runtime. Generate it into a fresh folder, then open that generated folder
in Android Studio:

```bash
PYTHONPATH=src python -m ugts_kc3 build-android examples/tom_signature_arena_3d/project.json build/UGTSKCKKijTGrove --apk
```

`android/UGTSKCKKijTGrove` is a retained earlier signature-arena source snapshot. It remains useful
as historical source, but it does not contain the latest optional graph VM, packed-kinematics,
transform-animation, transform-hierarchy or population modules and must not be used to inspect
opcodes 23–30, KCHI392 or reproduce the current First Steps APK. Generate a fresh project from the
packaged template for the authoritative timer/cone/message, multi-clip animation-control, semantic
Movement and retained display-hierarchy runtime.

## Toolchain baseline

- Android SDK/compile SDK 36; target SDK 36; min SDK 26.
- Android Gradle Plugin 8.13.2 and Gradle 8.13.
- Android NDK r29 (`29.0.14206865`) and CMake 3.22.1.
- JDK 17 or newer accepted by the selected AGP (the release environment used JDK 21 for host work).

The source package intentionally omits private release signing keys. The command above builds a
standard debug APK for learning and owner-device testing; store publication requires your own private key.

## Variants

- `pocoX7ProDebug`: ARM64-only and explicitly selects `poco_x7_pro_12gb`.
- `universalDebug`: ARM64, ARMv7 and x86_64; runtime selection chooses high, balanced or
  compatibility tiers from model/GPU/RAM/GLES/refresh information.

Each generated project derives a stable base package under `org.ugts.games` from the project id.
Gradle flavors can add a suffix, so deployment treats `app/build/outputs/apk/.../output-metadata.json`
as authoritative. The `applicationId` in that file is the exact installed identity; it must not be
reconstructed from the folder, title or base package.

## Runtime architecture

`NativeActivity` owns lifecycle and input. C++ loads `signature_scene.kc3d`, selects a profile,
creates an EGL ES 3 context, renders to a scaled offscreen framebuffer, blits to the display,
runs fixed-step gameplay, and adjusts the quality index after sustained frame or thermal stress.

Optional `packed_kinematics.kcpk` data is sparse: every moving node contributes a 24-byte record
(node index, profile index, reserved field and two unsigned 64-bit kinematic words), while all nodes
using a profile share its binary16 UGLUT2 log-encoded polar LUT. Projects without packed movers emit no
polar asset. Dynamic nodes cannot own this component because physics and packed movement would both
try to write the transform.

Optional `render_substrate.kcrp` is a strict 32-byte choice of root seed, packed-render mode and final
Bayer projection. Optional `polar_populations.kcpr` stores a bounded canonical operator table plus one
128-byte content-addressed recipe per real packed prototype. Ring and Polar Field need a 32-byte header,
five 16-byte operator meanings and one recipe (240 bytes total); Spiral adds one operator (256 bytes).
Legacy-only Ring, Spiral and Polar Field assets retain byte-identical KCPR v1. With Glow disabled, a
project opts into KCPR v2 only when it contains **Radial Burst (loops)**; a controlled standalone
one-Burst sidecar is 240 bytes. KCPR v3 is selected only when at least one recipe enables **Glow by
distance**; no-Glow v1/v2 assets remain byte-identical. V3 keeps the recipe record at 128 bytes by
reusing its final 12 reserved bytes for three canonical binary32 material-field lanes. The native
runtime keeps at most 64 recipe records and reconstructs random-access visible
members from their seed and lineage. It does not allocate copied ECS nodes or a resident matrix/pose
row for every requested display member.

Compatible packed prototypes and KCPR members share the same profile/mesh/material instance batch.
Direct mode decodes the packed words and reconstructs radius analytically in the vertex shader; LUT
mode uploads the exact binary16 lanes once per profile and samples them in the matching vertex path.
CPU remains the authoritative fallback for ownership conflicts and systems such as hierarchy or
animation. Glow by distance reuses UGLUT2 direction in LUT mode, uses cosine in Direct mode and uses
the quantized UGLUT2 reference in CPU fallback. The canonical top-origin 8x8 Bayer matrix runs only
in the final presentation pass. When the
driver supports `GL_EXT_disjoint_timer_query`, a four-slot nonblocking query ring reports later-available,
non-disjoint drawing samples; unsupported or failed timing is reported instead of estimated.

Radial Burst is a looping display effect, not a one-shot gameplay event. Its per-copy local packed
displacement compounds with the real prototype's packed anchor through the same log-encoded polar LUT
semantics. Direct remains the baseline reconstruction path; LUT shares the uploaded profile texture.
Each Burst recipe is capped at 512 instances, with at most 16 recipes and 2,048 Burst instances per
project. Native materialization is further bounded by the selected quality tier's maximum-visible
limit and the particle budget remaining after other visible work.

Optional `transform_animations.kcan` data is also sparse. Both `KCAN392` versions have a 24-byte
header and one 24-byte whole-pose key per saved time. KCAN v1 is the exact legacy format: projects
using only `metadata.transform_animation` retain their 16-byte node bindings and byte-for-byte
output, exposed by the runtime as one implicit `main` autoplay clip. The new
`metadata.transform_animation_library` selects KCAN v2 for the whole asset. V2 uses one 24-byte
binding per clip with scene-node index, unsigned-64 FNV-1a clip hash, duration, key range, loop mode
and autoplay flag. A mixed legacy node becomes a `main` autoplay binding. Projects without a clip
emit no KCAN asset.

Optional `hierarchies.kchi` data is the sparse retained-transform link table. Established KC3D392
records do not grow: each attached child's KC3D translation/rotation/scale is parent-local. KCHI adds
one 24-byte versioned header and one 8-byte pair of unsigned KC3D child/parent indices per link. A flat
project emits no KCHI file.

The native animation runtime captures each animated node's authored translation/rotation/scale as its base and composes
the quantized relative clip over it. At start and each fixed tick, packed polar movement runs first,
transform animation second, visual graphs next, generic body physics after that, and tag gameplay
next; the transform hierarchy publishes descendant world poses last. Validation rejects
dynamic nodes, Player, packed Movement Pattern, Populate Area and nonzero spin velocity so those
systems cannot compete for the same pose. Once, loop and ping-pong playback plus linear, step,
ease-in, ease-out, ease-in-out, smoothstep, smootherstep, back-out and elastic-out match the Python
sampler, including shortest-path normalized quaternion interpolation.

## Retained display hierarchy / KCHI392

An ordinary Mobile 3D node may name another ordinary node through `parent_id`. Missing references,
cycles and chains deeper than eight parent edges fail before export. Every object that owns children
must keep positive uniform scale; a parent animation must keep its scale uniform and positive at every
key. Attached children are display-only: Dynamic off, Collision None/non-sensor, no tags or spin, and
no visual graph, packed movement, scatter population or transform animation. An unattached root may
still move through otherwise-valid physics, spin, packed motion, animation or graph transforms; an
attached intermediate parent carries descendants only through its inherited transform.
Project export also rejects `hierarchy.parent_graph_scale` when a Logic Block can target a hierarchy
parent's scale without proving one complete saved positive-uniform XYZ vector. Per-axis and
runtime-selected writes do not reach native startup.

`transform_hierarchy.cpp` loads `KCHI392`, validates the 24-byte header and fixed 8-byte sorted links,
captures each child's immutable local TRS from KC3D, sorts links by depth and child index, and writes
composed world TRS back into ordinary `NodeData`. It composes after initial polar/animation loading,
again after Ready, and after graphs, generic bodies and tag gameplay on every fixed step. A project
without links calls the same loader with an empty asset and retains zero hierarchy records.

The Python desktop late system and `Mobile3DProject.to_scene()` use the same parent-before-child TRS
rule; static glTF keeps the parent/child nodes. `examples/parent_child_hierarchy_3d` verifies a
two-level moving carrier, a 1,633-byte KC3D and a 48-byte three-link KCHI. The separate host-native
acceptance consumes generated KC3D/KCHI, exercises three edges and malformed assets, and compiles the
same C++ module used by Android. It does not call `NativeActivity` on a phone, so install, launch,
Mali rendering and frame timing remain unverified for this slice. The local
`build/UGTS-Parent-Child-Hierarchy-3.9.2-Poco-X7-Pro-debug.apk` is 1,565,171 bytes with SHA-256
`813D290E2B89973FE4C429BF58FAD7F50BFB156C42EACB665A7ABB1B4BF36E20`; package/SDK/GLES,
ARM64-only native code, v2 debug signing and 16 KiB alignment inspect correctly. Authorized Poco
serial `XOVSTSHYNREMZ5D6` (`2412DPC0AG` / `rodin_eea`) installed it and cold-launched status OK in
448 ms; PID 25992 became resumed/visible/fullscreen. Runtime logs selected Mali-G720 MC7,
`poco_x7_pro_12gb`, `grove_g720_mc7_120`, balanced quality, 60 fps and render scale 1.00. This is an
install/startup result. A separate 15-second/five-sample profile in
`build/device-qa-hierarchy-poco-20260829/profile-15s.json` observed 630 intervals at 120.15 effective
FPS with 9.959 ms p95, thermal status 0 and no crashes/warnings. The companion
`hierarchy-running.png` shows one rendered frame. With only five nodes and roughly 60 submitted
triangles, neither capture proves child-following under interaction, large-game/AAA performance or
sustained thermal behavior.

## Generic dynamic bodies

`body_physics.cpp` is compiled into the Android library and the host-native acceptance executable.
After graph execution, it advances every live, active dynamic `NodeData` other than Player, applies
gravity and semi-implicit fixed-step translation, handles the world floor and X/Z bounds, then
resolves non-sensor solid pairs in stable UTF-8 object-ID order. Sphere and box contacts use the same
bounded-radius approximation, inverse-mass separation and minimum-restitution impulse as the desktop
oracle. This makes an owner-bound **Apply Force** useful on ordinary untagged objects.

`examples/dynamic_crate_parity_3d` is the narrow acceptance project. Its Ready graph pushes an
untagged mass-1.5 crate once. `tests/test_android_body_physics.py` generates its actual KC3D/KCVG,
loads those assets in C++, matches all seven Python-golden position/velocity bit checkpoints, and
requires the exact X `1.375` endpoint after 600 steps. The test also checks floor/bounds response,
static/dynamic and dynamic/dynamic contacts, sensor filtering, Player
exclusion and representative collectible/hazard/goal sensors. This host replay proves the portable
module and packed graph contract; it does not call Android `NativeActivity` or replace an on-device run.

Player intentionally retains the existing touch controller and its legacy floor/bounds response so
it is never integrated twice. Native body contacts are currently resolved and discarded: collision,
floor and bounds events plus generic grounded state are not yet available to native Logic Blocks.

The desktop editor's **Logic Trail** is deliberately absent from these assets. During Preview, block
badges and **Last Run** show execution order, values, selected flow and errors while the Logic tab is
read-only; Stop retains the latest display. That snapshot is nonserialized presentation state and
adds zero bytes to `KCVG001`, `KC3D392`, the APK or any other export.

## Saved Objects and Saved Scenes deployment boundary

**Saved Objects** are authoring-time single-node snapshots, not a native runtime object type. An
unused definition lives under project metadata: it changes the authoring project fingerprint but
adds no KC3D node, KCVG binding, KCPK component, KCAN binding or KCSP group. Once placed, the copy is
already one ordinary flat `Node3DRecord` before Android generation. KC3D and every sparse sidecar
therefore read the exact same final node tuple and existing node-index contract; Saved Objects need
no separate pack magic, native parser or C++ runtime type.

This is a no-instance-record claim, not a literal zero-dependency-byte claim. KC3D and KCVG still
emit the project's global mesh/material and graph resource tables without reachability pruning. A
resource retained only by an unplaced Saved Object can therefore remain in the APK.

Placed Saved Object copies share meshes, materials and graph bytecode. Material Look edits use copy-on-write when
a saved definition consumes that material. Graph edits remain intentionally live for every object
bound to those same Logic Blocks. Studio rejects Player, packed Movement Pattern, Populate Area and
literal-source graph cases before capture.

Linked **Saved Scenes** are also authoring-only. Each definition stores a bounded parent-local tree
once and each placement stores only one group transform. Android export calls the pure Saved Scene
materializer once, then gives the resulting canonical flat node tuple to KC3D and every optional
sidecar. Root/child IDs, internal graph references, graph bindings and leaf-animation keys are all
resolved before indices are assigned. `project.json` retains the links outside APK runtime assets;
`build-report.json` records both the authoring hash and materialized runtime hash.

No new JNI/native prefab type or Saved Scene pack magic is involved. Static linked groups therefore work with
the existing C++ ECS, graph VM, packed movement, scatter and animation loaders. Runtime parenting is
not retained for the linked definition: parent dynamic physics, spin, Animation and transform-writing
Logic Blocks are rejected, as are nested Saved Scenes, Player capture and transforms that would
require shear. Unlinking in the editor bakes one placement into ordinary nodes before the same export
path; those ordinary nodes may then use the separate display hierarchy when they satisfy its rules.

## Rigid-transform clip libraries / KCAN392

UGTS Studio's bottom **Animation** panel authors 1–16 named relative transform clips per eligible
static Mobile 3D node. New, Duplicate, Rename, Delete Clip and the one optional autoplay choice use
the project Undo stack, as do Length, Once/Repeat/Back and forth, whole-pose key and Arrival changes.
Each clip's first whole-pose key is fixed at time zero and preserves the base pose. Clip selection,
timeline Play/Stop and scrubbing are viewport-only presentation; they do not serialize a playhead or
running clock.

The child-facing Arrival chooser exposes every shared easing code: Straight (`linear`), Start gently
(`ease_in`), Stop gently (`ease_out`), Gently at both ends (`ease_in_out`), Smooth (`smoothstep`),
Extra smooth (`smootherstep`), Slight overshoot (`back_out`), Springy (`elastic_out`) and Jump
(`step`). Scale is kept positive, including easing overshoot, and the first key must remain an exact
relative identity.

The project contract caps one clip at 120 seconds and 128 keys, with at most 16 clips per node, 64
animated nodes, 256 clips and 4,096 keys per project. Key times must remain distinct after unsigned-16
normalization; translation, rotation and scale values must survive binary16 packing. Desktop Play
round-trips through that same quantization before attaching the priority -50 ECS system. The native
loader rejects bad magic, versions, counts, indices, duplicate `(node, clip hash)` bindings, more
than one autoplay clip per node, reserved fields, nonfinite/range-invalid values, truncation and
trailing bytes before content starts.

One mutable controller per animated node chooses at most one immutable clip. Mobile 3D Logic Blocks
can Play a named clip with optional restart or Stop it with either hold/resume or authored-pose reset
semantics. This is still narrower than a character animation suite: current glTF output is static,
and GLB animation import, skeletal animation/retargeting, crossfades/layered blending and animation-
state-machine authoring are absent.

## Logic ownership and opcodes 22–30

The Logic Blocks workspace follows the selected owner. An unbound 2D/3D object shows a transient
blank graph; its first meaningful edit creates and binds the graph in one Undo command, and Undo
removes both. Objects with several intentional bindings receive an exact graph chooser. Populate Area
prototypes cannot own Logic Blocks and must have the recipe turned off before graph creation.

The built-in Mobile 3D/native vocabulary now contains 30 blocks; its portable desktop/web/native
subset remains 25. `KCVG001` opcode 22 is **Find Nearby Object**: an origin object, one of the
portable tags `player`, `collectible`, `goal`, `decorative` or `hazard`, and a finite non-negative
inclusive radius. Native C++ excludes the origin and dead/inactive candidates, chooses the nearest
active/alive match, and uses object ID to break an exact-distance tie deterministically. Its
found/entity/distance result follows the same binary32 rules as desktop and the retained 2D web VM.
The First Steps Mobile 3D project demonstrates it in **World Logic → Find the Goal**, with explicit
Player origin, Goal tag, 9 m radius and the `nearby_goal` state key.

Append-only opcode 23 is **When Timer Rings**. Its `seconds` and `repeat` values are packed literals,
not connected runtime inputs: seconds must be finite positive binary32 through 86,400 and defaults
to 1, while repeat must be boolean and defaults to true. Native C++ advances a binding-local active
fixed-step counter. An inactive entity pauses its own timer while world bindings and the rest of the
world continue; Ready or restart resets it. Repeating and one-shot timers emit no more than one ring
per update and expose count, remaining fixed-step seconds and bound entity. No clock, suspended graph
or timer continuation is serialized. Desktop, retained web, pack and native golden fixtures cover
the same lifecycle, and the editor exposes bounded Seconds/Repeat controls with save/load and
Undo/Redo parity.

Append-only opcode 24 is **Find Object Ahead**. It accepts Origin, the same portable Tag and inclusive
Radius, plus one Vector4 storing explicit world-axis X/Y/Z and minimum cosine. Native C++ normalizes
the finite nonzero axis and candidate direction with the source-aligned round-after-each-operation
binary32 GSP4 schedule, then applies an inclusive cosine comparison. It uses no trigonometry and does
not read Origin rotation or scale. Found/entity/distance, filtering, nearest selection and UTF-8 tie
behavior remain identical to opcode 22.

Append-only opcode 25 is **When Message Heard**. Its `message` is a saved literal portable ID rather
than a linked input; matching is exact. The root exposes source, optional target and bound entity,
then its flow output. Existing opcode-15 sends enter one per-world, non-reentrant FIFO. Broadcasts
visit active entity bindings by canonical scene index then graph ID and world bindings last;
targeted sends visit the target owner's bindings plus world bindings. Nested sends are breadth-first,
all Ready handlers finish before Ready-time delivery, and no queue state is serialized. Native and
portable runtimes reject the 65th queued event with `EventLimit` and cap the whole outer batch—initial
handlers plus message handlers—at 16,384 node steps with `TotalStepLimit`.

Append-only opcodes 26 and 27 are **Play Animation** and **Stop Animation**. Play takes an entity,
portable clip ID and boolean Restart. Restart true, or selecting a different clip, starts at elapsed
zero; Restart false resumes the same paused clip. Stop with Reset false holds the sampled pose and
clock; Reset true clears the active clip and restores the authored base pose. Static editor/export
checks reject known missing targets or clips, while runtime-selected values report
`MissingController` or `MissingClip` rather than being ignored. The clip ID is shared across KCVG and
KCAN as unsigned 64-bit FNV-1a, so graph bytecode never depends on KCAN record order.

Append-only opcodes 28 and 29 are **Read Movement** and **Change Movement**. Both hardcode the
semantic virtual `polar_movement` component instead of packing its component-name string. Read takes
an entity, one of `radius`, `angle_degrees`, `facing_degrees`, `turns_per_second`,
`growth_per_second`, `turn_acceleration` or `growth_acceleration`, plus a numeric fallback. Change
takes the same entity/field choice and one numeric value. Native reads decode the packed component;
writes validate the selected profile, preserve every unrelated packed field, repack and compose the
authoritative transform immediately. Python/native packed-word and transform parity is covered. A
fixed four-node graph packs to 239 bytes/eight inputs with these blocks versus 268 bytes/ten inputs
through generic component blocks—a 29-byte reduction with no `polar_movement` string. The retained
browser runtime explicitly rejects both blocks as Mobile-3D-only rather than dropping them.

Append-only opcode 30 is **Show or Hide Extra Copies**. Its object input is a saved literal: an empty
choice means the graph owner only when that owner has Make Many, while World Logic or another owner
must choose an actual Make Many prototype. Its Boolean may be linked. The action changes one bit in
a fixed `uint64_t` runtime mask and continues through `out`; it has no data result. The prototype
remains alive/active and ordinary Logic Blocks continue. The shared CPU/Direct/LUT recipe loop tests
the bit before prototype lookup, random-access materialization or visible-node budget consumption.
The mask resets visible on a new runtime and never enters KCPR, KCPK, project JSON, ECS components,
snapshots or hashes. A Ready-plus-action graph costs 121 bytes, 29 more than Ready alone.

## Radial Burst / KCPR v2

**Make Many → Radial Burst (loops)** keeps exactly one authored ECS prototype. Its generated members
are display data, not independent entities, so opcode 30 hides only those extra copies and never the
prototype. Legacy-only recipe packs remain KCPR v1 with unchanged bytes and golden hashes; with Glow
disabled, KCPR v2 appears only when at least one Burst recipe exists. A controlled standalone Burst
pack contains a 32-byte header, five 16-byte operator meanings and one 128-byte recipe: 240 bytes total.

Burst's local radius/angle/height/scale envelope is deterministic for a fixed integer tick. It is
composed on top of the prototype's current packed anchor. CPU fallback, Direct and shared-LUT modes
consume the same packed endpoints; Bayer remains a separate final presentation pass. The editor's
stopped preview deliberately uses the loop midpoint. Desktop Play uses the real post-step world tick
and presents that fixed endpoint without manufacturing an interpolation alpha.

The build harness completed the separate 18-case Burst matrix: 32, 128 and 384 instances across CPU,
Direct and LUT, each with Bayer Off and subtle.

```powershell
python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only
```

The preserved `built_only` run is
`build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de`: 18/18 cases in 272
seconds. Each case contains a 1,690-byte KCPK, 240-byte KCPR and 32-byte KCRP; APK sizes range from
1,804,558 to 1,804,566 bytes. Native host vectors and the ARM64 builds cover implementation and link
boundaries, but none of these APKs has been installed or exercised through real GLES/Mali. No POCO
visual, timing, power or thermal claim follows from build-only evidence.

## Glow by distance / KCPR v3

Under any non-Off Make Many pattern, **Glow by distance** exposes one enable checkbox plus Start
distance, End distance and Glow strength. Start zero maps to the Movement profile's explicit clamped
core; otherwise Start and End must describe an increasing interval inside that profile. Strength is
bounded from 0 through 4. The authored nested object compiles to center log radius, inverse half-width
and strength, then forms a smooth bounded radial pulse. It changes material lighting only, not packed
movement, generated positions or ECS identity.

The modifier adds three canonical operator meanings and selects KCPR v3 for the complete asset. The
fixed 128-byte recipe record does not grow: v3 gives meaning to the final 12 bytes that are zero and
reserved in v1/v2. Recipes without the modifier remain valid zero-tail records in a mixed v3 pack.
When no recipe enables it, the compiler emits the exact old v1 or v2 asset. Enabling it changes the
full recipe content address but preserves the placement lineage namespace and deterministic prefix.
The native loader reconstructs the compiled Start/End interval from center and inverse half-width,
checks it against the profile-clamped explicit core and `rhoMax`, and rejects the asset rather than
running an out-of-profile field. Startup logs `format_version`, `glow_recipes`, `glow_instances` and
`gpu_instance_stride_bytes=36`, giving later device acceptance a fail-closed identity check instead
of relying on appearance alone.

Lineage lane 5 derives a count-independent 12-bit material phase. Direct/LUT GPU staging stores the
phase in one 32-bit integer attribute, increasing a visible polar instance from 32 to 36 bytes; no
phase array or matrix record is persisted for all requested copies. The shader evaluates a smooth
log-radius pulse and a phase-shifted direction. Shared LUT calls the existing UGLUT2 direction sample,
Direct calls cosine, and CPU fallback/reference evaluates the quantized UGLUT2 form. The resulting
0–4 scalar is added as `base colour × field` after ordinary material lighting; alpha stays unchanged.
The existing Bayer shader still runs later as the final presentation pass.

Burst needs distinct native groups for the real prototype and the generated copies because only the
copies use Burst's local displacement. A copy evaluates the Glow band from its local packed rho before
that pose compounds with the prototype anchor; the real prototype evaluates its own packed rho. This
preserves local-effect composition and does not reconstruct Cartesian distance. Both groups receive
the same modifier and seeded phase rules. Non-Burst Glow may keep prototype and copies in one
compatible group, and non-Glow batching is unchanged.

Double-click `RUN_POLAR_GLOW_LAB.cmd` from the repository root for the shortest manual check. It
generates the project if absent, then opens a 128-display Burst project with Shared LUT, subtle Bayer,
Glow distance 0–4 and strength 1.25. Building it proves only compilation/link/package integration. Until that exact APK is
installed and observed on POCO/Mali, visual parity, GPU timing, frame rate, power and thermal behavior
remain unmeasured.

Double-click `RUN_POLAR_GROW_LAB.cmd` for the separate v4 check. It generates
`build/polar-grow-lab/packed-polar-grow-burst-128-lut-subtle.json` with the same bounded field and
ticks **Grow glowing copies**. KCPR v4 adds one slot-12 apply operator but keeps each recipe at 128
bytes and native visible instances at 36 bytes. The multiplier is `clamp(1 + glow, 1, 5)` and is
applied only after a generated copy's ordinary/Burst display scale. Index-zero prototypes still use
Glow lighting, but never the size multiplier; their ECS transform, collider and picking remain
authoritative.

The separate fail-closed Glow benchmark matrix is:

```powershell
python validation/benchmark_polar_render_poco.py --workload glow --include-cpu --build-only
```

It covers 64/256/1,024 Ring displays, Direct/LUT with Bayer Off/Subtle, and CPU fallback with Bayer
Off. `--build-only` deliberately stops before ADB. Remove that flag only after `adb devices -l`
lists an authorized target; runtime acceptance then requires exact v3/Glow/stride/batch/ECS telemetry.

The corresponding fail-closed Grow matrix is:

```powershell
python validation/benchmark_polar_render_poco.py --workload grow --include-cpu --build-only
```

It uses the same 64/256/1,024 Ring cases. Build acceptance requires KCPR v4, native consumer
`android-kcpr392-v4`, the exact Glow meanings plus `polar_display_scale_from_glow`, one real ECS
prototype and the unchanged 36-byte GPU stride. A physical run is accepted only when startup reports
one Grow recipe, `count - 1` grown generated displays, `count` Glow-lit displays, one Direct/LUT batch
or zero CPU batches, and `ecs_generated=false`.

## First Steps compact graph evidence

First Steps demonstrates opcode 23 in **World Logic → Count the Timer Rings**, where a repeating
one-second timer stores its count as `timer_rings`, and opcode 24 in **Find the Goal Ahead**, where
3D Forward with Normal width stores `goal_ahead`. It demonstrates opcode 25 in World Logic → **Hear
the Dash Message**: the Dash graph sends `player.dashed`, and the separate `message_lesson` graph
receives it and stores `heard_message=true`. The current source exports seven graphs, 27 nodes and
seven bindings including four world bindings. Its 1,265-byte KCVG has SHA-256
`363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`; the 914-byte KCPK
(`8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`) and 60-byte KCSP
(`E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`) bring the compact sidecar
total to 2,239 bytes. Fresh idle execution has state SHA-256
`a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; dash/message execution sets
`heard_message=true` and `score=1`.

## Populate Area / KCSP392

The Mobile 3D first-steps project includes **Crystal Garden**, where one authored static crystal uses
an 18-object **Populate Area** recipe. The optional `scatter_populations.kcsp` sidecar contains one
24-byte header and one fixed 36-byte record per populated group. A group contains 2–256 display
objects including its authored prototype; the parser accepts at most 64 groups and 1,024 population
objects in total. Projects without populated groups emit no KCSP asset.

World number, prototype id and copy index feed a random-access SplitMix64-derived schedule. Native C++
regenerates the same binary32 translation, scale and yaw matrices as the desktop path. Increasing a
count therefore preserves every earlier copy as a deterministic prefix. The renderer uploads one
matrix buffer per group and submits generated copies through GLES `glDrawElementsInstanced`; the
authored prototype remains an ordinary scene node. When the selected quality tier's visible-node
budget cannot show every copy, the renderer submits the same deterministic prefix.

This is a render-only optimization, not a new gameplay entity source. Validation rejects prototypes
that are dynamic or moving, have a collider or Trigger Area, use player/collectible/goal/hazard tags,
or own Logic Blocks or a Movement Pattern. Copies do not receive independent collider, graph,
movement, input or gameplay state. The desktop Scene view is separately capped at 64 generated copies
per group and 256 globally; glTF bakes all copies as explicit render-only nodes. Mobile 3D has no
browser player, so there is no browser Populate Area parity.

KCSP's safety caps and instanced draw calls are not physical-device performance evidence. Population
placement does not avoid overlaps, and the native renderer currently has no per-copy frustum culling,
occlusion selection or LOD. Those boundaries still apply on the Poco profile.

## Trigger Area3D parity

A Mobile 3D sphere or box collider marked as a sensor tracks the first active node tagged `player`.
It emits one `trigger_enter` transition on entry and one `trigger_exit` transition on departure,
without collision impulse. Desktop Play and native C++ use the same translation/scale-aligned
sphere/sphere, box/box and sphere/box tests. Packed polar composition is applied before trigger
detection, so a moving sensor is tested at its composed position.

**Trigger Enter** and **Trigger Exit** are native graph roots as well as desktop Logic Blocks. A world
graph receives every transition; an entity graph receives only transitions for its bound sensor.
Each root exposes `sensor`, `player` and the graph's bound `entity`. Project validation and the native
tracker cap active trigger areas at 4,096; the native graph VM separately caps trigger dispatch at
256 transitions per fixed step so hostile content cannot create an unbounded graph workload.

The editor exposes this without project-data editing: **+ Trigger Area** creates a ready-made sensor,
while **Trigger Area → Use as Trigger** converts a selected 3D object. Choose Sphere and Radius or Box
and Size X/Y/Z. The Scene Tree and Resources panel identify Trigger Areas, and changes support
Undo/Redo and save/load.

For the decorative path, select **Crystal Garden** and edit **Populate Area** in the same Inspector.
Object count, World number, area, scale range and random yaw are one undoable recipe; Resources lists
it under **Populated Areas** rather than expanding the project into hundreds of saved nodes.

## Controls

Left touch moves and a left tap jumps. Right drag orbits; a short right-side tap dashes, including
while the left movement thumb remains held. Two-finger spacing changes camera distance. Keyboard uses
WASD/arrows to move, J to jump, and Enter/Shift to dash. Space triggers both beginner jump and dash
actions, matching the editor preview. Gamepads use the sticks, A and B.

## POCO tuning

The signature tier requests 120 fps, 1.0 render scale, up to 1024 visible nodes and ARM64.
This is a target policy, not a guarantee: Android, the display mode, thermal state and workload
can reduce the effective frame rate. The adaptive controller degrades safely when needed.

## Direct install

With exactly one authorized phone attached:

```bash
PYTHONPATH=src python -m ugts_kc3 android-devices
PYTHONPATH=src python -m ugts_kc3 build-android examples/tom_signature_arena_3d/project.json build/UGTSKCKKijTGrove --install
```

With the game open and the phone screen on, collect a non-invasive baseline without simulated
touches or device-setting changes:

```bash
PYTHONPATH=src python -m ugts_kc3 profile-android org.ugts.games.tom_klootwijk_signature_arena_3d.pocox7pro --seconds 30 --json
```

The profiler pins the same sole authorized device, reads the active NativeActivity surface through
SurfaceFlinger, and samples process PSS/RSS, Android thermal status, reported GPU temperature and
battery state; it also checks the running app's crash buffer. It clears only SurfaceFlinger's
diagnostic latency history between sample windows, injects no input and changes no game/device
setting. Its result describes that workload and duration; it is not a general device benchmark.

The desktop editor exposes the build targets **Poco X7 Pro APK (Debug)** and
**Poco: Build + Install + Open**.
Its blue **Deploy to Phone** toolbar action performs the full owner-device loop:

1. require exactly one authorized ADB device and remember its serial;
2. generate and compile the Poco debug project under the saved project's
   `.ugts-studio/deploy/<project-id>-android` folder;
3. install with `adb -s <serial> install -r -g`;
4. read Gradle's exact output `applicationId` and open
   `<applicationId>/android.app.NativeActivity` on that same serial.

No-device, unauthorized, offline and multiple-device states are reported in plain language before
compilation begins. Later messages preserve the completed build when install fails, and preserve the
installed APK when only launch fails, so Output always identifies the phase that needs attention.

After deployment, leave the game running and the screen on, then choose **Check Phone**
(`Ctrl+Shift+P`). The GUI runs the same default 30-second profile on a background worker so Studio
does not freeze, and reports frame cadence, PSS memory, available GPU temperature, crash lines and
warnings in Output. CLI JSON retains additional available RSS, battery and thermal fields.

The current PBR-lite/opcode-25 APK is locally built and inspected at
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk`: 1,484,357 bytes with SHA-256
`B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`. The explicit
`pbr-lite-op25-debug` copy is byte-identical. Shader linking, `aapt` and `apksigner`
verify package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
`3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES 3.0, ARM64-only native code, a debug
certificate and APK Signature Scheme v2; embedded KCVG/KCPK/KCSP hashes match the current source
sidecars. KCAN runtime markers are linked, while the unanimated starter omits the optional asset. The
Poco is absent from ADB, so this `B9B1…` APK has no install, launch, installed-byte hash
match or physical profile claim. The preceding local `message-op25-debug` /
`message-op25-audit-fixed-debug` snapshot remains 1,451,149 bytes / `1003F061…`.

The animation demo at `build/UGTS-Animation-Timeline-3.9.2-Poco-X7-Pro-debug.apk` is 1,483,820
bytes / `43D197EC…` and contains an 88-byte KCAN with one binding and two ping-pong keys. It is also
locally built and inspected only.

The last physically verified pre-audit opcode-25 APK is preserved explicitly as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-message-op25-pre-audit-debug.apk`: 1,449,653 bytes with
SHA-256 `FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`. Xiaomi
`2412DPC0AG` / `rodin` installed and cold-launched it. The pulled
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-message-op25-base.apk` is also 1,449,653 bytes and
has the exact same SHA-256. Its 30-second profile collected 756 intervals at 120.12 effective FPS,
8.372/10.183/12.641 ms p50/p95/p99, thermal status 0 and no crash lines or warnings; the capture is
`validation/device/opcode25-message-poco-profile.json`. That physical evidence belongs only to FBCB.

The preceding opcode-24 build is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk`, 1,460,361 bytes with SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`.

The preceding opcode-23 build is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.

The preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` owns the earlier Poco cold-launch,
hash-match and 30-second result: 120.23 effective FPS, 10.118 ms p95, 132,590–138,573 KiB PSS,
44.634–45.511 °C GPU temperature, thermal status 0 and no crash lines or warnings. The retained
64.9-second Poco idle baseline belongs to a still earlier 3.9.2 APK. Those older results remain
historical and do not replace the opcode-25 snapshot. Interaction-heavy/touch, unplugged battery,
long-duration thermal, 60/90 Hz fallback and representative lower-tier testing remain open, as does
the first device install/profile of the post-audit APK.
