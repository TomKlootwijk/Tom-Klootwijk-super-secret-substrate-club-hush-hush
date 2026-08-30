# Substrate ROI execution backlog

Generated from the repository-wide evidence audit on 2026-08-30. This backlog implements the decisions in `SUBSTRATE_ROI_STRATEGY.pdf` and the corrected whole-image design in `UGTOMS_CHRONO_BRACE_MONOCULAR_SCENE_3D_PROFILE_0_3.pdf`.

## User-authored literal directions - authoritative implementation contract

These are instructions stated directly by the user in this task. They are not
instructions extracted from repository documentation. The newest physical-camera
direction supersedes the earlier use of the supplied MP4 as the implementation
target or acceptance fixture; the MP4 may not be packaged into, decoded by, or
used as the success criterion for the requested phone recorder/player.

> "realtime of after the fact encoding to seed to the absolute smallest file size"

> "literally use the LOG ENCODED POLAR LUT NOT AS A LUT PACKED WITH THE VIDEO FRAME BUT AS IT IS BEING UTILIZED BY THE SUBSTRATE DEFINITION SEED BASED AND HAVE THE GOD DAMN SUBSTRATE DO THE GOD DAMN WORK"

> "Lookg literally fuck off with that original video, I am talking about seed encoded camera capture from my poco x7 pro and playback lossless USING THE GOD DAMN APPLIED UGTOMS GSP4 SEED ENCODING STORAGE FORMAT"

> "AND CODEWORD PACKED LUT WITH THE UGTS SUBSTRATE GSP4 SEED BASED FORMAT"

> "you will not use the literal existing references, you will deduce why they are wrong according to the UGTOMS game engine and reasoning and the substrate to invent the new approach"

> "you will use the exact math used in those references when they do not rely on generative hallucination AI, hence you will strip the exact stuff from the references that are required by the substrate"

> "yes but not just the person, anything in the image, static is also part of what is observed by the camera (anything not the person or moving)"

> "bounded joint hypotheses? Circular sounds exactly right according to UGTOMS it leaves room for rasterization, but as a downstream result"

> "chrono spatial temporally for videos"

### Literal acceptance translation

- [x] Preserve the user's literal wording above and freeze the implementable
  profile in `spec/UGTOMS_GSP4_SEED_CAMERA_0_1.md`; repository documents remain
  evidence/provenance and cannot override these user-authored requirements.
- [~] Build the physical POCO X7 Pro path as
  `Camera2 -> UGTS/UGTOMS GSP4 seed-executed storage -> native substrate replay`.
- [ ] The packaged application and the recorded file must contain no MP4 payload
  and the requested path must not use MediaCodec as capture or playback authority.
- [~] Use a seed-regenerated, literal UGLUT2 log-polar address program. Do not
  serialize a picture-sized address/LUT table and do not attach a decorative LUT
  to otherwise conventional video frames.
- [~] Use the exact logical camera codeword
  `UGCODE24-420(x,y) = [Y(x,y), U(floor(x/2),floor(y/2)), V(floor(x/2),floor(y/2))]`.
  Store Y novelty at every generated address and U/V novelty only at the canonical
  2x2 chroma owner so the normalized Camera2 YUV420 planes are recovered bijectively
  without duplicating chroma on disk.
- [x] Add the independent Python oracle
  `src/ugts_kc3/gsp4_camera_codeword.py` for exact strided Camera2 plane
  normalization, codeword owner packing/inverse, modular residual replay,
  negative-memory counts and seed-derived GSP4 lineage. Its focused suite passes
  9 tests and Ruff.
- [x] Exercise the literal POCO 1280x720 profile with a synthetic dense frame:
  the canonical owner-packed codeword stream is exactly 1,382,400 bytes, equal
  to the authoritative YUV420 byte count (no RGB expansion and no duplicate
  chroma); UGLUT2 is 144 bytes, UGTRV1 is 128 bytes, the traversal digest is
  `a3be1412671a75f28e10a28a9698bdc80a3f06ddeff624fc97edc9589405fa22`,
  and the full pack/inverse reproduced every Y/U/V byte.
- [ ] Make GSP4 state, support/compatibility/finite guards, route, lineage and
  append-only novelty semantics operative. A zero exact residual is negative
  memory and emits no novelty; a nonzero camera observation remains exact evidence.
- [ ] Support both bounded real-time emission and after-the-fact RTX 5070 Ti search
  for a smaller exact seed/program. Never silently drop a captured frame. If the
  phone cannot sustain the selected exact path, losslessly spool or stop with an
  explicit failure receipt.
