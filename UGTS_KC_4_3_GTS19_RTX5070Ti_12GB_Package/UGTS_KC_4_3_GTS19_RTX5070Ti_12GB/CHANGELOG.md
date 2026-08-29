# Changelog

## 4.3.0 — GTS-19 foundational upgrade

- Pinned an exact 19×19 area-scoring/positional-superko/7.5-komi proof target.
- Reframed exact score search as a family of Black score-threshold propositions.
- Added an explicit AND/OR proof-number kernel and bounded 19×19 attempt command.
- Made full repetition context part of every proof-authoritative Python state key.
- Added full-history D4 canonicalization; empty-board first actions reduce exactly to 55 placement classes plus pass.
- Added 2-bit board packing: 361 points occupy 91 bytes.
- Added deterministic tiny-board alpha-beta regression and recomputation certificates.
- Added a dependency-free C++17 transition/scoring core.
- Added an optional CUDA bitplane occupancy kernel and runtime GPU memory probe.
- Added laptop-aware free-VRAM planning, host/NVMe spill architecture, checkpoints, and proof claim gates.
- Added Codex agent instructions, phased tasks, and acceptance scripts.
- Preserved the prior KC 4.2 package/report under `baseline/` when present.

## 4.2 baseline

The prior package established a deterministic Go engine, exact tiny-board search,
superko-aware state, certificates, SGF/CLI tooling, and bounded approximate search.
Version 4.3 treats that work as the correctness baseline and specializes the next
stage for an unrestricted 19×19 proof campaign on a 12 GB laptop GPU.
