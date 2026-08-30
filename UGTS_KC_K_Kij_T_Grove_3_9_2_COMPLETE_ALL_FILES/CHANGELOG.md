# Changelog

## 3.9.2 — K-Kij-T / Grove

### Added

- Mobile 3D **Saved Objects** capture one safe flat object into authoring metadata, append ordinary
  deterministic ECS copies through **+ Saved Object…**, and remove library entries without deleting
  placed nodes. Save/place/remove are one Undo step each; resources and Logic Block bytecode stay
  shared, unused definitions add no native pack records, and unsafe Player/packed-motion/population/
  literal-self cases are rejected.
- Mobile 3D **Saved Scenes** capture bounded static multi-object groups as parent-local ECS snapshots,
  store each linked placement as one group transform, and materialize deterministic ordinary nodes
  for desktop, packed ECS, glTF and all native Android sidecars. **Save Together**, **+ Saved Scene…**
  and **Unlink** are atomic Undo/Redo operations. Internal graph references and leaf animations remap
  per instance without adding a native prefab ABI; nested scenes and runtime-moving parents remain
  outside the linked Saved Scene contract.
- Ordinary Mobile 3D nodes gain a bounded retained display-transform hierarchy. The dark Scene Tree
  nests attached rows and offers contextual **Attach to…** / **Detach** actions that preserve world
  pose and use one Undo/Redo edit. The Inspector shows child values as **Transform inside …**, while
  the viewport and translation gizmo remain world-space. Chains allow at most eight parent edges;
  children must be static, tagless, non-colliding/non-sensor display objects with zero spin and no
  Logic Blocks, Movement Pattern, Populate Area or Transform Animation. A moving root may carry the
  branch; attached intermediate parents move only through inherited composition. Parent scales must
  remain positive and uniform; `hierarchy.parent_graph_scale` rejects per-axis, dynamic or otherwise
  unprovable Logic Block scale writes to parents while allowing a complete saved uniform-positive XYZ.
- Desktop ECS recomposes retained children in the final late phase, native C++ recomposes them after
  Ready and every fixed-step transform writer, and static glTF preserves parent/child nodes. Android
  emits optional sparse `hierarchies.kchi` (`KCHI392`) data with a 24-byte header and one 8-byte
  child/parent index link; flat projects emit no sidecar. The checked-in
  `parent_child_hierarchy_3d` example verifies local/world poses, two-level following, KC3D/KCHI,
  glTF children and deterministic repetition. Its inspected ARM64/GLES 3 Poco APK installs and
  cold-launches on `2412DPC0AG` / `rodin_eea`; a bounded 15-second profile observes 120.15 effective
  FPS with 9.959 ms p95, thermal status 0 and no crashes/warnings. The scene is only five nodes and
  roughly 60 submitted triangles, so this is not a large-game/AAA or sustained-thermal result.
- Native Android generic body physics now advances every live, active ordinary dynamic node after
  Logic Blocks, with floor/XZ-bounds response and deterministic ID-sorted solid-pair impulses. The
  `dynamic_crate_parity_3d` acceptance consumes real KC3D/KCVG in C++, runs an untagged crate's Ready
  → Apply Force graph for 600 steps and reaches the exact binary32-friendly endpoint. Player remains
  on its legacy controller and native contact events/grounded state remain future work.
- UGTS Studio now defaults to a near-black/navy viewport-first theme with higher-contrast selection,
  cyan/amber accents, compact Play/Build/Deploy controls, tabbed Scene Tree/Resources and contextual
  docks that stay closed until their workflow needs them.
- The bottom Mobile 3D **Animation** dock authors up to 16 named relative transform clips per eligible
  static node. It provides a child-readable clip chooser plus New/Duplicate/Rename/Delete, one optional
  autoplay clip, whole-pose keys, nondestructive scrub/playback, Once/Repeat/Back and forth, a protected
  starting-pose key and atomic Undo/Redo for every authored library change. Stable clip IDs survive label
  renames; the GUI and runtimes expose the same nine easing modes with child-readable Arrival labels.
- Optional sparse `transform_animations.kcan` (`KCAN392`) keeps byte-exact version-1 output for legacy
  one-clip projects: one 24-byte header, 16-byte node binding and 24-byte key. Library projects use
  version 2 with a 24-byte `(node, clip hash, duration, key range, loop, autoplay)` binding and the same
  24-byte keys. Desktop ECS and native C++ share quantization, loop/easing and shortest-path quaternion
  behavior; unused projects emit no asset.
