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
using a profile share its binary16 UGLUT2 log-polar table. Projects without packed movers emit no
polar asset. Dynamic nodes cannot own this component because physics and packed movement would both
try to write the transform.

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
