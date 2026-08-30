# Grove 3.9.2 build status

Actual native Android source, C++ runtime, shaders, KC3D392 scene, Python package sources and interchange assets are included.

## Verified in current source on 30 August 2026

- The built-in Mobile 3D/native Logic Blocks registry contains 30 blocks. The portable subset shared
  by desktop, retained HTML5 and native remains 25; opcodes 26–30 are Mobile-3D-only.
- Append-only opcode 28 **Read Movement** and opcode 29 **Change Movement** hardcode the semantic
  virtual `polar_movement` component. They expose an entity, exactly one of seven friendly numeric
  movement fields, and a numeric fallback or value. Reads/writes have Python/native packed-word and
  transform parity. In the fixed four-node comparison the semantic KCVG is 239 bytes with eight
  inputs versus 268 bytes with ten inputs for generic component access: 29 bytes smaller and without
  a `polar_movement` string. Browser export rejects these blocks explicitly as Mobile-3D-only.
- Append-only opcode 30 **Show or Hide Extra Copies** changes one ephemeral Make Many visibility bit
  while the real prototype remains active. The fixed native mask costs eight bytes for up to 64
  recipes; hidden recipes consume no materialization or visible-node budget, and KCPR/KCPK/project/
  snapshot bytes are unchanged. Its frozen 121-byte KCVG is 29 bytes over Ready alone. Focused and
  broad desktop checks, native host/VM tests and an ARM64 NDK build pass.
- **Radial Burst (loops)** is implemented as bounded looping Make Many display data around one real
  packed ECS prototype. Legacy-only Ring/Spiral/Polar Field packs retain byte-identical KCPR v1 and
  their prior golden hashes; with Glow disabled, KCPR v2 is selected only when Burst exists. A
  controlled standalone one-Burst sidecar is 240 bytes. Local packed displacement compounds with the prototype anchor
  through log-encoded polar LUT semantics; Direct is the baseline native path, LUT uses the shared
  profile, and Bayer remains the final presentation pass. Limits are 512 instances per recipe,
  16 Burst recipes and 2,048 Burst instances per project, with 64 retained editor preview copies
  globally and native work bounded by maximum-visible plus the remaining particle budget.
- Desktop stopped Burst preview is the deterministic loop midpoint. Play uses the real post-step
  world tick and fixed endpoint without a synthetic interpolation alpha; it updates the retained
  display items in place and creates no generated ECS rows. Opcode 30 hides only those copies, not
  the real prototype.
- Optional **Glow by distance** is implemented across child authoring, desktop reference preview,
  KCPR packing/inspection, native parsing, CPU fallback and Direct/LUT GLES paths for Ring, Spiral,
  Polar Field and Burst. Start zero maps to the Movement profile's clamped explicit core. Each
  instance combines a bounded smooth log-radius pulse with a seeded 12-bit material phase. The field
  changes lighting only and creates no ECS or placement record.
- KCPR v3 is emitted only when a Glow modifier is present. No-Glow legacy v1 and Burst v2 assets keep
  byte-identical output. The 128-byte recipe does not grow: its last 12 formerly reserved bytes store
  three canonical binary32 Glow lanes. The controlled 128-display Burst+Glow sidecar is 288 bytes with
  eight operator meanings. Enabling Glow preserves spatial lineage/prefix while changing the full
  content address. Native visible-instance staging adds one 32-bit phase attribute, growing from 32
  to 36 bytes; it does not serialize per-copy transforms or phases.
- Shared LUT samples existing UGLUT2 direction, Direct uses cosine, and CPU fallback/reference uses
  the quantized UGLUT2 result. Lighting adds the bounded field as `base colour × field`; alpha and the
  final Bayer pass are unchanged. Burst has separate prototype and generated-copy draw groups so its
  local displacement is not applied to the prototype. Copies sample local packed rho before anchor
  composition, while the prototype samples its own packed rho; no Cartesian-distance reconstruction
  is substituted. `RUN_POLAR_GLOW_LAB.cmd` generates the project if absent, then opens a 128-display
  Burst/LUT/subtle-Bayer manual scene at Glow distance 0–4 and strength 1.25.
- Native KCPR load reconstructs the Glow interval and validates it against the profile-clamped core
  and `rhoMax`. Startup telemetry exposes `format_version`, `glow_recipes`, `glow_instances` and
  `gpu_instance_stride_bytes=36` for fail-closed later device proof. Those counters are implemented
  evidence hooks, not a claim that the current Glow path has run on POCO/Mali.
