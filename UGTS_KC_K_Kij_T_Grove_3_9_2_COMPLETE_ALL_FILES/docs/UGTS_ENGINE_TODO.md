# UGTS Engine implementation TODO

Updated: 2026-08-30

This is the authoritative implementation checklist for turning the current
UGTS-KC 3.9.2 codebase into a child-first, Godot-like desktop game engine with
compact Android deployment.  A checked item means the behavior exists and has
direct evidence.  It does not mean the larger section is finished.

## Non-negotiable outcome

- [ ] A child can create, connect, run, inspect, and deploy a small game without
  editing JSON or packed words.
- [ ] Desktop preview and native Android execute the same bounded ECS and Logic
  Block semantics.
- [ ] The compact render path is genuinely substrate-driven:
  `seed + operator recipe + packed ECS state -> shared log-encoded polar LUT ->
  procedural/instanced GPU rendering -> Bayer output projection`.
- [x] The exact POCO X7 Pro / Mali-G720 build is installed, visually checked,
  profiled, and compared with honest baselines.
- [x] Size, speed, determinism, and visual-quality claims are backed by named
  artifacts and reproducible commands.

## 1. Preserve and audit the UGTS substrate

- [x] Search the parent repository for the SCLP 3.6.2 log-radius polar definitions,
  UGTS 4.1 seed lineage, UGTS Foundation 5.0 packed operators, GPU-native LUT
  evidence, and Bayer Direct 3.9.4.
- [x] Keep the explicit log-radius singular core, bounded quantization domains,
  deterministic rounding, and binary validation.
- [x] Create a source-to-engine mechanism map: retained, translated, deferred,
  or rejected, with the reason for every imported mechanism.
- [x] Add content-addressed operator definitions so saved recipes refer to
  canonical meaning rather than duplicated blobs.
- [x] Add one canonical seven-vector artifact consumed by Python and native C++
  host tests, with matching shader-source formula checks for core handling,
  clamps, seams, Direct/LUT reconstruction, derivatives, heading, and next-state
  packed words.
- [ ] Execute those vectors through a physical GLES driver. Shader-source
  matching and host shader linking are not GPU execution evidence.

## 2. ECS composition

- [x] Desktop 2D component dictionaries, deterministic queries, ordered system
  phases, events, snapshots, and hashes.
- [x] Desktop 3D compatibility ECS facade with component aliases, queries,
  ordered phases, Logic Block systems, packed motion, animation, hierarchy,
  triggers, and bounded physics.
- [x] Android sparse specialized sidecars for packed polar motion, graphs,
  animations, hierarchy, populations, and body physics.
- [x] Finish the semantic `polar_movement` adapter so Logic Blocks edit radius,
  angle, facing, turn speed, radial growth, and both accelerations instead of
  raw 64-bit words.
- [x] Prove semantic polar reads/writes produce matching packed words and
  transforms on desktop and native Android.
- [x] Compose X/Z velocity from the same packed polar state while preserving
  authored/gameplay Y velocity, so collision math sees the motion it renders.
- [x] Move optional desktop 3D components into world-owned sparse pools behind
  a live `MutableMapping`, without changing project JSON, snapshots, or hashes.
- [ ] Replace the remaining built-in 3D monolithic compatibility record with
  explicit component pools/archetype views without breaking compatibility.
- [ ] Add safe runtime add/remove component operations and corresponding
  child-readable Logic Blocks.
- [x] Add cached desktop component-query plans that choose the smallest sparse
  pool while preserving live tag/alive/active filters and lexicographic order.
- [ ] Add compact indexes/plans for shared graph bindings, tags, spatial
  queries, and render batches.
- [ ] Define ownership/conflict rules for every transform writer.

## 3. Log-encoded polar LUT as a render substrate

- [x] Two-u64 pose/motion component with rho20, theta18, tick14, heading12 and
  four signed 16-bit derivative fields.
