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
- **Find Object Ahead** adds append-only opcode 24 under Sensing. It keeps the nearest-tag filters,
  tie-break and nullable outputs, then applies an inclusive
  source-aligned binary32 GSP4 cone. Its Vector4 stores explicit world-axis X/Y/Z plus minimum cosine;
  the runtime normalizes that axis without trigonometry and deliberately ignores Origin rotation and
  scale. Desktop, HTML5, compact pack and native Android share the schedule.
- **When Message Heard** completes the current 25-block vocabulary under Events as append-only opcode
  25. Its receiver stores one exact portable message name and exposes source, optional target and
  bound entity. **Send a Game Message** enters a bounded non-reentrant FIFO: nested sends are
  breadth-first, broadcasts visit active entity bindings by canonical scene index then graph ID with
  world logic last, and targeted sends reach the target owner plus world logic. Ready handlers finish
  before delivery; 64 queued events and 16,384 total node steps bound each outer batch.
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
  Normal width and stores `goal_ahead`.
- Its seventh graph, **World Logic → Hear the Dash Message**, receives `player.dashed` from the Dash
  graph and stores `heard_message=true`. First Steps now has seven graphs, 27 nodes and seven bindings
  including four world bindings.
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
- Focused opcode-25 desktop, browser, compact-pack, editor and native-host checks pass, along with
  targeted Ruff; the full suite is green: 510 passed, 100 subtests passed in 66.69s. First Steps emits a
  1,265-byte `KCVG001` pack with SHA-256
  `363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`, alongside the unchanged
  914-byte `KCPK392` (`8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`) and 60-byte
  `KCSP392` (`E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`), 2,239 bytes combined.
  Fresh idle execution has state SHA-256
  `a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; the dash/message path sets
  `heard_message=true` and `score=1`.
- The post-audit canonical opcode-25 APK is locally built and inspected at 1,451,149 bytes with
  SHA-256 `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`. The canonical
  `Poco-X7-Pro-debug`, `message-op25` and `message-op25-audit-fixed` paths are byte-identical;
  package/version/SDK/GLES, ARM64-only native code, debug-certificate v2 signing and the unchanged
  embedded KCVG/KCPK/KCSP assets verify. The Poco disconnected before final installation, so no
  install, launch or profile is claimed for this `1003…` build.
- The last physically verified pre-audit opcode-25 Poco APK is preserved as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-message-op25-pre-audit-debug.apk`: 1,449,653 bytes with
  SHA-256 `FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`.
- The preceding opcode-24 build is preserved as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk`, 1,460,361 bytes with SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`.
- The preceding opcode-23 build is preserved as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
  `C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.
- Xiaomi `2412DPC0AG` / `rodin` installed and cold-launched the pre-audit opcode-25 APK. Its pulled
  1,449,653-byte base APK hash-matches FBCB exactly; a 30-second read-only profile measured 120.12
  effective FPS, 8.372/10.183/12.641 ms p50/p95/p99, thermal status 0 and no crashes or warnings.
  The capture is `validation/device/opcode25-message-poco-profile.json`. Interaction-heavy/touch,
  unplugged, long-duration, explicit fallback-rate and lower-tier tests remain open, as does a first
  install/profile of the locally verified post-audit build.
- Earlier evidence remains historical: the 1,441,929-byte opcode-22 installed artifact has its
  retained 120.23-FPS/10.118-ms-p95 30-second result, and a still earlier APK retains the 64.9-second
  idle baseline. Neither substitutes for the opcode-25 snapshot or outstanding post-audit device run.
