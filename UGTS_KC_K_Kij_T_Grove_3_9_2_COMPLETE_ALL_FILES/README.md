# UGTS-KC 3.9.2 — K-Kij-T / Grove

This package is the complete 3.9.2 release: the 3.9.1 substrate and artifacts plus the actual K-Kij-T / Grove native Android upgrade.

Grove's phone runtime is native Android rather than an HTML wrapper. The retained 2D workflow still
exports HTML5. Mali-G720 MC7 / POCO X7 Pro 12 GB is the performance focus, with general Android
fallback tiers.

## Desktop editor and first game

The Grove engine work now includes an optional PySide6 desktop editor, deterministic visual-graph
runtime, compact polar ECS components backed by a log-encoded polar LUT, and direct APK
build/install/open tooling. Core simulation and build commands remain dependency-free; Qt is only
needed for the editor.

UGTS Studio can add, copy, delete, select and move 2D entities or 3D nodes with undo/redo. The
Inspector can assign 2D pictures, 3D shapes and materials; Wavefront OBJ shapes import as validated,
undoable project resources. For non-dynamic Mobile 3D nodes, **Movement Pattern** offers Off, Orbit,
Spiral Out and Spiral In without exposing packed hexadecimal words. Orbit and spiral movers share one
binary16 log-encoded polar LUT profile; each authored mover becomes two unsigned 64-bit words and one
24-byte sparse Android record. Dynamic nodes are guarded because physics already owns their transform.
Logic Blocks are editable typed data, not generated source hidden behind the GUI. They are also
selection-owned: choosing a 2D or 3D object opens only that object's logic. An object with no binding
shows a genuinely blank graph; its first meaningful graph edit creates and binds that graph as the
same undoable operation, and Undo removes both again. If an object intentionally owns several graphs,
the Logic Blocks header provides an exact chooser. A **Populate Area** prototype cannot own Logic
Blocks; turn Populate Area off before attaching logic.

Native Android no longer moves only the specially tagged Player. Every live,
active, ordinary dynamic Mobile 3D node now receives gravity, fixed-step
translation, floor/bounds response and deterministic ID-sorted solid-pair
resolution after Logic Blocks run. `examples/dynamic_crate_parity_3d` proves
this with a two-block **When Game Starts → Push an Object** graph owned by an
untagged crate. The generated KC3D/KCVG assets are consumed by a C++ host
acceptance for the exact 600-step binary32 endpoint. Player deliberately keeps
the existing touch controller for now, and native contacts are not yet exposed
as collision/floor/bounds Logic Block events.

Ordinary Mobile 3D objects now also support a bounded retained transform hierarchy. In Studio's dark
Scene Tree, right-click a display object and choose **Attach to…** or **Detach**; both operations keep
the object at the same world pose and enter Undo/Redo as one edit. Attached rows nest below their
parents. A child's Inspector is labelled **Transform inside …** because its saved Position, Turn and
Size are parent-local, while the viewport and translation gizmo continue to display and edit world
space.

This first hierarchy slice is intentionally visual-only. A child must be non-dynamic, tagless, use a
non-sensor None collider, have zero spin, and own no Logic Blocks, Movement Pattern, Populate Area or
Transform Animation. An unattached root may still move through ordinary systems—including physics,
spin, packed movement, animation or graph-authored transforms where otherwise valid—and descendants
follow after those writers finish; an attached intermediate parent moves only by following its own
parent. Chains are capped at eight parent edges, and every object that owns
children must keep positive uniform scale so parent/child TRS composition cannot introduce shear.
Project validation reports `hierarchy.parent_graph_scale` when Logic Blocks could change a hierarchy
parent's scale without proving a complete positive uniform XYZ vector; per-axis or runtime-selected
scale writes are rejected instead of risking a device-only failure.
Desktop ECS, native C++ and static glTF share the same parent-before-child composition. Android adds
the optional sparse `hierarchies.kchi` (`KCHI392`) sidecar: a 24-byte header plus one 8-byte
child-index/parent-index link, omitted entirely for flat projects. See
`examples/parent_child_hierarchy_3d` for the moving two-level carrier example and source verifier.

The 25-block portable core vocabulary includes **When Timer Rings** under **Events**. Set **Seconds**
on the block to a finite positive binary32 value up to 86,400 (default 1 second), and leave **Repeat**
on by default or turn it off for one ring. Each binding counts only its own active fixed updates: an
inactive entity pauses its timer while the rest of the world continues, and Ready or a game restart
resets it. The block can ring at most once per update and exposes **Count**, **Remaining** and the
bound **Entity** without serializing or suspending a running graph. The child-facing editor controls,
desktop Preview, retained 2D HTML5 VM, compact `KCVG001` opcode 23 and native Android VM share that
contract.

