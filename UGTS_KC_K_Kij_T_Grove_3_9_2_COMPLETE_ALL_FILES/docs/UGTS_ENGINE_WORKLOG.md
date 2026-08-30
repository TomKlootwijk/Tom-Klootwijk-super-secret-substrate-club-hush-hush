# UGTS Engine worklog

This is an append-only factual worklog.  Planned work belongs in
`UGTS_ENGINE_TODO.md`; this file records decisions, implementation, verification,
and failed approaches.  Performance statements apply only to the named build
and workload.

## 2026-08-29 — Baseline inherited and verified

- Confirmed the repository already contained a substantial 2D/3D engine layer,
  PySide6 editor, typed Logic Blocks, native Android GLES3 player, compact scene
  packs, packed polar kinematics, deterministic seeded populations, animations,
  triggers, body physics, and device tooling.
- Retained the existing dirty worktree and unrelated user artifacts; no reset or
  broad cleanup was performed.
- Completed the dark editor presentation and one-click `RUN_UGTS_STUDIO.cmd`
  launcher flow.
- Completed a bounded editable 3D transform hierarchy.  Ordinary nodes can be
  attached/detached with world-pose preservation and Undo/Redo.  Desktop,
  native KCHI, glTF, editor viewport, and Saved Scene boundaries were covered.
- Full source suite after the hierarchy slice: **627 passed, 145 subtests
  passed in 150.12 seconds**.

## 2026-08-29 — First exact-device hierarchy baseline

- Built `UGTS-Parent-Child-Hierarchy-3.9.2-Poco-X7-Pro-debug.apk`:
  1,565,171 bytes, SHA-256
  `813D290E2B89973FE4C429BF58FAD7F50BFB156C42EACB665A7ABB1B4BF36E20`.
- Installed and cold-launched it on authorized device `XOVSTSHYNREMZ5D6`, model
  `2412DPC0AG` / `rodin`, with a 448 ms reported launch time.
- Captured and visually inspected the device screenshot.  The five-node scene
  rendered the cyan carrier, amber arm, violet mast, lime beacon, and floor.
- Bounded 15-second profile observed 120.15 effective SurfaceFlinger cadence,
  8.376 ms p50, 9.959 ms p95, 10.473 ms p99, zero intervals above 1.5 display
  periods, roughly 138–143 MiB PSS, thermal status 0, and no crash-buffer lines.
- Evidence boundary: this was a tiny five-node, roughly 60-triangle baseline.
  It did not contain KCPK polar assets and does not prove a polar renderer,
  large-game performance, sustained thermals, or AAA output.

## 2026-08-29 — Substrate-use correction

- User clarified that the log-encoded polar LUT must participate in rendering,
  and that a Bayer matrix should be the final output projection.
- Audited the present path.  KCPK/UGLUT2 currently decodes on the CPU and writes
  ordinary `NodeData` transforms.  The renderer receives only matrices; the LUT
  never reaches GLES.  Therefore GPU LUT rendering was **not implemented** at
  this point.
- Audited sibling sources in the parent repository:
  - SCLP 3.6.2 supplies bounded log-radius polar charts, derivatives, packing, and
    explicit error/singularity rules.
  - UGTS 4.1 supplies deterministic SplitMix64 lineage useful for random-access
    seeded generation.
  - UGTS Foundation 5.0 supplies content-addressed packed operator ideas.
  - the GPU Native Addendum supplies evidence that LUT performance depends on
    locality, line pressure, and address span; a LUT is not automatically faster
    than direct math.
  - Bayer Direct 3.9.4 supplies the exact 8x8 threshold permutation and a clear
    rule that Bayer is a presentation stage, not authoritative state.
- Corrected the architecture target to:
  `seed + compact operator recipe + packed ECS state -> shared log-encoded polar
  LUT -> procedural/instanced GPU rendering -> Bayer output`.
- Recorded a critical honesty finding: the small APK mainly reflects a lean
  ARM64 native runtime today.  The engine has not yet achieved whole-scene
  substrate reconstruction from seeds and operator recipes.

## 2026-08-29 — Active implementation

- Started a semantic `polar_movement` ECS adapter for desktop and Android Logic
  Blocks.  Planned child-facing fields are radius, angle, facing, turns per
  second, grow/shrink speed, and both accelerations.  Raw 64-bit words remain an
  internal storage detail.
- Started native graph access that preserves the existing KCPK/KCVG binary
  layouts and immediately recomposes a polar transform after a semantic write.
- Designed the next renderer slice: keep CPU ECS/fixed-step state authoritative,
  group compatible polar entities by profile/mesh/material, upload one LUT per
  profile, bit-decode packed poses in the vertex shader, and issue instanced
  draws.  CPU matrix fallback and a GPU direct-math mode are required for fair
  comparison.
- Designed the Bayer integration as a configurable final GLES post stage with
  Off, Gentle, and limited-palette modes.  It will be tested for banding and
  visible patterns; it will not be described as animation or geometry
  smoothing.

## 2026-08-29 — Semantic polar ECS slice completed

- Added the virtual child-facing `polar_movement` component on desktop.  Its
  seven numeric fields decode from and re-encode to the existing KCPK words;
  snapshots and Android assets do not duplicate the friendly view.
- Added the same seven-field bridge to the native Graph VM.  Writes are finite,
  profile-bounded, binary32-canonical, preserve every untouched field and tick
  bit, and immediately publish the recomposed transform.
- Hid raw pose/motion words from beginner Logic Block choices and added friendly
  field names and help.  KCPK and KCVG versions did not change.
- Added native startup evidence for profile/component counts and active graph
  access.
- Full Python/editor suite reported by the implementation pass: **636 passed,
  145 subtests passed in 122.63 seconds**.  Native semantic host, existing Graph
  VM, polar ECS, and template-copy checks also passed.
- Corrected a remaining physics parity gap: desktop 3D composition now publishes
  X/Z velocity from the same packed polar state while preserving Y.  The
  added focused assertion and the complete semantic-polar file pass: **8
  passed**.  The native equivalent is included in the current renderer/native
  integration pass and is not yet claimed as device-proven.

## 2026-08-29 — Compact render-settings record completed

- Added optional `render_substrate.kcrp`, an exact 32-byte little-endian KCRP392
  record.  It carries one uint64 seed, requested polar mode (Auto, LUT, Direct,
  or CPU), and Bayer mode/levels/strength.
