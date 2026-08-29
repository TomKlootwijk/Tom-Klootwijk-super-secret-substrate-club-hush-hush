# Codex handoff - RTX 5070 Ti Laptop 12 GB

## Objective

Build and measure the supplied foundation, then extend it only through proof-preserving interfaces. The target is not "play strong chess"; it is to close content-addressed WDL obligations for the classical initial position while returning `UNKNOWN` whenever a proof is incomplete.

## First run

1. Record `nvidia-smi`, driver version, exact GPU name, total/free VRAM, laptop power mode, OS and CUDA toolkit.
2. Run `scripts/build_rtx5070ti.ps1` from a Visual Studio x64 developer environment or equivalent CMake/Ninja shell.
3. Run both native self-tests and the Python test suite.
4. Run `ugts-chess-gpu device-info`. Confirm the runtime compute capability is 12.0 before using the `sm_120` preset.
5. Run `scripts/run_codex_campaign.ps1`; retain all JSON output under `validation/device/`.

## Non-negotiable proof boundaries

- Candidate generation may be parallel, approximate or GPU-accelerated.
- Legal move verification, state transition, repetition identity and proof obligation checking remain deterministic and independently replayed.
- A root is WIN only if one verified child is LOSS from the child's perspective.
- A root is LOSS only if every legal action is covered and every child is verified WIN.
- A root is DRAW only after complete no-win coverage and a verified draw action/closed complement argument.
- A budget stop, cache miss, hash collision risk, unverified tablebase probe or finite horizon is UNKNOWN.
- Claimable draws are player actions. They are not forced terminals.
- Checkmate is terminal before an automatic 75-move draw.

## Suggested Codex engineering sequence

Checkpoint: the v2 CUDA correctness/replay gate, immutable-input equal-output
benchmark, append-only loss-preserving frontier recovery, and crash-recoverable
disk DAG core are implemented. The DAG checks exact legal move transitions,
child FEN/history and parent content addresses. Its rows intentionally remain
`UNKNOWN`; an append-only v1 overlay binds exact independently replayed WDL
certificates to DAG nodes without mutating them. A unified major-v2 journal
can deterministically import those seeds and store one-hop derivations as
strictly backward record-index/content-hash references. Both the portable v1
and compact v2 propagation paths are independently replayed. A deterministic,
restart-reconstructed local worklist is implemented and explicitly reports
stable emptiness as local quiescence, never as solving chess. An interrupted
propagation or parent-scheduling step invalidates its reconstructible RAM state
and forces an authority replay on retry. Scalable frontier expansion and
indexed replay are the next integration boundary. A bounded deterministic
expander and a conservative KQK/KRK-to-v2 seed adapter now exist; the former
now batches each parent under one frontier sync/SQLite transaction but still
needs an incremental fact-aware scheduler, and the latter never promotes a bare
probe.

1. Make the CUDA build pass without changing the host oracle.
2. Differential-test every CUDA-generated move list against `ugts_chess.rules.legal_moves` on all packaged fixtures and a seeded random legal corpus.
3. Benchmark CPU versus CUDA batch expansion with equal exact outputs. Do not
   interpret timing as clean unless exclusive GPU access and concurrent-load
   monitoring were actually enforced.
4. Add an append-only binary frontier format with full reconstructibility, CRC/SHA checks and a versioned rule-profile ID.
5. Add a disk-backed transposition/proof DAG. A 64-bit key may index records but may not replace the full state/history identity. Validate every move edge by replay.
6. Bind verified certificates through an append-only overlay; retain DAG rows as immutable `UNKNOWN` and replay the full overlay before exposing an effective value.
7. Propagate verified child facts only through independently reconstructed complete legal-action coverage; never close residual `UNKNOWN` as `DRAW`.
8. Replace copied child subtrees with compact derivation facts bound to prior audited v2 records. Implemented: major-v2 journal, v1 migration, strict derivation verifier and compact one-hop propagation.
9. Add a deterministic monotone worklist rebuilt from audited DAG/fact heads; local quiescence must never be reported as a classical solve. Implemented for the materialized local DAG.
10. Integrate external endgame partitions through an adapter whose results are rechecked and profile-labeled. Implemented conservatively for bundled KQK/KRK finite certificates; broader external partitions and authenticated cycle lemmas remain open.
11. Implement complete dead-position certificates or keep affected nodes UNKNOWN.
12. Close root shards independently; merge only verifier-accepted certificates.

The journals are correctness-first: every access currently replays the complete
chain, and seed facts replay their embedded certificates. V2 compact derivations
remove repeated child-subtree copies but do not yet remove the linear replay
cost. The worklist is reconstructible and deterministic, but it does not yet
expand the chess state space or provide thread-safe/distributed scheduling;
its elapsed-time bound is cooperative between full audited operations.
Detecting a
clean rollback to an earlier valid suffix requires an
externally retained head commitment; the API can check it, but an adjacent file
is not an independent witness. Hardlink aliases remain outside the path-derived
writer-lock guarantee.

The deterministic expander defaults to one parent and materializes only move
edges; claim actions remain in the proof semantics. Explicit unbounded
traversal is operationally dangerous. The current v2 linear fact chain cannot
support a trust-bearing sublinear sidecar on fresh open; that requires an
externally anchored authenticated checkpoint/Merkle format rather than a local
cache being promoted to authority.

## Required device evidence

Capture p50/p95/p99 batch latency, positions/s, moves/s, peak VRAM, host RAM, storage bytes per verified node, 5/15/30-minute clocks/temperature/power behavior, CUDA fallback reasons, and differential mismatch count. Any mismatch blocks proof use.