The vocabulary also includes **Find Nearby Object** under **Sensing**. Choose an explicit
**Origin** (the graph's object or another project object), one portable tag—Player, Collectible, Goal,
Decorative or Hazard—and an inclusive radius. The block ignores the origin and any inactive or dead
candidate, returns the nearest matching object, and resolves equal-distance results by deterministic
object ID. Its result and error rules match in desktop Preview, retained 2D HTML5 and native Android;
`KCVG001` stores it as compact opcode 22.

Append-only opcode 24 adds **Find Object Ahead** (`query.nearest_in_cone`) under **Sensing**. It keeps
the same portable tag, inclusive radius, filtering, nearest-result and tie rules, then applies a
source-aligned binary32 GSP4 cone. **Cone** is one explicit Vector4 containing world-axis X/Y/Z and
the minimum accepted cosine. The axis is normalized deterministically; no runtime trigonometry is
used, and rotating or scaling Origin does not turn or resize the saved world-space cone. The editor's
2D Right and 3D Forward presets write exact child-safe literals, while advanced graphs may link an
arbitrary finite nonzero axis and a minimum cosine from -1 through 1.

Append-only opcode 25 adds **When Message Heard** (`event.message`) under **Events**. A receiver saves
one exact portable message name on the block and exposes the sender, optional target and bound entity.
**Send a Game Message** now enters one bounded, non-reentrant FIFO shared by the world's active graph
bindings: broadcasts visit entity bindings in scene order and graph-ID order before world bindings,
while a targeted message reaches the target owner and world logic. Nested sends are breadth-first;
there is no payload or serialized queue. Desktop Preview, the retained 2D HTML5 VM, `KCVG001`
opcode 25 and the native Android VM use the same 64-event / 16,384-total-step safety contract.

During desktop Preview, the **Logic Blocks** tab stays open in read-only mode. Its **Last Run** panel
and block badges show execution order, values, chosen flow and errors from the current graph. The trail
survives Stop so it can be inspected, but it is presentation state only: it never changes project
data, is never serialized and contributes zero bytes to every export.

Mobile 3D **Appearance** now has a child-facing **Material Look** chooser: Matte, Toy Plastic, Metal
and Crystal Glow. A look keeps the object's colour and double-sided flag. If another authored object
shares the material, Studio clones it and rebinds only the selected prototype; its Populate Area
copies continue to share that prototype. The complete clone/rebind is one Undo step, including a
save-safe dirty marker. Looks are inferred from ordinary metallic/roughness/emissive values—no preset
name is serialized and the fixed 40-byte KC3D392 material payload does not grow.

Desktop Preview and native GLES use the same compact multiply-only **PBR-lite** response for those
saved values: diffuse, a broad-to-sharp roughness lobe, Schlick-style Fresnel, a small rim and
emissive light. This is intentionally a stable low-cost material model for Mali-class phones, not a
claim of a full texture/IBL/production PBR pipeline.

The bottom **Animation** panel now gives an eligible static Mobile 3D object a small library of named
relative transform clips. **Create Animation** starts a **Main** clip with a protected starting-pose
key. **New**, **Duplicate**, **Rename** and **Delete Clip** manage up to 16 clips on that object, and
one clip—or no clip—can be chosen to play when the game starts. For the selected clip, choose a Time,
edit the relative Position offset, Turn and Size multiplier, then add or update a whole-pose key.
Length, Once/Repeat/Back and forth, preview Play/Stop, scrubbing, Arrival and key removal stay in the
same child-facing panel. Authored changes are atomic Undo/Redo commands, while clip selection,
scrubbing and the preview clock are temporary viewport state and never dirty or serialize the
project. Arrival exposes all nine deterministic easing modes with child-readable names: Straight,
Start gently, Stop gently, Gently at both ends, Smooth, Extra smooth, Slight overshoot, Springy and
Jump.

Keys are relative to the object's authored pose, so moving or duplicating the object keeps every
clip attached to it. Mobile 3D Logic Blocks add **Play an Animation** and **Stop an Animation** as
append-only `KCVG001` opcodes 26 and 27. Choose this object or another animated object, then choose a
saved clip. **Restart** begins it from the first pose; leaving Restart off resumes the same paused
clip, while changing clips starts the new one at its beginning. Stop can either hold the current pose
for a later resume or **Reset** to the object's authored pose. Saved literal targets and clip choices
are checked while authoring; values chosen by a running graph are checked at runtime with a clear
Logic Trail/native issue.

Mobile 3D now has 30 built-in blocks while the portable desktop/retained-HTML5/native subset remains
25. Append-only opcodes 28 **Read Movement** and 29 **Change Movement** avoid exposing the virtual
`polar_movement` component name: choose an object, one of Radius, Angle, Facing, Turn speed, Growth
speed, Turn acceleration or Growth acceleration, and a numeric fallback/value. Reads and writes keep
Python/native packed words and transforms in parity. In the fixed four-node comparison this form
packs to 239 bytes/eight inputs instead of 268 bytes/ten inputs for generic component access, with no
`polar_movement` string. The retained browser exporter reports these blocks as Mobile-3D-only rather
than silently dropping them.

Append-only opcode 30 **Show or Hide Extra Copies** is the first dedicated Make Many Logic Block.
It changes one ephemeral bit for an authored Make Many object, leaving the real ECS prototype alive,
visible and selectable. The fixed recipe, content address, packed movement and generated prefix do
not change. Hidden recipes are skipped before CPU/Direct/LUT materialization or visible-budget use;
starting a new Play runtime restores all extra copies. A Ready-plus-action graph is 121 bytes, only
29 bytes more than its 92-byte Ready-only baseline.

Desktop Mobile 3D optional components now live in world-owned sparse pools behind each entity's live
dict-compatible `extra_components` view. Cached canonical query plans choose the smallest required
sparse pool, then evaluate mutable tags/alive/active and return lexicographic IDs. The
`polar_movement` virtual query aliases packed movement, and project JSON, snapshots and hashes do not
change. Built-in transform/body/collider/render fields remain in the compatibility record; full
archetype migration and tag/spatial/render-batch indexing are still future work.

Desktop Play and native Android consume the same duration/time/transform quantization. Android emits
the optional sparse `transform_animations.kcan` (`KCAN392`) asset only when at least one placed node
has a clip. Dynamic nodes, Player, Movement Pattern, Populate Area and spin-velocity ownership are
rejected instead of allowing competing transform writers.

At the file-format boundary, an unchanged old `metadata.transform_animation` project still compiles
to byte-for-byte-compatible **KCAN v1**: one implicit `main` autoplay clip per animated node, a
24-byte header, a 16-byte node binding and unchanged 24-byte keys. The new
`metadata.transform_animation_library` form uses **KCAN v2**. It keeps the 24-byte header and 24-byte
keys, but each 24-byte clip binding adds a stable unsigned-64 FNV-1a clip-ID hash and an autoplay
flag. A node may contain up to 16 clips, only one may autoplay, and only one clip is active at a time.
If any node uses the library form, the complete asset is v2; legacy nodes in that mixed asset become
the implicit `main` autoplay clip. Projects without clips still emit no KCAN asset.

This is bounded rigid-transform multi-clip authoring with direct Logic Blocks Play/Stop control, not
a full character-animation system. It does not add GLB import/animation authoring, skeletal rigs or
retargeting, crossfades/layered blending, animation-state-machine authoring, or animated glTF export;
the current glTF path remains static.

Mobile 3D has two honest reusable-authoring levels. **Saved Objects** remains the small one-node
stamp: select a safe object, press **Save Object**, then **+ Saved Object…** to place a fresh ordinary
ECS node. The snapshot is one-time, placed nodes are independent, and shared meshes, materials and
Logic Block bytecode stay compact.

**Saved Scenes** is the linked multi-object level. Ctrl-select two or more ordinary 3D objects, leave
the intended group root as the primary selection, and press **Save Together**. One definition stores
up to 64 parent-local ECS records and its captured relative Logic Blocks once. **+ Saved Scene…**
places only a stable instance ID plus one group transform in authoring metadata. The Scene Tree shows
that placement as one linked group with read-only child rows; the Inspector moves, turns or scales
the whole group. **Unlink** bakes that one placement into ordinary editable nodes, and Undo restores
the link.

Before validation, desktop Preview, packed ECS, KC3D/KCVG/KCPK/KCSP/KCAN, glTF or Android generation,
one pure deterministic materializer expands every linked placement into the same canonical flat node
order. Existing runtime ABIs therefore need no prefab opcode, native parser or per-instance hierarchy
record. Owner-relative graphs can remain shared; internal object references and leaf Animation keys
are remapped for each placement. Definitions are immutable snapshots in the current GUI—there is no
edit-in-place propagation, nested Saved Scene or per-instance child override. Saved Scene placements
still flatten their captured definition tree before runtime; they do not automatically become the
separate ordinary display hierarchy described above. Consequently, a Saved Scene parent may not use
dynamic physics, spin, Animation or transform-writing Logic Blocks; animate a leaf instead. Player
and world-centred packed Movement Patterns are rejected with child-readable explanations.

Projects support 64 Saved Scene definitions, 64 objects per definition, 256 linked placements and
4,096 final materialized objects. Unplaced definitions add no scene/component instance records, but
global resource tables are not reachability-pruned, so a mesh, material or graph retained only by a
library definition can still ship.

On Windows, double-click `RUN_UGTS_STUDIO.cmd` in this folder for a one-click launch. It checks the
editor dependency on first use and offers to install it only when needed. Studio starts in its dark,
viewport-first layout; Resources shares the left tab strip, and Output/Animation stay closed until a
workflow needs them.

```powershell
python -m pip install -e ".[editor]"
python -m ugts_kc3 editor
# After installation, the no-console desktop shortcut is also available:
ugts-studio

# A child-friendly first project with one readable logic graph
python -m ugts_kc3 new games\my_first_game --title "My First Game"

# The same gentle idea in a phone-ready 3D project
python -m ugts_kc3 new-3d games\my_first_phone_game --title "My First Phone Game"
```

Start with [`docs/FIRST_10_MINUTES.md`](docs/FIRST_10_MINUTES.md). Technical decisions and honest
boundaries are in [`docs/ENGINE_ARCHITECTURE.md`](docs/ENGINE_ARCHITECTURE.md).

The Mobile 3D first-steps lesson now includes **Crystal Garden**. One authored static crystal carries a
**Populate Area** recipe and becomes 18 deterministic display objects. A group may contain 2–256
objects including its authored prototype; a project may contain 64 groups and 1,024 population
objects in total. Android stores one 36-byte group record plus one shared 24-byte `KCSP392` header,
regardless of the group's object count. Raising the count preserves the existing deterministic prefix.

Populate Area is intentionally bounded decorative population, not general gameplay PCG. The editor
rejects dynamic, moving, collider/Trigger Area, gameplay-tagged, Logic Block or Movement Pattern
prototypes. Generated copies have no independent collider, graph, movement or gameplay identity.
Desktop authoring shows at most 64 generated copies per group and 256 globally; glTF bakes copies as
nodes, while native GLES draws generated copies with instancing and may keep a deterministic prefix
under its visible-node quality budget. The current implementation does not prevent overlaps and has
no per-copy frustum culling or LOD. Mobile 3D and Populate Area do not have a browser runtime; the
retained HTML5 workflow remains the 2D path.

Packed polar prototypes also expose **Make Many** with Off, Ring, Spiral, Polar Field and **Radial
Burst (loops)** patterns. For the shortest hands-on route, double-click `RUN_POLAR_GLOW_LAB.cmd` in
the repository root. It generates the project if absent, then opens a 128-display Burst project with
Shared LUT, subtle Bayer and **Glow by distance** set to 0–4 at strength 1.25.
This newer path keeps one real ECS object and stores a content-addressed `KCPR392` recipe instead of
copying component records or matrices. The recipe is random-access by a combined project/recipe seed;
increasing a supported count keeps the existing prefix and changes the recipe identity, not its byte
length (legacy workloads include 64 through 1,024). The Inspector shows the exact KCPR byte count
and full content address, while its viewport
preview is globally capped at 64 derived display copies. Generated members remain render data and
cannot silently acquire colliders, tags, graphs or gameplay identity.

Legacy-only Ring, Spiral and Polar Field assets remain byte-identical KCPR v1. With Glow disabled,
KCPR v2 is emitted only when a project contains Radial Burst; a controlled one-recipe Burst sidecar
is 240 bytes. Burst is a looping display effect, not a one-shot gameplay event: each derived copy
applies a local packed
radial displacement through the profile's log-encoded polar LUT semantics on top of its real packed
prototype anchor. A recipe allows at most 512 instances, a project at most 16 Burst recipes and
2,048 Burst instances. The editor still retains no more than 64 preview copies globally.

Every non-Off Make Many pattern can optionally enable **Glow by distance**. Start distance, End distance and
Glow strength define one smooth material field in the same bounded log-radius chart; a start of zero
means the profile's explicit core and never asks for `log(0)`. Each member also receives a repeatable
12-bit material phase from its existing random-access lineage, so the field is seeded without changing
placement or the count-stable spatial prefix. Turning the modifier off therefore preserves the exact
old result: KCPR v1 and v2 outputs remain byte-identical. Turning it on selects KCPR v3 for the asset,
while each recipe record stays 128 bytes by reusing its final 12 reserved bytes for three binary32
field lanes. Native GPU staging grows only from 32 to 36 bytes per visible polar instance: one 32-bit
attribute whose low 12 bits carry the derived phase, not a serialized per-copy transform row.

During desktop Play, those already-created preview copies now follow the real prototype's current
packed pose, Movement Pattern, height, scale and vertical velocity through the same random-access
recipe. Dead or hidden prototypes hide both the real mesh and its copies; reactivation reuses the
retained copy items, and Stop restores the authored preview. A stopped Radial Burst preview shows
the deterministic midpoint of its loop. Play passes the real post-step world tick and draws that
fixed endpoint; it does not invent an interpolation alpha. The Android renderer's previous/current
interpolation has not yet been added to the editor.

Android can compare CPU transform fallback, direct GPU polar decoding and a shared binary16
log-encoded polar LUT path. The LUT supplies the radius/direction reconstruction and packed-heading
direction used by instanced rendering; a final presentation-only Bayer 8x8 pass offers Off, subtle
gradient smoothing and bounded palette modes. Those choices and the render seed fit in the optional
32-byte `KCRP392` record. Source, native-host, shader-link and APK-build evidence exists; actual
POCO/Mali visual parity, GPU timing, power and thermal results still require a visible ADB device.
For Burst, native visibility is bounded by the normal maximum-visible limit and the remaining particle
budget; Direct remains the baseline reconstruction path and LUT uses the shared profile texture.
For Glow by distance, LUT mode samples that existing UGLUT2 direction, Direct uses the corresponding
cosine, and CPU fallback/reference uses the quantized UGLUT2 result rather than dropping the effect.
The bounded field is added as `base colour × field` during scene lighting; alpha and the downstream
Bayer pass are unchanged. Burst keeps its real prototype and local-displacement copies in separate
native draw groups. A Burst copy evaluates Glow from its local packed rho before that pose compounds
with the prototype anchor; the real prototype evaluates its own packed rho. This preserves local
effect composition instead of recomputing Cartesian distance. These paths are source/host/build
evidence only until the exact APK is viewed and measured on POCO/Mali.

The separate Burst build matrix is defined as 32/128/384 instances across CPU/Direct/LUT and Bayer
Off/subtle, for 18 cases:

```powershell
python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only
```

The preserved build-only run at
`build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de` completed all 18 cases
in 272 seconds. Each case carries a 1,690-byte KCPK, 240-byte KCPR and 32-byte KCRP; its APK is
1,804,558–1,804,566 bytes. `built_only` means exactly that: none of these Burst APKs has been
installed or executed on the POCO/Mali device, so the matrix makes no visual or performance claim.

The fail-closed Glow matrix uses 64/256/1,024 Ring displays, Direct/LUT with Bayer Off/Subtle, and
optional CPU fallback with Bayer Off:

```powershell
python validation/benchmark_polar_render_poco.py --workload glow --include-cpu --build-only
```

That command is a build/package check. Remove `--build-only` only when `adb devices -l` shows an
authorized phone; the harness then rejects a run unless startup telemetry proves KCPR v3, all three
Glow meanings, the 36-byte instance stride, one real prototype, the expected batch count—one for
Direct/LUT or zero for CPU fallback—and no generated ECS rows.

The Scene viewport now offers **Device Look (reference)**. It keeps the editor's CPU projection and
exact binary16 LUT composition, then runs the packaged native Bayer shader in a desktop OpenGL post
pass. Its badge says `CPU LUT + ... Bayer`; Bayer Off stays on the unchanged raster viewport, and GL
failure falls back without losing selection or zoom. This is useful for checking the ordered-dither
look, but it is deliberately not the native Android polar GPU path: painter geometry/shading, the
grid, and gizmos remain part of the reference image.

The same starter now includes **World Logic → Find the Goal**. Its **Find Nearby Object** block names
**Player** as the Origin, searches the **Goal** tag through an inclusive **9 m** radius, and stores the
`found` result in world state as `nearby_goal`. The explicit origin makes the lesson valid as
whole-scene logic rather than relying on a hidden object binding.

**World Logic → Find the Goal Ahead** uses **Find Object Ahead** with the saved 3D Forward world axis
and Normal width, then stores `goal_ahead`. The starter's initial player orientation makes that fixed
world direction a readable first lesson; turning Origin would not rotate the cone.

Its second world lesson, **Count the Timer Rings**, connects a repeating one-second **When Timer
Rings** block directly to `timer_rings`. It teaches periodic behavior without asking a child to build
an Every Frame counter or introducing hidden suspended state.

The **First Steps** editor tab also includes World Logic → **Hear the Dash Message**. The Dash graph
sends `player.dashed`; the separate `message_lesson` world graph receives it with **When Message
Heard** and sets `heard_message=true`, making cross-graph communication visible without source code.

## Retained 3.9.1 substrate — Tom Klootwijk Signature Edition
## Vector Art, Deterministic 2D/3D Game Runtime and Native Android Source Target

UGTS-KC 3.9.1 is an additive upgrade of the supplied KC Elizabeth 3.9 archive. It preserves the
complete vector-first 2D/HTML5 stack and the earlier KC scene, geometry, spatial, material,
two-hand, replay, glTF and USDA APIs, then adds a separate versioned mobile-3D path and a native
Android C++ source project.

## Release paths

```text
2D authoring:
vector assets + input + scene project
-> deterministic 2D game world
-> bounded visual-graph VM
-> self-contained Canvas/Web Audio HTML5 build

3D/mobile authoring:
meshes + materials + tagged nodes + camera/light/world + optional parent-local display transforms/clips
-> deterministic 3D arcade oracle
-> retained static glTF, or compact KC3D392 + optional KCHI392/KCAN392/KCSP392 data
-> Android NativeActivity + C++20 + EGL/OpenGL ES 3.0 instanced population rendering
-> POCO signature / high / balanced / compatibility quality policy
```

The combined engineering catalog now reaches **M449**. M390–M449 cover the mobile-3D model,
native pack, Android renderer, adaptive device policy and explicit Vulkan/4D boundaries.

## Signature Android target

The primary profile is **POCO X7 Pro 12 GB**:

- ARM64 native flavor;
- 120 fps request and full render scale starting policy;
- Mali-G720 / POCO model hints and a 10 GB usable-memory floor;
- dynamic-resolution fallback and sustained FPS/thermal quality stepping.

The universal flavor also targets ARM64, ARMv7 and x86_64 with runtime high, balanced and
compatibility profiles. A target policy is not a frame-rate guarantee: Android display mode,
workload and thermal state remain authoritative.

## Run the 3D workflow

```bash
# Runtime information
PYTHONPATH=src python -m ugts_kc3 info

# Validate and simulate the checked-in signature arena
PYTHONPATH=src python -m ugts_kc3 validate-3d   examples/tom_signature_arena_3d/project.json
PYTHONPATH=src python -m ugts_kc3 simulate-3d   examples/tom_signature_arena_3d/project.json   --steps 480 --move-z -1 --json

# Compile/inspect the native scene and regenerate Android source
PYTHONPATH=src python -m ugts_kc3 pack-3d   examples/tom_signature_arena_3d/project.json   build/signature_scene.kc3d --inspect
PYTHONPATH=src python -m ugts_kc3 build-android   examples/tom_signature_arena_3d/project.json   build/UGTSKCKKijTGrove --apk
```

The desktop editor can produce a Poco debug APK directly. Its blue **Deploy to Phone** toolbar action
preflights the one authorized ADB device, pins that device's serial for the entire operation, builds
under the saved project's `.ugts-studio/deploy/<project-id>-android` folder, installs the APK and opens
the game. It reads the exact flavor-aware `applicationId` emitted by Gradle and launches
`<applicationId>/android.app.NativeActivity`; it does not guess a package name. Output distinguishes a
build failure from an install failure and from an APK that installed but could not be opened. Open
the newly generated deployment/build folder in Android Studio for the current runtime;
`android/UGTSKCKKijTGrove` is a retained earlier arena snapshot. With the deployed game already running and
the phone screen on, **Check Phone** (`Ctrl+Shift+P`) starts a nonblocking 30-second ADB profile. It
reports frame cadence, process memory, GPU temperature when Android exposes it and app crash-buffer
warnings in Output. It injects no input, changes no device/game settings and does not touch the
project; only SurfaceFlinger's diagnostic latency history is cleared between sample windows. The
same read-only diagnostic is available through `profile-android`; CLI JSON retains additional
available RSS, battery and thermal fields.
The checked-in native project contains a
66-node interactive arena, `NativeActivity` lifecycle, fixed-step movement/gameplay, touch,
keyboard and gamepad input, camera orbit/pinch, asset-loaded GLSL ES 3 shaders, depth/culling,
dynamic-resolution framebuffer, high-refresh request and adaptive quality controller.

Mobile 3D sensor colliders now emit non-physical Trigger Enter and Trigger Exit transitions. Those
are portable Logic Block roots on desktop and in the Android C++ graph VM, for both world graphs and
graphs bound to the matching sensor. Children can create one with **+ Trigger Area**, or select any
3D object and turn on **Use as Trigger** in the **Trigger Area** Inspector group. Sphere uses Radius;
Box uses Size X/Y/Z. These edits support Undo/Redo and save/load, and the Scene Tree and Resources
panel label sensor objects as Trigger Areas.

Select **Crystal Garden** in the same starter to change **Populate Area** object count, World number,
area size, size variation and random turning. The change is one normal Undo/Redo operation and only
the compact recipe is saved; the Resources panel reports it under **Populated Areas**.

## Retained 2D/browser workflow

```bash
PYTHONPATH=src python -m ugts_kc3 validate   examples/elizabeth_vector_quest/project.json
PYTHONPATH=src python -m ugts_kc3 build-web   examples/elizabeth_vector_quest/project.json   examples/elizabeth_vector_quest/dist
```

The browser-playable demo remains at
`examples/elizabeth_vector_quest/dist/index.html`.

## Python 3D example

```python
from ugts_kc3 import InputFrame3D, tom_signature_arena_project

project = tom_signature_arena_project("Tom Klootwijk")
world = project.instantiate_world()
world.step(InputFrame3D(move_z=-1), steps=240)
print(world.state)
print(world.state_hash())
```

## Validation status

- Python source compilation and mobile-project JSON Schema validation pass.
- The Python scene-pack compiler and independent C++ parser agree on the KC3D392 format-1 pack.
- The host-native parser, POCO selector and adaptive-quality controller compile and execute.
- The Android source tree, manifest, Gradle/CMake configuration, shaders and asset references pass
  static release checks.
- Mobile 3D Trigger Enter/Exit roots and sensor overlap behavior have desktop/native parity, with
  explicit sensor and per-step dispatch caps.
- The bounded static-transform Animation panel has named clip-library save/load and Undo/Redo,
  nondestructive scrubbing, optional autoplay, desktop ECS playback, Mobile 3D Logic Blocks
  Play/Stop control and KCAN v1/v2 native-runtime parity. It does not claim GLB import/animation
  authoring, skeletal animation, crossfades or animation-state-machine authoring.
- Wheel/source distributions build and install in a fresh environment.
- The HTML5 runtime executes the full current 25-block graph vocabulary, including Repeatable Random
  Number, Find Nearby Object, Find Object Ahead, When Timer Rings, When Message Heard and sensor
  Trigger Enter/Exit context, and passes headless JavaScript runtime checks.
- Focused multi-clip and PBR-lite desktop, browser, compact-pack, editor, shader and native-host checks
  pass. The fresh Glow-integrated full suite is green: 752 tests and 291 subtests in 203.32 seconds.
- The child-friendly First Steps source now emits seven visual graphs with 27 nodes and seven
  bindings, including four world bindings. Fresh idle execution has state SHA-256
  `a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`;
  after the dash/message path it records `heard_message=true` and `score=1`. Its 1,265-byte
  `KCVG001` has SHA-256 `363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`;
  the unchanged 914-byte `KCPK392` and 60-byte `KCSP392` retain SHA-256
  `8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313` and
  `E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`, for 2,239 bytes combined.
- The current PBR-lite/opcode-25/animation-runtime APK is locally built and inspected at 1,484,357
  bytes with SHA-256 `B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`. The canonical
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk` and explicit
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-pbr-lite-op25-debug.apk` are byte-identical.
  Package/version/SDK/GLES, ARM64-only native code, debug-certificate v2 signing, linked GLES shaders
  and the unchanged embedded KCVG/KCPK/KCSP sidecars are verified. Its native library includes the
  KCAN runtime; the unanimated starter correctly emits no KCAN asset. The Poco is absent from ADB, so
  this `B9B1…` build has no install, launch, installed-byte hash match or physical profile claim.
- The current graph-controlled multi-clip demo is
  `build/UGTS-Multi-Clip-3.9.2-Poco-X7-Pro-debug.apk`: 1,504,091 bytes, SHA-256
  `94FD4CB4AD9C166F3E73EB8F0E66A68F5124781CD92E30AE4E31C01C2D37EA89`. It is v2-signed,
  ARM64-only, GLES 3, min-SDK 26/target-SDK 36, and packages a 240-byte KCAN v2 with two clips/seven
  keys plus a 191-byte KCVG with Play/Stop opcodes 26/27. No ADB device was attached, so this is a
  local build/inspection result rather than an install claim.
- The linked Saved Scene acceptance APK is
  `build/UGTS-Saved-Scenes-3.9.2-Poco-X7-Pro-debug.apk`: 1,505,487 bytes, SHA-256
  `70FD18B26DB7D41167E32EBD27088DC02474479F240B6A5DBF2654A6B36ED291`. It is v2-signed,
  ARM64-only, GLES 3, min-SDK 26/target-SDK 36, package
  `org.ugts.games.linked_saved_scenes_3d.pocox7pro`. Its APK contains only the materialized runtime:
  3,126-byte KC3D, 577-byte KCVG, 312-byte KCAN, 132-byte KCSP and 532-byte KCPK; their hashes match
  the standalone deterministic verifier. The linked authoring JSON stays outside runtime assets.
  ADB reports no connected device, so installation, launch and phone performance are not claimed.
- The retained-transform example `examples/parent_child_hierarchy_3d` verifies a moving/spinning root,
  two direct children and one grandchild through authored-local/world composition, desktop ECS and
  retained glTF. It emits a 1,633-byte KC3D and a 48-byte, three-link KCHI with SHA-256
  `D61049E17F196DF928D1E5A8387E22C7DF63E33932C756DD6629FD4D28A86BB9` and
  `2439348374214AABEE889C5D5BE1998755C6958037D95CFD0F59E2DF97C8F23F`; its 64-step canonical state
  hash is `ED2847B48F67128774F9A5664BE3259A2FBE67CC066D25AF61AA4A42C65298CB`.
  Separate generated KC3D/KCHI host-native coverage exercises a three-edge chain and malformed-pack
  rejection. Its local Poco artifact is
  `build/UGTS-Parent-Child-Hierarchy-3.9.2-Poco-X7-Pro-debug.apk`: 1,565,171 bytes, SHA-256
  `813D290E2B89973FE4C429BF58FAD7F50BFB156C42EACB665A7ABB1B4BF36E20`, package
  `org.ugts.games.parent_child_hierarchy_3d.pocox7pro`, SDK 26/36, GLES 3, ARM64-only, v2 debug-signed
  and 16 KiB aligned. Its 11 APK entries omit authoring `project.json`. Authorized Poco
  `XOVSTSHYNREMZ5D6` (`2412DPC0AG` / `rodin_eea`) installed it and cold-launched successfully in
  448 ms; PID 25992 became resumed, visible and fullscreen. Runtime logs selected Mali-G720 MC7,
  `poco_x7_pro_12gb`, `grove_g720_mc7_120`, balanced quality, 60-fps policy and 1.00 render scale.
  The bounded 15-second read-only profile in
  `build/device-qa-hierarchy-poco-20260829/profile-15s.json` observed 630 intervals at 120.15
  effective FPS: 8.376/9.959/10.473 ms p50/p95/p99, zero intervals over 1.5 vsync, thermal status 0,
  no crashes and no warnings. PSS was 141,406–146,004 KiB, RSS 261,218–267,114 KiB and reported GPU
  temperature 45.691–51.585 °C; battery stayed 55% / 33.7 °C. `hierarchy-running.png` confirms a
  rendered frame. This five-node/~60-submitted-triangle scene and short sample are not proof of visual
  motion-following under interaction, a large-game/AAA workload or sustained thermal performance.
- The generic-body acceptance APK is
  `build/UGTS-Dynamic-Crate-3.9.2-Poco-X7-Pro-debug.apk`: 1,531,353 bytes, SHA-256
  `AE8B5C6AE97E08E9380EEBE30087AF26575C495B17F23351532EB1AA666E68DD`. It is v2 debug-signed,
  ARM64-only, GLES 3, min/target/compile SDK 26/36/36, package
  `org.ugts.games.dynamic_crate_parity_3d.pocox7pro`, and passes both 4-byte and 16 KiB native
  alignment checks. Its 1,457-byte KC3D and 137-byte KCVG byte-match the deterministic verifier;
  authoring `project.json` is absent from the APK. ADB had no connected device, so this is a local
  build/inspection and host-native execution claim, not an install, launch or phone-performance claim.
- A separate animation-bearing APK at
  `build/UGTS-Animation-Timeline-3.9.2-Poco-X7-Pro-debug.apk` is 1,483,820 bytes with SHA-256
  `43D197ECF62F73349859FFED9D167BCA64BBFA092A6080BC03151E8B8F5B4E0F`. Its 88-byte KCAN asset
  (`2CEEF27205A1EEF140BB5BC03A519A00F2628D81B0D40DFD73555F91FCEE6FE2`) contains one two-key
  ping-pong goal animation. It is locally built/inspected only and has no physical-device claim.
- The preceding local post-audit opcode-25 snapshot remains at the `message-op25-debug` and
  `message-op25-audit-fixed-debug` paths: 1,451,149 bytes with SHA-256
  `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`. It also has no physical
  device claim.
- The last physically verified pre-audit opcode-25 snapshot is preserved explicitly as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-message-op25-pre-audit-debug.apk`, 1,449,653 bytes with SHA-256
  `FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`. Package/version/SDK/GLES,
  ARM64-only native code, debug-certificate v2 signing and that build's embedded sidecars are
  verified.
- Xiaomi model `2412DPC0AG` / codename `rodin` installed and cold-launched that APK. The pulled
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-message-op25-base.apk` is exactly 1,449,653
  bytes with the same SHA-256, proving the installed bytes match that preserved artifact.
- Its read-only 30-second Poco profile measured 120.12 effective FPS, 8.372 ms p50, 10.183 ms p95
  and 12.641 ms p99, with thermal status 0 and no crash-buffer lines or warnings. The captured result
  is `validation/device/opcode25-message-poco-profile.json`; this is a short idle-style profile, not
  a touch-heavy or long-duration thermal guarantee.
- The preceding opcode-24 artifact remains preserved at
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk`, 1,460,361 bytes with SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`.
- The preceding opcode-23 artifact is preserved separately as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
  `C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`; it is not the current source APK.
- The preceding installed/profiled opcode-22 baseline remains preserved for comparison. It is
  preserved as `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk`, 1,441,929 bytes with SHA-256
  `7F3080834EDB56EAAB0BFE8AEA1B1AD2D634C1AA7C4EB314C5B614760E48454F`. Local inspection verifies v2
  signing, minimum SDK 26, target SDK 36, GLES3 and package
  `org.ugts.games.my_mobile_3d_game.pocox7pro`; the same 1,441,929 bytes are installed, cold-launched
  and hash-matched on the Poco. It does not contain **When Timer Rings** or **When Message Heard**.
- The retained 30-second profile of that preceding APK measured 120.23 effective FPS, 10.118 ms p95,
  132,590–138,573 KiB PSS, 44.634–45.511 °C reported GPU temperature, thermal status 0, no crash
  lines and no warnings. This is a short opcode-22-scene baseline, not timer-capable device evidence
  or a sustained performance claim; it has been superseded by the exact opcode-25 device evidence above.

Current release evidence is summarized in [`docs/BUILD_STATUS_3_9_2.md`](docs/BUILD_STATUS_3_9_2.md).
The `validation/` folder retains earlier captured evidence.

## Package layout

- `src/ugts_kc3/mobile3d.py` — mobile-3D records, device policy and deterministic oracle.
- `src/ugts_kc3/androidexport.py` — KC3D392 compiler/inspector and Android source exporter.
- `src/ugts_kc3/polarpack.py` — sparse KCPK392 packed-movement asset and shared UGLUT2 profiles.
- `src/ugts_kc3/polar_population.py` / `polar_population_pack.py` — bounded seeded Ring, Spiral,
  Polar Field and looping Radial Burst display recipes, optional seeded Glow-by-distance material
  fields, plus the versioned, content-addressed KCPR392 sidecar.
- `src/ugts_kc3/renderpack.py` — optional 32-byte KCRP392 polar-mode, Bayer and render-seed record.
- `src/ugts_kc3/conformance/` — shared packed/direct/LUT vectors consumed by Python and native-host
  verification; shader checks cover source formulas, not physical GPU execution.
- `src/ugts_kc3/hierarchy3d.py` / `hierarchypack.py` — bounded local/world TRS composition and the
  optional sparse KCHI392 Android link sidecar.
- `src/ugts_kc3/scatter.py` / `scatterpack.py` — deterministic decorative populations and KCSP392.
- `src/ugts_kc3/android_template/` — packaged NativeActivity/GLES3 template.
- `android/UGTSKCKKijTGrove/` — retained earlier signature-arena Android source snapshot; regenerate
  from the packaged template for the current graph/polar/population runtime.
- `examples/tom_signature_arena_3d/` — editable project, native pack and glTF.
- `examples/linked_saved_scenes_3d/` — playable compact linked-group project and deterministic
  KC3D/KCVG/KCAN/KCSP/KCPK/glTF verifier.
- `examples/dynamic_crate_parity_3d/` — untagged dynamic-body/Apply Force desktop-to-native golden.
- `examples/parent_child_hierarchy_3d/` — editable two-level display hierarchy and deterministic
  desktop/KC3D/KCHI/glTF verifier.
- `examples/packed_polar_gpu_lab_3d/` — editable 64/256/1,024-object compact-render workload.
- `examples/elizabeth_vector_quest/` — retained 2D browser game.
- `spec/` — schemas, contracts and mechanism catalogs through M449.
- `docs/` — creation/build guides, release notes, evidence boundary and 4D roadmap.
- `native/host_tests/` — host-native validation fixture.
- `dist/` — Python wheel and source distribution.
- `validation/` — captured test/build/hash evidence.

## Evidence boundary

The 1,484,357-byte PBR-lite/opcode-25/animation-runtime ARM64 APK is locally inspected and
hash-identified as `B9B1…`, but that exact First Steps artifact has no physical-device run. The
1,483,820-byte animation-bearing `43D1…` APK is also locally inspected only. The preceding local
1,451,149-byte `1003…` snapshot is preserved separately and also has no physical-device claim.
The exact 1,449,653-byte pre-audit FBCB APK was installed, cold-launched, pulled back and hash-matched
on Xiaomi `2412DPC0AG` / `rodin`, then given the bounded 30-second profile reported above. That result
establishes only the preserved pre-audit artifact's idle-style launch and frame baseline; it does
not establish touch feel, interaction-heavy frame pacing, unplugged battery drain, long-duration
thermal equilibrium, explicit 60/90 Hz fallback behavior or representative lower-tier performance.
The 1,460,361-byte opcode-24 artifact remains preserved at the `cone-op24` path with hash prefix
`9170…`, and earlier opcode-22/3.9.2 baselines remain separate evidence for their exact artifacts.

The newer 1,565,171-byte hierarchy APK (`813D290E…`) separately owns the successful install/cold
launch and five-node 15-second Poco profile reported above. Its 120.15-FPS/9.959-ms-p95 tiny-scene
result does not transfer to First Steps, a large-game/AAA workload or sustained hierarchy gameplay.

This is still not a complete Godot-like engine. The child-facing editor, ECS, typed graph runtime,
native GLES Android path, Saved Objects, linked static Saved Scenes, bounded display-transform
hierarchies, rigid-transform clip libraries with direct Play/Stop control, generic native dynamic
bodies and current compact features are working slices. A general gameplay/physics scene graph,
editable Saved Scene definitions/overrides, GLB/skeletal animation, retargeting, crossfades/layered
blending, animation-state-machine authoring, Player-controller unification, native contact
events/grounded state, richer physics/content pipelines, production signing/distribution, Vulkan and
the broader production roadmap remain incomplete. 4D is a design-contract TODO only.

## Attribution

Prepared as the **Tom Klootwijk Signature Edition**. The earlier requester-supplied Kees Klootwijk
substrate attribution remains preserved. “Signature” is an edition label, not a cryptographic or
legal signature; requester identity/rights are not independently verified.
