# Native Android Guide — Grove 3.9.2

## Checked-in project

Open `android/UGTSKCKKijTGrove` in Android Studio. The same project can be regenerated and compiled:

```bash
PYTHONPATH=src python -m ugts_kc3 build-android examples/tom_signature_arena_3d/project.json build/UGTSKCKKijTGrove --apk
```

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

## Runtime architecture

`NativeActivity` owns lifecycle and input. C++ loads `signature_scene.kc3d`, selects a profile,
creates an EGL ES 3 context, renders to a scaled offscreen framebuffer, blits to the display,
runs fixed-step gameplay, and adjusts the quality index after sustained frame or thermal stress.

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

The desktop editor exposes the same flow as **Poco X7 Pro APK (Debug)** and **Poco APK + Install**.
