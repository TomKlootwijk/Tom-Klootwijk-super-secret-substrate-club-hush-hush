# Changelog

## 3.9.2 - K-Kij-T / Grove Creation Engine

- Adds a dockable PySide6 desktop editor with editable 2D/3D scenes, inspectors, real runtime preview,
  friendly project checks and direct web, glTF, Android source, Poco APK and ADB-install-and-open builds.
- Adds Mobile 3D **Saved Objects** as bounded authoring-time single-node snapshots. Definitions stay
  out of native packs until placed; placed copies are ordinary flat ECS nodes with shared resources
  and graph bytecode, and save/place/remove each use one atomic Undo command.
- Adds linked multi-object **Saved Scenes**. One parent-local definition is reused by compact
  ID-plus-transform placements; Save Together/place/Unlink are atomic, while one deterministic
  materializer feeds desktop ECS, KC3D, KCVG, KCPK, KCSP, KCAN, packed ECS, glTF and Android without
  adding a native prefab type. Static-parent and no-nesting limits are validated explicitly.
- Adds retained parent-local transforms for ordinary Mobile 3D display objects. The dark Scene Tree
  nests children and offers contextual **Attach to…** / **Detach** actions; reparenting preserves the
  world pose and is atomic under Undo/Redo. The child Inspector labels its saved values **Transform
  inside …**, while the viewport and X/Y/Z translation gizmo remain world-space.
- Bounds that first hierarchy slice to eight parent edges. Children must be static, tagless,
  non-colliding/non-sensor display objects with zero spin and no Logic Blocks, Movement Pattern,
  Populate Area or Transform Animation. Ancestors may move through otherwise-valid transform systems,
  and any ancestor that owns children must keep positive uniform scale. Validation rejects
  `hierarchy.parent_graph_scale` when a graph uses a per-axis, dynamic or otherwise unprovable parent
  scale write instead of one complete saved uniform-positive vector.
- Adds optional sparse `hierarchies.kchi` (`KCHI392`) Android data: a 24-byte header and one 8-byte
  child/parent index record per attached node, omitted for flat projects. Desktop late-phase
  composition, native C++ composition after Ready/fixed-step writers, static glTF children and the
  `parent_child_hierarchy_3d` source/native-pack acceptance share the bounded contract. Its exact
  ARM64/GLES 3 Poco APK installs/cold-launches and has a five-node 15-second 120.15-FPS/9.959-ms-p95
  baseline with thermal status 0 and no crashes/warnings; this is not an AAA or sustained benchmark.
- Adds native generic dynamic-body execution after Logic Blocks. Ordinary untagged bodies receive
  gravity/integration, floor/XZ-bounds response and stable-ID solid-pair impulses; the authored
  crate KC3D/KCVG host acceptance reaches its exact 600-step endpoint. Player-controller unification
  and native contact events remain outside this slice.
- Reworks UGTS Studio into a dark viewport-first layout with compact Play/Build/Deploy controls,
  tabbed Scene Tree/Resources and contextual Output/Animation/Inspector presentation.
- Adds the bottom Mobile 3D **Animation** dock with up to 16 named relative transform clips per
  eligible static node. New/Duplicate/Rename/Delete, one optional autoplay choice, whole-pose keys,
  nondestructive scrub/preview, Once/Repeat/Back and forth and atomic Undo/Redo make the bounded path
  editable without source code. The child chooser and runtimes expose the same nine easing modes.
- Adds **Play an Animation** and **Stop an Animation** Mobile 3D Logic Blocks. Append-only KCVG
  opcodes 26/27 select a named clip, restart or resume it, and pause with either pose hold or authored-
  pose reset semantics in desktop Preview and native Android.