- [ ] Playback must reproduce every authoritative dense Y, U and V byte, accepted
  sensor timestamp and declared metadata byte-for-byte before any display-only
  YUV-to-RGB conversion.
- [ ] Keep all observed content in scope: people, other moving objects, and the
  non-moving image regions. Non-moving or mask-complement pixels are observations,
  not automatically certified static geometry or empty space.
- [ ] Use no generative reconstruction, amodal completion or invented hidden
  geometry. Classical/OpenCV equations may propose and contract bounded 3D/4D
  hypotheses; unsupported space remains `UNKNOWN`, and rasterization is downstream.
- [ ] Own recorder/player behavior through an ordinary editable Grove scene node
  and sidecar binding. No bootstrap, hidden global instance or fullscreen-only
  special case.

## Decision

- [ ] Treat all ROI scores as **evidence-adjusted engineering ROI**, not proven financial return. The repository contains no customer, price, acquisition-cost, or support-cost evidence.
- [ ] Run one paid, bounded workflow experiment before creating another general-purpose format.
- [ ] First commercial experiment: package the KSGP1 local ground-station pass planner as a deterministic CLI with conventional inputs and CSV output.
- [ ] First exact-Grove product proof: turn the preserved packed-polar Android workload into an editable, signed visual or microgame demonstrator without expanding it into a general engine.
- [ ] Keep custom packed formats profile-specific and internal. Publish standards adapters, manifests, verifiers, and conventional materialized outputs.
- [ ] Do not create a universal `.ugtoms` transcoder. A by-reference conformance envelope is allowed only after its promotion gates are met.
- [x] Treat the implemented `UGTOMS-CSO-CHRONO-VIDEO-0.1-PROPOSAL` compiler as a narrow observation/proposal capability, never as a scanner, standard, unique reconstruction claim, or proof of physical 3D. The broader CSO/HCO/Chrono-BRACE contractor remains proposal work.
- [ ] Treat `UGTS_VSTL_MONOCULAR_CHRONO_LITERAL_HUMAN_0_1.pdf` as historical and architecturally superseded. Do not revive VSTL, a cross-time sheet, or an evidence-ledger object model.
- [ ] Use named vision/body systems only as mathematical provenance, falsification references, or optional frozen-hash proposal seeds. Strip exact non-generative equations into native typed operators; never import their object ontology or allow learned/completed output to write ECS authority.
- [ ] Keep negative memory strict: predictable canonical states are not stored. Retraction is a separate accepted novelty event; missing masks, occlusion, non-observation, or mask complement never mean empty space.

## Status and evidence rules

- `[ ]` not started
- `[~]` active or partially evidenced
- `[x]` completed with a named artifact
- A task is not complete because a test count is high. Completion requires serialized meaning, deterministic reconstruction or behavior, bounded failure/error, and captured evidence.
- Preserve chronology. A later physical artifact may supersede a stale status paragraph, but evidence from one component version must never be transferred to another.
- Use `component_version_id::mechanism_id`; never use a bare version number or bare `Mnnn` as library-wide identity.

## P0 - UGTOMS Chrono Scene/Object / Chrono-BRACE

Chrono-BRACE means **Bounded Ray-tube Adaptive Chart Evidence**. Its core is a bounded circular/fixed-point constraint process over camera, static/dynamic classification, target association, scale gauge, scene/object/chart motion, visibility, and deformation. Every decoded pixel footprint enters coverage as guarded static support, a moving-object branch, an occluder, unclassified, or unknown. A human object adds articulated HCO controls only when applicable. Rasterization is downstream and may feed a later proposal residual, but rendered pixels cannot certify themselves as observations.

### P0 correction logged - substrate-native pixel codewords

- [x] Clarify the seed-only size boundary. The current operator carries two
  `uint64` values (16 bytes). If `recipe_seed=1` is frozen by the profile, the
  minimum stored seed payload is one 64-bit root seed: exactly 8 bytes. The
  current self-verifying `UGTRV1` record remains 128 bytes because it also binds
  dimensions, operator meaning, UGLUT2 dependency and regenerated traversal.
- [x] Added the literal 8-byte fixed-profile seed artifact
  `sam_2353410928515192.ugtoms-traversal-seed64` and canonical pack/unpack tests.
  It is explicitly traversal-only. If used as a by-reference selector, bind it
  to a collision-resistant content-addressed evidence object; the 64-bit seed
  itself is not a standalone video or authoritative content identity.