- Optional **Grow glowing copies** is implemented as KCPR v4 in current source. It reuses the exact
  Glow sample as a bounded 1x..5x multiplier after generated ordinary/Burst scale; index-zero
  prototypes remain Glow-lit but keep authored ECS/collider/picking scale. Slot 12 / code `0x0053`
  adds no parameter lane, LUT, texture, instance byte or ECS row. The recipe remains 128 bytes and
  GPU visible instances remain 36 bytes; v1-v3 bytes and spatial lineage are preserved.
- `RUN_POLAR_GROW_LAB.cmd` generated and smoke-opened its separate 128-display Burst/LUT/subtle-Bayer
  manual project. The provenance-marked JSON is 21,694 bytes with SHA-256
  `ED7AFDB2775E2C6C308CA03066B3480000F98D18AE4072275F50D0576B502719`; its nine-operator KCPR v4 is
  304 bytes, SHA-256 `2D04A3788D2A472F65EA0F53573325B6F680F6D73190A229573926748657ADDF`.
- The exact Grow handoff is preserved under
  `build/release-handoff/20260830T023441Z-polar-grow`. Its ARM64-only, v2-signed,
  zip-aligned APK is **1,819,202 bytes**, SHA-256
  `E5348442B3B9E313D10EAD1AFB636ACFA9943CD11F415226F6EA5D255B50232C`.
  It was installed and launched on Poco `2412DPC0AG` / `rodin`. Runtime
  telemetry proved effective shared-LUT mode, KCPR v4, 128 GPU instances, 127
  generated/grown copies, zero CPU fallbacks, 36-byte stride, final Subtle
  Bayer and `ecs_generated=false`.
- Its 30-second physical profile measured **120.33 FPS** at 120 Hz,
  p50/p95/p99 **8.380/10.113/11.295 ms**, PSS 143,165–148,551 KiB, mean CPU
  8.313% of total eight-core capacity, exposed GPU temperature
  41.897–46.710 °C, thermal status 0 and no crash/profile warning. A sequential
  Glow-v3 control also measured 120.33 FPS and 10.041-ms p95; the 0.072-ms p95
  difference is too small and under-sampled for a causal overhead claim. The
  driver exposed no usable GPU timer query, so GPU-only milliseconds and power
  remain unmeasured.
- The exact 128-display Burst/Glow handoff is preserved under
  `build/release-handoff/20260830T012054Z-polar-glow`. Its ARM64-only, v2-signed, zip-aligned APK is
  **1,817,430 bytes**, SHA-256
  `17B3DAE3C4479B1BD09D335ACE551A9414BFD3BACB97BC1C976FA6E5E9C801F4`, application ID
  `org.ugts.games.packed_polar_recipe_lab_3d.pocox7pro`, min/target SDK 26/36. It embeds the exact
  1,690-byte KCPK, 288-byte KCPR v3, 32-byte KCRP and five inspected shaders without authoring JSON.
  Its original handoff evidence status is `built_only`; the exact APK was later
  installed as the same-phone 30-second Glow-v3 control, with that profile
  preserved in the Grow handoff folder.
- The separate fail-closed Glow matrix is defined by
  `python validation/benchmark_polar_render_poco.py --workload glow --include-cpu --build-only`:
  64/256/1,024 Ring displays, Direct/LUT with Bayer Off/Subtle, plus CPU fallback with Bayer Off.
  No physical matrix run is claimed.
- The corresponding Grow definition is
  `python validation/benchmark_polar_render_poco.py --workload grow --include-cpu --build-only`.
  It rejects builds without exact v4/operator/mask/one-ECS proof and rejects runtime logs without
  one Grow recipe, `count - 1` grown copies, `count` Glow samples, stride 36 and unchanged batches.
  No physical Grow matrix run is claimed.
- Burst core plus legacy recipe checks passed **32 tests and 25 subtests**; the related Python/editor/
  conformance set passed **57 tests and 102 subtests**. Native exact-vector execution passed
  **1 test and 2 subtests** across legacy and both Burst fixtures at ticks 0/1/4/7/8; the focused
  native wiring/render/conformance set passed **10 tests and 23 subtests**. The ARM64 native CMake
  target also built successfully. The two controlled 240-byte KCPR v2 assets have SHA-256
  `2F6717F35D90033A8476EAC20E74A625FE6DD74CF39B159172BBC7ED6A6BF807` (profile-core start) and
  `F9BF55A78D94EDFBE6731FE886F1A1EE1F6AC85DB70CB157C489BF18F8D3ECBD` (positive start).