- Mobile 3D Logic Blocks add append-only native opcodes 26 **Play Animation** and 27 **Stop Animation**.
  They choose the object, stable clip ID and restart/reset behavior, compose time zero immediately, and
  report missing targets or clips precisely. State-machine, crossfade, skeletal and glTF animation
  authoring remain explicit future work.
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
  two unsigned 64-bit packed polar words per moving node; dynamic nodes are guarded from conflicting
  transform ownership.
- Trigger areas use matching desktop/native scale-aware sphere/box overlap without collision impulse,
  with explicit sensor and per-step native graph-dispatch caps.
- Populate Area rejects dynamic/moving, collider/Trigger Area, gameplay-tagged, Logic Block and
  Movement Pattern prototypes. Copies are render-only, the desktop view caps generated copies at 64
  per group and 256 globally, and browser Mobile 3D, overlap avoidance, per-copy frustum culling and
  LOD remain explicit non-features.
- Adds a child-facing Mobile 3D **Material Look** chooser with Matte, Toy Plastic, Metal and Crystal
  Glow. Presets preserve colour/double-sided state, clone shared authored materials without splitting
  a prototype from its Populate Area copies, and undo/redo as one save-safe command. Preset names are
  presentation-only and add no serialized field or KC3D392 bytes.
- Replaces the flat Mobile 3D preview light with a compact multiply-only PBR-lite response shared by
  desktop Preview and native GLES. Existing base colour, metallic, roughness, emissive and
  double-sided fields remain the complete fixed material payload; full texture/IBL PBR is not claimed.
- Android export also rejects mutations aimed at frozen population prototypes from other-object or
  world graphs, and rounds authored transforms to the native binary32 schedule before scatter math.
  GLES startup now fails closed after any EGL/shader error, and nonuniformly scaled instances use an
  inverse-transpose normal matrix.
- Focused multi-clip/PBR-lite desktop, browser, compact-pack, editor, shader and native-host checks pass,
  along with targeted Ruff; the fresh Glow-integrated full suite is green: 752 tests and 291 subtests
  in 203.32 seconds.
  First Steps emits a
  1,265-byte `KCVG001` pack with SHA-256
  `363EED6B1054CE0809F57FDF934755670F40D1273EEC92BA3720CC7B9E80BB3B`, alongside the unchanged
  914-byte `KCPK392` (`8A45DDBF874D918CEDAEB0161E80FEF3314C2C2B0B21A45DA90E22A18C4DD313`) and 60-byte
  `KCSP392` (`E95BDE225571AB5F6EAC3B9C04CB1BD332A0C95C740B377AC2DEE30460DD2FD1`), 2,239 bytes combined.
  Fresh idle execution has state SHA-256
  `a1256e5e78e621f8a4ca75b896797ec4d96fbfce06d67b0e912359b3dc273b24`; the dash/message path sets
  `heard_message=true` and `score=1`.
- The current PBR-lite/opcode-25/animation-runtime APK is locally built and inspected at 1,484,357
  bytes with SHA-256 `B9B1A9A1E722C5B0D0DAA6DE3634E605E16D7903BA14626B4F99B58154918497`. The canonical
  `Poco-X7-Pro-debug` and explicit `pbr-lite-op25-debug` paths are byte-identical;
  package/version/SDK/GLES, ARM64-only native code, linked shaders, debug-certificate v2 signing and
  unchanged embedded KCVG/KCPK/KCSP assets verify; the native library contains KCAN runtime markers
  while the unanimated starter omits the optional asset. The Poco is absent from ADB, so no install,
  launch or profile is claimed for this `B9B1…` build. The preceding local `message-op25` and
  `message-op25-audit-fixed` snapshot remains 1,451,149 bytes / `1003F061…`, also without device evidence.
- The animation-bearing demo APK is 1,483,820 bytes with SHA-256
  `43D197ECF62F73349859FFED9D167BCA64BBFA092A6080BC03151E8B8F5B4E0F`; its 88-byte KCAN contains
  one binding and two ping-pong keys. It is locally inspected only.