- [x] Shared UGLUT2 binary16 log-encoded polar LUT with sine/cosine/radius
  reconstruction, scaled radius storage, strict parsing, and deterministic
  desktop/native CPU use.
- [x] Sparse KCPK records: 24 bytes per referenced scene node plus shared
  profiles; unused projects emit no KCPK asset.
- [x] Preserve raw half samples and radius scale for exact GPU upload.
- [x] Upload each referenced LUT profile once to GLES3.
- [x] Decode packed rho/theta/heading in the vertex shader.
- [x] In LUT mode, reuse the same seam-safe log-encoded polar LUT direction
  lookup for packed heading; keep Direct mode's trigonometry as the comparison
  baseline.
- [x] Batch compatible polar ECS entities by profile, mesh, and material and
  render them with `glDrawElementsInstanced`.
- [x] Interpolate previous/current packed poses for display without changing
  deterministic fixed-step simulation.
- [x] Keep CPU ECS state authoritative for Logic Blocks, physics, triggers,
  hierarchy, snapshots, and replay.
- [x] Provide three comparable modes: CPU transform fallback, GPU direct math,
  and GPU log-encoded polar LUT decode.
- [x] Log the selected mode, profile count, instance count, batch count, and
  fallback reason on the device.
- [x] Add bounded **Radial Burst (loops)** as the first local effect use: a
  packed local displacement compounds with one real prototype's packed anchor,
  using the Direct baseline or shared log-encoded polar LUT path before the
  final Bayer presentation pass.
- [x] Finish optional **Glow by distance** on the four non-Off Make Many recipes as the first
  material/field application: preserve the 128-byte recipe record, derive a
  repeatable material phase from lineage, sample the shared UGLUT2 direction
  lane in LUT mode, keep Direct as the comparison baseline, and feed bounded
  glow into lighting before the unchanged final Bayer pass. KCPR v1/v2 bytes
  must remain byte-identical; an asset opts into v3 only when at least one
  recipe uses the modifier, and mixed v3 assets may retain zero-tail non-Glow recipes.
- [ ] Extend suitable uses beyond orbit placement and Radial Burst: procedural
  material coordinates, field/effect sampling, scale-space LOD, and seeded
  polar geometry.  Do not force polar coordinates onto arbitrary topology,
  text, or ordinary UI data.
- [x] Implement the audited **Radial Burst (loops)** recipe as KCPR v2 only
  when used: seeded local packed-polar displacement around the real prototype,
  shared-LUT decoding of both anchor and local motion, bounded display-only
  staging, and Bayer only after final shading. Preserve byte-identical KCPR v1
  output for Ring/Spiral/Polar Field and do not mislabel it a one-shot event.
  Enforce 512 instances per recipe, 16 Burst recipes and 2,048 Burst instances
  per project; retain at most 64 editor preview copies globally and obey native
  maximum-visible plus the remaining particle budget.

## 4. Seeded compact operator recipes

- [x] UGTS 4.1-compatible SplitMix64 lineage and deterministic Populate Area.
- [x] Repeatable Random Number Logic Block with desktop/web/native agreement.
- [x] Add an optional strict 32-byte KCRP render-settings record carrying the
  render seed, polar execution mode, and Bayer projection parameters.
- [x] Define a compact bounded render-recipe asset containing seed, operator
  graph identity, profile references, limits, and error contract.
- [x] Generate many visual instances from one seed and recipe as render data,
  without copied ECS nodes or resident per-copy matrices; visible staging and
  the GL instance buffer are bounded by the configured visible-node cap rather
  than the recipe's total count.
- [x] Implement bounded Ring, Spiral, Polar Field, and Radial Burst display
  recipes through canonical typed operators with strict limits and dependency
  addresses. Legacy-only assets remain byte-identical KCPR v1; an asset uses
  KCPR v2 only when it contains Burst.
- [ ] Extend the bounded recipe vocabulary to sweeps, branches, particles, and
  material variations where those operators have a demonstrated use.
