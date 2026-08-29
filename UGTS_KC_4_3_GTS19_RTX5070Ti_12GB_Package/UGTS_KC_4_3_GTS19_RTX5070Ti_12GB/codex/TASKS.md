# Codex task ledger

Execute in order. Do not begin a later milestone by weakening an earlier gate.

## M0 — Reproduce 4.3

- [x] Install editable Python package.
- [x] Run all unit tests.
- [x] Regenerate exact 1×1 and 2×2 fixtures.
- [x] Verify both certificates in separate processes.
- [x] Build/run the C++ smoke test and CTest suite.
- [x] Capture `scripts/hardware_probe.py` output on the target laptop.

Artifacts: `fixtures/empty_1x1_*.json`, `fixtures/empty_2x2_*.json`,
`evidence/local_m0_1x1_verify.json`, `evidence/local_m0_2x2_verify.json`, and
`evidence/local_m0_hardware.json`.

## M1 — C++ semantic parity

- [x] Add canonical JSON state serialization to C++.
- [x] Add complete positional-superko context identity.
- [x] Add randomized legal-trace generator with fixed seeds.
- [x] Compare Python/C++ legal masks, transitions, captures, passes, terminal,
      score, and digests for at least 1,000,000 transitions.
- [x] Add adversarial snapback, ko, multi-capture, edge, and suicide cases.

Evidence: `evidence/local_m1_cpp_python_parity_v2_1m.json` records 1,000,007
transitions across 31,177 exact states, 13,187,153 authoritative comparisons,
fixed seeds `0x5eed19` and `0xc0ffee`, and zero mismatches (corpus SHA-256
`9effdd450e1e3e27f60ed9f29c1a8323a4f53b076ed884aa766e9eaff39d0702`).
V2 compares the shared semantic object, its byte-exact canonical JSON, and its
portable SHA-256 object ID in addition to every raw transition field. Hashes
remain locators only; `ExactStateEqual` compares the raw board, player, passes,
previous board, complete PSK set, and semantic rules tuple. The older v1 raw-field
artifact remains archived separately.

Gate: zero differences; every prior difference has a minimized fixture.

## M2 — Persistent exact history

Bounded vertical slices now include the host-local `ProofNumberDAG`, a canonical
structurally shared `PersistentHistory`, a PSK transition adapter that consumes
history roots without materializing flat sets, a bounded persistent-root tree
PNS, a restartable persistent-root proof-number DAG, and an immutable exact-object
segment/manifest store. They remain Python validation components. Live DAG nodes
now retain immutable history-root handles rather than full serialized state/
history artifacts, and compact load keeps the validated forest physically
shared. The complete forest and proof graph still reside in host RAM and do not
page through the segment path.

- [x] Design immutable collision-checked board objects (bounded Python slice).
- [x] Implement persistent superko set in host RAM (bounded Python slice).
- [x] Serialize many history versions as one exact shared forest (bounded slice).
- [x] Carry persistent roots through a restartable proof DAG (bounded Python slice).
- [x] Add compact shared-forest PNDAG checkpoints (bounded Python slice).
- [x] Remove retained per-node serialized history artifacts and preserve
      shared forest roots after compact restart (bounded Python slice).
- [x] Add exact-prefix immutable checkpoint generations, pinned resume, and
      externally journaled two-phase recovery (bounded slice).
- [x] Add Merkle root and content-addressed segment format (bounded Python slice).
- [ ] Add campaign-scale live-DAG NVMe paging/restart with explicit resource
      bounds.
- [x] Inject deliberate hash collisions and prove equality fallback works.

Bounded component gates: `scripts/storage_gate.py` deterministically replays a
canonical 19×19-shaped initial/one-move transition, pinned history rehydrate,
threshold-forced lazy spill, fresh restart, and injected collision fallback.
`scripts/persistent_pndag_gate.py` checks interrupted/resumed 2×2 threshold
proofs, compact shared-history checkpoints, exact graph equivalence, fresh
DAG/history objects, generation recovery, segment-backed byte rehydrate, atomic
publication failure, and simultaneous state/history digest collisions. The
storage gate
proves zero retained Python payload bytes after each fixture spill; the DAG
fixture separately proves zero retained serialized state/history artifacts.
Neither is a campaign peak-RSS or total-metadata bound. M2 remains open until
live persistent DAG records page through compact segment handles and
campaign-scale memory, mapping/handle, metadata-growth, and recovery costs have
explicit bounds.

