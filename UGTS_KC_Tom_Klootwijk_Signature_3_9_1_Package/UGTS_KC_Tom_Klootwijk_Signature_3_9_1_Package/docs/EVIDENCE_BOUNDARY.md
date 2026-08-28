# Evidence Boundary — Tom Klootwijk Signature 3.9.1

## Demonstrated by this archive

- All 276 Python tests pass: 225 retained tests and 51 new mobile-3D/Android-source tests.
- Python source compiles and the mobile-3D example passes semantic and JSON Schema validation.
- Project JSON round-trips with stable canonical hashes.
- Deterministic 3D simulation covers movement, gravity, floor/bounds, sphere-proxy contacts,
  collectibles, hazards, goals, snapshots and state hashes.
- The canonical 66-node project compiles into KC3D391 and glTF.
- An independent C++ parser reads the generated pack; its POCO profile selector and adaptive
  quality controller compile and execute in host-native validation.
- Android source generation produces complete Gradle, manifest, CMake, C++, shader and asset trees
  with a hashed build report.
- The retained 2D/browser project and JavaScript syntax validation remain passing.
- Python wheel/source distributions build and pass a fresh-environment CLI smoke test.

## Native Android boundary

The checked-in project implements a NativeActivity C++ game loop and GLES3 source backend.
The captured environment did not contain Android SDK/NDK packages and had no physical Android
device, so this archive does not claim:

- an APK/AAB was compiled or signed;
- installation, launch or frame-rate behavior on a POCO X7 Pro;
- thermal, battery, GPU or memory benchmarks on any phone;
- Play Store submission or certification.

The POCO 120 Hz/ultra configuration is a starting target policy with automatic fallback, not a
guarantee of sustained 120 fps.

## Broader non-claims

- Vulkan rendering (optional interface/manifest hook only).
- 4D runtime, 4D physics or 4D interchange (design TODO only).
- General certified rigid-body dynamics, joints, deformables or robust CCD.
- Skeletal animation/retargeting, editor UI, production multiplayer, anti-cheat, OpenXR or console
  platform SDKs.
- Independent verification of requester identity, attribution or ownership assertions.

## Determinism scope

Canonical state/project hashes normalize numerically equivalent integral values. Determinism is
expected for the same runtime version, project, fixed step and input sequence. Cross-language
floating-point bit identity and identical Android/Python rendering are not claimed.