- The separate Burst build matrix is defined as 32/128/384 × CPU/Direct/LUT × Bayer Off/subtle,
  for 18 cases:

  ```powershell
  python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only
  ```

  The preserved `built_only` run at
  `build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de` completed 18/18 in
  272 seconds. Every case records a 1,690-byte KCPK, 240-byte KCPR and 32-byte KCRP; APK sizes range
  from 1,804,558 to 1,804,566 bytes. None was installed or run through GLES/Mali, so no startup log,
  visual parity or physical POCO performance result is claimed.
- The final Grow-integrated complete-source checkpoint passed **763 tests and 305 subtests** in
  **238.71 seconds**. Focused integration passed **48 tests and 62 subtests**;
  targeted Ruff and independent re-review are green. The earlier Glow checkpoint passed **752 tests and 291 subtests** in
  203.32 seconds with zero failures or skips. The first run exposed one stale shader-source assertion
  that still expected the pre-Glow ordinary-node call; the assertion was updated to require the Glow
  uniform/call/reset wiring, its focused rerun passed, and the complete suite then passed. The prior
  Burst-only checkpoint remains **739 tests and 252 subtests** in 274.18 seconds. Repository-wide
  Ruff still reports 895 pre-existing legacy violations across 31 files.
- Desktop optional 3D components now have one world-owned sparse-pool authority behind each spawned
  entity's live dict-compatible `MutableMapping`. Cached query plans canonicalize/deduplicate the
  requested component set, select the smallest live sparse pool, apply mutable tags/alive/active at
  execution time, and preserve lexicographic IDs. `polar_movement` aliases packed membership;
  project JSON, snapshots and state hashes are unchanged. Built-in fields remain in the monolithic
  compatibility record, and tag/spatial/graph-binding/render-batch indexes remain open work.
- Recorded green evidence: the broad graph slice passed **141 tests and 53 subtests**; the combined
  semantic-movement/ECS/hierarchy/animation selection passed **139 tests and 47 subtests**; the
  wider sparse-query regression passed **152 tests and 60 subtests**, including all **4** new focused
  query-plan tests. Targeted Ruff and Python compilation pass. These are source/host parity results,
  not new physical-device or performance evidence.
- The opt-in desktop **Device Look (reference)** keeps CPU UGLUT2 composition and applies the
  packaged native Bayer shader in a QOpenGLWidget. Its active badge explicitly says CPU LUT, Off is
  unchanged raster, and every GL/settings failure has a visible raster fallback. Formula/source/
  fallback and adjacent render coverage passed **50 tests and 66 subtests**; a live Windows check
  ran the shared shader at a 959 x 629 physical framebuffer without failure. This is not the Android
  GPU polar path or POCO performance evidence.
- The checked-in packed-polar lab now uses opcodes 28/29. A fresh v2-signed Poco debug APK is
  **1,804,539 bytes**, SHA-256
  `78A195491B8D46D6946EA3B8C08FB86B3452B66D02105DD7F9A2D8AA51F386B9`, with a 752-byte KCVG,
  3,202-byte KCPK, and 32-byte KCRP. It is preserved under
  `build/op29-poco-build-20260830T005625`; ADB exposed no device, so it remains built-only.

## Verified in current source on 29 August 2026

- Focused multi-clip/PBR-lite registry/runtime, compact-pack, retained-browser, native-host/Android,
  shader, editor and First Steps checks pass, along with targeted Ruff. The full suite is green:
  596 passed, 135 subtests passed in 127.49s.
- The built-in vocabulary now contains 27 blocks: the existing 25-block portable desktop/web/native
  core plus two Mobile 3D-only animation actions. **When Timer Rings** is append-only `KCVG001`
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
- Mobile 3D Appearance exposes Matte, Toy Plastic, Metal and Crystal Glow as presentation-only
  **Material Look** choices. They preserve colour/double-sided state, safely clone a shared authored
  material for only the selected prototype, retain its population copies, and use one save-safe Undo
  command. Desktop and GLES share the compact PBR-lite surface calculation; Android retains its
  presentation-only emissive pulse. The KC3D392 material payload remains fixed at 40 bytes after id.
