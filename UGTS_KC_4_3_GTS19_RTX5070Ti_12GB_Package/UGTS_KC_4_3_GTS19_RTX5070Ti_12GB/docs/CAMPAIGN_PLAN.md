# Progressive proof campaign

The campaign is ordered to expose correctness defects before expensive runs.
Passing a phase is required before starting the next.

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

- Implement collision-checked content-addressed boards.
- Implement a persistent superko set with Merkle roots.
- Demonstrate restart-safe host/NVMe checkpoints.
- Inject hash collisions in tests and verify exact equality prevents corruption.

Exit criterion: checkpoint round-trip reproduces all proof numbers and roots.

## Phase 3 — proof-number coordinator

- Port threshold PNS/DFPN to C++.
- Add TT bounds keyed by complete state identity.
- Add deterministic work selection and saturating arithmetic.
- Re-solve 2×2 and progressively larger tractable fixtures.

Exit criterion: independent verifier accepts every fixture.

## Phase 4 — CUDA exact expansion

- Add group/liberty/capture kernels.
- Add exact batched child encoding.
- Keep superko on CPU initially, then migrate only with collision-safe lookup.
- Differential-test every CUDA child against Python and C++ CPU references.

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
