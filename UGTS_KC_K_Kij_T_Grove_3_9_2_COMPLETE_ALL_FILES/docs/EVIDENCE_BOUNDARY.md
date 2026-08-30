# Evidence Boundary — K-Kij-T / Grove 3.9.2

## Demonstrated by the current source and local artifacts

- The chrono-video proposal compiler binds the supplied MP4 by SHA-256
  `1867BAFA7C80C31F18856525CBF580EDAA36D524270B1FA59CC643B51964CBFD`,
  matches 229 PyAV frame PTS values to ffprobe at time base 1/1,000,000, and
  covers all 921,600 source pixels once per observation as canonical `UNKNOWN`.
  The full 1024x512 log-polar run used the RTX 5070 Ti CUDA backend, measured
  396.88 MiB peak allocated CUDA memory, and matched the NumPy Q8 oracle with
  maximum byte difference zero. Bundle verification passes over 15 hashed
  assets, including a byte-identical embedded source, 229-entry source
  `UGCVPTS1`, 58-entry derived-preview `UGCVPTS1`, 57 proposal slices and 57
  circular joint-hypothesis slices. Both timelines are `ONCE_HOLD_LAST`.
- The same fixture remains `UNBOUNDED_UNKNOWN` in physical 3D because the MP4
  supplies no verified intrinsics, distortion, shutter/exposure timing, camera
  poses or metric scale. The 7,721 static, 3,863 dynamic and 2,096 ambiguous
  tile labels are proposal occurrences across time, not unique objects or
  accepted scene classes. The 438 motion-chart candidates are likewise
  frame-local proposals, not a body skeleton or persistent material identity.
- Android source export packages the byte-identical source, both timeline
  caches, manifest, ledgers, preview and separate `UGCVLUT1`. Native C++ verifies
  asset/media/LUT hashes and exact source/input/output PTS; source mode applies
  the Q8 LUT in an external-OES GLES shader, while preview mode has a separate
  copy shader with no LUT interface. Two owned RGBA8 slots prime ordinal zero,
  prefetch one verified ordinal, publish on integer half-open selection, discard
  stale outputs, and explicitly count/log late boundaries. Decoder failure stays
  fail-closed while the ordinary editable scene continues.
- The audited 19,036,992-byte POCO-debug APK has SHA-256
  `C9CF4D757A8961A45675A95C4C6F62CC1811F1DB188E4DD7F01F13F7E9A89DD4`.
  Its 16 chrono assets total 22,399,330 bytes, both MP4s are ZIP-stored, all 90
  exported-source ledger entries rehash, and the AArch64 library links
  `libmediandk.so`. No ADB device is attached, so this remains build/source
  evidence: MediaCodec/SurfaceTexture behavior, shader compilation, transform/
  crop/orientation, app-to-display timing, YUV-to-RGB conversion, performance,
  power and thermals are not physically proven. Explicit LOOP wrap is known to
  be late/best-effort; it is inactive in the delivered ONCE profiles.

- Focused opcode-25/PBR-lite desktop, browser, compact-pack, editor, shader and native-host checks
  pass, along with targeted Ruff. The full suite is green: 596 passed, 135 subtests passed in 127.49s.
- Logic Blocks authoring is selection-owned: unbound 2D/3D objects remain absent from project data
  until their first edit creates and binds a graph, exact Undo removes both, ordered multi-bindings
  remain explicit choices, and Populate Area prototypes refuse ownership.
- The complete current registry contains 27 blocks: 25 in the retained desktop/browser/native core
  plus two Mobile 3D-only animation actions. **When Timer Rings** remains compact `KCVG001`
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
- Material Look presets, safe shared-material cloning, one-step undo/redo and the save-index dirty
  marker are exercised directly. Desktop/native PBR-lite formulas cover an antiparallel light/view
  boundary without undefined normalization. Preset names are not serialized and KC3D392 retains its
  existing 40-byte material value payload.
- Generic native dynamic-body acceptance covers live/active filtering, gravity and fixed-step
  translation, floor/XZ-bounds restitution, deterministic object-ID pair order, sensor filtering,
  inverse-mass separation and minimum-restitution impulses. The host-native test consumes the actual
  generated KC3D/KCVG for `dynamic_crate_parity_3d`, runs its owner-bound Ready → Apply Force graph,
  and reaches exact crate X `1.375` after 600 steps while excluding Player from generic integration.
  The arm64 NDK source compiles and links in the Poco Gradle build. This is portable-module and packed-
  asset execution evidence, not proof that Android `Engine::fixedUpdate` executed on a phone.
