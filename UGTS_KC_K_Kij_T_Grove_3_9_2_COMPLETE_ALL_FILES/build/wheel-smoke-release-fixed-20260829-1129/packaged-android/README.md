# UGTS-KC 3.9.2 — Native Android Source

This is a dependency-free `NativeActivity` project. The game loop, scene loader, GLES 3.0 renderer,
dynamic-resolution framebuffer, fixed-step gameplay, device tier selection, touch/gamepad input and
adaptive thermal/FPS quality logic, Grove juice events, particles and optional post-processing are
implemented in C++.

## Build

Open this directory in Android Studio, or use the checked, pinned Gradle 8.13 wrapper with Android
SDK 36, Android Gradle Plugin 8.13.2, CMake 3.22.1 and Android NDK r29 (`29.0.14206865`):

```powershell
.\gradlew.bat assemblePocoX7ProDebug
```

Common variants:

- `pocoX7ProDebug`: ARM64-only, explicit POCO X7 Pro 12 GB profile.
- `universalDebug`: ARM64, ARMv7 and x86_64 with runtime profile selection.
- Release variants are source-ready but require your own signing configuration.

The wrapper is copied from the verified UGTS 4.1.1 parent package and pins the distribution SHA-256.
The project intentionally includes no private signing key; use debug builds for direct learning and
device testing, then configure a private release key only when publishing.

## Controls

- Left side drag: movement; left-side tap: jump. The movement thumb remains active while another finger acts.
- Right side drag: orbit camera; right-side tap: dash. Touch roles follow pointer IDs, so finger ordering is safe.
- Two-finger spacing: camera distance.
- Gamepad left/right sticks: movement/look; A: jump; B: dash.
- Keyboard: WASD/arrows move; J jumps; Enter/Shift dash; Space triggers both beginner jump and dash actions.

The runtime currently uses OpenGL ES 3.0. Vulkan is declared optional and reserved as a future backend.

## Visual graph boundary

When the source project contains bound visual graphs, export adds the compact `visual_graphs.kcvg`
asset. The C++20 VM supports Ready, Tick, Input Pressed, Trigger Enter/Exit, Branch,
constants/state/NodeData component reads, scalar math/comparisons, Set State, Set Component,
Emit Event, Apply Force, Set Active and Despawn.
NodeData paths are transform position/translation/scale/rotation (and numeric fields), velocity,
angular velocity, alive and active. Event payloads must currently be empty; events are delivered to a
bounded native queue and Android log, and their Python event-record output cannot be linked. Mapping
literals, dynamic configuration ports and other component paths fail export with an explicit error
instead of being ignored. Both per-node graph bindings and sparse project-level `world_graphs`
bindings run in the native VM.

## Packed polar ECS boundary

Nodes may opt into a sparse two-word `packed_kinematic` component in authoring metadata. Export then
adds `packed_kinematics.kcpk`; projects without such nodes add neither an asset nor component records.
Named profiles come from `project.metadata["packed_kinematic_profiles"]` and share one scaled UGLUT2
binary16 table apiece. At each fixed tick the native runtime advances the quantized log-radius/angle
motion, writes X/Z and heading-as-Y-yaw into that node's existing `NodeData`, and only then runs visual
graphs and gameplay physics. Authored Y, scale, velocity, collider and material stay untouched. The
runtime bounds profile/component/LUT counts and rejects truncated packs, unknown references,
noncanonical signed motion lanes, invalid samples and trailing bytes before starting content.
