# UGTS-KC 3.9.2 — K-Kij-T / Grove

Creation-engine release focused on a learnable desktop workflow and a compact native Mali-G720 MC7
result, with adaptive fallbacks for general Android phones.

## What is actually in this release

- Dockable PySide6 UGTS Studio with 2D/3D scene authoring, undo/redo, picture/shape/material choices,
  real preview, readable checks and direct build targets.
- A 24-block visual-logic vocabulary shared by desktop, retained 2D HTML5 and native Android,
  including append-only opcode 22 **Find Nearby Object** with deterministic nearest-tag sensing and
  append-only opcode 23 **When Timer Rings** with binding-local active fixed-step timing, bounded
  literal settings and no serialized suspended state. Append-only opcode 24 **Find Object Ahead**
  adds a source-aligned binary32 GSP4 cone whose Vector4 stores world-axis X/Y/Z plus minimum cosine;
  it uses no runtime trigonometry and ignores Origin rotation and scale.
- Selection-owned Logic Blocks: unbound 2D/3D objects start blank, first edit binds atomically with
  Undo, multiple bindings have a chooser, and Populate Area prototypes cannot own graphs.
- A six-graph/23-node Mobile 3D First Steps project with six bindings including three world bindings:
  **Find the Goal** searches from Player for Goal within 9 m and stores `nearby_goal`, while **Count
  the Timer Rings** stores a repeating one-second timer count as `timer_rings`. **Find the Goal
  Ahead** uses the saved 3D Forward world axis and Normal width and stores `goal_ahead`.
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

The full suite passes 483 tests plus 87 subtests in 59.77 seconds. Focused opcode-24 verification
passes 14 tests plus 25 subtests; targeted Ruff, launcher/editor smokes and all native-host targets
also pass. First Steps emits a 1,085-byte KCVG with SHA-256
`2c5c6edb0c804da7fb2b6edab8c6beab12ccd2dac8b4e743d03c6194aff4af27`, a 914-byte KCPK with
SHA-256 `8a45ddbf874d918cedaeb0161e80fef3314c2c2b0b21a45da90e22a18c4dd313`, and a 60-byte KCSP with
SHA-256 `e95bde225571ab5f6eac3b9c04cb1bd332a0c95c740b377ac2dee30460dd2fd1`, totaling 2,059 bytes.
Fresh source execution sets `goal_ahead=true` and produces state SHA-256
`71df205686c92c217c3b1e23ad00929a331d07b5bb43e64d27023ec17d490a9c`.

The local Android SDK/NDK compiles the current child-friendly opcode-24 project into the v2-signed,
ARM64-only `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk` (1,460,361 bytes; SHA-256
`917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`). `aapt`/`apksigner`
inspection verifies package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
`3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES3, ARM64-only native code, the debug
certificate and v2 signature. Embedded KCVG/KCPK/KCSP hashes match the current source sidecars.

ADB reported zero devices during current verification, so the opcode-24 APK is not claimed as freshly
installed, launched or profiled. The preceding opcode-23 build is preserved as
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk` (1,443,529 bytes; SHA-256
`C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`). The preserved 1,441,929-byte opcode-22
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` owns the
30-second Poco result: 120.23 effective FPS, 10.118 ms p95, 132,590–138,573 KiB PSS,
44.634–45.511 °C reported GPU temperature, thermal status 0 and no crash lines or warnings. A still
earlier 3.9.2 APK owns the retained 64.9-second idle baseline. Those historical results do not replace
a fresh opcode-24 run, interaction-heavy/touch, unplugged, long-duration thermal or 60/90 Hz/lower-
tier fallback evidence. Vulkan and a full AAA asset/content pipeline remain future work.
