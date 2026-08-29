# Progressive proof campaign

Production campaign deployment is ordered to expose correctness defects before
expensive runs. Bounded implementation and validation slices from later phases
may be developed early, but campaign execution does not advance until every
prior phase's exit criterion passes.

## Phase 0 — reproduce the release

- Run Python unit tests.
- Build the C++ CPU core and run CTest.
- Regenerate the 1×1 and 2×2 exact fixtures.
- Verify the certificates from a fresh process.
- Confirm the bounded 19×19 command returns a valid status and preserves the
  canonical root digest.

## Phase 1 — C++ parity

- Implement every Python rules profile needed by the canonical game.
- Differential-test at least one million randomized legal transitions.
- Compare complete boards, captures, legal masks, pass state, terminal state,
  area score, and superko rejection.
- Add corpus minimization for any mismatch.

Exit criterion: zero mismatches and reproducible seeds.

## Phase 2 — durable exact state identity

The bounded Python components now validate collision fallback, canonical
structurally shared PSK roots, root-backed transitions, immutable exact-object
segments, atomic restart, live mapped-read integrity checks, and external tip
pinning. A second bounded DAG carries the persistent roots through exact 2×2
restart and matches uninterrupted proofs under forced digest collisions. The
deterministic M2 storage gate demonstrates zero retained Python payload bytes
after bounded fixture spills. A compact codec now stores all DAG histories as
one shared forest, and an exact two-phase generation wrapper prevents forked
work replacement when its preparation is externally journaled. Live proof
nodes now keep immutable history-root handles rather than serialized history
artifacts, and compact restart preserves physical forest sharing. Phase 2
remains open because those roots are not paged through segment handles; the
segment layer has not bounded peak RSS,
mappings/handles, cumulative metadata, or recovery at campaign scale.

- [done, bounded] Implement collision-checked content-addressed boards.
- [done, bounded] Implement a persistent superko set with Merkle roots.
- [done, bounded] Demonstrate restart-safe immutable host segments.
- [done, bounded] Demonstrate restart-safe persistent-root DAG semantics.
- [done, bounded] Inject index collisions and verify exact equality prevents
  corruption.
- [done, bounded checkpoint] Replace repeated durable per-state history
  artifacts with one compact shared forest and verify the bytes through a
  segment-backed restart.
- [done, bounded live handles] Replace retained per-state serialized history
  artifacts with immutable forest-root handles in the persistent proof DAG.
- Page live history/proof records through bounded segment handles.
- Add resident-memory-bounded NVMe spill/restart and campaign recovery tooling.

Exit criterion: exact checkpoint round-trip reproduces all proof numbers and
roots, and live proof/history paging has explicit resident-memory,
mapping/handle, metadata-growth, and recovery bounds.

## Phase 3 — proof-number coordinator

The flat and persistent-root Python slices validate proof-number DAG
recomputation across restart. A native exact host-memory DAG now accepts sizes
1×1 through 19×19 and matches the Python oracle's deterministic partial and
completed 2×2 graph fingerprints, with exact full-state identity,
transposition reuse, most-proving selection, and saturating proof arithmetic.
Its pinned two-expansion canonical 19×19 preflight is `UNKNOWN` (`PN=1`,
`DN=361`). A bounded binary native checkpoint now resumes only from an explicit
path plus external full-file SHA pin, semantically reconstructs the entire DAG,
and publishes immutable exact-prefix generations. It still materializes the
entire DAG and checkpoint in host memory and has no production TT records, CUDA
integration, or certificate verifier; it therefore does not count as the
production C++ DFPN coordinator.

- [done, bounded] Port threshold proof-number DAG semantics to C++ for 1×1..19×19.
- Add TT bounds keyed by complete state identity.
- [done, bounded] Add deterministic work selection and saturating arithmetic.
- [done, bounded] Add strict native checkpoint/restart with externally pinned,
  content-addressed generations.
- Add independent certificate verification.
- [done, bounded] Match both completed 2×2 threshold graphs to Python.
- Solve and independently verify progressively larger tractable fixtures.

Exit criterion: independent verifier accepts every fixture.

## Phase 4 — CUDA exact expansion

- [done, bounded] Harden and differentially verify the packed occupancy-mask
  primitive across deterministic protocol cases, pre-enqueued stream pairs,
  the production grid-stride boundary, input alias/immutability, tail bounds,
  and invalid arguments (zero mismatches; occupancy only).
- [done, bounded] Add deterministic fixed-slot local groups, liberties,
  simultaneous captures, own-liberty/no-suicide handling, and child bitplanes;
  CPU-recompute every point and retain CPU exact PSK/pass/metadata authority
  (25,281 unique slots, 50,562 across two parity modes, zero mismatches).
- Benchmark the occupancy primitive under campaign-shaped batches.
- Scale the differential gate from this bounded slice to 10,000,000 adversarial
  and randomized point slots and measure campaign-shaped throughput.
- Integrate verified batches into the proof coordinator only after that gate;
  migrate superko from CPU only with collision-safe exact lookup.

Exit criterion: no mismatch across randomized and adversarial ko/capture suites.

## Phase 5 — sound reductions

Implement one at a time, each with a proof witness and an off switch:

- full-history D4 canonicalization;
- exact score intervals;
- unconditional life/territory;
- local decomposition with certified interfaces;
- solver-generated opening orbit certificates.

Exit criterion: enabling a reduction does not change any solved fixture value.

## Phase 6 — board-size ladder

Attempt empty boards under the same area/PSK semantics at increasing sizes. Do
not skip difficult smaller boards merely to report a larger heuristic run.
Archive rules/root digests, logs, checkpoints, and certificates for every exact
result.

## Phase 7 — 19×19 threshold 1

Run the empty-root proposition `Black can force score2 >= 1`. The campaign may
run indefinitely and resume from checkpoints. The only terminal statuses are:

- root proof number zero: Black win proven;
- root disproof number zero: White win proven;
- resource stop: UNKNOWN.

## Phase 8 — exact margin, optional

After win/loss is independently verified, solve additional odd thresholds by
binary search over the 723 possible score values. At most ten threshold
questions identify the exact minimax margin, but each can require a major proof.