- [ ] If a tiny seed capsule is used operationally, define it explicitly as a by-reference
  selector for a content-addressed evidence object. Never describe that 8-byte
  selector as a standalone lossless video: the exact residual evidence must be
  present in the `.ugtc4d`, an external store, decoder assets, or memory.
- [ ] Reject any seed-only claim unless the exact source RGB24+PTS stream is
  regenerated without an undeclared model, baked-in corpus, network object or
  residual. Moving the observations into an application/model is relocation,
  not compression; fabricating absent observations is forbidden.
- [x] Validated the user's correction that each raster sample can be treated as
  one reversible 24-bit, three-lane substrate codeword at a seed-regenerated
  UGLUT2 chrono-spatial address. Do not serialize a per-pixel LUT and do not
  describe an ordinary RGB frame with a LUT attached as the finished codec.
- [~] The exact baseline is now authored as custom `UGTC4D/UGFRM2/UGRICE1`:
  122,660,608 bytes, 229/229 accepted PyAV RGB24+PTS frames replayed, a shared
  144-byte literal UGLUT2, one 128-byte `UGTRV1` seed/operator recipe, zero
  stored pixel-permutation bytes, and no H.264/AV1/ZIP payload. This is 19.3734%
  of 633,139,200 decoded RGB bytes but 10.11025 times the 12,132,305-byte lossy
  source MP4. It is decoded-observation losslessness, not MP4-bitstream,
  sensor/photon, or physical-3D losslessness.
- [x] Benchmarked 29 GSP4-inspired reversible lane/bit configurations across all
  229 frames: 6,641 frame/config UGRICE replay plus RGB round trips, zero
  failures, and an exhaustive 16,777,216-codeword check for the winning q709
  transform. Best all-intra stream is q709 `[Y,Cb,Cr]` at 122,773,583 bytes.
  Retaining temporal frame 114 gives a measured 122,327,747-byte entropy sum and
  led to the authored q709 file at 122,540,032 bytes. A fresh process re-decoded
  the original MP4 and matched all 229 RGB24 frame hashes and half-open PTS
  intervals; file SHA-256 is
  `f1a87daabab4948cf1ad47bc6660963f10470eed3e88516619b1e2a84564ccd5`.
  The selected modes are 227 q709 frames, one older-lift frame and one temporal
  frame. This is the smallest authored exact result among the tested profiles,
  not a global or information-theoretic optimum.
- [ ] Keep DINOv3 or any learned feature output proposal-only. A learned feature
  may select a predictor/context, but it cannot replace an exact residual or
  certify geometry because it is not a bijection back to the observed RGB.
- [x] QR-like packing was falsified as a compression win for this fixture under
  the same UGRICE layer: lane bitplanes used 316,524,893 bytes, 24-bit grouped
  bitplanes 344,847,805 bytes, and seed/address XOR 633,216,144 bytes. Reject a
  candidate if its presentation merely rearranges bits
  without reducing total custom entropy, or if rho/theta/lineage consume the
  same 24 bits without an independently recoverable exact color residual.

### Implemented fixture snapshot - 2026-08-30

- [x] Added `src/ugts_kc3/chrono_video.py`, `compile-chrono-video`, and
  `verify-chrono-video`; added the versioned contract and manifest schema under
  `spec/`.
- [x] Added independent `UGCVLUT1` RGBA16UI/Q8 pixel-address semantics without
  changing UGLUT2. Python rejects bad magic/version/length/hash, NumPy is the
  integer oracle, and PyTorch CUDA must match it byte-for-byte.
- [x] Compiled the supplied MP4 into
  `UGTOMS_CHRONO_VIDEO_SAMPLE_0_2_SOURCE_LUT_FINAL/`: 229 exact-PTS
  observations, 58 analyzed/preview slices, 57 proposal slices, 57
  joint-hypothesis slices, and 921,600 pixels covered once per observation.
  The bundle embeds a byte-identical 12,132,305-byte source copy and separate
  strict `UGCVPTS1` source/preview timelines.
- [x] Verified the full 1024x512 CUDA run at 396.88 MiB peak allocated VRAM,
  12.54 seconds wall time, and maximum CPU/CUDA byte difference zero. These are
  one-run engineering measurements, not a benchmark distribution.
- [x] Added one editable, ordinary, non-dynamic Grove observation root and
  hash-verified Android asset packaging. Native C++ verifies `UGCVLUT1` and
  `UGCVPTS1`, validates source/input/output PTS, and keeps two explicit modes:
  authoritative source + live Q8 LUT, or already-polar derived preview with LUT
  reapplication forbidden.