- The graph-controlled multi-clip Poco demo APK is
  `build/UGTS-Multi-Clip-3.9.2-Poco-X7-Pro-debug.apk`: 1,504,091 bytes with SHA-256
  `94FD4CB4AD9C166F3E73EB8F0E66A68F5124781CD92E30AE4E31C01C2D37EA89`. It is an ARM64-only,
  GLES 3, min-SDK 26/target-SDK 36 debug build signed with APK Signature Scheme v2. Its 240-byte KCAN
  v2 contains two clips and seven keys; its 191-byte KCVG contains Play/Stop opcodes 26/27. It is
  locally built and inspected only because no ADB device was attached for installation.
- The linked Saved Scene Poco acceptance APK is
  `build/UGTS-Saved-Scenes-3.9.2-Poco-X7-Pro-debug.apk`: 1,505,487 bytes with SHA-256
  `70FD18B26DB7D41167E32EBD27088DC02474479F240B6A5DBF2654A6B36ED291`. It is v2-signed,
  ARM64-only/GLES 3 and its KC3D/KCVG/KCAN/KCSP/KCPK assets byte-match the deterministic example
  verifier. No phone was attached, so this is a local build/inspection claim only.
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

## 2026-08-30 — Semantic Movement and sparse ECS query update

- The Mobile 3D/native Logic Blocks registry now contains 29 blocks while the portable
  desktop/retained-web/native subset remains 25. Append-only opcodes 28 **Read Movement** and 29
  **Change Movement** hardcode virtual `polar_movement` and expose only an entity, one of seven
  friendly numeric fields, and fallback/value. Python/native packed-word and transform parity is
  covered; browser export rejects both as Mobile-3D-only. The fixed four-node KCVG is 239 bytes/eight
  inputs versus 268 bytes/ten inputs for generic component access, with no `polar_movement` string.
- Optional desktop `GameWorld3D` components now live in world-owned sparse pools behind a live
  dict-compatible `MutableMapping`. Cached canonical plans choose the smallest required sparse pool,
  retain live tag/alive/active filtering and lexicographic order, and map virtual
  `polar_movement` membership to packed movement. Saved project JSON, snapshots and hashes are
  unchanged. Built-in record/archetype migration and tag/spatial/graph-binding/render-batch indexes
  remain open.
- Recorded checks are green: broad graph **141 tests + 53 subtests**; combined
  movement/ECS/hierarchy/animation **139 + 47**; wider sparse-query scope **152 + 60**, including all
  **4** focused query-plan tests; targeted Ruff and Python compilation pass.
- Added the opt-in desktop **Device Look (reference)** viewport. It visibly identifies CPU UGLUT2
  composition plus the packaged native Bayer shader, preserves exact raster output when Off, and
  falls back safely when OpenGL/settings fail. The post includes editor grid/gizmos and makes no
  Android GPU or performance-parity claim. Focused and adjacent coverage passed **50 tests + 66
  subtests**; a live Windows GL pass succeeded at a 959 x 629 physical framebuffer.
- The checked-in packed-polar lab now uses dedicated opcodes 28/29. Its 64-binding KCVG is 752 bytes
  instead of 781 through generic component blocks. A fresh 1,804,539-byte v2-signed Poco debug APK
  with SHA-256 `78A195491B8D46D6946EA3B8C08FB86B3452B66D02105DD7F9A2D8AA51F386B9`
  is preserved with built-only evidence; ADB exposed no device for install or profiling.

## 2026-08-30 — Live Make Many control

- Added append-only opcode 30 **Show or Hide Extra Copies**. The Mobile 3D/native registry now has
  30 blocks while the portable desktop/web/native subset remains 25. Its literal target chooser
  lists only authored Make Many prototypes and is hidden in 2D; browser export rejects it explicitly.
- One ephemeral runtime bit per recipe, stored as a fixed eight-byte project mask on native, gates
  generated display copies without changing the real ECS object, KCPR/KCPK, content addresses,
  snapshots, hashes or deterministic prefix. CPU, Direct and LUT rendering skip a hidden recipe
  before materialization and visible-budget consumption.
- A frozen Ready-plus-action KCVG is 121 bytes, SHA-256
  `DCA7CF42A184CE9F50C0B90646756A90ED4E782EA8EB2697553525880B4E529C`, exactly 29 bytes above its
  Ready-only baseline. Focused desktop verification passed **6 tests + 2 subtests**; the broader
  graph/pack/editor/web/population selection passed **137 + 74** and Mobile ECS/Saved Scene/
  animation regressions passed **33 + 8**. Native host/VM suites and the ARM64 NDK build passed.