- Projects without `metadata.substrate_render` emit no sidecar and retain legacy
  behavior.  Opted-in records reject unknown keys, invalid modes, non-finite or
  out-of-range values, corruption, and trailing bytes.
- Android source builds now package the runtime record and include its parsed
  values, byte count, and SHA-256 in `build-report.json`.
- Default opted-in record SHA-256:
  `82811b7c5bd6d787b35942a1edf37f9783b2e2f239ef4da8e1055795df2f0610`.
- Verification: **7 tests and 30 subtests** for the format; **28 tests and 13
  subtests** across adjacent Android exporter/polar/animation/population paths;
  Ruff and diff checks passed.
- Evidence boundary: the record is now portable, but native GPU consumption and
  child-facing project settings UI were still in progress at this entry.

## 2026-08-29 — Child-facing render settings completed

- Added a Render tab to the Project dock for mobile 3D projects.  Learners can
  choose Auto/shared-LUT/direct/CPU packed movement and Off/Subtle/Retro colour
  projection without editing JSON or matrix values.
- The tab explains that ECS movement stays authoritative and that the output
  choice changes drawing only.  It shows the exact 32-byte Android recipe and
  deterministic seed when enabled.
- Changes are validated, undoable, redoable, and preserve advanced custom
  values until a beginner preset is deliberately chosen.
- Verification: the new editor tests pass **2/2**; the render-settings,
  movement-pattern, beginner-lesson, and KCRP group passes **16 tests and 30
  subtests**.

## 2026-08-29 — Editable packed-polar lab completed

- Added `examples/packed_polar_gpu_lab_3d/project.json` with 64 genuine static
  ECS mover nodes.  There are no scatter copies.  All movers share one
  five-vertex/six-triangle mesh, one material, a shared 256-entry log-encoded
  polar LUT/profile, and one four-node owner-relative Logic Blocks definition.
- The shared graph reads each owner's semantic Turns per second every second,
  multiplies it by -1, and writes it back.  The graph definition is stored once;
  KCVG contains 64, 256, or 1024 compact owner bindings.
- Added a deterministic SplitMix64-style generator for exact 64/256/1024
  variants and Auto/LUT/Direct/CPU plus Off/Subtle/Retro/Custom output modes.
- Verified KCPK sizes of **3,202**, **7,810**, and **26,242 bytes**.  Each added
  ECS mover changes the pack by exactly **24 bytes**; every workload keeps one
  shared LUT.
- Desktop proof reached tick 120, reversed all 64 semantic turn speeds, returned
  64 entities from string and typed ECS queries, and preserved authored Y.
- Independent rerun: example verifier `PASS`; focused CI example test **1/1**.
- Evidence boundary: this proves authored ECS/graph/pack composition, not GPU
  execution or POCO performance.  Those require the native build and device
  evidence still in progress.

## 2026-08-29 — Native Direct/LUT/Bayer substrate source completed

- Added strict native KCRP parsing plus CPU, direct-GPU, and shared-LUT GPU
  execution modes. Compatible packed movers are grouped by profile, mesh, and
  material and drawn through bounded 32-byte instance records.
- The LUT texture uploads the authored binary16 lanes directly. A review found
  and corrected an axis inversion before device measurement: texture R is now
  cosine/world X, G is sine/world Z, and B is normalized log-radius.
- Previous/current packed poses interpolate only for display. The CPU ECS
  remains authoritative, and hierarchy-linked or animation-owned movers fail
  back to CPU so children cannot detach from a GPU-interpolated parent.
- Added explicit packed ownership rejection for Player control, authored spin,
  generic X/Z or rotation writes, and symbolic or numeric field aliases. Y,
  uniform scale, and Y velocity remain ordinary authored state.
- Added the canonical top-origin 8x8 Bayer threshold stage. Off retains the
  legacy blit when post-processing is off; enabled modes clamp the source,
  quantize it, and blend with bounded strength at physical output pixels.
- Focused evidence reported by the native pass: **31 tests and 33 subtests**,
  all direct/LUT/Bayer shader variants linked with `glslangValidator`, and a
  fresh 36-task `assemblePocoX7ProDebug` build succeeded.
- Built APK: **1,664,323 bytes**, SHA-256
  `348BB30405B9284E7B3509270C7FF30ECF68C57B20DA2AFF09371A168F81A2DB`.
  It contains KCPK, KCRP, `polar_scene.vert`, and the Bayer post shader.
- Evidence boundary: ADB listed no attached device during this build. The APK
  was not installed or visually/timing-verified on Mali, so this entry proves
  source, host, shader-link, and Android compilation—not phone performance.

## 2026-08-29 — Metrics and compact recipe integration active

- Extended phone profiles with `/proc` scheduler-delta CPU sampling. Reports
  now distinguish one-core-equivalent work from percentage of the entire
  phone, alongside frame cadence, memory, temperatures, battery, thermals, and
  crash evidence. Focused profiler/harness/editor verification: **24 passed**;
  Ruff and diff checks passed.
- Added a resumable A/B harness choice for the real-ECS workload or a compact
  recipe workload. The recipe lab keeps five environment nodes plus one real
  packed ECS prototype while requesting 64, 256, or 1024 display instances;
  KCPK stays byte-identical as the display count grows.
- Added and tested a KCPR392 content-addressed recipe draft with Ring, Spiral,
  and Polar Field operators. Review rejected an initial `log/exp` generation
  schedule because different desktop/Android math libraries could invalidate
  a bit-exact claim.
- Review also found that Direct mode's `r0 * exp(rho)` can overflow its
  intermediate for a valid tiny-`r0` profile even when the final radius is
  representable. Passing precomputed `log(r0)` and evaluating one bounded
  exponent is part of the active native correction; no affected-profile claim
  is made before that lands.
- The replacement in progress stores binary32 log-radius offsets directly,
  uses a bounded rational spiral, and adds periodic offsets in theta18 and
  heading12 code space. This deliberately keeps transcendental reconstruction
  in the shared LUT/render path rather than authoritative recipe generation.

## 2026-08-29 — KCPR392 Python contract frozen

- Completed a strict optional content-addressed polar display-recipe asset:
  32-byte header, minimal sorted 16-byte operator meanings, and one 128-byte
  sparse recipe per real packed ECS prototype. Ring/Polar Field are 240 bytes
  total for one recipe; Spiral is 256 bytes because it adds one operator.
