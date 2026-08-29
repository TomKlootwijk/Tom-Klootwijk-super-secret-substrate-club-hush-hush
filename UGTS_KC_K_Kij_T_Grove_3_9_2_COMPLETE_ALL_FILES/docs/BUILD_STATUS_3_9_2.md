# Grove 3.9.2 build status

Actual native Android source, C++ runtime, shaders, KC3D392 scene, Python package sources and interchange assets are included.

## Verified in current source on 29 August 2026

- The full suite passes 483 tests plus 87 subtests in 59.77 seconds. Focused opcode-24 verification
  passes 14 tests plus 25 subtests across registry/runtime, compact pack, retained browser, native
  host/Android fixtures, editor authoring and First Steps integration. Targeted Ruff,
  launcher/editor smokes and all native-host build targets also pass.
- The built-in vocabulary now contains 24 blocks. **When Timer Rings** is append-only `KCVG001`
  opcode 23. **Seconds** is a saved finite positive binary32 literal no greater than 86,400 and
  defaults to 1; **Repeat** is a saved boolean literal and defaults to true. Each graph binding owns
  its active fixed-step count. An inactive entity pauses only its binding while the world continues,
  Ready/restart resets the count, and a timer emits at most one ring per update. Outputs are count,
  remaining fixed-step seconds and the bound entity; no suspended graph or timer state is serialized.
  The editor, desktop VM, retained browser VM, compact pack and native Android VM share this contract.
- **Find Nearby Object** remains append-only opcode 22. Current fixtures cover its explicit/bound
  origin, five portable tag choices, inclusive binary32 radius, dead/inactive and self filtering,
  nullable miss, nearest result, deterministic ID tie-break and desktop/browser/native parity.
- **Find Object Ahead** is append-only opcode 24. It adds an inclusive, source-aligned binary32 GSP4
  cone to the same filters, nearest selection, ID tie and nullable outputs. Its `cone` Vector4 stores
  explicit world-axis X/Y/Z and minimum cosine. The finite nonzero axis is normalized with the shared
  float32 schedule; candidate direction uses the source-aligned clamped distance denominator. There
  is no runtime trigonometry, and Origin rotation/scale are deliberately irrelevant.
- The offscreen UGTS Studio smoke run covers 2D/3D selection-owned graph authoring, appearance,
  Undo/Redo, live score and Poco build targets. Check Phone remains nonblocking and refuses a missing
  device, stopped game or inactive surface without mutating project or device/game settings.
- The child-friendly Mobile 3D source exports six visual graphs with 23 nodes and six bindings,
  including three world bindings. `visual_graphs.kcvg` is 1,085 bytes with SHA-256
  `2c5c6edb0c804da7fb2b6edab8c6beab12ccd2dac8b4e743d03c6194aff4af27`. **Find the Goal** explicitly
  searches from Player for Goal within 9 m and stores `found` as `nearby_goal`; **Count the Timer
  Rings** stores a repeating one-second timer's count as `timer_rings`; **Find the Goal Ahead** stores
  `goal_ahead=true` in the verified fresh run. Its state SHA-256 is
  `71df205686c92c217c3b1e23ad00929a331d07b5bb43e64d27023ec17d490a9c`.
- The same source emits a 914-byte packed log-polar kinematics asset with SHA-256
  `8a45ddbf874d918cedaeb0161e80fef3314c2c2b0b21a45da90e22a18c4dd313` and a 60-byte `KCSP392`
  asset with SHA-256 `e95bde225571ab5f6eac3b9c04cb1bd332a0c95c740b377ac2dee30460dd2fd1`, representing a recipe
  for one authored crystal plus 17 deterministic render-only copies. The three compact sidecars total
  2,059 bytes.
- Native touch routing keeps left/right roles by pointer ID, so holding movement while tapping dash
  remains independent of Android pointer-array order. Cancel, drag-not-tap, look and pinch paths are
  covered by the host harness.
- The canonical `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk` is the new opcode-24 artifact:
  1,460,361 bytes with SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`. Local `aapt`/`apksigner`
  inspection verifies package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
  `3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES 3.0, ARM64-only native code, a
  debug certificate and APK Signature Scheme v2. Embedded KCVG/KCPK/KCSP sizes and hashes match the
  current source sidecars exactly. ADB reported zero devices, so no install, cold launch, installed
  hash match or profile is claimed for this APK.