## 2026-08-30 — Radial Burst (loops)

- Added bounded **Make Many → Radial Burst (loops)** around one real packed ECS prototype. Generated
  copies remain display-only. Their local packed displacement compounds with the prototype anchor
  through log-encoded polar LUT semantics; the effect loops and is not a one-shot gameplay event.
- Preserved byte-identical KCPR v1 output and prior golden hashes for legacy-only Ring, Spiral and
  Polar Field recipes. With Glow disabled, KCPR v2 is emitted only when Burst exists. Each controlled
  standalone Burst sidecar is 240 bytes: a 32-byte header, five 16-byte operator meanings and one
  128-byte recipe.
- Added child-readable Burst controls and an in-place desktop preview. Stopped authoring shows the
  deterministic midpoint; Play uses the real post-step fixed world tick and presents its fixed
  endpoint without a synthetic interpolation alpha. Opcode 30 still hides copies only.
- Enforced 512 instances per Burst recipe, 16 Burst recipes and 2,048 Burst instances per project.
  The editor retains at most 64 generated preview items globally; native materialization also obeys
  maximum-visible and the remaining particle budget. Direct is the baseline packed reconstruction,
  LUT shares the profile texture, and Bayer remains the final presentation pass.
- Added Python/editor/native-host parity vectors and completed an ARM64 native CMake build. The
  18-case 32/128/384 × CPU/Direct/LUT × Bayer Off/subtle build-only matrix completed via
  `python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only`.
  Its preserved 18/18 run contains 1,690-byte KCPK, 240-byte KCPR and 32-byte KCRP assets, with APKs
  from 1,804,558 to 1,804,566 bytes. None was installed or executed through POCO/Mali, so no visual
  or device-performance result is claimed.

## 2026-08-30 — Log-radius Glow by distance

- Added optional **Make Many → Glow by distance** authoring for Ring, Spiral, Polar Field and Radial
  Burst. Start/End distance and strength define a bounded smooth pulse in the packed Movement
  profile's log-radius chart. Start zero maps to the explicit clamped core without evaluating
  `log(0)`. The modifier changes material presentation only: it adds no ECS rows, colliders, graph
  owners or placement changes.
- KCPR v3 is emitted only when at least one Glow-by-distance modifier is enabled. No-Glow Ring,
  Spiral and Polar Field keep byte-identical v1 output, and no-Glow Burst keeps byte-identical v2
  output. The fixed recipe record remains 128 bytes: v3 reuses its final 12 reserved bytes for
  binary32 center-rho, inverse half-width and strength. The controlled 128-display Burst+Glow fixture is
  288 bytes—32-byte header, eight 16-byte operator meanings and one 128-byte recipe.
- Glow keeps the old spatial lineage namespace and derives a count-independent 12-bit material phase
  from random-access lineage lane 5. Only visible native GPU staging grows, from 32 to 36 bytes per
  polar instance, by storing that phase in one 32-bit integer attribute; no per-copy phase or
  transform record is serialized.
- Shared LUT samples the existing UGLUT2 direction, Direct uses matching cosine, and CPU fallback and
  desktop reference evaluate the quantized UGLUT2 path rather than omitting the effect. The bounded
  field is added to scene lighting as `base colour × field`; alpha is untouched and the existing
  final Bayer pass remains downstream and unchanged. Burst deliberately uses separate prototype and
  generated-copy draw groups because only the latter applies the local Burst displacement. Each copy
  samples its local packed rho before anchor composition; the prototype samples its own packed rho,
  with no Cartesian-distance reconstruction.
- Added `RUN_POLAR_GLOW_LAB.cmd` as the one-click manual route to a generated 128-display Burst/LUT/
  subtle-Bayer project with Glow distance 0–4 and strength 1.25. Implementation evidence is bounded
  to desktop/source, native-host and Android build checks until that exact path is installed, viewed
  and measured on POCO/Mali; no physical visual or performance result is claimed.
- Added the fail-closed
  `python validation/benchmark_polar_render_poco.py --workload glow --include-cpu --build-only`
  matrix definition for 64/256/1,024 Ring displays. Runtime mode refuses acceptance without exact
  KCPR v3/operator/36-byte-stride/batch/ECS telemetry.