- The deployed operator parameters now contain exact binary32 log-radius
  offsets. Runtime member derivation uses SplitMix64 lineage, staged binary32
  basic arithmetic, rational spiral saturation, and direct theta18/heading12
  code addition. No runtime `log`, `exp`, sine, or cosine participates in the
  authoritative recipe result.
- Full 128-bit content addresses include count and every consumed dependency.
  Separate 128-bit lineage namespaces exclude count only, so 64 -> 256 -> 1024
  preserves the existing member prefix. Mesh/material addresses hash the exact
  f32/u32/u8 lanes visible in KC3D rather than authoring-only JSON precision.
- Generated members remain display values. A 1024-member recipe still creates
  exactly one real ECS prototype; it does not invent 1023 selectable entities,
  colliders, tags, or graph owners. The editor viewport derives at most 64
  random-access preview copies instead of allocating the full population.
- Stable count-64 fixtures: Ring **240 bytes** / SHA-256
  `019C33DC2CDB7278540B4E69509EB062CE1DED7183629481DB3C374D7C10F568`;
  Spiral **256 bytes** /
  `6B5358DCC568E7F23561C1F52B949CE5C753B5332A58329E3E1C9DDCCAEBEE55`;
  Polar Field **240 bytes** /
  `FFCF6CA9A2A49F95F895BB5EE7616DE07662CA95F1BB0D2FB6D65E6AD9BCAD59`.
- Implementation pass evidence: **22 tests and 38 subtests**, Ruff clean.
  Independent focused rerun with the compact recipe lab and native graph
  ownership test: **20 tests and 16 subtests**, Ruff clean.
- Evidence boundary: this entry freezes the Python/export/desktop/viewport
  contract. Native KCPR parsing/render consumption and POCO measurement remain
  active and are not claimed here.

## 2026-08-29 — Native KCPR, bounded Make Many, and timer source completed

- Added strict optional `polar_populations.kcpr` consumption in
  `polar_populations.hpp/.cpp`. Native parsing validates the canonical header
  and operator meanings, KCRP/root-seed agreement, bounds, profile/prototype/
  mesh/material dependency addresses, full 128-bit content addresses, and
  count-stable lineage namespaces. The maximal host parity case reported
  `PASS native KCPR392 polar populations generated=16380 tested=64`.
- Generated members remain render data, not `NodeData` ECS rows. The runtime
  retains only bounded recipe metadata/ranges for the total population and
  materializes visible members while drawing under `maxVisibleNodes`;
  visible-copy staging and the GLES instance buffer are capped by that limit
  rather than total recipe count.
  CPU/fallback paths compose Cartesian data only for visible members, while
  Direct/LUT use packed instance words. Runtime logs separate requested total,
  visible, GPU, CPU, materialized, and Cartesian-composed counts.
- Native KCPR now supplies the existing Direct/LUT instancing and final Bayer
  source paths, with explicit fallback logging. This is source/host evidence,
  not a claim that the current Android APK or target-device path has run.
- Added the child-facing Make Many Inspector with Off, Ring, Spiral, and Polar
  Field choices; uint64 seed and friendly labels instead of raw math by default;
  exact KCPR byte-count and full-address readout; stock Goal-spin/Movement
  ownership handoff; and validated undo/redo. Generated preview copies cannot
  be selected instead of their real prototype, and the preview budget is at
  most 64 across all active recipes.
- Tightened benchmark runtime proof to fail closed on the exact requested and
  effective polar mode, instance/profile/batch counts, any unintended fallback,
  recipe GPU/CPU counts, Bayer configuration, and visible/materialized/
  Cartesian-composed counts. A fallback invalidates a requested GPU case.
- Added a nonblocking `GL_EXT_disjoint_timer_query` implementation with four
  reusable query slots. It polls `GL_QUERY_RESULT_AVAILABLE_EXT` on later
  frames, discards disjoint intervals, never calls `glFinish` or a client wait,
  and reports support, counter bits, samples, total/mean/max/last time,
  disjoint intervals, and pending queries. The Android profiler parses those
  fields or reports unsupported/runtime-failure state explicitly.
- Focused verification command:
  `python -m pytest -q tests/test_polar_population_recipe.py
  tests/test_android_polar_population_native.py
  tests/test_android_render_substrate_native.py tests/test_android_profile.py
  tests/test_polar_render_benchmark_harness.py` with `QT_QPA_PLATFORM=offscreen`,
  `PYTHONPATH=src`, and bytecode writes disabled: **43 passed, 19 subtests
  passed in 20.91s**.
- Fresh-build boundary: benchmark run
  `build/poco-polar-render-benchmarks/20260829T213228Z-seed-5eed3920c0dec0de`
  stopped on its first `polar-1024-direct-off` case during CMake compiler-ABI
  `try_compile`. The deeply nested Windows build path could not create/set the
  `CMakeTmp` working directory (`No such file or directory`), so no fresh APK
  containing the current KCPR renderer and timer source is proven. Earlier APK
  evidence remains historical evidence for that earlier source state only.
- No ADB device was available. There is no current install, screenshot, runtime
  proof, GPU timer sample, Direct/LUT/Bayer A/B result, Mali timing, power, or
  thermal claim.

## 2026-08-30 — Short-path matrix and shared polar conformance completed

- Fixed the Windows build-transport blocker without deleting its evidence.
  Benchmark Android source is now generated and built in a short system
  temporary workspace such as `C:\Users\Tom\AppData\Local\Temp\kc392-*`, then
  exact evidence is copied back while the disposable Gradle tree is removed.
  Each case keeps append-only `build-attempt-NNN` records, including partial
  artifacts and errors, so a retry cannot rewrite a failed attempt.
- The first short-path smoke built an APK but exposed a harness proof bug: it
  compared the build report's base ID directly with the Poco flavor ID. Preserved
  attempt 001 records `build report and APK metadata application ids differ`
  and its partial 1,786,658-byte APK SHA-256
  `37F9CBB19734C71435C3A18E9B9EE5D969BA49E1CD00FE1E33A92765A4E12B53`.
  The check now requires the actual AGP ID to equal the base ID plus
  `.pocox7pro`; attempt 002 completed append-only, with final APK SHA-256
  `15CCD87D2ABFEFF4B6E53C31DEB31974E6A6C7899CCF71680136A64DE816A12B`.