- [x] Implemented API-26 MediaCodec/MediaExtractor -> SurfaceTexture/external-OES
  playback. Two owned RGBA8 slots publish ordinal zero before the clock anchor,
  stage at most one verified next ordinal, swap on the integer half-open
  selector boundary, discard stale outputs, and log any missed boundary as
  `physical_exact_timing=false`. Runtime failure closes decoder resources,
  remains fail-closed, and leaves the ordinary editable scene alive.
- [x] Built and audited the 19,036,992-byte POCO-debug ARM64 APK, SHA-256
  `C9CF4D757A8961A45675A95C4C6F62CC1811F1DB188E4DD7F01F13F7E9A89DD4`.
  All 16 declared chrono assets (22,399,330 bytes) match the APK, both MP4s are
  ZIP-stored, the package is 16 KiB aligned and v2 debug-signed, and the AArch64
  library links `libmediandk.so`.
- [x] Restricted the Android build report to 90 immutable exported-source
  inputs; volatile Gradle/CMake/IDE/build state is excluded and all 90 ledger
  entries still match after the APK build.
- [ ] Attach the POCO over ADB; install/cold-launch; require the native
  source/LUT/timeline/PTS receipts and zero late-boundary errors; verify shader
  compilation, SurfaceTexture transform/crop/orientation, decoder component,
  visible output, PSS, frame cadence, thermals, crash buffer, and fallback. No
  physical-phone, photon-time, or device YUV-to-RGB byte-parity claim exists yet.
- [ ] Either pre-stage ordinal zero before an explicit LOOP wrap or keep LOOP
  best-effort and visibly labelled. The delivered source and preview timelines
  are `ONCE_HOLD_LAST`, so this limitation is inactive in the audited fixture.
- [ ] Add measured camera calibration/Camera2 timing or a calibration target,
  then implement the outward-rounded circular contractor before promoting any
  physical static, moving-object, or human support.

### Authority, time, and exact-math registry

- [~] The scoped chrono-video contract and manifest JSON Schema are implemented; a complete scene/object contract, separate `HUMAN_CHRONO_OBJECT_CONTRACT.md`, and full eight-block mapping remain open.
- [ ] Define one scene-capture authority, guarded static-scene support, stable moving-object branches/entities, geometric chart/material lineage, one-writer ownership, and per-field `STATIC_SUPPORTED`, `OBJECT_OBSERVED_PARTIAL`, `PROXY_ONLY`, `DERIVED`, `BOUNDED_SUPPORT`, `UNCLASSIFIED`, or `UNKNOWN` status.
- [x] Define and implement the all-pixel coverage rule. “Not the selected person,” “not detected as moving,” and mask complement are not synonyms for static background; every tile stays canonical `UNKNOWN`.
- [~] Exact decoded PTS/time base and immutable commit/knowledge sequence are implemented. Exposure/rolling-shutter row intervals remain unavailable for the supplied MP4 and must be added for calibrated capture.
- [ ] Key every materialization by `(revision_hash, target_source_pts, knowledge_cutoff_seq, policy_hash)` and support causal versus sealed-offline historical views without future-evidence leakage.
- [ ] Create an exact-math operator registry. Each entry must bind primary source/equation, coordinate convention, units, normalized-versus-axial depth semantics, gauge, assumptions, input uncertainty/bounds, deterministic implementation/hash, failure state, and authority class.
- [ ] First operator set: coded-pixel footprint and row-aware ray tube; mask-set/IoU; normalized feature cosine and deterministic candidate matching; epipolar/Sampson residuals; cheirality/parallax; robust reprojection triangulation/refinement; affine depth/point alignment; deterministic articulated transform composition; novelty fold.
- [x] The implemented compiler uses no diffusion, amodal/content completion, Gaussian/novel-view generation, learned hidden body/texture, learned identity/shape space, pose corrective, or learned metric scale.

### Native bounded circular core

