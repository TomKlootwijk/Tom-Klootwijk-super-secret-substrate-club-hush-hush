# Grove 3.9.2 build status

Actual native Android source, C++ runtime, shaders, KC3D392 scene, Python package sources and interchange assets are included.

## Verified in current source on 29 August 2026

- Focused opcode-25 registry/runtime, compact-pack, retained-browser, native-host/Android, editor and
  First Steps checks pass, along with targeted Ruff. The full suite is green: 510 passed, 100
  subtests passed in 66.69s.
- The built-in vocabulary now contains 25 blocks. **When Timer Rings** is append-only `KCVG001`
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
- **When Message Heard** is append-only opcode 25. Its saved literal message name is exact and
  portable; outputs expose source, optional target and bound entity. Opcode 15 sends enter a bounded,
  non-reentrant FIFO with breadth-first nested delivery. Broadcasts visit active entity bindings by
  canonical scene index then graph ID and world bindings last; a target reaches that owner plus world
  logic. Ready handlers register and finish before delivery. The cap is 64 events and 16,384 total
  outer-root/handler steps, with explicit `EventLimit`/`TotalStepLimit`; no payload or queue is serialized.
- The offscreen UGTS Studio smoke run covers 2D/3D selection-owned graph authoring, appearance,
  Undo/Redo, live score and Poco build targets. Check Phone remains nonblocking and refuses a missing
  device, stopped game or inactive surface without mutating project or device/game settings.
- The child-friendly Mobile 3D source exports seven visual graphs with 27 nodes and seven bindings,
  including four world bindings. `visual_graphs.kcvg` is 1,265 bytes with SHA-256
  `363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`. **Find the Goal** explicitly
  searches from Player for Goal within 9 m and stores `found` as `nearby_goal`; **Count the Timer
  Rings** stores a repeating one-second timer's count as `timer_rings`; **Find the Goal Ahead** stores
  `goal_ahead=true`; the **First Steps** editor tab adds World Logic → **Hear the Dash Message**.
  The Dash graph sends `player.dashed`, and the separate `message_lesson` world graph receives it.
  Verified idle state has SHA-256
  `a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`, while the dash/message path
  sets `heard_message=true` and `score=1`.
- The same source emits a 914-byte packed log-polar kinematics asset with SHA-256
  `8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313` and a 60-byte `KCSP392`
  asset with SHA-256 `E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`, representing a recipe
  for one authored crystal plus 17 deterministic render-only copies. The three compact sidecars total
  2,239 bytes.
- Native touch routing keeps left/right roles by pointer ID, so holding movement while tapping dash
  remains independent of Android pointer-array order. Cancel, drag-not-tap, look and pinch paths are
  covered by the host harness.
- The post-audit canonical opcode-25 APK is locally built and inspected at 1,451,149 bytes with
  SHA-256 `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`. The canonical
  `Poco-X7-Pro-debug`, `message-op25-debug` and `message-op25-audit-fixed-debug` paths are
  byte-identical. Package/version/SDK/GLES, ARM64-only native code, debug-certificate v2 signing and
  the unchanged embedded KCVG/KCPK/KCSP assets verify. The Poco disconnected before final
  installation, so no install, launch, installed-byte hash match or profile is claimed for this
  `1003…` build.
- The last physically verified pre-audit opcode-25 artifact is preserved explicitly at
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-message-op25-pre-audit-debug.apk`: 1,449,653 bytes with SHA-256
  `FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`. Local `aapt`/`apksigner`
  inspection verifies package `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 /
  `3.9.2-poco-x7-pro`, minimum SDK 26, target/compile SDK 36, GLES 3.0, ARM64-only native code, a
  debug certificate and APK Signature Scheme v2. Embedded KCVG/KCPK/KCSP sizes and hashes match
  that build's sidecars exactly.
- The preceding opcode-24 artifact is preserved at
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk`: 1,460,361 bytes, SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`.
- The preceding opcode-23 artifact is preserved as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`: 1,443,529 bytes, SHA-256
  `C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`. It is not the current source
  artifact and has no fresh physical-device evidence.

## Physically verified pre-audit opcode-25 artifact

- Xiaomi model `2412DPC0AG` / codename `rodin` installed and cold-launched the 1,449,653-byte
  opcode-25 APK above. The pulled
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-message-op25-base.apk` has the exact same
  SHA-256 `FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`, proving the installed
  bytes match that preserved artifact.
- The verified idle state SHA-256 is
  `a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; exercising dash/message
  behavior records `heard_message=true` and `score=1`.
- Its bounded 30-second read-only profile collected 756 frame intervals at 120.12 effective FPS:
  8.372 ms p50, 10.183 ms p95 and 12.641 ms p99. Android thermal status remained 0; the crash buffer
  was empty and the profiler emitted no warnings. The complete capture is
  `validation/device/opcode25-message-poco-profile.json`.

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

## Remaining release and device boundary

The post-audit canonical APK is locally built, inspected and hash-identified, but has no device run
because the Poco disconnected immediately before final installation. The exact pre-audit FBCB APK
has the successful install, cold launch, pulled-byte hash match and short 30-second Poco profile.
Neither short profile is a general device guarantee. A first post-audit install/hash/profile,
interaction-heavy/touch frame pacing, unplugged battery drain, long-duration thermal
equilibrium, explicit 60/90 Hz fallback behavior and representative lower-tier hardware remain open.

UGTS is also not yet a complete Godot-like engine. The current editor, ECS, typed graphs and native
GLES path are useful working slices, but reusable scene/prefab and animation workflows, richer
physics/content pipelines, production signing/distribution and Vulkan remain incomplete.