- Reproducibility was tested rather than assumed. Explicit
  `-Wl,--build-id=sha1` alone was insufficient: two clean 1,786,718-byte APKs
  differed at SHA-256
  `C29FB69181C4D104177EF3B650A18A5E574824A5D0147D961B20FC2983CDB4D3`
  and
  `66A5B7990199E7324E99434788382C54B6570594D27A662FC9F83776041F55EB`.
  After applying `-fdebug-prefix-map` to normalize the independent source and
  build directories to stable DWARF paths, both clean builds produced the same
  APK SHA-256
  `B417EE9E303BCE3ABBE7FE709A77433D04E426E47CAD1B8880E17130CB6B335B`.
  Their embedded 1,756,032-byte `libugts_kc_native.so` files both have SHA-256
  `5EE54BD46375EBE9EE45847131755642F8B37270F9691E66697C954E5510254C`
  and GNU build ID `8A4D75726438F50328566565391A4EEAB5AD9D39`.
- Added `src/ugts_kc3/conformance/polar_substrate_vectors.tsv`, one 4,994-byte
  canonical seven-case artifact with SHA-256
  `CDF8B4A20869C2BC35C4330C35DC7E43C33459CE40F37FD63139C0A41B01DB57`.
  Python and the native host executable consume the same fixed expectations for
  the explicit core, radius clamps, theta/heading seams, LUT interpolation,
  Direct/LUT position/velocity/acceleration/heading, and packed next state.
  Shader snippets are checked against `polar_scene.vert`, but the artifact marks
  that evidence `shader_source_formula_only_no_gpu_execution`.
- LUT rendering now obtains packed heading from the same seam-safe log-encoded
  polar LUT direction lookup used for angular direction. Direct mode retains
  `sin`/`cos` as the independent comparison path. Focused evidence reported
  **66 tests and 69 subtests passed**, Ruff clean, native host conformance
  `PASS ... vectors=7 source_formula_only=true`, and successful Direct/LUT
  shader linking. A fresh 1,789,411-byte current-source Poco debug APK built with
  zero native stderr; SHA-256
  `6348E44A6B75281C469135AFF3C9A17A37739701673AE14F36B17001D1A165C3`.
- The post-fix full `python -m pytest -q` run completed with exit 0:
  **701 passed and 236 subtests passed in 165.86 seconds**, with no warning
  summary/output. Its first run's sole failure was a stale source-slicing
  assertion in
  `test_renderer_uploads_camera_and_every_packed_material_field`; the assertion
  was corrected to follow `drawOrdinaryNode`, passed isolated, and then passed
  in the complete run.
- Ran `python validation/benchmark_polar_render_poco.py` with
  `--workload recipe --include-cpu --build-only`. Run
  `build/poco-polar-render-benchmarks/20260829T215836Z-seed-5eed3920c0dec0de`
  completed all **15** short-workspace cases: 64/256/1024 CPU Off and
  Direct/LUT with Bayer Off/Subtle. All 15 numbered attempts are complete and
  use `org.ugts.games.packed_polar_recipe_lab_3d.pocox7pro`.
- The 3,317-byte `run-manifest.json` has SHA-256
  `0104FF9C2B0B2B7916F99580DA8A89AFEE8693CDA14C07D767E3AC8677E1B337`;
  the 11,076-byte `comparison-summary.json` has SHA-256
  `9A3B4443EA6F4A1125C0463428EB884B2857EE13795AD0A21DD0BB30C0E8B05A`.
  The summary says `built_only` for every case, null FPS/p95 values, and zero
  available comparisons. These hashes prove preserved build evidence, not
  physical rendering or relative performance.
- No ADB device was available. None of these results proves POCO/Mali runtime,
  screenshots, GPU timer support or samples, FPS, Direct/LUT/Bayer performance,
  power, or thermal behavior.

## 2026-08-30 — Release-content verification completed

- Built a wheel and source distribution from a frozen workspace snapshot under
  `build/release-content-verification/20260829T221517Z-final-package-go`; the
  snapshot SHA-256 is
  `948CD26FD532B36FFF0DB31E88F9AAF29FA305BCF0B82358AB3334904863D5DA`.
- The 534,168-byte wheel has SHA-256
  `494962E7AABB7ED199CEA57D23C6DB85DCE5B8A3884F29B8F1DCEA83E00E76E9`;
  the 621,456-byte source distribution has SHA-256
  `7D197636619B01154CA4C6C7573EE0D2FDCBE2527E4FB88868528C88C26C8E49`.
- Verified all 25 required conformance and Android-template paths in both
  archives, byte-for-byte against the frozen snapshot. This includes the shared
  TSV, `gpu_timer_query.*`, `polar_populations.*`, `polar_scene.vert`, and their
  runtime/template dependencies. Neither archive contains Python bytecode.
- Installed the wheel locally with `pip --no-index --no-deps` in a fresh Python
  3.12 virtual environment. Package imports, resource reads, distribution/version
  `3.9.2`, and isolated `python -I -m ugts_kc3 --help` all exited successfully.
- This proves release contents and isolated Python installation only. It does
  not add physical Android execution or Mali performance evidence.

## 2026-08-30 — Semantic Movement blocks completed

- Expanded the built-in Mobile 3D/native registry from 27 to **29** blocks;
  the portable desktop/retained-web/native subset remains **25**.
- Added append-only opcode 28 **Read Movement** (`value.polar_movement`) and
  opcode 29 **Change Movement** (`action.set_polar_movement`). Both hardcode the
  semantic virtual `polar_movement` component and expose only an entity, one of
  its seven friendly numeric fields, and a numeric fallback or new value.
- The dedicated blocks preserve Python/native packed-word and composed-transform
  parity. In the fixed four-node comparison their KCVG is **239 bytes / 8
  inputs**, versus **268 bytes / 10 inputs** for generic component blocks: 29
  bytes smaller with no `polar_movement` string. The retained browser exporter
  rejects both as Mobile-3D-only rather than silently omitting them.
- Broad graph coverage passed **141 tests and 53 subtests**. The combined
  semantic-movement/ECS/hierarchy/animation selection passed **139 tests and 47
  subtests**.

## 2026-08-30 — Desktop sparse optional-component queries completed

- Moved optional `GameWorld3D` components into world-owned sparse pools. A
  spawned entity's `extra_components` becomes a live dict-compatible
  `MutableMapping`, so assignment, replacement, deletion and normal bulk
  mutators update the same pool authority.
- Added cached canonical query plans: component-name permutations deduplicate
  to one shape, execution chooses the smallest required sparse pool, then
  evaluates mutable tag/alive/active filters and emits lexicographically ordered
  entities. Virtual `polar_movement` membership maps to `packed_kinematic`.