## M3 — Production DFPN

The bounded Python PNDAGs exercise saturating proof arithmetic, real shared
states, persistent-root transitions, complete-edge auditing, and
interrupted-versus-uninterrupted 2×2 equivalence. A native exact host-memory DAG
now accepts sizes 1×1 through 19×19 and matches the Python flat-DAG graph
fingerprints for both tested completed 2×2 thresholds. Its canonical
two-expansion empty-19×19 run remains `UNKNOWN` with `PN=1`, `DN=361`, 725
nodes, and 724 edges. A strict content-addressed native full-snapshot restart
slice now exists, but these remain bounded semantics; the production C++ DFPN
coordinator, campaign-scale paged store, and verifier are not complete.

- [x] Port proof/disproof semantics to C++ (bounded host-memory 1×1 through
      19×19 slice).
- [x] Add most-proving selection, thresholds, and saturating arithmetic
      (bounded host-memory slice).
- [ ] Add complete-state TT with exact/lower/upper records where applicable.
- [x] Add deterministic checkpoint/resume (bounded native full-snapshot slice;
      externally pinned and strict, not campaign-scale paging).
- [ ] Match Python exact results on all tractable fixtures.

Gate: independent process verifies fixtures after resume.

## M4 — Exact CUDA expansion

- [x] Preserve, harden, and exact-reference-test the occupancy-mask kernel
      (bounded primitive; zero mismatches on the target GPU).
- [ ] Benchmark occupancy under campaign-shaped batches.
- [x] Add deterministic group and liberty kernel (bounded local slice).
- [x] Add captures and canonical own-liberty/no-suicide guard (bounded slice).
- [x] Encode fixed-slot children without race-dependent ordering (bounded slice).
- [x] CPU-recompute every point, including GPU rejects, and fail on mismatch.
- [x] Retain exact-superko, pass, metadata, and proof authority on CPU initially.
- [ ] Auto-size memory from `cudaMemGetInfo`.

The current v1 evidence is 25,281 unique point slots and 50,562 comparisons
across two parity modes, zero differences. Gate remains: 10 million
randomized/adversarial child comparisons, zero differences.

## M5 — Proof-safe reductions

- [ ] Integrate existing full-history D4 canonicalization and inverse move
      transforms into the production proof-DAG/certificate path.
- [ ] Exact lower/upper score intervals.
- [ ] Unconditional-life/territory witness format.
- [ ] Certified local separators and interface states.
- [ ] Reduction-on/off equivalence tests.

Gate: all exact fixture values unchanged; witnesses independently check.

## M6 — Board-size campaign

- [ ] Establish an ordered board-size ladder.
- [ ] Archive every exact result with rules/root hashes.
- [ ] Record nodes, proof updates, storage, time, power/temperature where safe.
- [ ] Independent verification from clean checkout.

Gate: no skipped correctness failures; results reproducible.

## M7 — Empty 19×19 threshold 1

- [ ] Start/resume canonical campaign.
- [ ] Checkpoint at configured intervals.
- [ ] Mirror immutable segments and manifests.
- [ ] Periodically run independent partial audits.
- [ ] Maintain `UNKNOWN` until root proof or disproof number is zero.

Gate for a solved claim: `scripts/claim_gate.py` accepts a full proof manifest and
a second implementation verifies it.

## M8 — Exact margin, only after M7

- [ ] Select remaining odd score thresholds adaptively.
- [ ] Reuse only state facts valid across thresholds.
- [ ] Prove enough thresholds to isolate one of 723 possible scores.
- [ ] Publish a score certificate and independent verification report.
