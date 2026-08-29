# Changelog

## 3.9.2 — K-Kij-T / Grove

### Added

- UGTS Studio **Deploy to Phone** now preflights and pins one authorized ADB device, builds below the
  saved project's `.ugts-studio/deploy` path, installs the Poco debug APK, and opens the native game.
- UGTS Studio **Check Phone** (`Ctrl+Shift+P`) and CLI `profile-android` run the same nonblocking,
  default 30-second ADB observation of a running deployed game with its screen on, reporting frame
  cadence, process memory, available GPU temperature and app crash warnings without injected input
  or setting changes; CLI JSON retains additional available battery/thermal fields.
- Mobile 3D objects now have a child-facing X/Y/Z translation gizmo with live Inspector preview and
  exactly one undoable edit per drag; packed motion continues to own X/Z while Y stays editable.
- Scene Trees now show metadata-titled **World Logic** entries. Selecting one opens that exact graph,
  keeps object tools out of the way and shows only its whole-scene Logic Trail.
- Logic Blocks are now selection-owned. Unbound 2D/3D objects show a transient blank graph; the first
  edit creates and binds it, exact Undo removes both, multiple bindings expose a chooser, and
  Populate Area prototypes cannot own graphs.
- **Repeatable Random Number** adds deterministic bounded number picking with matching binary32 results
  in desktop Preview, HTML5 and native Android (`KCVG001` opcode 21).
- **Find Nearby Object** is append-only opcode 22 under Sensing. It uses
  an explicit/bound origin, five portable tags, an inclusive radius, nearest active/alive selection
  and deterministic object-ID ties with desktop, HTML5 and native Android parity.
- **When Timer Rings** is append-only opcode 23 under Events
  stores only a finite positive binary32 **Seconds** literal up to 86,400 (default 1) and a boolean
  **Repeat** literal (default true). Each binding advances on its own active fixed updates, pauses
  with an inactive owner, resets on Ready/restart, rings at most once per update and exposes count,
  remaining time and entity with no serialized or suspended execution state. Editor authoring,
  desktop, HTML5 and native Android have matching behavior.
- **Find Object Ahead** completes the current 24-block vocabulary under Sensing as append-only opcode
  24. It keeps the nearest-tag filters, tie-break and nullable outputs, then applies an inclusive
  source-aligned binary32 GSP4 cone. Its Vector4 stores explicit world-axis X/Y/Z plus minimum cosine;
  the runtime normalizes that axis without trigonometry and deliberately ignores Origin rotation and
  scale. Desktop, HTML5, compact pack and native Android share the schedule.
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
- Its fourth lesson, **World Logic → Find the Goal**, searches from explicit Player origin for Goal
  within 9 m and stores the result as `nearby_goal`.
- Its fifth graph, **World Logic → Count the Timer Rings**, stores a repeating one-second timer's
  count as `timer_rings`.
- Its sixth graph, **World Logic → Find the Goal Ahead**, uses the saved 3D Forward world axis and
  Normal width and stores `goal_ahead`; First Steps now has six graphs, 23 nodes and six bindings
  including three world bindings.
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
- Android export also rejects mutations aimed at frozen population prototypes from other-object or
  world graphs, and rounds authored transforms to the native binary32 schedule before scatter math.
  GLES startup now fails closed after any EGL/shader error, and nonuniformly scaled instances use an
  inverse-transpose normal matrix.
- The full suite passes 483 tests plus 87 subtests in 59.77 seconds. Focused opcode-24 verification
  passes 14 tests plus 25 subtests; targeted Ruff, launcher/editor smokes and all native-host targets
  pass. First Steps emits a 1,085-byte `KCVG001` pack with SHA-256
  `2c5c6edb0c804da7fb2b6edab8c6beab12ccd2dac8b4e743d03c6194aff4af27`, alongside a 914-byte
  `KCPK392` (`8a45ddbf874d918cedaeb0161e80fef3314c2c2b0b21a45da90e22a18c4dd313`) and 60-byte
  `KCSP392` (`e95bde225571ab5f6eac3b9c04cb1bd332a0c95c740b377ac2dee30460dd2fd1`), 2,059 bytes combined.
  Fresh execution sets `goal_ahead=true` and has state SHA-256
  `71df205686c92c217c3b1e23ad00929a331d07b5bb43e64d27023ec17d490a9c`.
- The canonical opcode-24 Poco APK is locally built and inspected at 1,460,361 bytes with SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`. Its package/version/SDK/GLES,
  ARM64-only native code, debug-certificate v2 signing and embedded source-matching sidecars verify;
  ADB reported zero devices, so no fresh install, launch or profile is claimed.
- The preceding opcode-23 build is preserved as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
  `C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.
- Device evidence now distinguishes the retained 64.9-second idle Poco baseline from the later
  1,441,929-byte opcode-22 `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk`. That most
  recently installed artifact cold-launches, hash-matches and
  has a retained 30-second baseline at 120.23 effective FPS, 10.118 ms p95, thermal status 0 and no
  crash lines or warnings, but it precedes **When Timer Rings** and **Find Object Ahead**. A fresh opcode-24 physical-device
  run, plus interaction-heavy, unplugged, long-duration and fallback-tier runs, remains open.