- Saved project JSON, runtime snapshots and state hashes remain unchanged.
  Built-in transform/body/collider/render storage remains in the compatibility
  record; full archetypes plus tag/spatial/graph-binding/render-batch indexes
  remain TODO.
- The **4** focused pool/query-plan tests pass. The wider scoped regression
  passed **152 tests and 60 subtests**; targeted Ruff and Python compilation
  also pass.

## 2026-08-30 — Device Look reference and opcode-29 Poco build completed

- Added `editor/device_look.py` and an opt-in **Device Look (reference)**
  viewport control. The editor keeps its exact binary16 UGLUT2 CPU composition,
  copies the completed authoring viewport into RGBA8, and runs the packaged
  `grove_post.vert` / `grove_post.frag` Bayer branch through an OpenGL widget.
  Desktop core GLSL changes only the ES preamble; the canonical 64-entry matrix,
  top-origin physical-pixel phase, threshold, quantization, and mix remain in
  the shared native shader source.
- The visible active state says `CPU LUT + <mode> Bayer`, including when the
  phone profile asks for Direct. Bayer Off performs no GL copy or clamp. Invalid
  settings, headless Qt, an unavailable context, or a post failure preserve the
  raster viewport and selection/zoom state. The tooltip states that the grid
  and gizmos are included and that this is not Android GPU/performance parity.
- Formula/source/fallback and adjacent editor/polar verification passed **50
  tests and 66 subtests**; targeted Ruff passed. A live Windows OpenGL check at
  device-pixel ratio 1.5 allocated the exact Qt physical size **959 x 629**,
  ran the packaged shader without a GL failure, and restored QWidget/Smart
  updates when disabled. Headless CI intentionally proves only formula, source,
  and fallback behavior.
- Updated the checked-in 64/256/1024 packed-polar lab to use dedicated opcodes
  28/29. Its 64-binding KCVG is **752 bytes** with 10 inputs and no
  `polar_movement` string, versus **781 bytes** and 12 inputs through generic
  blocks. The deterministic lab verifier and focused tests passed.
- Fresh short-path `poco-debug` generation and native compilation produced
  `build/op29-poco-build-20260830T005625/UGTS-Packed-Polar-Op29-Poco-debug.apk`:
  **1,804,539 bytes**, SHA-256
  `78A195491B8D46D6946EA3B8C08FB86B3452B66D02105DD7F9A2D8AA51F386B9`.
  It is v2-signed, min SDK 26 / target SDK 36, application ID
  `org.ugts.games.packed_polar_gpu_lab_3d.pocox7pro`, and embeds the exact
  752-byte KCVG, 3,202-byte KCPK, and 32-byte KCRP recorded in `evidence.json`.
  `adb devices -l` was empty, so this is build/package evidence only: it was not
  installed, launched, screenshotted, timed, or profiled on the POCO/Mali GPU.

## 2026-08-30 — Live desktop Make Many Play preview completed

- `EditorDocument.step_play()` now carries each live Mobile 3D object's
  translation, rotation, scale, velocity and active state plus a transient
  packed-movement view containing the previous/current pose words, motion word
  and profile id. The transient previous word is not serialized into project
  JSON or runtime snapshots.
- The Scene viewport updates only its already-created global maximum of 64
  KCPR display items in place through the existing authored recipe, LUT and
  random-access lineage. It creates no generated ECS rows or per-copy runtime
  state. Runtime height, scale and vertical velocity compound with the packed
  prototype pose.
- Dead or inactive prototypes hide the real mesh and its copies; reactivation
  restores the prototype and reuses the same retained copy objects. Malformed
  transient packed or transform data hides the affected rendering for that
  frame instead of crashing Play. Stop intentionally rebuilds the authored
  preview.
- The focused polar-recipe/Device-Look rerun passed **33 tests and 19
  subtests**; the wider editor/viewport/Play selection passed **93 tests and 28
  subtests**, and hierarchy/Saved Scene coverage passed **29 tests and 10
  subtests**. Targeted Ruff passed.
- This is current-endpoint rendering only. The editor has no real accumulator
  alpha and therefore does not yet match Android's previous/current packed-pose
  presentation interpolation.

## 2026-08-30 — First child-facing Make Many runtime block completed

- Expanded the Mobile 3D/native registry from 29 to **30** blocks while the
  portable desktop/web/native subset remains 25. Append-only opcode 30 is
  `action.set_polar_population_visible` / **Show or Hide Extra Copies** with a
  literal Make Many object, linked-or-literal Boolean, no data output and one
  `out` flow.
- Desktop owns copy visibility in `PolarPopulationRuntimeState`, outside
  `world.state`, sparse ECS component pools, project JSON, snapshots and hashes.
  Native owns the same meaning in one safe `uint64_t` mask for all 64 bounded
  recipe slots. Both initialize visible before Ready and reset with a new
  runtime.
- Hiding extra copies leaves the real prototype alive, active, visible and
  selectable. The common native CPU/Direct/LUT recipe loop skips the hidden
  recipe before prototype lookup, materialization or visible-budget use.
  KCPR/KCPK bytes, content addresses, counts and deterministic prefixes remain
  unchanged.
- The frozen Ready-plus-action graph is **121 bytes**, SHA-256
  `DCA7CF42A184CE9F50C0B90646756A90ED4E782EA8EB2697553525880B4E529C`,
  versus **92 bytes** for Ready alone: an exact 29-byte increment.
- Focused Python/editor/pack/browser coverage passed **6 tests and 2 subtests**;
  the broad graph/pack/editor/web/population selection passed **137 tests and
  74 subtests**, and Mobile ECS/Saved Scene/animation regressions passed **33
  tests and 8 subtests**. Native KCPR/VM and graph regressions passed, and the
  Android ARM64 CMake target built successfully. The raw ungenerated template's
  full APK link still rejects its intentional `__APPLICATION_ID__` placeholder;
  this is not a generated-project build failure.

## 2026-08-30 — Radial Burst loop and build-only matrix completed

- Added **Make Many → Radial Burst (loops)** as a bounded looping display effect
  around one real packed ECS prototype. Its local packed displacement compounds
  with the prototype anchor through log-encoded polar LUT semantics. It is not a
  one-shot gameplay event and creates no generated ECS identities.