- Extends optional sparse `KCAN392` without breaking legacy bytes. Projects using only the old
  `transform_animation` form still emit exact v1 (24-byte header, 16-byte node binding, 24-byte key)
  with an implicit `main` autoplay clip. Libraries emit v2, whose 24-byte clip binding adds a stable
  FNV-1a clip hash and autoplay flag; key encoding and quantization are unchanged. No clip means no
  asset. GLB/skeletal animation, retargeting, crossfades and state-machine authoring remain future
  work, and current glTF animation export remains static.
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
- Executes the full current 25-block vocabulary in HTML5 and compact `KCVG001` Android bytecode,
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
- Adds **When Message Heard** under Events as append-only KCVG opcode 25. A saved exact portable
  message name selects the receiver; source, optional target and bound entity are outputs. Existing
  message sends enter a 64-event, non-reentrant FIFO with breadth-first nesting, deterministic
  broadcast/target routing and a 16,384-node-step outer-batch limit.
- Adds a phone-ready beginner template whose seven graphs run in the desktop oracle, browser VM where
  applicable, and native Android VM.
- Adds **World Logic → Find the Goal** to that template: explicit Player origin, Goal tag, 9 m radius
  and `nearby_goal` world-state result.
- Adds **World Logic → Count the Timer Rings** to that template: a repeating one-second timer writes
  `timer_rings`.
- Adds **World Logic → Find the Goal Ahead** to that template: 3D Forward plus Normal width writes
  `goal_ahead`.
- Adds **World Logic → Hear the Dash Message** to that template: the Dash graph sends
  `player.dashed`, and the separate `message_lesson` graph receives it and writes
  `heard_message=true`. First Steps now contains seven graphs, 27 nodes and seven bindings including
  four world bindings.
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
- Focused opcode-25/PBR-lite desktop, browser, compact-pack, editor, shader and native-host checks pass,
  along with targeted Ruff; the full suite is green: 596 passed, 135 subtests passed in 127.49s.
  First Steps emits a
  1,265-byte KCVG with SHA-256
  `363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`, a 914-byte KCPK with
  SHA-256 `8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`, and a 60-byte KCSP with
  SHA-256 `E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`, totaling 2,239 compact
  sidecar bytes. Fresh idle execution has state SHA-256
  `a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; dash/message execution sets
  `heard_message=true` and `score=1`.
- Adds child-facing Material Looks and compact desktop/GLES PBR-lite shading without growing the
  fixed KC3D392 material payload.
- Adds a native Poco ARM64 Gradle/NDK build path. The current PBR-lite/opcode-25/animation-runtime APK
  is locally built and inspected at 1,484,357 bytes with SHA-256
  `B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`; the canonical and explicit
  `pbr-lite-op25` paths are byte-identical and contain unchanged compact sidecars plus the linked KCAN
  runtime. The Poco is absent from ADB, so this `B9B1…` build has no install, launch or profile claim.
  The animation-bearing `43D197EC…` demo contains one 88-byte two-key KCAN and is also local-only.
  The preceding local
  `message-op25` / `message-op25-audit-fixed` snapshot remains 1,451,149 bytes / `1003F061…`.
  The last physically verified pre-audit APK is preserved as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-message-op25-pre-audit-debug.apk`: 1,449,653 bytes with
  SHA-256 `FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`.
  Xiaomi `2412DPC0AG` / `rodin` installed and cold-launched it; the pulled base APK hash-matches it,
  and its 30-second profile reports 120.12 effective FPS, 8.372/10.183/12.641 ms p50/p95/p99,
  thermal status 0 and no crashes or warnings. The capture is
  `validation/device/opcode25-message-poco-profile.json`. The preceding opcode-24 artifact remains
  preserved at the `cone-op24` path with SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`; the opcode-23 and opcode-22
  artifacts retain their historical evidence. Interaction-heavy/touch, unplugged, long-duration,
  explicit fallback-rate, representative lower-tier and first post-audit device runs remain open.
- Builds and inspects the linked Saved Scene acceptance APK at 1,505,487 bytes / SHA-256
  `70FD18B26DB7D41167E32EBD27088DC02474479F240B6A5DBF2654A6B36ED291`. Its ARM64/GLES 3/v2-signed
  package contains byte-matched KC3D/KCVG/KCAN/KCSP/KCPK materialization assets and no authoring JSON;
  ADB had no device, so install/launch/profile evidence remains open.
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
