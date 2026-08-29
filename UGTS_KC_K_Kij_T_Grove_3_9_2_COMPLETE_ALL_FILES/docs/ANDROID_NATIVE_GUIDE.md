# Native Android Guide — Grove 3.9.2

## Generate the current project

The packaged generator/template is the authority for the current graph, packed-motion and population
runtime. Generate it into a fresh folder, then open that generated folder in Android Studio:

```bash
PYTHONPATH=src python -m ugts_kc3 build-android examples/tom_signature_arena_3d/project.json build/UGTSKCKKijTGrove --apk
```

`android/UGTSKCKKijTGrove` is a retained earlier signature-arena source snapshot. It remains useful
as historical source, but it does not contain the latest optional graph VM, packed-kinematics or
population modules and must not be used to inspect opcodes 23–24 or reproduce the current First Steps
APK. Generate a fresh project from the packaged template for the authoritative timer/cone runtime.

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

The desktop editor's **Logic Trail** is deliberately absent from these assets. During Preview, block
badges and **Last Run** show execution order, values, selected flow and errors while the Logic tab is
read-only; Stop retains the latest display. That snapshot is nonserialized presentation state and
adds zero bytes to `KCVG001`, `KC3D392`, the APK or any other export.

## Logic ownership and opcodes 22–24

The Logic Blocks workspace follows the selected owner. An unbound 2D/3D object shows a transient
blank graph; its first meaningful edit creates and binds the graph in one Undo command, and Undo
removes both. Objects with several intentional bindings receive an exact graph chooser. Populate Area
prototypes cannot own Logic Blocks and must have the recipe turned off before graph creation.

The compact native vocabulary now contains 24 blocks. `KCVG001` opcode 22 is **Find Nearby Object**:
an origin object, one of the portable tags `player`, `collectible`, `goal`, `decorative` or `hazard`,
and a finite non-negative inclusive radius. Native C++ excludes the origin and dead/inactive
candidates, chooses the nearest active/alive match, and uses object ID to break an exact-distance tie
deterministically. Its found/entity/distance result follows the same binary32 rules as desktop and
the retained 2D web VM. The First Steps Mobile 3D project demonstrates it in **World Logic → Find the
Goal**, with explicit Player origin, Goal tag, 9 m radius and the `nearby_goal` state key.

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

First Steps demonstrates opcode 23 in **World Logic → Count the Timer Rings**, where a repeating
one-second timer stores its count as `timer_rings`, and opcode 24 in **Find the Goal Ahead**, where
3D Forward with Normal width stores `goal_ahead`. The current source exports six graphs, 23 nodes and
six bindings including three world bindings. Its 1,085-byte KCVG has SHA-256
`2c5c6edb0c804da7fb2b6edab8c6beab12ccd2dac8b4e743d03c6194aff4af27`; the 914-byte KCPK
(`8a45ddbf874d918cedaeb0161e80fef3314c2c2b0b21a45da90e22a18c4dd313`) and 60-byte KCSP
(`e95bde225571ab5f6eac3b9c04cb1bd332a0c95c740b377ac2dee30460dd2fd1`) bring the compact sidecar
total to 2,059 bytes.

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

The canonical opcode-24 APK is locally built and inspected at 1,460,361 bytes with SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`. `aapt` and `apksigner`
verify package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
`3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES 3.0, ARM64-only native code, a debug
certificate and APK Signature Scheme v2; embedded KCVG/KCPK/KCSP hashes match the source sidecars.
ADB reported zero devices, so this opcode-24 APK has not been freshly installed, cold-launched or
profiled.

The preceding opcode-23 build is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.

The preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` owns the earlier Poco cold-launch,
hash-match and 30-second result: 120.23 effective FPS, 10.118 ms p95, 132,590–138,573 KiB PSS,
44.634–45.511 °C GPU temperature, thermal status 0 and no crash lines or warnings. The retained
64.9-second Poco idle baseline belongs to a still earlier 3.9.2 APK. A fresh opcode-24 device run,
interaction-heavy/touch, unplugged battery, long-duration thermal, 60/90 Hz fallback and
representative lower-tier runs remain open.
