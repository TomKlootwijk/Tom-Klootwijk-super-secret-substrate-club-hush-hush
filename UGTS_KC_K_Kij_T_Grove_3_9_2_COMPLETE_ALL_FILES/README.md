# UGTS-KC 3.9.2 — K-Kij-T / Grove

This package is the complete 3.9.2 release: the 3.9.1 substrate and artifacts plus the actual K-Kij-T / Grove native Android upgrade.

Grove's phone runtime is native Android rather than an HTML wrapper. The retained 2D workflow still
exports HTML5. Mali-G720 MC7 / POCO X7 Pro 12 GB is the performance focus, with general Android
fallback tiers.

## Desktop editor and first game

The Grove engine work now includes an optional PySide6 desktop editor, deterministic visual-graph
runtime, compact log-polar ECS components and direct APK build/install/open tooling. Core simulation and
build commands remain dependency-free; Qt is only needed for the editor.

UGTS Studio can add, copy, delete, select and move 2D entities or 3D nodes with undo/redo. The
Inspector can assign 2D pictures, 3D shapes and materials; Wavefront OBJ shapes import as validated,
undoable project resources. For non-dynamic Mobile 3D nodes, **Movement Pattern** offers Off, Orbit,
Spiral Out and Spiral In without exposing packed hexadecimal words. Orbit and spiral movers share one
binary16 log-polar lookup profile; each authored mover becomes two unsigned 64-bit words and one
24-byte sparse Android record. Dynamic nodes are guarded because physics already owns their transform.
Logic Blocks are editable typed data, not generated source hidden behind the GUI. They are also
selection-owned: choosing a 2D or 3D object opens only that object's logic. An object with no binding
shows a genuinely blank graph; its first meaningful graph edit creates and binds that graph as the
same undoable operation, and Undo removes both again. If an object intentionally owns several graphs,
the Logic Blocks header provides an exact chooser. A **Populate Area** prototype cannot own Logic
Blocks; turn Populate Area off before attaching logic.

The now-25-block vocabulary includes **When Timer Rings** under **Events**. Set **Seconds** on the block
to a finite positive binary32 value up to 86,400 (default 1 second), and leave **Repeat** on by
default or turn it off for one ring. Each binding counts only its own active fixed updates: an
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

On Windows, double-click `RUN_UGTS_STUDIO.cmd` in this folder for a one-click launch. It checks the
editor dependency on first use and offers to install it only when needed.

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
meshes + materials + tagged nodes + camera/light/world
-> deterministic 3D arcade oracle
-> glTF with baked decorative copies, or compact KC3D392 + optional KCSP392 population data
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
- Wheel/source distributions build and install in a fresh environment.
- The HTML5 runtime executes the full current 25-block graph vocabulary, including Repeatable Random
  Number, Find Nearby Object, Find Object Ahead, When Timer Rings, When Message Heard and sensor
  Trigger Enter/Exit context, and passes headless JavaScript runtime checks.
- Focused opcode-25 desktop, browser, compact-pack, editor and native-host checks pass. The full suite
  is green: 510 passed, 100 subtests passed in 66.69s.
- The child-friendly First Steps source now emits seven visual graphs with 27 nodes and seven
  bindings, including four world bindings. Fresh idle execution has state SHA-256
  `a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`;
  after the dash/message path it records `heard_message=true` and `score=1`. Its 1,265-byte
  `KCVG001` has SHA-256 `363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`;
  the unchanged 914-byte `KCPK392` and 60-byte `KCSP392` retain SHA-256
  `8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313` and
  `E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`, for 2,239 bytes combined.
- The post-audit canonical opcode-25 APK is locally built and inspected at 1,451,149 bytes with
  SHA-256 `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`. The canonical
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk`, `message-op25-debug` and
  `message-op25-audit-fixed-debug` files are byte-identical. Package/version/SDK/GLES, ARM64-only
  native code, debug-certificate v2 signing and the unchanged embedded sidecars are verified. The
  Poco disconnected before final installation, so this `1003…` build has no install, launch,
  installed-byte hash match or physical profile claim.
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
- `src/ugts_kc3/scatter.py` / `scatterpack.py` — deterministic decorative populations and KCSP392.
- `src/ugts_kc3/android_template/` — packaged NativeActivity/GLES3 template.
- `android/UGTSKCKKijTGrove/` — retained earlier signature-arena Android source snapshot; regenerate
  from the packaged template for the current graph/polar/population runtime.
- `examples/tom_signature_arena_3d/` — editable project, native pack and glTF.
- `examples/elizabeth_vector_quest/` — retained 2D browser game.
- `spec/` — schemas, contracts and mechanism catalogs through M449.
- `docs/` — creation/build guides, release notes, evidence boundary and 4D roadmap.
- `native/host_tests/` — host-native validation fixture.
- `dist/` — Python wheel and source distribution.
- `validation/` — captured test/build/hash evidence.

## Evidence boundary

The 1,451,149-byte post-audit canonical opcode-25 ARM64 APK is locally inspected and hash-identified
as `1003…`, but the Poco disconnected before its final install, so it has no physical-device claim.
The exact 1,449,653-byte pre-audit FBCB APK was installed, cold-launched, pulled back and hash-matched
on Xiaomi `2412DPC0AG` / `rodin`, then given the bounded 30-second profile reported above. That result
establishes only the preserved pre-audit artifact's idle-style launch and frame baseline; it does
not establish touch feel, interaction-heavy frame pacing, unplugged battery drain, long-duration
thermal equilibrium, explicit 60/90 Hz fallback behavior or representative lower-tier performance.
The 1,460,361-byte opcode-24 artifact remains preserved at the `cone-op24` path with hash prefix
`9170…`, and earlier opcode-22/3.9.2 baselines remain separate evidence for their exact artifacts.

This is still not a complete Godot-like engine. The child-facing editor, ECS, typed graph runtime,
native GLES Android path and current compact features are working slices; reusable scene/prefab and
animation workflows, richer physics/content pipelines, production signing/distribution, Vulkan and
the broader production roadmap remain incomplete. 4D is a design-contract TODO only.

## Attribution

Prepared as the **Tom Klootwijk Signature Edition**. The earlier requester-supplied Kees Klootwijk
substrate attribution remains preserved. “Signature” is an edition label, not a cryptographic or
legal signature; requester identity/rights are not independently verified.
