# Changelog

## 2.0.0 - 2026-08-29

- Promoted the package to component-scoped identity `ugts.application.chess-proof@2.0.0`.
- Added complete classical root decomposition into twenty content-addressed obligations.
- Added exact history-aware state identity, including legal-en-passant repetition semantics.
- Added optional current and intended-move draw claims, automatic fivefold/75-move guards and checkmate precedence.
- Added four-valued bounded WDL certificates (`WIN`, `LOSS`, `DRAW`, `UNKNOWN`) with an independent verifier.
- Added a SQLite proof-campaign ledger with leases, candidate/checker separation and a hash-chained event journal.
- Hardened campaign verification to hash and replay exact WDL certificates, bind full history/FEN/rule profiles, and reject fabricated checker records.
- Added an append-only checksummed frontier format carrying exact state, repetition history, lineage and content hashes.
- Added a crash-recoverable disk-backed transposition/DAG index with collision-safe exact lookup, multi-parent edges and fail-closed frontier/index audits.
- Added an independent C++20 legal/perft/search/mate/retrograde executable.
- Added a 64-byte packed position, 16-bit move protocol, CPU fallback and optional CUDA candidate/fixed-point kernels.
- Added an RTX 5070 Ti Laptop 12 GB SM120 profile, Codex build scripts and explicit device-evidence gates.
- Added deterministic fixture/reachable-position CUDA qualification plus captured CPU/CUDA parity and large-batch throughput evidence.
- Hardened retained CUDA qualification to a non-downgradable v2 profile with deterministic corpus reconstruction, exact artifact replay, fresh device probing and fresh execution of the caller-selected binary.
- Isolated concurrent GPU batch and benchmark invocations with unique immutable artifacts; v4 benchmarking rechecks input identity around every process and discloses that exclusive timing access is not enforced.
- Made frontier recovery preserve and fsync every suspect suffix in a content-addressed sidecar before truncation, including the ambiguous final-frame length-corruption case.
- Bound mate certificates to full history-aware game-state identity and made WDL claim witnesses canonical and multiplicity-sensitive.
- Enforced exact legal transition semantics in the disk-backed proof DAG while keeping its indexed values immutable `UNKNOWN`.
- Added a mandatory-fsync, append-only verified-certificate overlay that binds exact canonical WDL bundles to full DAG state identity, replays the whole journal before exposing values, rejects conflicting promotions and preserves torn suffixes before recovery.
- Made WDL bundle export retain only the root-reachable certificate closure and fail closed on duplicate hashes, missing children or cycles.
- Added audited one-hop DAG WDL propagation with exact edge replay, full-node identity, WIN-witness versus complete LOSS/DRAW rules, canonical current/intended claims, mixed-depth child-proof rebasing and independent verification before overlay append.
- Added canonical v1 overlay record/head commitments, bounded exact reference resolution and an external-head rollback check without changing the v1 disk format.
- Added a unified major-v2 WDL fact journal with deterministic v1 seed migration, mandatory-fsync hash-chained appends, loss-preserving recovery and compact backward-only derivation references.
- Added compact one-hop propagation that binds the earliest exact DAG edge and prior fact record for every used UCI action, recomputes terminal/claim/coverage semantics, and replaces copied mixed-depth subtrees with checked proof heights.
- Added a strict Draft 2020-12 schema for v2 seed, derivation and external-head records.
- Added a restart-reconstructible deterministic WDL worklist with ordered full-frontier manifest heads, terminal/verified-child parent seeding, monotone parent fan-out, exception-safe authority reconstruction, stable-head limit/quiescence checks, and an explicit `local_quiescence_not_chess_solved` boundary.
- Added bounded deterministic ProofDAG expansion with canonical parent/UCI scheduling, exact history-preserving child reconstruction, partial-parent restart, duplicate-occurrence collapse, safe one-parent default, and explicit move-edge-only closure semantics.
- Added bounded ProofDAG move batching with full prevalidation, aggregate byte/request caps, one frontier fsync and one SQLite transaction per non-empty batch, ordered exact boundaries, poisoned-handle crash semantics, and replayable durable prefixes.
- Reworked deterministic expansion around one initial and one final full materialization replay, with exact incremental parent scheduling, ordered-manifest advancement, optional stable-v2-fact skipping, distinct raw/eligible closure reporting, and hostile-mutation rejection.
- Added canonical externally retainable ProofDAG prefix commitments with strict serialization, ordered occurrence manifests, exact historical-prefix reconstruction, and explicit rollback/rewrite/concurrent-mutation failures.
- Unified expansion and worklist DAG heads on that canonical commitment. Legacy in-memory names remain aliases, but any previously serialized worklist/expansion head must be replayed and re-emitted because its old schema or digest cannot be converted without the authoritative DAG.
- Added a standalone canonical campaign WDL fact-projection receipt and strict structural schema. Its verifier reconstructs the exact root obligation, replays both retained authorities, selects a fact by its exact prefix head, cross-binds every prior fact occurrence and derivation edge inside the embedded ProofDAG head, and accepts only valid append-only extensions; campaign-v2 promotion remains intentionally unavailable.
- Added a conservative bundled KQK/KRK-to-v2 adapter in which tablebase probes are horizon hints only and every promoted seed is an independently replayed history-aware WDL certificate.
- Dedicated the campaign to Anna Cramling and the Cow Opening without changing any proof obligation or acceptance rule.
- Retained exact KQK/KRK WDL/DTM tables, mate certificates, replay and offline proof-viewer assets.
- The initial position remains `UNKNOWN`; no game-theoretic solution is claimed.

## 1.0.0 - 2026-08-29

- Added strict standard-chess state and legal move kernel.
- Added UGTS move proposals, deterministic commits, hash lineage and replay.
- Added alpha-beta, iterative deepening, quiescence and transposition records.
- Added finite-horizon forced-mate certificates and an independent verifier.
- Added exact KQK and KRK retrograde DTM tablebases with 19-bit dense keys.
- Added CLI, JSON schemas, mechanism catalog, offline proof viewer and validation evidence.