- [~] Joint hypothesis records now cover camera/calibration, static/dynamic class, object association, scale gauge, scene/object/chart motion, visibility, deformation, timing, and depth. They correctly remain `UNBOUNDED_UNKNOWN`; contraction/promotion is not implemented.
- [ ] Implement an inclusion-sound, outward-rounded contractor with canonical branch/prune order, capacity/budget limits, contradiction receipts, and a fixed-point/budget-stop result.
- [x] Keep physical support `UNBOUNDED_UNKNOWN` whenever calibration, timing, pose, gauge, or depth lacks finite bounds; the bundle verifier rejects promotion in this fixture.
- [ ] Promote support only when all surviving branches agree within spatial tolerance; genuinely independent original-observation groups pass; cheirality, parallax, reprojection, rigidity/seam, occlusion, reduced-rank, eigenvalue, and condition-number guards pass; and gauge/units are declared.
- [ ] Treat silhouettes as motion-dependent visual-hull bounds, not surface points. Treat chart coordinates as parameterization, not material identity; material lineage starts at an accepted support event.
- [ ] Split/discontinue charts for moving objects, vegetation/water/reflections, cloth, hair, skin sliding, seams, non-rigidity, crop gaps, or contradictions. Never average incompatible static/object branches into an attractive scene.
- [ ] Define visibility as `VISIBLE`, `OCCLUDED`, `OUT_OF_VIEW`, or `UNKNOWN`; require a certified nearer occluder for `OCCLUDED` and never carve free space from mask complement alone.
- [ ] Freeze canonical novelty events and ordering: root/chart pose delta, chart open/split/discontinuity, support birth/tighten/split/retract, owner handoff, and checkpoint seal. An equal pre/post state emits no event.
- [~] Proposal-label novelty is stored only on change, with no implicit retraction, and the source remains external by hash/reference. Authoritative support novelty/checkpoint folding awaits the contractor.

### Editable engine object and downstream outputs

- [~] The first fixture is an editable project with one ordinary observation root and strict sidecar binding, not a bootstrap. Inspector scrub controls and promoted moving-object roots remain open because nothing is promoted yet.
- [x] Current KC3D, KCAN, KCHI, KCPK, KCPR, KCRP, and UGLUT2 meanings remain unchanged; chrono video uses separate `UGCVLUT1` and JSON/JSONL sidecars.
- [ ] Make the CSO camera/object fold systems sole writers of their declared fields and execute before current packed movement/rigid animation. Static support never writes moving transforms. Use integer/rational PTS selection rather than floating `world.time` as evidence time.
- [ ] Implement same-time surfel, sparse-voxel, observed-open-mesh, authored-proxy, hybrid, and raster materializers. Every face/voxel sample must share one source time; stitching, closure, smoothing, collision, and hidden topology remain `PROXY_ONLY` or `DERIVED`.
- [x] Homography-compensated raster residuals return only `PROPOSAL_ONLY`; canonical tiles remain `UNKNOWN`, and the verifier rejects geometry/static commits.
- [~] JSON/JSONL receipts plus an H.264 raster preview are implemented and the original MP4 remains reprocessing truth. glTF/GLB, PLY, OpenUSD/Alembic, and OpenVDB must wait for genuinely promoted geometry.
- [ ] Defer compact binary CSO/object/HCO sidecars and a by-reference UGTOMS manifest until editable JSON works, two readers agree, malformed inputs fail closed, and measured seek/runtime/distribution gains beat conventional baselines.

### Supplied-video fixture and promotion gates

- [x] Bind `C:/Users/Tom/Videos/KasiaDansGedicht/sam_2353410928515192.mp4` by SHA-256 `1867BAFA7C80C31F18856525CBF580EDAA36D524270B1FA59CC643B51964CBFD`; preserve 1280x720 H.264 Main, 229 frames, 62500/2489 fps, 1/1,000,000 time base, and exact frame PTS in the fixture receipt.
- [x] Keep the fixture fail-closed: no intrinsics, distortion, metric scale, IMU, depth, or shutter/exposure calibration means no exact physical rays, accepted static-scene 3D, metric camera motion, accepted moving-object/person 3D support, or full body.
- [~] The model-free baseline now has all-pixel coverage, deterministic feature/homography residual proposals, static/dynamic/ambiguous branches, frame-local motion charts, human-specialized UNKNOWN records, proposal novelty, and same-time raster output. Manual constraints, persistent associations, calibrated camera/static support, and the bounded contractor remain open.
- [ ] After the core is independently usable, optional learned mask/feature/depth/pose candidates may be added only with model/code/checkpoint/config/license hashes and removable proposal components. Adapter removal must not change schema, authority, or replay meaning.
- [ ] Compare equal-quality objectives against original video, glTF curves, USD/Alembic geometry caches, OpenVDB, and conventional point/voxel storage. Measure bytes, residual density, edit time, random seek, replay equality, screen/world error where calibrated, CPU/GPU cost, memory, and privacy burden.
- [ ] Kill or narrow the profile if uncertainty rarely contracts, the conventional baseline is simpler/equivalent, novelty density approaches source/cache size, circular contraction is unstable or too expensive, or users gain no material editability/seek/provenance benefit.
- [ ] Keep body measurement, medical, forensic, biometric/gait identity, garment fit, inverse biomechanics, and safety uses out of scope without separately calibrated/regulated validation.

