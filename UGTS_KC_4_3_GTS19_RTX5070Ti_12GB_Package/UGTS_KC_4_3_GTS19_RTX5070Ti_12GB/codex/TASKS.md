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
PNS, and an immutable exact-object segment/manifest store. They remain Python
validation components and are not yet the proof DAG's production storage path.

- [x] Design immutable collision-checked board objects (bounded Python slice).
- [x] Implement persistent superko set in host RAM (bounded Python slice).
- [x] Add Merkle root and content-addressed segment format (bounded Python slice).
- [ ] Add NVMe spill and restart.
- [x] Inject deliberate hash collisions and prove equality fallback works.

Bounded component gate: exact history members and roots survive restart and
injected index collisions. M2 remains open until the proof DAG uses this path and
storage can spill/restart under an explicit resident-memory bound.

## M3 — Production DFPN

The bounded Python PNDAG now exercises saturating proof arithmetic, real shared
states, complete-edge auditing, and interrupted-versus-uninterrupted 2×2
equivalence. These are fixture-level semantics only; no production C++ DFPN item
below is complete.

- [ ] Port proof/disproof semantics to C++.
- [ ] Add most-proving selection, thresholds, and saturating arithmetic.
- [ ] Add complete-state TT with exact/lower/upper records where applicable.
- [ ] Add deterministic checkpoint/resume.
- [ ] Match Python exact results on all tractable fixtures.

Gate: independent process verifies fixtures after resume.

## M4 — Exact CUDA expansion

- [ ] Preserve and benchmark the occupancy-mask kernel.
- [ ] Add deterministic group and liberty kernels.
- [ ] Add captures and own-liberty/suicide guard.
- [ ] Encode children without race-dependent ordering.
- [ ] Verify every GPU child against CPU; reject on mismatch.
- [ ] Add batched exact-superko lookup or retain CPU verification.
- [ ] Auto-size memory from `cudaMemGetInfo`.

Gate: 10 million randomized/adversarial child comparisons, zero differences.

## M5 — Proof-safe reductions

- [ ] Full-history D4 canonicalization with move transform inversion.
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
