# UGTS-KC Chess 2.0 - Classical Game-Theoretic Campaign

Canonical component identity: `ugts.application.chess-proof@2.0.0`

## Dedication

This proof campaign is dedicated to **Anna Cramling and the Cow Opening**.
The dedication may guide campaign lineage and work priority, but never changes
the proof standard: all twenty initial legal moves remain quantified
obligations, and incomplete evidence remains `UNKNOWN`.
The scheduler gives the transpositional Cow starts `1.d3` and `1.e3` equal,
modest priority; this is a queue-order hint only.

This package is an upgraded proof foundation for an **attempted game-theoretic solution of classical chess**. It turns the initial position into twenty independently checkable root obligations, preserves exact legal and history state, supplies bounded WIN/LOSS/DRAW certificates, retains exact KQK/KRK tablebases, and adds two native C++20 programs with optional CUDA 12.8+ backends for an NVIDIA GeForce RTX 5070 Ti Laptop GPU with 12 GB VRAM.

The captured result is **UNKNOWN for the orthodox initial position**. That is a valid proof status, not a draw claim. The package does not present engine strength, a principal variation, or a finite search cutoff as a solution.

## Exact and proof-oriented parts

- Strict FEN and full orthodox legal-move generation: castling, en-passant, promotion and king safety.
- Checkmate, stalemate, automatic fivefold/75-move draws, and a conservative built-in dead-position certificate subset.
- Threefold and 50-move claims represented as optional actions, including claims made by declaring an intended move.
- History-correct state hashes using exact repetition-count records; 64-bit keys remain cache keys only.
- Bounded WDL proof nodes: WIN needs one certified LOSS child; LOSS needs complete successor coverage; DRAW needs complete no-win coverage plus a draw strategy or closed complement; cutoffs remain UNKNOWN.
- SQLite proof-campaign ledger with twenty root shards, leases, candidate records, replayed certificate verification and a hash-chained event journal.
- Append-only, checksummed frontier records binding canonical FEN, exact repetition history, lineage and the canonical rules profile.
- A crash-recoverable SQLite transposition/DAG index derived from that frontier; indexed WDL remains immutable `UNKNOWN`, while a separate append-only overlay exposes non-`UNKNOWN` values only after full certificate replay.
- An append-only verified-certificate overlay binding canonical certificate bytes to the exact DAG node, full FEN/history, rule profile and first frontier occurrence, with mandatory fsync and fail-closed whole-journal replay.
- Audited one-hop WDL propagation from verified child facts: WIN accepts one exact losing-child witness, while LOSS/DRAW require complete reconstructed legal-move coverage and canonical draw-claim actions; composed proofs are independently replayed before overlay append.
- Canonical v1 overlay record/head commitments for exact reference resolution and externally anchored rollback detection, without changing any v1 journal bytes.
- A unified major-v2 WDL fact journal that re-verifies imported standalone seed certificates, then stores compact one-hop derivations as backward-only references to exact prior record indices and full content hashes. Mixed child depths use a checked proof height instead of subtree copying.
- Compact v2 propagation with exact earliest-edge replay, terminal precedence, WIN witnesses, complete LOSS/DRAW UCI coverage, and independently recomputed current/intended draw claims.
- A deterministic, restart-reconstructible monotone worklist for the materialized DAG. It binds an ordered full-frontier manifest and the fact-journal head, seeds terminals and verified-child parents, invalidates reconstructible scheduling state after an interrupted step, and labels an empty stable queue only as `local_quiescence_not_chess_solved`.
- Bounded deterministic DAG expansion that fills missing exact legal-move edges in canonical parent/UCI order, resumes partial parents without duplicate work, preserves full history twins, and never equates move materialization with solving chess. One initial and one final full replay bracket an incremental exact in-memory scheduler; an optional stable v2 fact head skips already verified nodes. Each parent batch uses one frontier fsync and one SQLite transaction. The safe default expands one parent; unbounded traversal must be requested explicitly.
- Canonical externally retainable ProofDAG head commitments that bind the complete ordered occurrence prefix, exact node/edge counts and byte boundary, detect valid-prefix rollback or same-size rewrite when checked against an independent copy, and never promote a local cache into authority.
- A standalone canonical campaign fact-projection receipt that binds one exact root obligation to compact v2 fact and ProofDAG prefixes. Verification fully replays both authorities and proves that every fact occurrence/dependency lies inside the embedded DAG head; it deliberately cannot promote a certificate-only v2 campaign row.
- A proof-preserving bundled KQK/KRK fact adapter. Tablebase probes select only a deterministic bounded-search horizon; a v2 seed is appended only after the ordinary history-aware certificate verifier and the fact journal both replay it successfully.
- Exact KQK and KRK WDL/DTM tables and retained forced-mate certificates.
- Native C++ legality, alpha-beta, mate proof and fixed-point demonstration.
- Optional CUDA proposal/fixed-point kernels. CUDA does not bypass the independent verifier.

## RTX 5070 Ti Laptop handoff

Two native executables are built:

- `ugts-chess2`: rules, perft, bounded search, mate proof, root sharding and a finite WDL fixed-point demonstration.
- `ugts-chess-gpu`: 64-byte packed position / 16-bit move protocol, CPU fallback, CUDA batch move expansion and device inspection.

The checked-in RTX preset requests CUDA architecture `120` (`sm_120`). Runtime device inspection is authoritative: laptop power limits, free VRAM, driver/toolkit compatibility and thermal behavior vary by system.

