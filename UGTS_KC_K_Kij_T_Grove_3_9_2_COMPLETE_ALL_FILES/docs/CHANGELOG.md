# Changelog

## 3.9.2 - K-Kij-T / Grove Creation Engine

- Adds a dockable PySide6 desktop editor with editable 2D/3D scenes, inspectors, real runtime preview,
  friendly project checks and direct web, glTF, Android source, Poco APK and ADB-install-and-open builds.
- Adds typed, serializable Logic Blocks with deterministic ordering and bounded desktop execution.
- Makes Logic Blocks selection-owned: an unbound selected 2D/3D object shows a transient blank graph;
  the first edit creates and binds it, exact Undo removes both, multiple bindings expose a chooser,
  and Populate Area prototypes cannot create bindings.
- Adds a desktop-only **Logic Trail** presentation: read-only live execution badges plus a **Last Run**
  list for values, flow and errors. The latest trail remains after Stop but is not serialized and adds
  zero bytes to exports.
- Adds a child-facing X/Y/Z translation gizmo for Mobile 3D. Dragging previews in the Inspector and
  commits exactly one undoable transform edit; Preview cancels transient drags safely.
- Adds metadata-titled **World Logic** entries to 2D and 3D Scene Trees, with exact graph editing,
  undo/redo context and owner-safe whole-scene Logic Trails.
- Executes the full current 24-block vocabulary in HTML5 and compact `KCVG001` Android bytecode,
  including sparse world graphs, Apply Force and Trigger Enter/Exit with bounded sensor context.
- Adds the pure **Repeatable Random Number** Logic Block as append-only KCVG opcode 21. Its bounded
  binary32-canonicalized World/Pick inputs, range/result and existing SplitMix64 compatibility schedule have exact
  desktop/browser/native golden parity, including dynamically linked inputs; First Steps binds a
  tiny Ready lesson to Floor and saves one visible deterministic result for Logic Trail and Android.
- Adds **Find Nearby Object** under Sensing as append-only KCVG opcode 22: explicit/bound origin,
  Player/Collectible/Goal/Decorative/Hazard choices, inclusive radius, nearest active/alive match and
  deterministic object-ID tie-breaking with desktop/browser/native parity.
- Adds child-facing **When Timer Rings** under Events as append-only KCVG opcode 23. Literal Seconds
  is finite positive binary32 through 86,400 (default 1) and Repeat is boolean (default true).
  Binding-local active fixed steps pause with an inactive owner and reset on Ready/restart; each
  update produces at most one ring with count/remaining/entity outputs and no serialized suspended
  state. Editor, desktop, browser, pack and native behavior match.
- Adds **Find Object Ahead** under Sensing as append-only KCVG opcode 24. It preserves opcode 22's
  nearest-tag filters, tie and nullable outputs, then applies an inclusive source-aligned binary32
  GSP4 cone. A Vector4 stores explicit world-axis X/Y/Z plus minimum cosine; runtime normalization
  uses no trigonometry and ignores Origin rotation and scale.
- Adds a phone-ready beginner template whose six graphs run in the desktop oracle, browser VM where
  applicable, and native Android VM.
- Adds **World Logic → Find the Goal** to that template: explicit Player origin, Goal tag, 9 m radius
  and `nearby_goal` world-state result.
- Adds **World Logic → Count the Timer Rings** to that template: a repeating one-second timer writes
  `timer_rings`.
- Adds **World Logic → Find the Goal Ahead** to that template: 3D Forward plus Normal width writes
  `goal_ahead`. First Steps now contains six graphs, 23 nodes and six bindings including three world
  bindings.
- Extends the Mobile 3D beginner template with **Crystal Garden**: one authored static object and an
  undoable deterministic **Populate Area** recipe. Groups allow 2–256 objects, with 64 groups and
  1,024 population objects per project.
- Adds optional `KCSP392` data with a shared 24-byte header and fixed 36-byte group records, glTF copy
  baking, and native GLES instanced rendering of a deterministic quality-budget prefix.
- Adds pointer-ID-aware two-thumb Android controls with density-scaled tap detection and a native
  host gesture harness; Space now has the same beginner jump/dash meaning as the editor preview.
- Adds undoable scene add/copy/delete, contextual Logic Block choices, 2D picture or 3D
  shape/material assignment, and bounded Wavefront OBJ mesh import.
- Adds a one-click Windows launcher and a prominent GUI ADB deploy action that pins one authorized
  device, builds, installs and opens the exact Gradle-reported application ID.
- Adds nonblocking GUI **Check Phone** (`Ctrl+Shift+P`) and CLI `profile-android`. With the deployed
  game running and screen on, the default 30-second read-only ADB check reports frame cadence,
  process memory, available GPU temperature and crash-buffer warnings without injected input or
  setting edits; CLI JSON retains additional available battery/thermal fields.
- Fixes synchronous Add Block reloading so a new logic block stays selected and Undo remains reliable.
- Adds composable desktop 3D ECS access plus compact log-polar pose/motion components, shared binary16
  LUTs and checksummed `UGECS1` deployment files.