## P0 - commercial and evidence hygiene (days 0-14)

### Rights, privacy, and naming

- [ ] Create a root rights inventory covering every component, third-party dataset, font, model, texture, binary, report, and generated artifact.
- [ ] Have the owner or counsel choose and add the root license, NOTICE, and third-party notices. Do not infer a corpus-wide grant from submodule licenses.
- [ ] Produce a public/redacted copy of the cross-domain review; remove private personal identifiers and scan all release candidates for personal data.
- [ ] Refresh the component registry so Grove 3.9.2, KSEED 4.1, Atlas 4.1.1, KLB 0.5/0.6, GSP4 0.5, Foundation 5, GPU Native 1.1, KC 4.2, Go, and Chess have unambiguous component IDs and lineage.
- [ ] Record absent or reconstructed sources explicitly. In particular, preserve the Atlas 4.1.1 statement that it is a clean reimplementation and do not attribute KSEED 4.1 device evidence to it.

### Claims and evidence registry

- [ ] Create `evidence/registry.json` with: evidence ID, component ID, date, device/host, source hashes, verifier command, capability profile, status, limits, and superseded status references.
- [ ] Freeze a one-page claim matrix for each launch lane: claim, supporting artifact, nonclaim, expiry/recheck condition, and owner.
- [ ] Reconcile Grove `BUILD_STATUS_3_9_2.md`: retain the dated 763-test/305-subtest and physical Grow records, and mark older contradictory tail sections as historical.
- [ ] Reconcile KSEED 4.1 README/release status with the dated 2026-08-28 Poco device run. Keep the 23.29% frame-overwrite defect prominent.
- [ ] Reconcile KLB status files with preserved v0.5 physical RTX evidence and keep v0.6 network-GPU acceptance explicitly open.
- [ ] Add one read-only verification command per preserved proof: KSGP pass CSV, Grove Grow bundle, KSEED log, GPU Native physical report bundle, HTML5 build report, and GSP4 manifest.
- [ ] Require every public benchmark to include a conventional baseline at equal behavior/error and a clear workload contract.

### Format registry

- [ ] Create a format registry for KC3D392, UGECS1, UGLUT2, KCPK392, KCPR392, KCRP392, KCVG001, KCAN392, KCHI392, KCSP392, KSEED, KSGP1, UGKG, UGNL, UGDEPLOY, G64/G32/G24, E16/E32, and UG5N.
- [ ] For every format record: magic, version, owner component, authority level, units/frames, limits, required capabilities, reader/writer paths, fixture hashes, migration policy, and failure behavior.
- [ ] Mark JSON/project records as editable authority where applicable; mark APK, ZIP, wheel, PLY, glTF, USDA, PDF, and HTML as distributions or materialized derivatives unless a component contract says otherwise.
- [ ] State that SHA-256 and hash chains prove byte integrity/lineage only; they do not prove authorship, authorization, trusted time, or legal ownership.

## P1 - launch lane 1: local pass planner (days 15-45)

### Product boundary

- [ ] Define the named user and decision: a local operator needs deterministic acquisition/loss windows for a bounded object list and station, without materializing a dense trajectory horizon.
- [ ] Freeze inputs as OMM/CSV plus explicit station/time/Earth-model metadata; keep KSGP1 as the internal canonical payload; emit sorted CSV and JSON evidence.
- [ ] Publish the workload boundary: direct/query-first is for first or sparse queries; resident dense materialization can win repeated queries.
- [ ] Do not call avoided trajectory materialization lossless compression.

### Packaging

- [ ] Ship a lightweight CLI package that can inspect, verify, and produce pass events without CUDA or ML dependencies.
- [ ] Add a Python wheel with pinned dependencies and a clean-install verification command.
- [ ] Add an OpenAPI description only after the CLI contract is frozen; an OCI service is optional, not the first milestone.
- [ ] Include a conventional CSV output fixture, a JSON manifest, a KSGP1 fixture, hashes, units/frames, failure states, and an independent SGP4 comparison.

### Acceptance and kill gates