- [x] Verify the KCPR v3 Glow-by-distance operator meaning, binary32 pulse
  parameters, content address, seed phase, CPU fallback, Direct shader, LUT
  shader, editor preview, and malformed-input rejection with shared evidence.
- [x] Implement KCPR v4 **Grow glowing copies** as a second consumer of the
  exact same seeded log-radius Glow field: generated display copies multiply
  their authored/Burst scale by `1 + glow`, bounded to 1x..5x, while the real
  ECS prototype, collider, picking, snapshots and spatial lineage remain
  unchanged. Preserve the 128-byte recipe, 36-byte instance stride, v1-v3
  bytes/content identities, Direct/LUT/CPU reference semantics, and final-only
  Bayer projection; then prove editor stopped/Play parity, strict native
  parsing, fail-closed telemetry and an ARM64 build before claiming completion.
- [x] Make every generated item random-access by lineage so changing a count
  preserves the existing prefix.
- [x] Expose Off, Ring, Spiral, Polar Field, and **Radial Burst (loops)** through
  the child-readable Make Many Inspector, with discriminated controls,
  validated undo/redo, movement/spin ownership handoff, exact compactness/
  address inspection, prototype-only selection, and a global preview cap of 64
  generated copies.
- [ ] Add reusable Saved Object/Scene recipe presets without duplicating the
  canonical operator meanings.
- [x] Keep gameplay-promoted instances explicit; render-only generated members
  must never pretend to be independent ECS entities.

## 5. Bayer output projection

- [x] Locate and audit the sibling Bayer Direct 3.9.4 8x8 threshold definition
  and its evidence boundary.
- [x] Add an 8x8 ordered-dither stage at the end of the GLES post pass.
- [x] Offer Off, Gentle gradient smoothing, and intentional limited-palette
  modes with bounded strength/levels.
- [x] Apply Bayer only to presentation; it must never alter gameplay, ECS,
  topology, picking, or deterministic state.
- [x] Make the output mode editable in project settings and portable in a tiny
  validated render-profile asset.
- [x] Implement the portable record as optional `render_substrate.kcrp` and add
  child-facing Packed movement and Colour smoothing choices to the Render tab.
- [x] Add an opt-in desktop **Device Look (reference)** pass that preserves the
  exact CPU binary16 LUT composition, runs the packaged native Bayer shader at
  physical-pixel phase, labels the CPU/GPU boundary, and falls back to raster.
- [ ] Verify output-resolution anchoring, rotation/orientation stability,
  screenshot determinism where applicable, and absence of accidental crawling.
- [ ] Compare Bayer off/on for banding, visible patterning, GPU time, power, and
  thermal cost.  Do not call it motion or geometry smoothing.

## 6. Node graph coding and child-first authoring

- [x] Serializable typed Logic Blocks, portable Android VM, messages, timers,
  triggers, spatial sensing, animation actions, trace view, and bounded limits.
- [x] Add dedicated Mobile 3D **Read Movement** and **Change Movement** blocks
  that hide the `polar_movement` component name and expose only one of its
  seven friendly numeric fields.
- [x] Add the first dedicated child-facing Render recipe block: **Show or Hide
  Extra Copies** hides only Make Many display data through an ephemeral bounded
  mask, without exposing component/record names or deactivating the prototype.
- [ ] Add further Render recipe blocks only when they introduce real bounded
  capability rather than duplicating Show/Hide Object or static Inspector data.
- [ ] Add reusable subgraphs/functions with typed inputs and outputs.
- [ ] Add graph variables, arrays/collections, spawn/component actions, and
  explicit error paths without unbounded execution.
- [ ] Add further recipe presets such as sweeps, branches, Seeded Grove, and
  Bayer Palette only when each has bounded semantics and remains editable.
- [ ] Improve inline help, examples, undo/redo, keyboard navigation, color-blind
  cues, and readable error recovery for first-time learners.

## 7. Editor and desktop runtime

- [x] One-click Windows launcher, dark theme, Scene Tree, Inspector, viewport,
  Logic Blocks, animation timeline, build, deploy, and phone profiling actions.