The latest physical-device run and its explicit claim boundary are summarized
in [`validation/device/README.md`](validation/device/README.md).

```powershell
# Windows PowerShell from the package root
powershell -ExecutionPolicy Bypass -File scripts/build_rtx5070ti.ps1
powershell -ExecutionPolicy Bypass -File scripts/run_codex_campaign.ps1
```

```bash
# Linux / WSL host validation
bash scripts/build_host.sh
PYTHONPATH=src python -m ugts_chess campaign-init \
  --out-dir examples/campaign --force
PYTHONPATH=src python -m ugts_chess campaign-verify examples/campaign/initial.sqlite3
```

## Quick exact checks

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m ugts_chess perft --depth 4
PYTHONPATH=src python -m ugts_chess bounded-wdl \
  --fen "8/8/8/1Q6/8/8/k7/2K5 w - - 100 2" --plies 1
cpp/build/host-release/ugts-chess2 selftest
cpp/build/host-release/ugts-chess-gpu self-test
```

## Proof campaign rule

A worker may propose `win`, `draw` or `loss` for one root shard. It becomes authoritative only after a separate checker validates the rule profile, complete legal successor obligations, repetition and move-count history, certificate hashes and terminal proof. A GPU hash, cache hit or score is never enough.

## Known proof gaps

- The initial 32-piece value is unresolved.
- The built-in dead-position recognizer certifies a common exact subset; a global classical proof requires a complete dead-position oracle or certificate mechanism.
- KQK/KRK are bundled, not the full external 3- through 7-piece corpus. Their adapter can certify short finite proofs, but most cyclic tablebase draws remain `UNKNOWN` because the current certificate language has no authenticated tablebase-cycle lemma.
- The disk-backed DAG validates exact legal move transitions, child FEN/history and parent content addresses, and its SQLite rows remain immutable `UNKNOWN`. Both the portable v1 certificate overlay and the unified v2 fact journal supply independently replayed effective values without mutating those rows. Correct local expansion, closure and projection receipts now exist, but solution-scale scheduling and the explicit campaign-v3 promotion/checker/event migration remain unfinished.
- Campaign schema 2.0 is certificate-only. Fact-backed promotion must cross a declared campaign-3.0 boundary; silently reusing its certificate path/hash/checker fields would change the authority protocol and is rejected as unsound.
- V1/v2 fact access currently replays the full journal, and v2 seed records still replay their embedded standalone certificates. Compact derivations remove repeated subtree materialization, but indexed/checkpointed replay is still needed for solution-scale throughput.
- The worklist is deliberately in-memory and reconstructible from the two authorities. It is deterministic and crash-safe through replay, not yet thread-safe, distributed, or storage-efficient; local quiescence says nothing about unexplored chess states. Time bounds are cooperative between full audits/steps rather than hard real-time deadlines.
- Expansion now performs a constant number of full authority scans per invocation rather than per parent, then maintains exact parent coverage, priority and ordered-manifest state incrementally. It still uses O(total materialized nodes) RAM, is single-handle/single-process rather than distributed, and requires a final full replay before reporting. “Complete” in an expansion report means only eligible legal move-edge coverage; verified nodes may be skipped, raw materialized closure is reported separately, and optional draw-claim actions remain proof semantics handled by propagation.
- A disposable v2 lookup sidecar cannot replace fresh hostile-rewrite replay: the current linear chain has no sublinear membership/non-membership proof. Safe cross-open indexing requires a separately anchored authenticated checkpoint/Merkle design rather than trusting local SQLite metadata.
- A clean rollback to an earlier valid journal or ProofDAG prefix cannot be detected without an externally retained head. Canonical ProofDAG and fact/overlay commitment APIs exist, but the head must actually be stored or signed outside the authority it protects; an adjacent file is not independent, and path-derived locks do not converge across hardlink aliases.
- The legacy one-hop API still emits a portable self-contained bundle by copying and depth-rebasing child subgraphs. The v2 compact path supersedes that representation for deep closure by binding exact prior fact records and computing `1 + max(child proof height)` without copying their evidence.
- The local v2 device gate compiled real `sm_120` CUDA with `nvcc` 12.8 and compared 4,112 deterministic fixture/reachable positions against the exact Python oracle with zero move-set mismatches or fallbacks. Its replay gate reruns the caller-selected exact binary, but GPU execution remains a self-report rather than independent hardware attestation; the corpus does not cover all chess states.
- Large-batch measurements show a local throughput benefit, but no sustained thermal, battery or playing-strength advantage is claimed. The newest timing was captured without exclusive GPU access while another workload could contend for compute, so it is evidence of parity and a noisy local snapshot, not a clean performance result.

## Package map

- `src/ugts_chess/` - Python rule oracle, WDL proof semantics, campaign ledger, tablebases and CLI.
- `cpp/` - C++20 host solvers, compact proposal protocol, CPU fixed point and optional CUDA kernels.
- `examples/campaign/` - root database, twenty shard records and exact depth-four workload evidence.
- `spec/` - formal definition, schemas, RTX profile, source register and mechanism catalog.
- `scripts/` - Codex-oriented Windows and host build/run scripts.
- `tests/` and `validation/` - captured tests, perft, native builds, protocol differential checks, schemas and hashes.
- `report/` - upgraded foundational report and editable DOCX source.

See `docs/CODEX_HANDOFF.md` first on the target laptop.