- Mobile 3D **Saved Objects** store at most 64 validated single-node definitions in authoring
  metadata. Save, place and remove are atomic Undo operations; removing a definition keeps placed
  nodes. An unused definition adds no KC3D/KCVG/KCPK/KCSP record, while a placed copy is one ordinary
  flat node with shared resources and shared Logic Block bytecode. Player, packed-Movement,
  Populate Area and literal-self graph hazards are rejected. Mesh/collider footprint checks choose a
  deterministic free starting position, and material copy-on-write treats definitions as consumers
  so later look edits do not mutate the saved snapshot.
- Mobile 3D **Saved Scenes** store up to 64 static parent-local objects per definition and up to 256
  linked placements as one stable ID plus one group transform each. Save Together, place and Unlink
  are atomic Undo/Redo operations. The pure materializer produces one canonical flat order for
  validation, desktop ECS, KC3D/KCVG/KCPK/KCSP/KCAN, packed ECS, glTF and Android, with internal graph
  references and leaf Animation keys remapped per placement. Android materializes once and reports
  separate authoring/runtime hashes. Nested scenes, runtime-moving parents, shear, definition edit
  mode and per-instance child overrides are explicitly rejected or not claimed.
- Ordinary Mobile 3D nodes now support the separate retained display-transform hierarchy. Source
  validation covers missing parents, cycles, the maximum eight parent edges, uniform-positive parent
  scale, `hierarchy.parent_graph_scale` rejection of unprovable graph writes and every display-only
  child restriction. The dark Scene Tree nests children and its
  **Attach to…** / **Detach** operations preserve world pose through Undo/Redo; the Inspector exposes
  local values while the viewport/gizmo stay world-space. Desktop ECS publishes child world poses in
  the final late phase, and static glTF retains the parent/child nodes.
- The focused hierarchy core/editor/native/example run is green: 30 passed and 10 subtests passed in
  14.67 seconds.
- `parent_child_hierarchy_3d` verifies a moving/spinning root, two children and one grandchild. Its
  1,633-byte KC3D has SHA-256
  `D61049E17F196DF928D1E5A8387E22C7DF63E33932C756DD6629FD4D28A86BB9`; its optional 48-byte,
  three-link KCHI has SHA-256
  `2439348374214AABEE889C5D5BE1998755C6958037D95CFD0F59E2DF97C8F23F`; and its deterministic
  64-step state hash is `ED2847B48F67128774F9A5664BE3259A2FBE67CC066D25AF61AA4A42C65298CB`.
  The normalized project-content SHA-256 is
  `201AC0C62FD761FA65C2F72ABD7AEB9F5B7EF806210679812EF882CF1768D8A4`.
  Generated KC3D/KCHI host-native coverage compiles the Android `transform_hierarchy.cpp`, exercises
  a three-edge chain plus malformed packs, and confirms that flat projects omit `hierarchies.kchi`.
  The locally built `build/UGTS-Parent-Child-Hierarchy-3.9.2-Poco-X7-Pro-debug.apk` is 1,565,171
  bytes with SHA-256 `813D290E2B89973FE4C429BF58FAD7F50BFB156C42EACB665A7ABB1B4BF36E20`.
  Inspection verifies package `org.ugts.games.parent_child_hierarchy_3d.pocox7pro`, SDK 26/36,
  GLES 3, ARM64-only native code, v2 debug signing, 4-byte/16 KiB alignment, 11 entries and no
  authoring `project.json`. Authorized serial `XOVSTSHYNREMZ5D6` (`2412DPC0AG` / `rodin_eea`)
  installed it and cold-launched with status OK in 448 ms; PID 25992 was resumed, visible and
  fullscreen. Runtime logs selected Mali-G720 MC7, `poco_x7_pro_12gb`, `grove_g720_mc7_120`, balanced
  quality, 60 fps and render scale 1.00. The 15-second/five-sample read-only profile observed 630
  SurfaceFlinger intervals at 120.15 effective FPS with 8.376/9.959/10.473 ms p50/p95/p99 and zero
  intervals over 1.5 vsync. PSS was 141,406–146,004 KiB, RSS 261,218–267,114 KiB, reported GPU
  temperature 45.691–51.585 °C, battery 55% / 33.7 °C unchanged, thermal status 0, crash lines 0
  and warnings empty. A short process-CPU sample read 48.1–56.0% on Android's one-core scale across
  an eight-core device. The capture is
  `build/device-qa-hierarchy-poco-20260829/profile-15s.json`; `hierarchy-running.png` confirms one
  rendered frame. This is only five nodes and roughly 60 submitted triangles, not a motion-heavy,
  large-game/AAA or sustained-thermal result.