- [ ] Reproduce the preserved 717-event local-pass corpus with exact sorted event identity and no truncation.
- [ ] Re-run a physical GPU preset and require direct/dense event equality, zero propagation failures, and captured device/driver/timing evidence.
- [ ] Measure end-to-end latency including parse, propagation, event extraction, serialization, and startup. Report p50/p95 and memory.
- [ ] Test at least one external OMM corpus and one independent SP3/reference trajectory with declared tolerances.
- [ ] Interview 3-5 target users and obtain one paid design-partner commitment before building multi-station optimization.
- [ ] Kill or reposition the product if a conventional library is faster, simpler, safer, and equally reproducible for the target workload.

## P1 - launch lane 2: exact-Grove Android demonstrator (days 15-60)

- [ ] Start from the editable `packed_polar_gpu_lab_3d` scene and preserved Grow recipe; do not create a hidden code-only/bootstrap scene.
- [ ] Preserve the exact chain: seed + bounded recipe + packed ECS -> shared UGLUT2 -> instanced/procedural GPU work -> Bayer projection.
- [ ] Make recipe, palette/material bands, instance count, and seed editable in the existing studio/scene data.
- [ ] Produce a release-signed APK or reusable AAR only after signing ownership and update policy are decided.
- [ ] Repeat device evidence on at least three GPU/device classes with thermal and electrical power measurements, usable GPU timing where available, and zero fallback.
- [ ] Add a causal Direct-vs-LUT and Glow-vs-Grow matrix; the preserved one-pair comparison is not causal proof.
- [ ] Keep KCPR display members render-only unless gameplay entity semantics are explicitly designed and verified.
- [ ] Do not claim GLB import, skeletal animation, production physics, streaming LOD, Vulkan integration, or general PCG.
- [ ] Stop engine expansion unless a design partner specifically values packed procedural presentation over a conventional engine workflow.

## P1 - launch lane 3: offline HTML5 (days 15-45)

- [ ] Rebuild the Elizabeth vector example from canonical `project.json` and capture the output hash/build report.
- [ ] Verify offline launch in a clean browser with keyboard, gamepad, touch, audio, collision, save, and reload.
- [ ] Add a repeatable accessibility pass for keyboard-only operation, focus visibility, contrast, captions/text equivalents, reduced motion, and screen-reader landmarks.
- [ ] Keep the promise to the implemented 2D event/graph runtime. Do not imply browser parity with the mobile 3D packed-polar renderer.
- [ ] Test one concrete paid use case: interactive technical explainer, training module, or bounded educational game.

## P1 - KSEED evidence logger (days 30-75)

- [ ] Fix capture scheduling/buffering so frame overwrite is below the agreed target; report arrival, processed, overwritten, and keyframe rates separately.
- [ ] Define the product as an integrity-checked observation/index log, not a scanner, SLAM replacement, image codec, or retained photograph archive.
- [ ] Add operator annotations/checklists, calibrated time/location, capture policy, and explicit links to selected evidence files.
- [ ] Add optional encrypted selected images or residuals when the use case requires visual proof; raw photons remain external to the compact log.
- [ ] Add hardware-backed signing and an external trusted-time/anchor option. Keep hashes distinct from signatures.
- [ ] Export conventional inspection derivatives: JSON/JSONL, GeoPackage for offline spatial handoff, and PLY only where geometry has actually been reconstructed.
- [ ] Validate one field-maintenance or repeat-pass workflow with false-positive/false-negative costs and a conventional baseline.

## P1 - GPU event-filter SDK (days 30-75)

- [ ] Freeze the fixed query semantics and supported record/capability profiles for G64/G32/G24 and E16/E32.
- [ ] Publish a minimal C/C++ ABI plus JSON query/output fixtures and a CPU oracle.
- [ ] Require fail-closed overflow and parity for every promoted profile.
- [ ] Benchmark only workloads with demonstrably sparse event yield; include transfer, commit, compaction, and readback costs.
- [ ] Do not transfer UGTS-GN Vulkan/CUDA results to Grove GLES. Treat them as separate components until an integration proof exists.

## P2 - incomplete, high-upside modules (days 60-120; conditional)

### Multi-station scheduling

- [ ] Start only after the local pass planner has a design partner.
- [ ] Define station resource conflicts, deterministic tie-breaking, link-budget boundaries, data freshness, and replay semantics.
- [ ] Prove two-or-more-station conflict resolution on a dated corpus with event parity and no hidden dense precompute.

### By-reference UGTOMS conformance envelope