- KCPR remains byte-identical v1 for legacy-only Ring, Spiral and Polar Field
  assets, including their prior golden hashes. A pack selects v2 only when it
  contains Burst. The controlled profile-core-start and positive-start one-Burst
  packs are each **240 bytes**, with SHA-256
  `2F6717F35D90033A8476EAC20E74A625FE6DD74CF39B159172BBC7ED6A6BF807`
  and `F9BF55A78D94EDFBE6731FE886F1A1EE1F6AC85DB70CB157C489BF18F8D3ECBD`.
  Each contains a 32-byte header, five 16-byte operator meanings and one
  128-byte recipe.
- Burst limits are 512 instances per recipe, 16 recipes and 2,048 instances per
  project. The desktop keeps only its existing global maximum of 64 preview
  items; native work also obeys maximum-visible and the remaining particle
  budget. Opcode 30 hides the extra copies only and leaves the real prototype
  visible.
- Stopped desktop authoring displays the deterministic loop midpoint. Play
  passes the real post-step fixed world tick and draws the fixed endpoint with
  no invented interpolation alpha. Direct is the native baseline, LUT uses the
  shared profile path, and Bayer remains the final presentation pass.
- Core plus legacy recipe coverage passed **32 tests and 25 subtests**; the
  related Python/editor/conformance selection passed **57 tests and 102
  subtests**. Native exact-vector execution passed **1 test and 2 subtests** at
  ticks 0, 1, 4, 7 and 8, and the native wiring/render/conformance selection
  passed **10 tests and 23 subtests**. The ARM64 native CMake target built
  successfully in 16 seconds.
- Executed and preserved the separate **18-case** build matrix: 32/128/384 instances across
  CPU/Direct/LUT and Bayer Off/subtle:

  ```powershell
  python validation/benchmark_polar_render_poco.py --workload burst --include-cpu --build-only
  ```

  Run `build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de`
  finished `built_only`, 18/18, in 272 seconds. Every case records a 1,690-byte
  KCPK, 240-byte KCPR and 32-byte KCRP; APKs range from 1,804,558 to 1,804,566
  bytes. No APK was installed or run through GLES/Mali, so the matrix is not
  POCO visual or performance evidence.
- The final full suite passed **739 tests and 252 subtests** in 274.18 seconds,
  with no failures or skips. Ruff is green for the focused changed/new paths.
  Global Ruff still reports 895 pre-existing legacy violations in 31 files,
  none in the Radial Burst or validation files changed here.

## 2026-08-30 — Burst release contents cleaned and smoke-installed

- Rejected the first Burst distribution candidate after inspection found that
  the broad Android-template include had swept local `.gradle`, `.cxx`,
  `app/build`, and project `build` caches into a 6,074,659-byte wheel. This was
  packaging contamination, not intentional runtime content.
- Added explicit `MANIFEST.in` prunes for those four generated directories. The
  clean candidate is preserved under
  `build/release-content-verification/20260830T002800Z-radial-burst-clean`.
- Its 570,134-byte wheel has SHA-256
  `23DD2FD473A16AE5677D1A8F0CDCD25ED8B376D5A136609806CDA418B8185BF5`;
  its 675,353-byte source archive has SHA-256
  `3E2D826C72EE77DD0AC3D4DC42249B2AE5E3756F0163834E408B173F7844D2E2`.
  All copied package sources matched byte-for-byte, all 15 selected
  Burst/native/shader resources were exact, and neither archive contained
  bytecode or Android build-cache paths.
- Installed that wheel with `--no-index --no-deps` into fresh Python 3.12.10.
  The isolated import returned version 3.9.2, a 32-instance/five-operator Burst
  preset, all four sampled native/shader/conformance resources, and working
  `python -I -m ugts_kc3 --help`.

## 2026-08-30 — Glow-by-distance material field completed in source/build evidence

- Audited three next-step candidates against the parent SCLP chart contract:
  Burst-loop restart, nearby-body impulse, and a material field. The material
  field is the smallest next slice that adds a genuinely new rendering use of
  the existing log-encoded polar LUT; a force block would first need a separate
  typed ownership/units contract and must not merely rename position decoding.
- Froze an optional child-facing **Glow by distance** modifier for the four
  non-Off Make Many recipes. It reuses the existing 128-byte KCPR record: an
  asset opts into v3 only when at least one recipe enables the modifier, and
  mixed v3 assets may retain zero-tail non-Glow recipes. V3 interprets the final
  12 bytes as three canonical binary32 pulse/glow parameters. Existing v1/v2
  bytes and spatial lineage must remain unchanged.
- The rendering contract derives a 12-bit material phase from the existing
  count-independent seed lineage. LUT mode must sample the existing UGLUT2
  direction lane at the phase-shifted angle; Direct mode remains the cosine
  baseline. The bounded result enters lighting, while Bayer remains the final
  presentation-only pass. CPU fallback must implement the effect rather than
  silently drop it.
- Implemented the contract across Python recipe/pack/inspection, the dark
  child-facing Make Many Inspector with undo/save/load and exact stopped/Play
  preview, native strict parsing, CPU fallback, Direct/LUT GLES shaders and
  startup telemetry. The native visible instance is now 36 bytes for all polar
  groups (32 spatial bytes plus one 32-bit material-phase attribute); the KCPR
  recipe remains 128 bytes and no generated ECS row or per-copy transform is
  persisted.
- Added canonical operator meanings `log_radius_pulse` (`0x0050`, slot 9),
  `seeded_material_phase` (`0x0051`, slot 10) and `polar_material_glow`
  (`0x0052`, slot 11). The controlled 288-byte KCPR v3 fixture has SHA-256
  `41EE7092D634033D3D5F26A11BBA1C2C1CEB2FABC92E97D4A7BD3F584501190F`;
  legacy no-Glow v1/v2 fixtures remain byte-identical.
- Added `RUN_POLAR_GLOW_LAB.cmd`. Its generated 128-display Burst/Shared-LUT/
  subtle-Bayer project validates with Glow distance 0–4 and strength 1.25. The
  launcher's noninteractive smoke completed successfully.
- Added the fail-closed
  `python validation/benchmark_polar_render_poco.py --workload glow --include-cpu --build-only`
  benchmark definition for 64/256/1,024 Ring displays. Direct/LUT run with
  Bayer Off/Subtle and optional CPU fallback runs with Bayer Off. Build proof
  requires KCPR v3 and the exact operator mask/hashes; runtime proof requires
  exact Glow/36-byte-stride telemetry, one real ECS prototype, the expected
  batch count (one for Direct/LUT, zero for CPU fallback), and
  `ecs_generated=false`.
