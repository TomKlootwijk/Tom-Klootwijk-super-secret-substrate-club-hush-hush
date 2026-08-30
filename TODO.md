# Substrate ROI execution backlog

Generated from the repository-wide evidence audit on 2026-08-30. This backlog implements the decisions in `SUBSTRATE_ROI_STRATEGY.pdf`.

## Decision

- [ ] Treat all ROI scores as **evidence-adjusted engineering ROI**, not proven financial return. The repository contains no customer, price, acquisition-cost, or support-cost evidence.
- [ ] Run one paid, bounded workflow experiment before creating another general-purpose format.
- [ ] First commercial experiment: package the KSGP1 local ground-station pass planner as a deterministic CLI with conventional inputs and CSV output.
- [ ] First exact-Grove product proof: turn the preserved packed-polar Android workload into an editable, signed visual or microgame demonstrator without expanding it into a general engine.
- [ ] Keep custom packed formats profile-specific and internal. Publish standards adapters, manifests, verifiers, and conventional materialized outputs.
- [ ] Do not create a universal `.ugtoms` transcoder. A by-reference conformance envelope is allowed only after its promotion gates are met.

## Status and evidence rules

- `[ ]` not started
- `[~]` active or partially evidenced
- `[x]` completed with a named artifact
- A task is not complete because a test count is high. Completion requires serialized meaning, deterministic reconstruction or behavior, bounded failure/error, and captured evidence.
- Preserve chronology. A later physical artifact may supersede a stale status paragraph, but evidence from one component version must never be transferred to another.
- Use `component_version_id::mechanism_id`; never use a bare version number or bare `Mnnn` as library-wide identity.

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