- Bounded retained display hierarchy coverage exercises `hierarchy.parent_graph_scale` for safe
  complete-vector versus per-axis/dynamic parent scale writes, local/world TRS
  round-trips, world-pose-preserving attach/detach/delete, the local Inspector/world viewport-gizmo
  boundary, nested Scene Tree rows, desktop late-phase following and retained static glTF children.
  `parent_child_hierarchy_3d` produces a 1,633-byte KC3D (`D61049E1…`) and a 48-byte three-link KCHI
  (`24393483…`) and reaches deterministic 64-step state hash `ED2847B4…`. Separate host-native
  coverage consumes generated KC3D/KCHI, compiles Android's `transform_hierarchy.cpp`, checks a
  three-edge chain, re-composition after ancestor movement and malformed assets. The 1,565,171-byte
  hierarchy APK (`813D290E…`) is ARM64/GLES 3, v2 debug-signed and 16 KiB aligned. Authorized Poco
  serial `XOVSTSHYNREMZ5D6` (`2412DPC0AG` / `rodin_eea`) installed it and cold-launched status OK in
  448 ms; PID 25992 became resumed/visible/fullscreen and logs selected Mali-G720 MC7 plus the Poco
  profile. Its bounded 15-second/five-sample capture observed 630 SurfaceFlinger intervals at 120.15
  effective FPS, 8.376/9.959/10.473 ms p50/p95/p99, no interval over 1.5 vsync, thermal status 0 and no
  crashes/warnings. Memory ranges were 141,406–146,004 KiB PSS and 261,218–267,114 KiB RSS; reported
  GPU temperature was 45.691–51.585 °C and battery remained 55% / 33.7 °C. Evidence is stored in
  `build/device-qa-hierarchy-poco-20260829/profile-15s.json` and `hierarchy-running.png`. The focused
  hierarchy core/editor/native/example run completed with 30 passed and 10 subtests. This five-node,
  roughly 60-submitted-triangle sample does not establish animated-following under interaction,
  large-game/AAA performance, unplugged drain or sustained thermal behavior.
- The bounded Mobile 3D Animation slice has direct named-library authoring/save-reopen/Undo/Redo/
  scrub and ECS playback coverage: up to 16 relative whole-pose clips per eligible static node, zero
  or one autoplay choice, plus Logic Blocks Play/Stop/restart/resume/hold/reset control. Desktop
  playback uses the same duration/u16-time/binary16-transform quantization as optional `KCAN392`.
  Golden coverage keeps legacy KCAN v1 bytes exact; v2 inspection/native tests cover stable clip
  hashes, autoplay, malformed input, multi-clip control, both graph actions, once/loop/ping-pong, all
  nine easing codes and shortest-path normalized quaternion interpolation. No KCAN bytes are emitted
  for a project with no clip on a placed node.
- The current PBR-lite/opcode-25 APK is locally built and inspected at
  `build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-debug.apk`: 1,484,357 bytes, SHA-256
  `B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`. The explicit
  `pbr-lite-op25-debug` copy is byte-identical. Local inspection verifies package/version/SDK/GLES,
  ARM64-only native code, linked shaders, debug-certificate v2 signing, unchanged embedded
  KCVG/KCPK/KCSP assets and KCAN runtime markers. The unanimated starter correctly emits no KCAN
  asset. The Poco is absent from ADB, so no install, launch, installed-byte hash match or profile is
  claimed for this `B9B1…` build.
- The animation-bearing `build/UGTS-Animation-Timeline-3.9.2-Poco-X7-Pro-debug.apk` is 1,483,820
  bytes with SHA-256 `43D197ECF62F73349859FFED9D167BCA64BBFA092A6080BC03151E8B8F5B4E0F`. Its 88-byte KCAN
  (`2CEEF27205A1EEF140BB5BC03A519A00F2628D81B0D40DFD73555F91FCEE6FE2`) has one binding and two
  ping-pong keys. It is also local-only evidence with no install, launch or physical profile claim.
- The generic-body `build/UGTS-Dynamic-Crate-3.9.2-Poco-X7-Pro-debug.apk` is 1,531,353 bytes with
  SHA-256 `AE8B5C6AE97E08E9380EEBE30087AF26575C495B17F23351532EB1AA666E68DD`. Local inspection verifies
  package `org.ugts.games.dynamic_crate_parity_3d.pocox7pro`, ARM64/GLES 3, SDK 26/36/36, v2 debug
  signing and 16 KiB native alignment. Its KC3D/KCVG match the verifier and no authoring project JSON
  is packaged. No ADB device was present, so install, launch and device execution are unclaimed.
