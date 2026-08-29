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
- Added the deterministic, chunked `UGTS_TRACE_V1` Python/C++ differential
  endpoint and completed the M1 gate: 1,000,006 fixed-seed legal transitions,
  10,093,588 exact raw-field comparisons, adversarial tactical fixtures, and
  zero mismatches.
- Added shared `UGTS-GO-STATE-v1` canonical semantic serialization and native
  collision-independent exact state equality over the complete PSK context.
- Compiled the optional CUDA targets with CUDA 12.8 and ran the device probe on
  the RTX 5070 Ti Laptop GPU (compute capability 12.0). The occupancy kernel has
  not yet been reference-tested and is not proof-authoritative.

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
