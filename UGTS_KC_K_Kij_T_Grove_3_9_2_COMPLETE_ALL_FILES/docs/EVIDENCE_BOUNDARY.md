# Evidence Boundary — K-Kij-T / Grove 3.9.2

## Demonstrated by the current source and local artifact

- The full suite passes 483 tests plus 87 subtests in 59.77 seconds. Focused opcode-24 verification
  also passes 14 tests plus 25 subtests; targeted Ruff, launcher/editor smokes and all native-host
  build targets pass.
- Logic Blocks authoring is selection-owned: unbound 2D/3D objects remain absent from project data
  until their first edit creates and binds a graph, exact Undo removes both, ordered multi-bindings
  remain explicit choices, and Populate Area prototypes refuse ownership.
- The complete current vocabulary contains 24 blocks. **When Timer Rings** is compact `KCVG001`
  opcode 23. Its saved **Seconds** literal is finite positive binary32 through 86,400 (default 1),
  and its saved **Repeat** literal is boolean (default true). Tests cover binding-local active fixed
  steps, inactive-owner pause while the world continues, Ready/restart reset, count/remaining/entity
  outputs, at most one ring per update, no serialized/suspended execution state, and matching editor,
  desktop, browser, pack and native behavior.
- **Find Nearby Object** remains compact opcode 22 and has golden-tested desktop/browser/native
  behavior for origin, five portable tags, inclusive radius, active/alive filtering, nearest
  selection and deterministic object-ID ties.
- **Find Object Ahead** is compact opcode 24. It preserves those filters, tie and outputs, then uses
  an inclusive source-aligned binary32 GSP4 cone. The Vector4 is explicit world-axis X/Y/Z plus
  minimum cosine; normalization and candidate direction use the shared float32 schedule without
  trigonometry, and Origin rotation/scale do not affect it.
- First Steps emits six graphs, 23 graph nodes and six bindings including three world bindings. Its
  1,085-byte KCVG pack has SHA-256
  `2c5c6edb0c804da7fb2b6edab8c6beab12ccd2dac8b4e743d03c6194aff4af27`; the 914-byte KCPK has
  SHA-256 `8a45ddbf874d918cedaeb0161e80fef3314c2c2b0b21a45da90e22a18c4dd313`, and the 60-byte KCSP has
  SHA-256 `e95bde225571ab5f6eac3b9c04cb1bd332a0c95c740b377ac2dee30460dd2fd1`, so all three total 2,059
  bytes. Fresh execution sets `goal_ahead=true`; state SHA-256 is
  `71df205686c92c217c3b1e23ad00929a331d07b5bb43e64d27023ec17d490a9c`.
- The canonical opcode-24 `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk` is locally built and
  inspected: 1,460,361 bytes, SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`, package
  `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 / `3.9.2-poco-x7-pro`, minimum SDK 26,
  target/compile SDK 36, GLES 3.0, ARM64-only, debug-certificate signed and APK Signature Scheme v2
  verified. Embedded KCVG/KCPK/KCSP sizes and hashes match the current source sidecars exactly.
- The preceding opcode-23 build is preserved separately as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
  `C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.

## Physical Android boundary

An early 3.9.2 APK was installed, cold-launched, hash-matched and visually smoke-checked on the
authorized Xiaomi `2412DPC0AG` / `rodin`. Its retained 64.9-second idle profile measured frame
cadence, process memory, available GPU temperature, Android thermal status and crash-buffer state;
the exact workload and limitations are recorded in
`validation/poco_x7_pro_idle_profile_2026_08_29.json`.

The later 1,441,929-byte `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` with SHA-256
`7F3080834EDB56EAAB0BFE8AEA1B1AD2D634C1AA7C4EB314C5B614760E48454F` is also installed,
cold-launched and hash-matched byte-for-byte on that Poco. Local inspection verifies APK Signature
Scheme v2, a debug certificate, ARM64-only native code, minimum SDK 26, target SDK 36, GLES3 and
package `org.ugts.games.my_mobile_3d_game.pocox7pro`. Its retained 30.0-second profile collected 756
intervals at 120.23 effective FPS with 8.298/10.118/11.872 ms
p50/p95/p99 and two intervals over 1.5 display periods. PSS was 132,590–138,573 KiB, RSS
250,478–257,854 KiB, available GPU temperature 44.634–45.511 °C, battery 37 °C / 78% unchanged,
maximum thermal status 0, crash buffer empty and warnings empty. The exact current result is
`validation/poco_x7_pro_current_profile_2026_08_29.json`.

Despite the validation filename, that preserved APK is the preceding four-graph/opcode-22 installed
artifact; it contains neither **When Timer Rings** nor **Find Object Ahead**. Both captures are short baselines for their exact
APK/workload, not general phone guarantees. ADB reported zero devices during current verification,
so no install, cold launch, installed hash match or physical-device profile is claimed for the
locally built/inspected current six-graph/opcode-24 APK.
Interaction-heavy/touch, unplugged battery, long-duration thermal equilibrium, explicit 60/90 Hz
fallback and representative lower-tier-device runs remain open. Play Store submission, release
signing and certification are not claimed.

## Broader non-claims

- Vulkan rendering (optional interface/manifest hook only).
- 4D runtime, 4D physics or 4D interchange (design TODO only).
- General certified rigid-body dynamics, joints, deformables or robust CCD.
- General gameplay PCG beyond bounded decorative Populate Area, plus skeletal animation/retargeting,
  production multiplayer, anti-cheat, OpenXR and console platform SDKs.
- Independent verification of requester identity, attribution or ownership assertions.

## Determinism scope

Canonical state/project hashes normalize numerically equivalent integral values. Determinism is
expected for the same runtime version, project, fixed step and input sequence. Repeatable Random
Number (opcode 21), Find Nearby Object (opcode 22), When Timer Rings (opcode 23) and Find Object
Ahead (opcode 24) have explicit binary32 cross-language parity fixtures. The cone guarantee covers
the documented world-axis Vector4 and source-aligned GSP4 float32 schedule, not hidden orientation or
runtime trigonometry. Timer progress is derived from a binding-local active-step
counter and fixed step, not a serialized clock or suspended graph. Those narrow guarantees do not
imply bit-identical rendering or unrestricted cross-language floating-point identity for every
subsystem.