- Built and statically inspected the exact ARM64 handoff APK at
  `build/release-handoff/20260830T012054Z-polar-glow/packed-polar-glow-burst-128-lut-subtle-poco-debug.apk`:
  **1,817,430 bytes**, SHA-256
  `17B3DAE3C4479B1BD09D335ACE551A9414BFD3BACB97BC1C976FA6E5E9C801F4`.
  It is v2-signed, zip-aligned, min/target SDK 26/36, ARM64-only, application ID
  `org.ugts.games.packed_polar_recipe_lab_3d.pocox7pro`, and embeds the exact
  1,690-byte KCPK, 288-byte KCPR, 32-byte KCRP and five inspected shaders.
- Focused Glow core coverage passed **37 tests and 41 subtests**; editor Glow
  coverage passed **4 tests and 12 subtests**; native exact host execution passed
  six vectors/63 generated copies; the broad native selection passed **60 tests
  and 59 subtests**; shader/render selections passed **8 tests and 5 subtests**;
  the benchmark harness passed **19 tests and 11 subtests**; and its ARM64 NDK
  target built successfully. Targeted Ruff and compile checks passed.
- The first `python -m pytest -q` complete-suite run found one stale pre-Glow shader-source assertion:
  **1 failed, 751 passed and 291 subtests passed** in 244.12 seconds. The source
  was correct; the test was updated to require the new Glow uniform lookup,
  ordinary-node argument and scatter reset. Its focused rerun passed, followed
  by a clean full run of **752 tests and 291 subtests** in 203.32 seconds.
- ADB remained empty, so the APK is explicitly `built_only`: it was not installed,
  viewed, timed or profiled on the POCO/Mali GPU. Compact source and packaging
  results are evidence; visual quality, frame timing, power and thermals remain
  open physical-device work.

## Worklog rules for subsequent entries

- Record exact files and formats changed.
- Record exact commands and test counts.
- Record artifact byte sizes and SHA-256 hashes.
- Record device serial/model, application id, run duration, workload, and
  environmental caveats for every phone result.
- Record regressions and abandoned approaches, not only successes.
- Never turn an intended optimization into a performance claim before an A/B
  measurement on the target device.

## 2026-08-30 — Grow glowing copies implementation started

- Audited the next compact substrate applications against the shipped ECS,
  KCPR, editor and native paths. A true Seeded Grove remains a later connected-
  geometry/branch-grammar feature; relabelling independent Polar Field copies
  would not implement that mechanism.
- Froze **Grow glowing copies** as the next bounded vertical slice. It will
  reuse the already-compiled binary32 Glow field exactly once and multiply only
  generated display-copy scale by `clamp(1 + glow, 1, 5)`. The authored ECS
  prototype, collider, picking, graph state, snapshots and random-access
  spatial lineage must remain unchanged. For Burst the order is authored scale,
  then Burst life envelope, then the shared distance-field multiplier.
- KCPR v4 is reserved for the new slot-12 apply operator while retaining the
  existing 128-byte recipe and 36-byte visible-instance stride. No additional
  recipe parameter, texture, LUT or instance lane is allowed; v1-v3 compiler
  bytes and identities must stay exact. Direct uses cosine, LUT uses the shared
  UGLUT2 direction lane, CPU/editor use the quantized LUT reference, and Bayer
  remains the last presentation-only pass.
- Implementation and verification are now in progress. There is no new device
  result yet: ADB must be checked again before any POCO/Mali execution claim.

## 2026-08-30 — Grow editor, manual lab and fail-closed evidence slice completed

- Added the child-facing **Grow glowing copies** checkbox beneath **Glow by
  distance**. Its help says exactly what is affected: generated display copies
  may grow from 1x to 5x, while the real object and collider remain unchanged.
  False remains omitted from JSON, preserving Glow-only records; true survives
  preset changes, Undo/Redo, strict save/load and profile validation.
- Corrected a pre-existing desktop parity gap while touching this path: the
  ordinary index-zero prototype now receives its exact Glow lighting sample in
  stopped and Play previews. Grow is never applied to it. Retained generated
  preview items consume the already-scaled core display instance once, expose
  the reference multiplier for inspection and are not multiplied a second time.
- Added `--grow-glowing-copies` to the one-prototype recipe-lab generator and a
  separate `RUN_POLAR_GROW_LAB.cmd`, leaving the v3 Glow launcher/project as an
  exact control. The noninteractive one-click smoke generated and opened
  `build/polar-grow-lab/packed-polar-grow-burst-128-lut-subtle.json`: 21,620
  bytes, content SHA-256
  `4EB1378D1C2ACA8FB420EB83A53C8977E2FF40A9FB8C6D57BF5AF666F9676502`.
  Its 128-display/127-copy KCPR v4 is 304 bytes with nine meanings and SHA-256
  `2D04A3788D2A472F65EA0F53573325B6F680F6D73190A229573926748657ADDF`.
- Extended the POCO harness with `--workload grow`. Build proof requires v4,
  native consumer `android-kcpr392-v4`, exact Glow plus slot-12/code-`0x0053`
  hashes, the Ring mask and one ECS prototype. Runtime proof requires one GPU
  batch for Direct/LUT (zero for CPU), 36-byte instances, `glow_instances=count`,
  `grow_instances=count-1` and `ecs_generated=false`. The v1-v3 telemetry parser
  retains its old layout; the two Grow counters are accepted and required only
  on v4.
- Focused editor, generator/launcher and benchmark coverage passed **31 tests
  and 35 subtests** in 2.84 seconds. The benchmark file alone passed **21 tests
  and 21 subtests** after the v3 telemetry-compatibility refinement. Ruff passed
  all seven changed Python files. No APK was installed or run on POCO/Mali in
  this slice, so visual quality, frame timing, power and thermals are not claimed.
- The subsequent adjacent editor Burst/Play/Populate-Area regression selection
  passed **37 tests and 36 subtests** in 5.91 seconds.

## 2026-08-30 — Grow v4 integrated, reviewed, built and profiled on POCO

- Completed the frozen KCPR v4 contract across Python authoring/inspection,
  generated desktop display data, native strict parsing, CPU fallback, Direct
  and shared-LUT GLES paths, startup telemetry and the final Bayer chain. The
  same exact Glow sample is now retained once per generated desktop Grow copy
  and consumed for both lighting and scale. It is not evaluated twice. Native
  uses the top bit of the existing phase word to distinguish generated copies;
  the low 12-bit seeded material phase, 36-byte stride, 128-byte recipe and
  spatial lineage remain unchanged.
