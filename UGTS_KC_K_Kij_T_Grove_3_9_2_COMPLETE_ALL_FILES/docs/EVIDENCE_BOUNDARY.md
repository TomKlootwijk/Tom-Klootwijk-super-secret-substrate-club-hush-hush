# Evidence Boundary — K-Kij-T / Grove 3.9.2

## Demonstrated by the current source and local artifacts

- Focused opcode-25 desktop, browser, compact-pack, editor and native-host checks pass, along with
  targeted Ruff. The full suite is green: 510 passed, 100 subtests passed in 66.69s.
- Logic Blocks authoring is selection-owned: unbound 2D/3D objects remain absent from project data
  until their first edit creates and binds a graph, exact Undo removes both, ordered multi-bindings
  remain explicit choices, and Populate Area prototypes refuse ownership.
- The complete current vocabulary contains 25 blocks. **When Timer Rings** remains compact `KCVG001`
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
- **When Message Heard** is compact opcode 25. Its receiver saves one exact portable message name and
  exposes source, optional target and bound entity. **Send a Game Message** enters one non-reentrant
  FIFO: nested sends are breadth-first; broadcasts visit active entity bindings by canonical scene
  index then graph ID before world bindings; targeted sends reach the target owner and world logic.
  Ready handlers finish before delivery. A batch is bounded to 64 queued events and 16,384 total
  initial-handler/message-handler node steps, with explicit `EventLimit`/`TotalStepLimit` failures.
- First Steps emits seven graphs, 27 graph nodes and seven bindings including four world bindings.
  The Dash graph sends `player.dashed`; the separate World Logic `message_lesson` / **Hear the Dash
  Message** graph receives it and stores `heard_message=true`. Its 1,265-byte KCVG pack has SHA-256
  `363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`; the 914-byte KCPK has
  SHA-256 `8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`, and the 60-byte KCSP has
  SHA-256 `E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`, so all three total 2,239
  bytes. Fresh idle execution has state SHA-256
  `a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; dash/message execution sets
  `heard_message=true` and `score=1`.
- The post-audit canonical opcode-25 APK is locally built and inspected at
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk`: 1,451,149 bytes, SHA-256
  `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`. The
  `message-op25-debug` and `message-op25-audit-fixed-debug` copies are byte-identical. Local
  inspection verifies package/version/SDK/GLES, ARM64-only native code, debug-certificate v2 signing
  and the unchanged embedded KCVG/KCPK/KCSP assets. The Poco disconnected before final installation,
  so no install, launch, installed-byte hash match or profile is claimed for this `1003…` build.
- The last physically verified pre-audit opcode-25 APK is preserved as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-message-op25-pre-audit-debug.apk`: 1,449,653 bytes, SHA-256
  `FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`, package
  `org.ugts.games.my_mobile_3d_game.pocox7pro`, version 392 / `3.9.2-poco-x7-pro`, minimum SDK 26,
  target/compile SDK 36, GLES 3.0, ARM64-only, debug-certificate signed and APK Signature Scheme v2
  verified. Embedded KCVG/KCPK/KCSP sizes and hashes match that build's source sidecars exactly.
- The preceding opcode-24 build remains preserved separately as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-cone-op24-debug.apk`, 1,460,361 bytes with SHA-256
  `917028CB74AE8DE31E0DDAAD02F6D589012F17754DFD213D8D2B4330DBDEE1A1`.
- The preceding opcode-23 build is preserved separately as
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-timer-op23-debug.apk`, 1,443,529 bytes with SHA-256
  `C502D88CFD7EE4A8F824E0F4EC2A3D6C2938DE080F79F0ACB8E9288CC9BFBD83`.

## Physical Android boundary

Xiaomi `2412DPC0AG` / `rodin` installed and cold-launched the preserved 1,449,653-byte pre-audit
opcode-25 APK. The pulled
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-message-op25-base.apk` has the exact same SHA-256
`FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`, proving the installed bytes
match that preserved artifact. Its 30-second read-only profile collected 756 frame intervals at
120.12 effective FPS with 8.372/10.183/12.641 ms p50/p95/p99, maximum thermal status 0, an empty
crash buffer and no warnings. The exact capture is
`validation/device/opcode25-message-poco-profile.json`. This remains the current physical snapshot,
but it predates the native audit fixes; installing, pulling/hash-matching and profiling the locally
verified post-audit APK are still pending.

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
artifact; it contains neither **When Timer Rings**, **Find Object Ahead** nor **When Message Heard**.
The opcode-22 and still-earlier captures remain historical short baselines for their exact
APK/workloads, not general phone guarantees or substitutes for the opcode-25 snapshot above.
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
Ahead (opcode 24) have explicit binary32 cross-language parity fixtures. When Message Heard (opcode
25) has cross-runtime fixtures for exact matching, canonical routing order, target/broadcast scope,
breadth-first nesting and the event/total-step limits. The cone guarantee covers
the documented world-axis Vector4 and source-aligned GSP4 float32 schedule, not hidden orientation or
runtime trigonometry. Timer progress is derived from a binding-local active-step
counter and fixed step, not a serialized clock or suspended graph. Those narrow guarantees do not
imply bit-identical rendering or unrestricted cross-language floating-point identity for every
subsystem.
