# Changelog

## 4.3.0 — GTS-19 foundational upgrade

### Verified M0 and M1 semantic foundation

- Closed the M0 reproduction gate on the target laptop: the full Python suite,
  deterministic 1×1/2×2 fixture generation, separate certificate verification,
  C++ build/CTest, canonical bounded preflight, and hardware probe all pass.
- Made Windows acceptance fail closed on every native nonzero exit and made both
  platform acceptance scripts generate and independently reverify both tiny
  certificates with the declared 20,000-node budget.
- Strengthened the `UNKNOWN` claim gate to require the pinned rules, threshold 1,
  hardcoded and runtime-recomputed canonical root digest, and positive root proof
  and disproof numbers. The 19×19 root remains `UNKNOWN`.
- Introduced `UGTS-GO-RECOMPUTE-CERT-v2`, whose hashed certificate core contains
  only deterministic proof-relevant root/rules/value data; runtime statistics and
  principal-variation diagnostics are excluded from the certificate identity.
- Hardened the Python exact oracle with strict state/history validation,
  finite-superko profile guards, deterministic pass-first ordering with an off
  switch, budget-safe principal-variation reporting, and exact PNS reset/parity
  regressions.
- Added a C++ `IllegalMove` exception taxonomy so rule-illegal moves can become
  `false` in legal masks while malformed state/rules errors remain fatal instead
  of silently shortening the legal action set.
- Added the deterministic, chunked `UGTS_TRACE_V2` Python/C++ differential
  endpoint and completed M1: 1,000,007 fixed-seed legal transitions,
  13,187,153 exact raw/canonical comparisons, adversarial tactical fixtures,
  byte-exact canonical JSON, portable SHA-256 object IDs, and zero mismatches.
- Added shared `UGTS-GO-STATE-v1` canonical semantic serialization and native
  collision-independent exact state equality over the complete PSK context.
- Added portable C++ SHA-256 vectors, int64 score arithmetic, fail-closed uint64
  ply exhaustion, and previous-board/history lineage validation.
- Added a bounded 1×1/2×2 exact proof-number DAG with collision-safe interning,
  complete-edge audits, real transpositions, atomic self-hashed checkpoints,
  deterministic resume, and fresh-process proof-cache recomputation. This is a
  host-local vertical slice, not production DFPN or a 19×19 certificate.
- Added a separate bounded C++17 1×1 through 19×19 proof-number DAG with exact canonical
  state-byte identity, real transposition reuse, deterministic most-proving
  selection, saturating uint64 recurrence, and graph fingerprints that match
  the Python oracle for both completed 2×2 threshold fixtures. Its canonical
  JSON CLI labels expansion-budget stops as `UNKNOWN` non-certificate attempts,
  declares exact proof-arithmetic width/endianness, and fails closed on output
  errors; the
  pinned two-expansion 19×19 result is `UNKNOWN` (`PN=1`, `DN=361`). A bounded
  native full-snapshot restart now uses external full-file pins and strict
  semantic/lineage reload, but there is no paged campaign store, CUDA proof path,
  or whole-game resource bound.
- Added a bounded immutable PSK radix trie with insertion-order-independent
  Merkle roots, exact-byte collision leaves, structurally shared transitions,
  pinned restart validation, and a PSK engine that never reconstructs flat
  histories during moves. A bounded persistent-root tree PNS matches the exact,
  flat-PNS, and proof-DAG truth values on complete 1×1/2×2 thresholds.
- Added `UGTS-PY-PERSISTENT-PSK-FOREST-v1`, a canonical multi-root artifact that
  globally deduplicates exact boards and immutable trie nodes, preserves ordered
  root references and structural sharing, rebuilds exact roots independently on
  load, and fails closed on malformed shared-DAG references.
- Added a restartable bounded persistent-root proof-number DAG. Canonical state
  identity excludes campaign-only ply, audits complete legal edges, recomputes
  cached proof numbers, survives injected
  allocation/publication failures, and resumes both 2×2 threshold outcomes to
  the exact uninterrupted graph. A compact evidence gate covers fresh objects
  and simultaneous forced state/history digest collisions.