- Closed all independent-review findings. KCPR v4 is permanently bounded to
  its 13-code vocabulary through `0x0053` in Python and native readers. The
  Grow launcher now validates existing content without rewriting it: exact
  legacy content is accepted, new files carry profile provenance so intentional
  edits remain openable, and an unrelated unmarked v4 Ring/direct/Bayer-off
  project is rejected. The reviewer rechecked all three fixes and reported no
  remaining issue.
- Regenerated the one-click source with that provenance marker. The final JSON
  is **21,694 bytes**, SHA-256
  `ED7AFDB2775E2C6C308CA03066B3480000F98D18AE4072275F50D0576B502719`,
  content hash
  `06DDBE9D6B01D5651DE99EF2E9A614A393D38F06FB8C24451DA511D54E819C7B`.
  Its runtime KCPR remains the exact **304-byte** v4 sidecar with SHA-256
  `2D04A3788D2A472F65EA0F53573325B6F680F6D73190A229573926748657ADDF`.
- Focused final integration passed **48 tests and 62 subtests**. Targeted Ruff
  passed. The complete repository suite passed **763 tests and 305 subtests**
  in 238.71 seconds with no failure. The native host test compiled/executed the
  exact vectors, and the final short-path ARM64 Gradle/NDK build reported
  `BUILD SUCCESSFUL in 55s`.
- Preserved the exact debug handoff under
  `build/release-handoff/20260830T023441Z-polar-grow`. The ARM64-only APK is
  **1,819,202 bytes**, SHA-256
  `E5348442B3B9E313D10EAD1AFB636ACFA9943CD11F415226F6EA5D255B50232C`.
  APK Signature Scheme v2, min/target SDK 26/36 and 16-KiB-aware zip alignment
  verify. It packages the exact 1,690-byte KCPK, 304-byte KCPR and 32-byte KCRP
  and no authoring JSON.
- Installed and cold-launched that exact APK on authorized ADB device
  `XOVSTSHYNREMZ5D6`, Xiaomi/Poco model `2412DPC0AG` (`rodin`). Native telemetry
  reported shared-LUT effective mode, 128 GPU instances, one LUT profile, two
  GPU batches, 127 GPU-generated copies, zero CPU fallbacks, KCPR v4, one Glow
  recipe/128 samples, one Grow recipe/127 grown copies, stride 36 and
  `ecs_generated=false`. The physical screenshot is preserved.
- The 30-second Grow profile sampled 756 frame intervals and measured **120.33
  effective FPS** on a 120-Hz surface, frame p50/p95/p99 **8.380/10.113/11.295
  ms**, one interval over 1.5 display periods, PSS 143,165–148,551 KiB, RSS
  262,770–270,174 KiB, mean CPU 8.313% of total eight-core capacity (66.508%
  of one core), exposed GPU temperature 41.897–46.710 °C, battery 33.0–33.1 °C
  and 98% unchanged, thermal status 0, no crash lines and no warnings.
- A same-phone sequential 30-second Glow-v3 control also held **120.33 FPS**;
  p95 was 10.041 ms versus Grow's 10.113 ms. The 0.072-ms difference is not a
  causal overhead claim from one A/B pair. The Mali driver exposed no usable
  disjoint timer query, so GPU-only milliseconds and electrical power draw
  remain unmeasured. The final Grow APK was reinstalled and launched after the
  A/B. A later final check found the USB/ADB connection disconnected; all
  recorded phone evidence completed before that disconnect.

## 2026-08-30 - UGTOMS cross-domain claim review completed

- Audited the complete parent corpus at
  `C:\Tom Klootwijk super secret substrate club hush hush`, with GSP4 as the
  strongest direct adapter. The retained architectural claim is that UGTOMS is
  a proposed substrate-codec family and common intermediate target with bounded
  domain pilots. The evidence does not establish one byte-compatible universal
  codec, universal compression, historical priority over unrelated work, or
  ownership of third-party applications and standards.
- Recorded the direct GSP4 bridge result: 126 candidates, 8,064-byte G64 state,
  4,032-byte G32 state, and 4.364554 m maximum sampled position error inside a
  declared 25 m guard. The 2x reduction applies to the candidate buffer only,
  not the deployment or learned model.
- Generated the private review artifact at
  `output/pdf/UGTOMS_cross_domain_pilot_overview_review_draft.pdf`: **21 pages**,
  **205,109 bytes**, SHA-256
  `DD190BE704D004DA3B23A630726CF77D89FBC462B18114B35439013360E787A9`.
  It contains the requested Tom Klootwijk identity anchor, explicitly labels
  the BSN as user-supplied, and recommends redaction for a public edition.
- Rendered every page at 2x resolution and inspected the complete contact set.
  PyPDF and PyMuPDF extraction found every required identity, claim, metric,
  and caveat string; all detected text blocks remained within page bounds. The
  output is an engineering and open-use review draft, not an operative license,
  identity verification, patent filing, ownership ruling, or safety approval.
- This documentation pass performed no new Poco run and makes no new device
  performance claim. Phone measurements in the PDF remain tied to their named
  preserved artifacts.
- The curated pre-push repository suite passed **785 tests and 362 subtests**
  in **248.30 seconds**. The staged source diff check and common API-token and
  private-key signature scan also passed. Generated caches, compiler
  intermediates, package smoke environments, and the unrelated root-PDF
  deletion were not selected for the commit.

## 2026-08-30 - UGTOMS deterministic AI conduit concept note

- Added `output/pdf/UGTOMS_AI_deterministic_knowledge_conduit.pdf`: **5 pages**,
  **18,631 bytes**, SHA-256
  `A54E89CB742B1AD91B832387C128E7FEF1802CB34B3DF21967F0477DC2A21F13`.
- The note treats human knowledge as typed, versioned and attributable durable
  state; deterministic selection, derivation, permission and action gates sit
  between that state and an optional probabilistic LLM presenter. Unsupported
  material has an explicit `UNKNOWN` route rather than being promoted to fact.
- Kept the existing tests. They remain conformance and release gates while the
  active authoring loop stays focused on implementation. No additional engine
  suite was run for this documentation-only addition.
- Rendered and visually inspected all five pages. Text extraction, required
  content, page count and page-bound checks passed. The note explicitly avoids
  claiming guaranteed truth, AGI, safety certification or one finished
  universal interoperable codec.
