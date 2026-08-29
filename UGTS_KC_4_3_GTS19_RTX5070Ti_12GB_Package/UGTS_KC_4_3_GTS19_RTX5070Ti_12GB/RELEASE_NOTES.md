# Release notes — UGTS-KC 4.3.0 GTS-19

## Purpose

This release is a game-theoretic **attempt and implementation foundation** for
the empty unrestricted 19×19 game identified by
`UGTS-GO19-AREA-PSK-K7.5-v1`. It is packaged for continued work by Codex on a
user-specified RTX 5070 Ti Laptop GPU with 12 GB VRAM.

## Current determination

- Exact empty 2×2 regression: Black by 0.5 under the fixture profile.
- Empty 19×19 threshold `Black score2 >= 1`: **UNKNOWN** after the included
  bounded proof-number preflight.
- No 19×19 winner or exact margin is claimed.

## Verified implementation status

- M0 is complete on the target Windows laptop: the Python suite, deterministic
  1×1/2×2 fixture generation, fresh-process certificate verification, C++
  build/CTest, canonical bounded preflight, and hardware probe pass.
- Recomputations use `UGTS-GO-RECOMPUTE-CERT-v2`. Its hashed core is limited to
  deterministic proof-relevant rules/root/value fields; timing, search counters,
  and principal-variation diagnostics cannot perturb certificate identity.
- The Python exact oracle now validates state/history inputs, rejects profiles
  whose infinite-play utility is undefined, handles a completed root safely when
  principal-variation extraction reaches a budget, and retains differential
  off-switch coverage for pass-first ordering.
- C++ distinguishes rule-illegal moves from malformed inputs with the
  `IllegalMove` exception taxonomy, preventing invalid states from being silently
  reported as shorter legal masks.
- A bounded native 1×1 through 19×19 proof-number DAG now uses complete canonical
  state bytes as identity, reuses real transpositions, selects deterministically,
  and saturates 64-bit proof arithmetic without wraparound. Its partial and
  complete 2×2 graph fingerprints match the Python oracle for thresholds 1 and
  3. A canonical non-certificate CLI pins the empty-19×19 two-expansion result
  as `UNKNOWN` with proof/disproof `1/361`, 725 nodes, and 724 edges. A bounded
  externally pinned native full-snapshot restart is included, but it is not the
  production DFPN coordinator, a paged campaign store, or a CUDA proof path.
- M1 v2 compared
  1,000,007 legal transitions across 31,177 exact states, including adversarial
  snapback, ko, multi-capture, edge, suicide, pass, and terminal cases, with zero
  mismatches across 13,187,153 authoritative raw/canonical fields. The native core also
  has exact complete-history equality and shared `UGTS-GO-STATE-v1`
  serialization, and v2 compares exact JSON bytes plus portable SHA-256 object
  IDs. Hashes never establish identity.
- A bounded host-local `ProofNumberDAG` now checkpoints and resumes exact 1×1/2×2
  PSK searches. It detects digest collisions by raw equality, audits every
  expanded legal edge, reconstructs proof numbers in a fresh process, and
  preserves an older checkpoint when atomic replacement fails before
  publication. A post-replace durability failure is not a transactional rollback
  guarantee. It is explicitly not
  production DFPN, persistent NVMe history, or a standalone certificate.