- Replaced retained live per-node legacy state/history blobs with exact immutable
  history-root handles while preserving every digest input, wire byte, graph
  hash, and collision fallback. A 63-node fixture now retains zero serialized
  artifacts (3,544,779 bytes remain transient when legacy bytes are requested).
  Compact restart reuses its 1,163 validated physical trie nodes rather than
  duplicating 6,558 summed per-root references.
- Added immutable bounded persistent-PNDAG checkpoint generations with chained
  exact run envelopes, exact node-prefix lineage validation, mandatory complete
  external tip pins on restart, and exact verified-byte reload. Externally
  journaled `prepare`/`commit_prepared` records make pre/post-`CURRENT` recovery
  idempotent; larger counters can no longer replace a forked or solved graph.
  Direct retries reconcile an already-installed intended `CURRENT`; ambiguous
  post-replace failures expose the exact preparation through a dedicated
  commit-uncertain exception instead of losing the recovery record.
- Added a compact persistent-PNDAG checkpoint codec that stores one globally
  shared exact history forest, delegates reconstructed semantics to the strict
  legacy loader, and binds loader output back by exact reserialization. A
  20-expansion 2×2 fixture shrank from 7,104,362 to 350,147 bytes (95.1%) while
  remaining a fully materialized bounded snapshot rather than live DAG paging.
- Added deterministic exact-object binary segments, append-only self-hashed
  manifests, and atomic `CURRENT` publication. Restart verifies every reachable
  segment and exact object. Lazy mode drops retained Python payload copies after
  spill, streams sealing without a duplicate full-segment value, detects
  post-open segment mutation, supports an externally pinned tip, and has a
  deterministic 19×19-shaped one-transition/collision evidence gate.
  New directory entries are durably retried on POSIX, counter exhaustion is
  checked before sealing, and append reload reuses existing mappings while
  independently verifying each current pathname. This remains a single-writer
  storage slice rather than production proof-DAG/NVMe integration.
- Hardened the optional CUDA occupancy launch against shape/grid/index overflow,
  documented its asynchronous device-buffer contract, and added a target-GPU
  parity gate. CUDA 12.8 on the RTX 5070 Ti Laptop GPU (compute capability 12.0)
  passed 13 protocol cases, 13,038 Python/CUDA and 33,580,510 total C++/CUDA
  exact word comparisons, 33,606,586 input-immutability comparisons, 320 canary
  checks, 12 negative checks, the real grid-stride cap, permitted input aliasing,
  and Compute Sanitizer with zero mismatches/errors.
- Added a sibling asynchronous pre-superko CUDA point-transition kernel with
  deterministic group/liberty floods, simultaneous captures, canonical
  no-suicide handling, and fixed-slot child bitplanes. A fail-closed C++ adapter
  CPU-recomputes every point and keeps pass, exact PSK, metadata, and proof
  authority on CPU. The bounded target-GPU v1 gate covered 25,281 unique slots
  (50,562 across default/nondefault parity modes) plus 524,533 low-level
  grid-stride candidates with zero mismatches; memcheck, racecheck, and initcheck
  were clean. This is not the 10-million-slot M4 gate or a proof-path result.

### Foundational package

- Pinned an exact 19×19 area-scoring/positional-superko/7.5-komi proof target.
- Reframed exact score search as a family of Black score-threshold propositions.
- Added an explicit AND/OR proof-number kernel and bounded 19×19 attempt command.
- Made full repetition context part of every proof-authoritative Python state key.
- Added full-history D4 canonicalization; empty-board first actions reduce exactly to 55 placement classes plus pass.
- Added 2-bit board packing: 361 points occupy 91 bytes.
- Added deterministic tiny-board alpha-beta regression and recomputation certificates.
- Added a dependency-free C++17 transition/scoring core.
- Added an optional CUDA bitplane occupancy kernel and runtime GPU memory probe.
- Added laptop-aware free-VRAM planning plus host/NVMe spill, checkpoint, and
  proof-claim contracts.
- Added Codex agent instructions, phased tasks, and acceptance scripts.
- Preserved the prior KC 4.2 package/report under `baseline/` when present.

## 4.2 baseline

The prior package established a deterministic Go engine, exact tiny-board search,
superko-aware state, certificates, SGF/CLI tooling, and bounded approximate search.
Version 4.3 treats that work as the correctness baseline and specializes the next
stage for an unrestricted 19×19 proof campaign on a 12 GB laptop GPU.