- [x] Editable ordinary parent/child hierarchy with local Inspector and
  world-space viewport transforms.
- [x] Add the explicitly limited **Device Look (reference)** toggle for CPU-LUT
  authoring plus the shared Bayer presentation formula; Off leaves raster
  output unchanged and unavailable GL never breaks the editor.
- [ ] Replace the projected authoring viewport with the same GPU render path
  used by the game, including log-encoded polar LUT and Bayer preview modes.
- [x] Add child-facing project render settings and the Make Many seeded-recipe
  preview, including static file-byte/address compactness inspection.
- [x] Add `RUN_POLAR_GLOW_LAB.cmd` as a one-click 128-display Burst + Glow +
  Shared-LUT + subtle-Bayer manual project, generated only when absent and
  opened directly in the editor.
- [x] Add **Grow glowing copies** below Glow by distance with strict undo/save/
  load, child-readable generated-display-only help, exact stopped/Play preview,
  Glow-lit but never grown prototype parity, and a separate one-click
  `RUN_POLAR_GROW_LAB.cmd` comparison project.
- [x] Make the globally bounded Make Many preview follow its real packed ECS
  prototype during desktop Play, including hide/reactivate and authored Stop
  restoration, without generated ECS rows or fake interpolation.
- [x] Show Radial Burst halfway through its loop while stopped and advance it
  from the real post-step world tick during Play. Desktop intentionally draws
  fixed endpoints because it has no honest render-accumulator alpha.
- [ ] Add a clearer general component panel and live measured performance
  inspector; static recipe size is not a substitute for runtime profiling.
- [ ] Add docking/layout persistence, command search, asset import pipeline,
  multi-scene workflow, and stable crash recovery.
- [ ] Add a true desktop packaged player/export path independent of the editor.

## 8. Android / POCO proof and performance gates

- [x] Historical baseline: build, install, cold-launch, screenshot, and profile
  an earlier ARM64 GLES3 APK on the connected POCO X7 Pro / Mali-G720.
- [x] Historical five-node baseline: about 1.57 MB APK, 120 Hz compositor
  cadence, no observed large intervals or crashes in the bounded 15-second run.
- [x] Build an editable packed-polar GPU lab with 64, 256, and 1024 mover
  workloads sharing one recipe and log-encoded polar LUT where limits permit.
- [ ] Capture identical-work A/B runs for CPU fallback, GPU direct math, and GPU
  LUT, then Bayer off/on.
- [ ] Record warm-up, duration, frame p50/p95/p99, missed intervals, CPU, PSS,
  GPU/battery temperature, battery level, thermal status, crashes, exact APK
  hash, and exact asset sizes.
- [x] Implement a nonblocking `GL_EXT_disjoint_timer_query` source path with a
  bounded query ring, later-frame availability polling, disjoint invalidation,
  and explicit unsupported/runtime-failure reporting; never wait on the GPU.
- [x] Make the benchmark harness fail closed unless runtime logs prove the exact
  requested/effective mode and counts, zero unintended fallback, bounded
  materialization/Cartesian composition, and the requested Bayer settings.
- [x] Route benchmark Android generation through a short system-temporary
  workspace, then copy exact evidence back. This fixes the nested Windows path
  failure while leaving the original failed run intact.
- [x] Preserve numbered failed and successful build attempts append-only,
  including partial artifacts and errors, and validate the build-report base
  application ID against the actual Poco flavor-suffixed APK ID.
- [x] Add explicit SHA-1 native build IDs and normalized DWARF source/build
  prefixes, and prove two independent clean builds produce byte-identical APK
  and embedded native-library hashes.
- [x] Complete the unified build-only 15-case recipe matrix: 64/256/1024 CPU
  Off plus Direct/LUT with Bayer Off/Subtle. Preserve per-case APK and compact
  asset hashes plus a hashed manifest and comparison summary.