- The full suite passes 483 tests plus 87 subtests in 59.77 seconds. Focused opcode-24 verification
  passes 14 tests plus 25 subtests; targeted Ruff, launcher/editor smokes and all native-host targets
  pass. First Steps emits a 1,085-byte KCVG with SHA-256
  `2c5c6edb0c804da7fb2b6edab8c6beab12ccd2dac8b4e743d03c6194aff4af27`, a 914-byte KCPK with
  SHA-256 `8a45ddbf874d918cedaeb0161e80fef3314c2c2b0b21a45da90e22a18c4dd313`, and a 60-byte KCSP with
  SHA-256 `e95bde225571ab5f6eac3b9c04cb1bd332a0c95c740b377ac2dee30460dd2fd1`, totaling 2,059 compact
  sidecar bytes. Fresh execution sets `goal_ahead=true`; state SHA-256 is
  `71df205686c92c217c3b1e23ad00929a331d07b5bb43e64d27023ec17d490a9c`.
- Adds a native Poco ARM64 Gradle/NDK build path. The canonical opcode-24 APK is locally built and
  inspected at 1,460,361 bytes with SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`; package/version/SDK/GLES,
  ARM64-only, debug-certificate v2 signing and embedded current sidecars are verified. ADB reported
  zero devices, so it has no fresh install/profile evidence. The preceding 1,443,529-byte opcode-23
  build is preserved as `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk` with SHA-256
  `C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`. The preserved 1,441,929-byte opcode-22
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` retains the
  120.23-FPS/10.118-ms-p95 30-second Poco result, and a still earlier
  APK retains the 64.9-second idle result. Interaction-heavy/unplugged/long-duration/fallback-tier
  and opcode-24 device evidence remain open.
- Keeps Populate Area honest and decorative: unsafe transform/collider/gameplay/graph/movement
  ownership is rejected; copies have no such semantics. Desktop presentation is capped at 64
  generated copies per group and 256 globally, while browser Mobile 3D, overlap avoidance, per-copy
  frustum culling and LOD are not implemented.
- Rejects cross-owner/world-graph writes into frozen population prototypes, aligns authored decimal
  transforms with the native binary32 scatter schedule, makes GLES initialization fail closed, and
  corrects normal transforms for nonuniformly scaled instances.

## 3.9.1 - Tom Klootwijk Signature Native Android and Mobile-3D Edition

- Preserves the complete 3.9 vector/2D/browser release and all retained APIs.
- Adds a serializable mobile-3D project schema, primitive meshes and deterministic arcade oracle.
- Adds POCO X7 Pro 12 GB, high, balanced and compatibility Android profiles.
- Adds ordered render tiers plus sustained FPS/thermal degradation and recovery.
- Adds KC3D391 binary compilation, inspection and independent C++ parsing.
- Adds a pure NativeActivity C++20 Android source project with EGL/OpenGL ES 3.0,
  dynamic resolution, touch/gamepad/keyboard input and high-refresh requests.
- Adds a 66-node signature arena, glTF output and Android source-generation CLI.
- Adds M390-M449, taking the extended engineering catalog to M449.
- Adds 51 tests; the complete package now runs 276 tests.
- Defines Vulkan and 4D as explicit future boundaries rather than implemented features.

## 3.9.0 - KC Elizabeth Vector Game-Creation Edition

- Preserves the complete KC 3.0 package and its 117 passing tests.
- Adds M330-M389, taking the combined engineering catalog to M389.
- Adds serializable vector paths, gradients, primitive factories, adaptive flattening and deterministic SVG export.
- Adds a dependency-free 2D collision and spatial-hash layer.
- Adds action-based keyboard, pointer, gamepad and touch input plus record/replay frames.
- Adds keyframe animation, easing, loops, ping-pong, crossfades and state machines.
- Adds layered tilemaps, ASCII import, A* pathfinding, flood search and merged collision boxes.
- Adds procedural sound cues, ADSR envelopes, note parsing and beat sequences.
- Adds a deterministic entity/component game world with fixed-step movement, collision lifecycle events, player dash, health, hazards, collectibles, bounds, cameras, snapshots, state hashes and saves.
- Adds a validated game-project model and schema shared across Python and browser output.
- Adds a self-contained Canvas/Web Audio HTML5 runtime with keyboard, gamepad, touch, HUD, particles, pause/restart, save/load, mute and diagnostics.
- Adds a CLI for project creation, validation, headless simulation, browser builds and SVG export.
- Adds Elizabeth's Vector Garden as a complete editable and browser-playable example.
- Adds 108 tests; the complete package now runs 225 tests.

## 3.0.0 - Interactive Graphics and Two-Hand Runtime Companion

- Retains M001-M257 by source/reference and appends M258-M329.
- Adds scene assets, nodes, layers, transforms, migration and content hashes.
- Adds adaptive curve compilation, strokes, swept tubes and marching tetrahedra.
- Adds AABB/BVH/frustum/ray/streaming/interest queries.
- Adds PBR preview materials, color transforms and a small material graph.
- Adds typed left/right hand input, pinch hysteresis, bimanual transforms and handover lineage.
- Adds deterministic event proposal commit, snapshots, checkpoints, replay and divergence detection.
- Adds SVG, glTF and USDA output adapters.
- Adds a complete runnable sandbox and 70 new tests; the package runs 117 tests total with the retained 2.0 suite.

## 2.0.0 - Pattern, Kinematic Calculus and Dynamics Expansion

- Added M198-M257 and 47 tests.