- [ ] Define a small JSON Schema envelope containing profile ID, original payload hash/bytes reference, units/frames, tolerances, capability requirements, provenance, residual/literal reference, and verifier command.
- [ ] Wrap KCPR, KSGP1, KSEED, and one GPU record corpus without transcoding or changing their bytes.
- [ ] Implement two independent readers and malformed/unknown-profile fail-closed fixtures.
- [ ] Demonstrate exact round trips and conventional materialization for four profiles.
- [ ] Promote only after two unrelated domains and two independent implementations use it. Until then, do not assign a universal `.ugtoms` payload format.

### GSP4 spatial gate

- [ ] Split deterministic graph/manifest inspection from optional PyTorch proposer dependencies.
- [ ] Add GeoPackage import/export and GeoParquet 1.1 analytics output; pin the stable profile.
- [ ] Treat the ML model as proposal-only; current smoke accuracy near 0.55 is not product authority.
- [ ] Close physical GPU validation and test a real asset/proximity/anomaly dataset before operational claims.

### Deterministic knowledge conduit

- [ ] Limit the first pilot to one bounded technical manual with novice, technician, and auditor views.
- [ ] Ingest PDF/DOCX/HTML as sources; normalize authoritative claims to versioned JSON/JSON-LD with provenance and UNKNOWN/fail-closed paths.
- [ ] Keep an LLM optional and non-authoritative: presenter/proposer only.
- [ ] Produce a human PDF view plus a machine-readable answer receipt; PDF is not the authority.

### Accessible Definition Breaker

- [ ] Build only a bounded hybrid prototype: printable PDF/SVG cards + project JSON + offline HTML.
- [ ] Co-design and validate with children, disabled users, educators, and assistive-technology specialists before product claims.

## Public format policy

| Boundary | Use now | Rule |
|---|---|---|
| Contracts/configuration | JSON + JSON Schema 2020-12 | Version, validate, canonicalize only where the profile defines it. |
| Event exchange | CSV for simple tables; JSONL for replay/receipts | State units, order, time basis, and failure state. |
| Provenance | JSON-LD 1.1 with a W3C PROV mapping | Use for exchange; do not force RDF into hot runtime records. |
| Spatial offline | GeoPackage 1.4 | Prefer for mobile/offline field handoff. |
| Spatial analytics | GeoParquet 1.1 | Pin stable 1.1; do not default production to an RC. |
| 2D/browser | SVG + self-contained HTML | Keep canonical project JSON beside the materialized output. |
| 3D interchange | glTF 2.0.1 now; GLB only after implementation | Current export is static presentation, not runtime authority. |
| Orbit exchange | OMM/OEM/CSV and SP3 reference checks | Keep KSGP1 internal and name the dynamical/Earth model. |
| Distribution | Python wheel, APK/AAR, optional OCI/OpenAPI | Distribution containers require manifests and real signatures for release. |
| Human reports | PDF | Never make a PDF the only machine authority. |

## Stop list

- [ ] Do not build a new universal binary format before the conformance-envelope gates close.
- [ ] Do not present seed/recipe size divided by baked output size as whole-product compression when mesh, texture, decoder, or reconstruction work is omitted.
- [ ] Do not claim authenticity, ownership, or trusted time from a content hash alone.
- [ ] Do not claim KSEED retains images, scans a scene, or proves metric SLAM.
- [ ] Do not claim KSGP wins resident repeated-query workloads without measurement; preserved evidence shows dense reuse can win.
- [ ] Do not productize SARA as secret recovery, signing, or a wallet.
- [ ] Do not market Go/Chess packages as solved; their full roots remain UNKNOWN/UNRESOLVED.
- [ ] Do not claim full 4D, general PCG, GLB/skeleton, full OpenUSD, Unity/Godot, production physics, or Vulkan Grove support.
- [ ] Do not add Unity/Godot integration until a customer and payload profile justify it. If Unity 6.3 is ever chosen, integrate into an editable scene and never use a bootstrap.

## 90-day decision record

- [ ] Day 14: rights/privacy/version/evidence blockers have named owners and dated resolution plans.
- [ ] Day 30: KSGP CLI reproduces the preserved fixture and installs cleanly without GPU/ML extras.
- [ ] Day 45: one external orbit corpus and conventional baseline are measured; 3-5 interviews complete.
- [ ] Day 60: exact-Grove signed demonstration and multi-device measurement plan are reviewable.
- [ ] Day 75: one paid or explicitly budgeted design partner exists, or the primary lane is stopped/repositioned.
- [ ] Day 90: choose exactly one: scale local pass planning, pivot to field evidence logging, or remain a conformance/benchmark library. Record why the other lanes are deferred.
