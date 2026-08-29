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
Logic Blocks are editable typed data, not generated source hidden behind the GUI.

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
build failure from an install failure and from an APK that installed but could not be opened. You can
still open `android/UGTSKCKKijTGrove` in Android Studio.
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
- The HTML5 runtime executes the full current 20-block graph vocabulary, including sensor Trigger
  Enter/Exit context, and passes headless JavaScript runtime checks.
- All 412 Python regression tests, the native scatter/pointer-ID/Trigger Area harnesses and the editor 2D/3D
  authoring smoke pass.
- The actual child-friendly first-steps project compiles from this repository's long Windows path
  to a 1,436,161-byte ARM64 Poco debug APK. Its two native learner graphs, packed log-polar asset and
  18-object population recipe are 496, 914 and 60 bytes respectively.

Current release evidence is summarized in [`docs/BUILD_STATUS_3_9_2.md`](docs/BUILD_STATUS_3_9_2.md).
The `validation/` folder retains earlier captured evidence.

## Package layout

- `src/ugts_kc3/mobile3d.py` — mobile-3D records, device policy and deterministic oracle.
- `src/ugts_kc3/androidexport.py` — KC3D392 compiler/inspector and Android source exporter.
- `src/ugts_kc3/polarpack.py` — sparse KCPK392 packed-movement asset and shared UGLUT2 profiles.
- `src/ugts_kc3/scatter.py` / `scatterpack.py` — deterministic decorative populations and KCSP392.
- `src/ugts_kc3/android_template/` — packaged NativeActivity/GLES3 template.
- `android/UGTSKCKKijTGrove/` — generated Android Studio source project.
- `examples/tom_signature_arena_3d/` — editable project, native pack and glTF.
- `examples/elizabeth_vector_quest/` — retained 2D browser game.
- `spec/` — schemas, contracts and mechanism catalogs through M449.
- `docs/` — creation/build guides, release notes, evidence boundary and 4D roadmap.
- `native/host_tests/` — host-native validation fixture.
- `dist/` — Python wheel and source distribution.
- `validation/` — captured test/build/hash evidence.

## Evidence boundary

The current ARM64 POCO-targeted APK was compiled with the local Android SDK/NDK; its SHA-256 is
`0696375DD496ADC6D71505749BB760E4EBF7F05D2A76030F0B38577BD022B3DD`. An authorized physical
Xiaomi `2412DPC0AG` / `rodin` was detected as a Mali-G720 MC7, and the GUI deploy path installed and
launched UGTS 3.9.2 on it. The phone disconnected before sustained frame, memory, touch and thermal
capture, and the exact current hash above has not yet been confirmed on-device. Vulkan remains a future
backend hook. 4D is a design-contract TODO only.

## Attribution

Prepared as the **Tom Klootwijk Signature Edition**. The earlier requester-supplied Kees Klootwijk
substrate attribution remains preserved. “Signature” is an edition label, not a cryptographic or
legal signature; requester identity/rights are not independently verified.
