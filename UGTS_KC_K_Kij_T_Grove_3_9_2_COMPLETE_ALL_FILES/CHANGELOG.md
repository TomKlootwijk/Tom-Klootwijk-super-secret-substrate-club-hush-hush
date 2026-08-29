# Changelog

## 3.9.2 — K-Kij-T / Grove

### Added

- UGTS Studio **Deploy to Phone** now preflights and pins one authorized ADB device, builds below the
  saved project's `.ugts-studio/deploy` path, installs the Poco debug APK, and opens the native game.
- Mobile 3D **Movement Pattern** controls provide Off, Orbit, Spiral Out and Spiral In through readable
  radius, turn-speed and start-angle fields.
- Trigger Enter and Trigger Exit Logic Block roots run with sensor/player context in desktop,
  browser and native Android runtimes; Mobile 3D supports world and matching-sensor graph bindings.
- A 3D-only **+ Trigger Area** action and **Use as Trigger** Inspector controls expose Sphere/Radius or
  Box/Size X/Y/Z authoring with Undo/Redo and save/load.
- Desktop Preview adds a read-only **Logic Trail** with per-block execution badges and a **Last Run**
  list for values, chosen flow and errors. Trails survive Stop for inspection but are nonserialized
  presentation state with zero export cost.
- The Mobile 3D starter adds the **Crystal Garden** lesson and undoable **Populate Area** recipes for
  bounded static decoration: 2–256 objects per group, at most 64 groups and 1,024 objects total.
- Optional `KCSP392` population data uses one 24-byte header plus 36 bytes per group. glTF bakes its
  deterministic copies; native GLES regenerates the same prefix and renders it with instancing.

### Changed

- Android launch uses the validated, flavor-aware `applicationId` from Gradle output metadata and the
  explicit `<applicationId>/android.app.NativeActivity` component on the same pinned device.
- Deployment output distinguishes build, install and launch phases and keeps completed artifacts usable
  when a later phase fails.
- Packed movement shares binary16 UGLUT2 profiles and adds only one 24-byte sparse record containing
  two unsigned 64-bit log-polar words per moving node; dynamic nodes are guarded from conflicting
  transform ownership.
- Trigger areas use matching desktop/native scale-aware sphere/box overlap without collision impulse,
  with explicit sensor and per-step native graph-dispatch caps.
- Populate Area rejects dynamic/moving, collider/Trigger Area, gameplay-tagged, Logic Block and
  Movement Pattern prototypes. Copies are render-only, the desktop view caps generated copies at 64
  per group and 256 globally, and browser Mobile 3D, overlap avoidance, per-copy frustum culling and
  LOD remain explicit non-features.
