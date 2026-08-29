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