- Native Android now advances ordinary untagged dynamic ECS nodes rather than only the Player.
  `body_physics.cpp` performs generic gravity/integration, floor and X/Z bounds response, plus
  deterministic object-ID-sorted solid-pair resolution after Logic Blocks. The authored
  `dynamic_crate_parity_3d` Ready graph pushes its mass-1.5 crate to an exact X `1.375` after 600
  `1/64`-second host-native steps while Player remains untouched; all seven position/velocity bit
  checkpoints match the Python golden. The acceptance consumes the real
  generated 1,457-byte KC3D and 137-byte KCVG and the arm64 NDK r29 build compiles/links the same
  module. Player still has a special controller, and native contact events/grounded state are not
  claimed.
- The bottom Mobile 3D **Animation** dock authors up to 16 named relative transform clips per eligible
  static node. New/Duplicate/Rename/Delete, one optional autoplay selection, whole-pose keys,
  scrub/play, Once/Repeat/Back and forth and nine child-readable Arrival modes round-trip through
  save/load; authoring edits are atomic Undo/Redo while selection and scrubbing remain non-serializing
  viewport state. **Play an Animation** / **Stop an Animation** Logic Blocks provide named selection,
  restart/resume, hold and reset semantics in desktop and native. Exact KCAN v1 remains available for
  legacy one-clip metadata; library data selects KCAN v2 with stable clip hashes and autoplay flags.
  Both share binary32 duration, unsigned-16 time, binary16 relative transforms and shortest-path
  normalized quaternion interpolation. The optional sidecar is omitted when unused; the retained
  two-key v1 fixture is 88 bytes. The `/W4 /permissive-` native host harness covers malformed packs,
  both KCAN versions, multi-clip control, graph actions, all easings, loops and inactive clocks. The
  244,747-byte Windows GUI capture
  `build/ugts-studio-animation-timeline-windows-20260829.png` has SHA-256
  `270917AC0000E4ED2E31332F20E4566AB8F2762ADE4A50F5D7FB0E2B5B45A606` and shows the authored
  half-second pose without changing source transforms.
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
- The same source emits a 914-byte packed polar kinematics asset with SHA-256
  `8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313` and a 60-byte `KCSP392`
  asset with SHA-256 `E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`, representing a recipe
  for one authored crystal plus 17 deterministic render-only copies. The three compact sidecars total
  2,239 bytes.
- Native touch routing keeps left/right roles by pointer ID, so holding movement while tapping dash
  remains independent of Android pointer-array order. Cancel, drag-not-tap, look and pinch paths are
  covered by the host harness.
- The current PBR-lite/opcode-25/animation-runtime APK is locally built and inspected at 1,484,357
  bytes with SHA-256 `B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`. The canonical
  `Poco-X7-Pro-debug` and explicit `pbr-lite-op25-debug` paths are byte-identical.
  Package/version/SDK/GLES, ARM64-only native code, linked shaders, debug-certificate v2 signing and
  unchanged embedded KCVG/KCPK/KCSP assets verify. The native library contains the KCAN filename,
  magic and final scale-safety checks; the unanimated starter correctly emits no KCAN asset. The Poco
  is absent from ADB, so no install, launch, installed-byte hash match or profile is claimed for this
  `B9B1…` build.
- `build/UGTS-Animation-Timeline-3.9.2-Poco-X7-Pro-debug.apk` is 1,483,820 bytes with SHA-256
  `43D197ECF62F73349859FFED9D167BCA64BBFA092A6080BC03151E8B8F5B4E0F`. It is v2-signed,
  ARM64-only, package `org.ugts.games.animation_timeline_demo.pocox7pro`, and contains an 88-byte
  `transform_animations.kcan` with SHA-256
  `2CEEF27205A1EEF140BB5BC03A519A00F2628D81B0D40DFD73555F91FCEE6FE2`: one binding, two keys and
  a two-second ping-pong goal clip. It is locally built/inspected only; ADB had no connected device.
- `build/UGTS-Multi-Clip-3.9.2-Poco-X7-Pro-debug.apk` is the current graph-controlled animation
  fixture: 1,504,091 bytes with SHA-256
  `94FD4CB4AD9C166F3E73EB8F0E66A68F5124781CD92E30AE4E31C01C2D37EA89`. It is v2-signed,
  ARM64-only, GLES 3, min-SDK 26/target-SDK 36, and contains a 240-byte KCAN v2 with two clips/seven
  keys plus a 191-byte KCVG with opcodes 26/27. It is locally built/inspected only because ADB had
  no connected device.
