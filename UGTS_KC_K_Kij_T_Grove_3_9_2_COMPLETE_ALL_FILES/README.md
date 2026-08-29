# UGTS-KC 3.9.2 — K-Kij-T / Grove

This package is the complete 3.9.2 release: the 3.9.1 substrate and artifacts plus the actual K-Kij-T / Grove native Android upgrade.

Grove is native Android, not HTML5. It targets Mali-G720 MC7 / POCO X7 Pro 12 GB as the performance focus while keeping general Android fallback tiers.

## Desktop editor and first game

The Grove engine work now includes an optional PySide6 desktop editor, deterministic visual-graph
runtime, compact log-polar ECS components and direct APK build/install tooling. Core simulation and
build commands remain dependency-free; Qt is only needed for the editor.

UGTS Studio can add, copy, delete, select and move 2D entities or 3D nodes with undo/redo. The
Inspector can assign 2D pictures, 3D shapes and materials; Wavefront OBJ shapes import as validated,
undoable project resources. Logic Blocks are editable typed data, not generated source hidden behind
the GUI.

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

PCG is future TODO only.

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
-> glTF or compact KC3D392 scene pack
-> Android NativeActivity + C++20 + EGL/OpenGL ES 3.0
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

The desktop editor can produce a Poco debug APK directly, optionally installing it when exactly one
authorized ADB device is connected. Its blue **Deploy to Phone** toolbar action preflights ADB,
builds into an editor-owned cache and installs in one operation. You can still open
`android/UGTSKCKKijTGrove` in Android Studio.
The checked-in native project contains a
66-node interactive arena, `NativeActivity` lifecycle, fixed-step movement/gameplay, touch,
keyboard and gamepad input, camera orbit/pinch, asset-loaded GLSL ES 3 shaders, depth/culling,
dynamic-resolution framebuffer, high-refresh request and adaptive quality controller.

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

- The retained and new automated Python tests pass; the current count is reported by the verification command rather than frozen in this document.
- Python source compilation and mobile-project JSON Schema validation pass.
- The Python scene-pack compiler and independent C++ parser agree on the KC3D392 format-1 pack.
- The host-native parser, POCO selector and adaptive-quality controller compile and execute.
- The Android source tree, manifest, Gradle/CMake configuration, shaders and asset references pass
  static release checks.
- Wheel/source distributions build and install in a fresh environment.
- The HTML5 runtime executes the full current 18-block graph vocabulary and passes headless JavaScript runtime checks.
- The 352-test regression suite, native pointer-ID gesture harness and editor 2D/3D authoring smoke pass.
- The actual child-friendly first-steps project compiles from this repository's long Windows path
  to a 1,351,488-byte ARM64 Poco debug APK. Its native graph and packed log-polar assets are 308 and
  914 bytes respectively.

Captured evidence is under `validation/`.

## Package layout

- `src/ugts_kc3/mobile3d.py` — mobile-3D records, device policy and deterministic oracle.
- `src/ugts_kc3/androidexport.py` — KC3D392 compiler/inspector and Android source exporter.
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

An ARM64 POCO-targeted APK has been compiled with the local Android SDK/NDK; its SHA-256 is
`954ECB28E41F79C752151D7D9F9B21BD793106D8AA0DEE5923DD3CD5F069AE96`. No physical POCO X7 Pro is
connected, so installation, device compatibility, sustained 120 Hz performance, thermal behavior
and profiling remain unverified. Vulkan is a future backend hook. 4D is a design-contract TODO only.

## Attribution

Prepared as the **Tom Klootwijk Signature Edition**. The earlier requester-supplied Kees Klootwijk
substrate attribution remains preserved. “Signature” is an edition label, not a cryptographic or
legal signature; requester identity/rights are not independently verified.