- Separate bounded M2 components now provide a canonical structurally shared
  PSK history with compact multi-root forest serialization, root-backed
  transitions that match the flat reference, a
  restartable 1×1/2×2 persistent-root proof-number DAG, and deterministic
  immutable board/history segments with append-only manifests and verified
  restart. The DAG gate resumes both 2×2 threshold outcomes to graph-identical
  results under fresh DAG/history objects. A separate one-expansion `UNKNOWN`
  fixture validates simultaneous forced state/history digest collisions. An
  immutable checkpoint-generation wrapper requires a complete external tip on
  resume, exact-prefix-validates every adjacent graph, and rejects valid older
  `CURRENT` rollback relative to that pin. Its externally journaled two-phase
  preparation can idempotently recover before or after `CURRENT` replacement.
  A separate compact codec deduplicates all checkpoint histories into one
  ordered forest and strictly reconstructs the legacy graph; it reduces bounded
  durable bytes but still fully materializes both forms. Lazy
  segment reads detect persistent post-open backing-file changes, reuse verified
  mappings while independently checking their current paths, and startup can
  require an externally pinned manifest tip; sealing streams to a fsynced
  temporary file without materializing a second complete segment. The storage
  gate covers a 19×19-shaped one-move transition, forced spill/restart, pinned
  rehydrate, and collision fallback while retaining root status `UNKNOWN`.
  Live persistent-DAG nodes now retain exact immutable history-root handles
  instead of serialized history artifacts; a 63-node fixture retained zero of
  the prior 3,544,779 artifact bytes, and compact load preserved 1,163 physical
  forest nodes versus 6,558 summed root references. These roots are still not
  paged from the segment store; injected digest callbacks are test-only, and the
  storage layer remains single-writer without campaign peak-memory,
  handle/metadata, or recovery bounds.
- CUDA 12.8 compiled the hardened occupancy primitive, and the runtime probe
  identified the NVIDIA GeForce RTX 5070 Ti Laptop GPU at compute capability
  12.0. Thirteen protocol cases plus a direct production-grid-stride fixture
  produced 13,038 Python/CUDA, 33,580,510 total C++/CUDA, and 33,606,586
  input-immutability comparisons, plus 320 canary and 12 negative checks, with
  zero mismatches; Compute Sanitizer reported zero errors.
- A bounded sibling CUDA slice now emits deterministic pre-superko point
  transitions for groups, liberties, captures, canonical no-suicide, and child
  bitplanes. Its CPU adapter recomputes every point and exclusively owns pass,
  exact PSK, metadata, and proof updates. The target gate covered 25,281 unique
  slots and 50,562 cross-stream Python/C++/CUDA comparisons with zero mismatches;
  the direct guard crossed 524,280 production candidates and sanitizer
  memcheck/racecheck/initcheck were clean. It is not the 10-million-slot M4 gate,
  a benchmark, proof-path integration, or a solved claim.
- Acceptance is fail closed on Windows native-command failures and validates the
  canonical `UNKNOWN` preflight envelope before printing success.

## Important entry points

- Human overview: `README.md`
- Mathematical target: `docs/FORMAL_SPEC.md`
- Optimization rules: `docs/EXACTNESS_CONTRACT.md`
- Codex instructions: `codex/AGENTS.md` and `codex/PROMPT_FOR_CODEX.md`
- Acceptance gate: `codex/acceptance.sh` or `codex/acceptance.ps1`
- Canonical configuration: `configs/go19_canonical.toml`
- Laptop configuration: `configs/rtx5070ti_laptop_12gb.toml`
- M0 evidence: `evidence/local_m0_1x1_verify.json`,
  `evidence/local_m0_2x2_verify.json`, and
  `evidence/local_m0_hardware.json`
- M1 v2 evidence: `evidence/local_m1_cpp_python_parity_v2_1m.json`
- Bounded M2 storage evidence: `evidence/local_m2_storage_gate.json`
- Bounded M2 persistent-PNDAG evidence:
  `evidence/local_m2_persistent_pndag_gate.json`
- Bounded M4 CUDA occupancy evidence:
  `evidence/local_m4_cuda_empty_mask_parity.json`
- Source-pinned bounded CUDA memcheck evidence:
  `evidence/local_m4_cuda_compute_sanitizer.json`
- Bounded CUDA local-transition parity and sanitizer evidence:
  `evidence/local_m4_cuda_local_transition_parity.json` and
  `evidence/local_m4_cuda_local_transition_compute_sanitizer.json`

## Next target-laptop action

Page the live history/proof records through bounded segment handles, then bound
peak memory, mappings/handles, manifest metadata, and recovery for
campaign-scale NVMe spill/restart. Keep CUDA outside the proof path until the
10-million-slot legal-child gate and campaign integration invariants pass.
