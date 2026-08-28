# UGTS-KC 3.9.1 — Tom Klootwijk Signature Edition
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
-> self-contained Canvas/Web Audio HTML5 build

3D/mobile authoring:
meshes + materials + tagged nodes + camera/light/world
-> deterministic 3D arcade oracle
-> glTF or compact KC3D391 scene pack
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
PYTHONPATH=src python -m ugts_kc3 build-android   examples/tom_signature_arena_3d/project.json   build/UGTSKC391Signature
```

Open `android/UGTSKC391Signature` in Android Studio. The checked-in native project contains a
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

- **276 automated Python tests pass**, including all 225 retained tests and 51 new 3.9.1 tests.
- Python source compilation and mobile-project JSON Schema validation pass.
- The Python scene-pack compiler and independent C++ parser agree on the checked-in KC3D391 pack.
- The host-native parser, POCO selector and adaptive-quality controller compile and execute.
- The Android source tree, manifest, Gradle/CMake configuration, shaders and asset references pass
  static release checks.
- Wheel/source distributions build and install in a fresh environment.
- The retained HTML5 runtime still passes JavaScript syntax validation.

Captured evidence is under `validation/`.

## Package layout

- `src/ugts_kc3/mobile3d.py` — mobile-3D records, device policy and deterministic oracle.
- `src/ugts_kc3/androidexport.py` — KC3D391 compiler/inspector and Android source exporter.
- `src/ugts_kc3/android_template/` — packaged NativeActivity/GLES3 template.
- `android/UGTSKC391Signature/` — generated Android Studio source project.
- `examples/tom_signature_arena_3d/` — editable project, native pack and glTF.
- `examples/elizabeth_vector_quest/` — retained 2D browser game.
- `spec/` — schemas, contracts and mechanism catalogs through M449.
- `docs/` — creation/build guides, release notes, evidence boundary and 4D roadmap.
- `native/host_tests/` — host-native validation fixture.
- `dist/` — Python wheel and source distribution.
- `validation/` — captured test/build/hash evidence.

## Evidence boundary

This archive does **not** claim an Android APK/AAB was compiled, signed, installed or profiled on a
physical POCO X7 Pro. It supplies the complete native source project and validates its portable C++
core, but the release environment did not include an Android SDK/NDK installation or physical
device. Vulkan is a future backend hook. 4D is a design-contract TODO only.

## Attribution

Prepared as the **Tom Klootwijk Signature Edition**. The earlier requester-supplied Kees Klootwijk
substrate attribution remains preserved. “Signature” is an edition label, not a cryptographic or
legal signature; requester identity/rights are not independently verified.