- The preceding local `message-op25-debug` / `message-op25-audit-fixed-debug` snapshot remains
  1,451,149 bytes with SHA-256
  `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`; it also has no device claim.
- A fresh target install of the pre-hierarchy 460,901-byte wheel (`99199CF7…`) and inspection of the 521,862-byte
  source archive (`9F36075D…`) include the multi-clip transform-animation adapter, packer and timeline,
  expose the GUI entry point, contain the final native KCAN and generic-body source/CMake/Engine
  wiring, and generate Android source with `body_physics.cpp/.hpp` from the installed package.
  Installed unsaved-project defaults resolve to `Documents/UGTS Studio`, not Python's `Lib` folder.
  Those exact package hashes predate `hierarchy3d`, KCHI and the native transform-hierarchy module;
  they are not distribution evidence for the retained-hierarchy slice.
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

The exact 1,565,171-byte hierarchy APK (`813D290E…`) installed and cold-launched on authorized
`2412DPC0AG` / `rodin_eea`; the resumed/visible/fullscreen PID and Mali-G720 profile log are recorded.
Its 15-second read-only capture measured the 120.15-FPS/9.959-ms-p95 five-node baseline summarized
above, with thermal status 0 and no crashes/warnings. This is the newest feature-bearing physical
snapshot, but its tiny geometry workload, short duration and lack of interaction mean it is not a
large-game, AAA or sustained performance result.

Xiaomi `2412DPC0AG` / `rodin` installed and cold-launched the preserved 1,449,653-byte pre-audit
opcode-25 APK. The pulled
`build/UGTS-First-Steps-3.9.2-Poco-X7-Pro-installed-message-op25-base.apk` has the exact same SHA-256
`FBCBF8710E8B7D850BEAA10E87DA53DD9373EB8AC35B836F4E62A01BEC743B7E`, proving the installed bytes
match that preserved artifact. Its 30-second read-only profile collected 756 frame intervals at
120.12 effective FPS with 8.372/10.183/12.641 ms p50/p95/p99, maximum thermal status 0, an empty
crash buffer and no warnings. The exact capture is
`validation/device/opcode25-message-poco-profile.json`. This remains the retained 30-second
opcode-25 snapshot, but it predates the native audit fixes; installing, pulling/hash-matching and
profiling the locally verified post-audit First Steps APK are still pending.

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
- General certified rigid-body dynamics, joints, deformables or robust CCD. Ordinary native dynamic
  bodies now have bounded integration/contact response, but Player still uses a special controller and
  native collision/floor/bounds events plus generic grounded state are not exposed.
- General gameplay PCG beyond bounded decorative Populate Area. Animation beyond the rigid-transform
  clip-library and direct Play/Stop slice—GLB animation import, skeletal animation/retargeting,
  crossfades/layered blending, animation-state-machine authoring and animated glTF export—is not
  claimed. Production multiplayer, anti-cheat, OpenXR and console platform SDKs are also not claimed.
- A general gameplay/physics scene graph or retained-runtime prefab system. Ordinary attached visual
  objects do follow moving ancestors through the bounded eight-edge hierarchy, but children cannot
  own physics, collision/triggers, tags, graphs, movement, population or animation. Saved Scenes remain
  a separate linked-static authoring feature: their captured definition tree compiles flat and does
  not provide retained prefab instances, nested scenes, live definition editing, per-instance child
  overrides or prefab-local mutable state; Saved Scene parents that would move are rejected.
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

The dynamic-crate guarantee is likewise narrow: exact binary32-friendly inputs produce the checked
seven position/velocity bit checkpoints and 600-step endpoint through the host-native graph/body
replay. It does not yet cover Android lifecycle, device execution, the verifier's complete canonical
state SHA-256 through an Android engine loop, or unrestricted physics scenes.

The hierarchy guarantee is likewise narrow: parent-local TRS, positive uniform parent scale,
canonical parent-before-child ordering, eight parent edges and visual-only children are checked in
Python and the host-native C++ module. KCHI contains only child/parent KC3D indices; it relies on the
KC3D child records for immutable local TRS. The guarantee does not cover rendering bit identity,
device lifecycle, child gameplay/physics/contact semantics or unrestricted affine/shear transforms.

KCAN determinism is likewise narrow: duration is binary32, time is a normalized unsigned-16 code,
relative TRS uses binary16 and quaternion interpolation follows the shared shortest-path normalized
schedule. It covers the bounded static named-clip controller and direct Play/Stop operations, not
graphical raster parity, skeletal animation, crossfades or state-machine transitions.