- [x] Define the separate 18-case Burst matrix: 32/128/384 across CPU, Direct,
  and LUT, each with Bayer Off/Subtle. The command is
  `python validation/benchmark_polar_render_poco.py --workload burst
  --include-cpu --build-only`.
- [x] Execute and preserve all 18 Burst build-only cases. Run
  `build/poco-polar-render-benchmarks/20260830T000848Z-seed-5eed3920c0dec0de`
  finished `built_only` with 18/18 cases in 272 seconds; each case records a
  1,690-byte KCPK, 240-byte KCPR and 32-byte KCRP plus its APK/evidence.
- [x] Add a fail-closed `--workload glow` POCO matrix harness for 64/256/1024
  Ring displays. It requires KCPR v3, the exact three Glow operator meanings,
  one real ECS prototype, the expected batch count (one for Direct/LUT, zero
  for CPU fallback), exact Glow/stride telemetry, and no generated ECS rows
  before accepting a physical run.
- [x] Add the matching fail-closed `--workload grow` definition. Require KCPR
  v4, exact slot-12 meaning/mask and native consumer, one real ECS prototype,
  `count - 1` generated Grow instances, `count` Glow instances, 36-byte stride,
  unchanged batch counts and no generated ECS rows before accepting a run.
- [x] Build and statically inspect the 128-display Burst + Glow handoff APK,
  preserving its exact ARM64 APK, KCPK/KCPR/KCRP, shaders, native build ID,
  signing/SDK/package evidence and hashes. It remains `built_only`.
- [ ] Prove timer-query support or its clean absence on the target device and
  capture valid Burst CPU/Direct/LUT and Bayer A/B samples on the POCO. Current
  source/host/ARM64-build evidence is not physical GLES/Mali execution.
- [ ] Run sustained 10-minute and 30-minute thermal tests before any broad
  performance or battery claim.
- [ ] Stress collisions, graphs, hierarchy, messages, seeded generation, and
  render batching together rather than profiling only an idle visual scene.

## 9. Packaging and release discipline

- [x] Current source test baseline: 627 passed and 145 subtests passed before
  the semantic-polar/GPU-render work began.
- [x] Re-run the focused native/Python/editor tests for the KCPR, strict proof,
  profiler, and benchmark-harness slice.
- [x] Re-run focused Python/native/shader-source conformance and reproducible
  build-harness checks after the heading-LUT and short-path integration.
- [x] Re-run the complete suite after integration: `python -m pytest -q`
  finished with 701 tests and 236 subtests passed in 165.86 seconds, exit 0,
  with no warning summary/output.
- [x] Re-run the final Burst-integrated suite: 739 tests and 252 subtests passed
  in 274.18 seconds with zero failures or skips. Focused changed/new paths are
  Ruff-clean; global Ruff retains 895 pre-existing legacy violations across 31
  files, none in the Radial Burst or validation files changed here.
- [x] Re-run the final Glow-integrated suite: 752 tests and 291 subtests passed
  in 203.32 seconds with zero failures or skips after updating one stale
  pre-Glow shader-source assertion to require the new uniform/call/reset path.
- [x] Rebuild the settled source/documentation as a wheel and sdist, verify all
  25 required conformance/Android-template paths byte-for-byte, and smoke-install
  the wheel in a fresh isolated Python 3.12 environment.
- [x] Keep generated Android-template `.gradle`, `.cxx`, `app/build`, and
  project `build` directories out of wheel/sdist contents even when local APK
  builds have populated those directories.
- [x] Rebuild the Burst-integrated distribution from a clean short-path source
  snapshot, byte-compare the packaged Python/native/shader sources, reject
  bytecode/build-cache contamination, and smoke-import Burst from Python 3.12.
- [ ] Archive exact source packs, APKs, screenshots, profiles, hashes, and
  inspection reports without overwriting evidence from earlier builds.
- [ ] Keep claims explicitly bounded: compactness is measurable; “AAA” requires
  content, rendering, tooling, sustained performance, and production evidence
  that do not yet exist.
