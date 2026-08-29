# UGTS-KC 3.9.2 — K-Kij-T / Grove

Creation-engine release focused on a learnable desktop workflow and a compact native Mali-G720 MC7
result, with adaptive fallbacks for general Android phones.

## What is actually in this release

- Dockable PySide6 UGTS Studio with 2D/3D scene authoring, undo/redo, picture/shape/material choices,
  real preview, readable checks and direct build targets.
- A 25-block visual-logic vocabulary shared by desktop, retained 2D HTML5 and native Android,
  including append-only opcode 22 **Find Nearby Object** with deterministic nearest-tag sensing and
  append-only opcode 23 **When Timer Rings** with binding-local active fixed-step timing, bounded
  literal settings and no serialized suspended state. Append-only opcode 24 **Find Object Ahead**
  adds a source-aligned binary32 GSP4 cone whose Vector4 stores world-axis X/Y/Z plus minimum cosine;
  it uses no runtime trigonometry and ignores Origin rotation and scale. Append-only opcode 25
  **When Message Heard** adds exact, bounded FIFO cross-graph messages with source/target/entity context.
- Selection-owned Logic Blocks: unbound 2D/3D objects start blank, first edit binds atomically with
  Undo, multiple bindings have a chooser, and Populate Area prototypes cannot own graphs.
- A seven-graph/27-node Mobile 3D First Steps project with seven bindings including four world bindings:
  **Find the Goal** searches from Player for Goal within 9 m and stores `nearby_goal`, while **Count
  the Timer Rings** stores a repeating one-second timer count as `timer_rings`. **Find the Goal
  Ahead** uses the saved 3D Forward world axis and Normal width and stores `goal_ahead`. In the
  **First Steps** editor tab, World Logic → **Hear the Dash Message** receives the Dash graph's
  `player.dashed` message and stores `heard_message=true`.
- ECS composition plus two-word packed log-polar pose/motion components and shared binary16 LUTs.
- Native Android Studio/Gradle project with a GLES3 renderer, dynamic internal resolution,
  pointer-ID-aware two-thumb controls and adaptive Poco/general-device profiles.
- Full-screen Grove juice/post pass with glow, flash, chromatic separation, vignette,
  saturation/contrast response and pickup/goal shockwave.
- KC3D392 scene packs, glTF interchange and all retained 3.9/3.9.1 2D, browser and 3D APIs.
- GUI **Check Phone** (`Ctrl+Shift+P`) and CLI `profile-android` for a nonblocking default 30-second
  observation of a running deployed game with its screen on, covering frame cadence, memory, GPU
  temperature when exposed by Android, and crash warnings without injected input or setting edits.

## PCG

General gameplay PCG remains a future TODO. Grove ships only bounded decorative **Populate Area**:
static render-only copies with explicit caps and no independent collider, movement, gameplay or
Logic Block identity.

## Build boundary

Focused opcode-25 parity checks and targeted Ruff pass; the full suite is green: 510 passed, 100
subtests passed in 66.69s. First Steps emits a 1,265-byte KCVG with SHA-256
`363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`, a 914-byte KCPK with
SHA-256 `8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`, and a 60-byte KCSP with
SHA-256 `E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`, totaling 2,239 bytes.
Fresh idle execution produces state SHA-256
`a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; dash execution sets
`heard_message=true` and `score=1`.

The post-audit canonical opcode-25 APK is locally built and inspected at 1,451,149 bytes with SHA-256
`1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`. The canonical,
`message-op25` and `message-op25-audit-fixed` paths are byte-identical, v2-signed, ARM64-only and
contain the unchanged current sidecars. The Poco disconnected before final installation, so this
`1003…` build has no install, launch or physical profile claim.

The last physically verified pre-audit opcode-25 APK is preserved at the explicit
`message-op25-pre-audit-debug` path (1,449,653 bytes; SHA-256
`FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`). `aapt`/`apksigner`
inspection verifies package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
`3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES3, ARM64-only native code, the debug
certificate and v2 signature.
Embedded KCVG/KCPK/KCSP hashes match that build's source sidecars.
Xiaomi `2412DPC0AG` / `rodin` installed and cold-launched it; the pulled 1,449,653-byte base APK has
the same SHA-256. Its 30-second profile measured 120.12 effective FPS, 8.372/10.183/12.641 ms
p50/p95/p99, thermal status 0 and no crashes or warnings; see
`validation/device/opcode25-message-poco-profile.json`. This physical evidence belongs only to FBCB.

The preceding opcode-24 build is preserved at
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk` (1,460,361 bytes; SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`). The opcode-23 build remains
preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk` (1,443,529 bytes; SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`). The preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` owns the
30-second Poco result: 120.23 effective FPS, 10.118 ms p95, 132,590–138,573 KiB PSS,
44.634–45.511 °C reported GPU temperature, thermal status 0 and no crash lines or warnings. A still
earlier 3.9.2 APK owns the retained 64.9-second idle baseline. Interaction-heavy/touch, unplugged,
long-duration thermal and 60/90 Hz/lower-tier fallback evidence remain open. UGTS is not yet a
complete Godot-like engine: reusable scenes/prefabs, animation, richer physics/content pipelines,
production distribution, Vulkan and a full AAA asset/content pipeline remain future work.
