# Changelog

## 0.3.0

- Analyzed the uploaded RTX 5070 Ti Laptop results and preserved them under `benchmarks/rtx5070ti_v0.2/`.
- Documented that the 65,536-candidate v0.2 test is launch-sized, that chain depth materially increases reconstruction cost, and that fitted arbitrary PLY motion can erase compression.
- Added KLOC1: a 256-byte header, 64-byte orbital seed records, 64-byte hash-linked timeline nodes, and a UTF-8 string table.
- Added a dependency-free CelesTrak OMM CSV adapter and packed an actual 32-object GPS Operational snapshot.
- Added deterministic host/device Kepler propagation with pack-time secular J2 rates, explicitly bounded as a coarse benchmark predictor rather than SGP4.
- Added `klb_orbit passes` for coarse acquisition/loss event CSV generation without CUDA.
- Added a full seven-day 52°N, 5°E application output with 717 crossing events over 19,353,600 candidate intervals.
- Added `klb_orbit_bench` with direct seed, dense materialization, dense query, end-to-end dense, block-reduced counters, optional warp-compacted events, CPU oracle comparison, p50/p95/p99, automatic sustained inner repeats, and VRAM safety checks.
- Added file, smoke, laptop and approximately 2 GiB VRAM stress presets.
- Added Windows/Linux demo, stress, refresh and Nsight Compute scripts.
- Added current-deployment analysis, OrbitSeed design, KLOC1 format and expanded validation documentation.
- Removed uploaded build/report/frame-export bloat from the clean source package while retaining the relevant raw benchmark results.

## 0.2.0

- Added KLSC1: an embedded KLB37 base plus 96-byte hash-linked frame nodes and 16-byte sparse novelty records.
- Added checkpoint snapshots and bounded parent-linked delta reconstruction.
- Added generated procedural chains and a stable-correspondence PLY sequence fitter.
- Added CPU sequence verification and reconstructed-frame export.
- Added a CUDA deployment benchmark with direct compressed query, materialized dense baseline, compact event append, CPU/GPU reconstruction checks, and exact compressed/dense event-set comparison.
- Added RTX 5070 Ti Laptop `sm_120`/`compute_120` build configuration, scripts, sample chain, format documentation, provenance notice, and validation boundaries.

## 0.1.0

- Initial 37-bit continuous log-spherical KLB stream, parity grammar, XOR swizzle, Klein routing abstraction, cone-field traversal, PLY adapter, CPU oracle, and CUDA baseline benchmark.
