# Changelog

## 3.9.2 - K-Kij-T / Grove Creation Engine

- Adds a dockable PySide6 desktop editor with editable 2D/3D scenes, inspectors, real runtime preview,
  friendly project checks and direct web, glTF, Android source, Poco APK and ADB-install-and-open builds.
- Adds typed, serializable Logic Blocks with deterministic ordering and bounded desktop execution.
- Adds a desktop-only **Logic Trail** presentation: read-only live execution badges plus a **Last Run**
  list for values, flow and errors. The latest trail remains after Stop but is not serialized and adds
  zero bytes to exports.
- Executes the full current 20-block vocabulary in HTML5 and compact `KCVG001` Android bytecode,
  including sparse world graphs, Apply Force and Trigger Enter/Exit with bounded sensor context.
- Adds a phone-ready beginner template whose two lessons run in the desktop oracle, browser VM where
  applicable, and native Android VM.
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
- Fixes synchronous Add Block reloading so a new logic block stays selected and Undo remains reliable.
- Adds composable desktop 3D ECS access plus compact log-polar pose/motion components, shared binary16
  LUTs and checksummed `UGECS1` deployment files.
- Adds a native Poco ARM64 Gradle/NDK build path. A physical Poco-class `rodin` device accepted and
  launched a GUI deployment; sustained frame pacing and thermals remain unverified.
- Keeps Populate Area honest and decorative: unsafe transform/collider/gameplay/graph/movement
  ownership is rejected; copies have no such semantics. Desktop presentation is capped at 64
  generated copies per group and 256 globally, while browser Mobile 3D, overlap avoidance, per-copy
  frustum culling and LOD are not implemented.

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
