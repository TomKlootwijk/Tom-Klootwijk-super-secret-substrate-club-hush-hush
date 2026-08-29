# Codex task ledger

Execute in order. Do not begin a later milestone by weakening an earlier gate.

## M0 — Reproduce 4.3

- [ ] Install editable Python package.
- [ ] Run all unit tests.
- [ ] Regenerate exact 1×1 and 2×2 fixtures.
- [ ] Verify both certificates in separate processes.
- [ ] Build/run the C++ smoke test.
- [ ] Capture `scripts/hardware_probe.py` output on the target laptop.

Artifacts: `evidence/local_m0_*`.

## M1 — C++ semantic parity

- [ ] Add canonical JSON state serialization to C++.
- [ ] Add complete positional-superko context identity.
- [ ] Add randomized legal-trace generator with fixed seeds.
- [ ] Compare Python/C++ legal masks, transitions, captures, passes, terminal,
      score, and digests for at least 1,000,000 transitions.
- [ ] Add adversarial snapback, ko, multi-capture, edge, and suicide cases.

Gate: zero differences; every prior difference has a minimized fixture.

## M2 — Persistent exact history

- [ ] Design immutable collision-checked board objects.
- [ ] Implement persistent superko set in host RAM.
- [ ] Add Merkle root and content-addressed segment format.
- [ ] Add NVMe spill and restart.
- [ ] Inject deliberate hash collisions and prove equality fallback works.

Gate: state identity survives restart and collision injection.

## M3 — Production DFPN

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