- The preceding opcode-23 artifact is preserved as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`: 1,443,529 bytes, SHA-256
  `C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`. It is not the current source
  artifact and has no fresh physical-device evidence.

## Preceding installed opcode-22 artifact evidence

- `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-base.apk` preserves the preceding four-graph/
  opcode-22 artifact. It is 1,441,929 bytes with SHA-256
  `7F3080834EDB56EAAB0BFE8AEA1B1AD2D634C1AA7C4EB314C5B614760E48454F`. Local build inspection
  verifies APK Signature Scheme v2 with a debug certificate, ARM64-only native code, minimum SDK 26,
  target SDK 36, GLES3 and package `org.ugts.games.my_mobile_3d_game.pocox7pro`.
- That preceding APK installs and cold-launches on Poco serial `XOVSTSHYNREMZ5D6`; the installed
  `base.apk` is 1,441,929 bytes and matches the preserved snapshot SHA-256 above. Android reports version 392 /
  `3.9.2-poco-x7-pro`, package `org.ugts.games.my_mobile_3d_game.pocox7pro`, ARM64 and PID 26017.
- Its retained 30.0-second profile collected 756 frame intervals at 120.23
  effective FPS on an 8.3333 ms display period: 8.298 ms p50, 10.118 ms p95 and 11.872 ms p99, with
  only two intervals above 1.5 display periods. PSS was 132,590–138,573 KiB, RSS
  250,478–257,854 KiB and reported GPU temperature 44.634–45.511 °C. Battery stayed at 78% and
  37 °C, maximum Android thermal status was 0, the app crash buffer was empty and the profiler emitted
  no warnings. The result is `validation/poco_x7_pro_current_profile_2026_08_29.json`.
- `build/UGTS-3.9.2-Poco-nearby-profile-render.png` confirms that opcode-22 scene rendered on-device; the
  captured image includes a MIUI system overlay above the app and is not presented as a clean
  marketing screenshot.

## Retained earlier build and device evidence

- Before the current Logic Blocks/Find Nearby integration, the local Android SDK 36, NDK r29, Gradle
  8.13 and Android Gradle Plugin 8.13.2 compiled the First Steps project from the repository's full
  long Windows path. That earlier ARM64 Poco debug APK was 1,438,457 bytes with SHA-256
  `2205B4C92CBBA17FDEC35DFD792AB1915DCF733ACC3B1BDECB313A8A90F4AA43`.
- Android build-tools verified that earlier APK's v2 debug signature and expected `arm64-v8a`, GLES
  3.0, minimum SDK 26, target SDK 36 and `NativeActivity` metadata. An authorized Xiaomi
  `2412DPC0AG` (`rodin`, MT6899) installed and cold-launched it; on-device `sha256sum` matched, the
  native log selected Mali-G720 MC7 / 120 FPS / signature-ultra, and a screenshot confirmed GLES
  rendering.
- A retained 64.9-second idle-render profile of that earlier APK collected 1,512 SurfaceFlinger
  intervals at 120.15 effective FPS: 8.393 ms p50, 10.032 ms p95 and 11.144 ms p99. PSS stayed from
  133,713 to 134,089 KiB, reported GPU temperature from 48.0 to 49.5 °C, Android thermal status at 0,
  and the app crash buffer empty. Methodology and limitations are in
  `validation/poco_x7_pro_idle_profile_2026_08_29.json`.
- That opcode-22 feature snapshot was rebuilt as a wheel and source archive. The wheel installed into a
  fresh target directory, reported that target as its import origin and passed the complete offscreen
  editor smoke. That installed copy also generated its Android source as 51 files / 306,288
  bytes with project digest prefix `38205fd7148b`.

## Remaining device boundary

The current opcode-24 APK is locally built and inspected, but its physical-device steps remain open.
The 30-second result above is a short baseline for the exact preceding opcode-22 APK, not a general
device guarantee or evidence for **When Timer Rings** or **Find Object Ahead**. The prior 64.9-second idle baseline remains
separate evidence for its exact still-earlier APK and workload. A fresh opcode-24 install, cold
launch, installed hash match and profile remain unverified, alongside
interaction-heavy/touch frame pacing, unplugged battery drain, long-duration thermal equilibrium,
explicit 60/90 Hz fallback behavior and representative lower-tier hardware. Vulkan is not
implemented; the demonstrated Android renderer is GLES3.