- `build/UGTS-Saved-Scenes-3.9.2-Poco-X7-Pro-debug.apk` is the linked-group acceptance fixture:
  1,505,487 bytes with SHA-256
  `70FD18B26DB7D41167E32EBD27088DC02474479F240B6A5DBF2654A6B36ED291`. `aapt`, `apksigner` and
  `zipalign` verify package `org.ugts.games.linked_saved_scenes_3d.pocox7pro`, version 392,
  min/target/compile SDK 26/36/36, GLES 3, ARM64-only native code, v2 debug signing and 16 KiB native
  alignment. Its 3,126-byte KC3D, 577-byte KCVG, 312-byte KCAN, 132-byte KCSP and 532-byte KCPK
  byte-match the verifier. Four ordinary nodes plus one stored three-node definition and three
  transform-only descriptors materialize to 13 ECS nodes and nine render-only scatter copies.
  Authoring JSON is not packaged. ADB had no connected device, so no install/launch/profile claim is
  made for this artifact.
- `build/UGTS-Dynamic-Crate-3.9.2-Poco-X7-Pro-debug.apk` is the generic-body acceptance fixture:
  1,531,353 bytes with SHA-256
  `AE8B5C6AE97E08E9380EEBE30087AF26575C495B17F23351532EB1AA666E68DD`. Android build-tools verify
  package `org.ugts.games.dynamic_crate_parity_3d.pocox7pro`, version 392, min/target/compile SDK
  26/36/36, GLES 3, ARM64-only native code, v2 debug signing and 16 KiB native alignment. Its
  1,457-byte KC3D and 137-byte KCVG exactly match the standalone verifier and authoring JSON is absent
  from the APK. With no ADB device attached, install, launch and phone performance are not claimed.
- The preceding local post-audit snapshot remains at `message-op25-debug` and
  `message-op25-audit-fixed-debug`: 1,451,149 bytes, SHA-256
  `1003F0617F247C9F0C1E7269F8F15F462AAD7F4E81E2409CF4B091622F3CA922`, without device evidence.
- The most recent pre-hierarchy Python wheel is 460,901 bytes with SHA-256
  `99199CF741343D9760375520256B133E0C3E21DBAABC1F5201EFCAE02D27A0D7`; the source archive is
  521,862 bytes with SHA-256 `9F36075D7601F4588FAFCAB151DAA8F7511F7BFF5F0CD9AB499F6A8F28BBC5EA`.
  Both install into separate clean virtual environments, import the animation adapter/pack/timeline,
  expose the `ugts-studio` GUI entry point, contain the final native KCAN plus generic-body
  source/CMake/Engine wiring and export deterministic KCAN v1/v2 animation assets. The installed
  wheel generated a 53-file Android source tree with `body_physics.cpp/.hpp` and the integration call.
  The installed editor's unsaved-project root is `Documents/UGTS Studio`, not Python's protected
  `Lib` directory. These exact hashes predate KCHI/retained-hierarchy source and must not be cited as
  distribution evidence for that later slice; replacement packages are still required.
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

The PBR-lite canonical First Steps APK is locally built, inspected and hash-identified, but still has
no device run for that exact artifact. The exact pre-audit FBCB APK has its successful install, cold
launch, pulled-byte hash match and 30-second Poco profile. The newer hierarchy APK now has the exact
install/cold-launch and tiny-scene 15-second profile above. None of these short profiles is a general
device guarantee. A first post-audit First Steps install/hash/profile, interaction-heavy hierarchy
motion capture, unplugged battery drain, long-duration thermal equilibrium, explicit 60/90 Hz
fallback behavior and representative lower-tier hardware remain open. No exact Glow-by-distance APK
has yet established POCO/Mali visual parity, timing, frame rate, power or thermal behavior.

UGTS is also not yet a complete Godot-like engine. The current editor, ECS, typed graphs, Saved
Objects v1, linked static Saved Scenes, bounded display-transform hierarchies and rigid-transform clip
libraries, generic native bodies and native GLES path are useful working slices, but a general
gameplay/physics scene graph, live Saved Scene definition editing/overrides, GLB/skeletal animation,
retargeting, crossfades/layered blending, animation-state-machine authoring, unified Player physics,
native contact events, richer physics/content pipelines, production signing/distribution and Vulkan
remain incomplete.
