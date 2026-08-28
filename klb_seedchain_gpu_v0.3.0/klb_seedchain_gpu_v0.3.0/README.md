# KLB SeedChain GPU 0.3.0

A low-level CUDA/C++ testbed for chain-linked seed reconstruction, compact event queries, and dense-versus-procedural crossover measurement on an NVIDIA GeForce RTX 5070 Ti Laptop GPU.

Version 0.3 keeps the original KLB37/KLSC1 point-sequence implementation and adds a practical real-data deployment:

> **OrbitSeed:** pack a CelesTrak GPS Operational OMM CSV snapshot into 64-byte orbital seeds and hash-linked timeline nodes, reconstruct satellite state on demand, and query coarse ground-station visibility/acquisition events directly on the GPU.

The code uses raw CUDA allocations, constant memory, raw fixed-width records, and directly launched kernels. It does not depend on PyTorch, TensorRT, OptiX, Vulkan, Unity, Godot, a database, or a mesh framework. It is not literally driverless bare metal; the NVIDIA driver and CUDA runtime still provide allocation, launch, synchronization and profiling.

## What changed after the uploaded RTX run

The v0.2 results were correct but too small to expose the real crossover:

```text
points/candidates                   65,536
compressed query, frame 239         0.041238 ms
dense frame query                   0.013246 ms
compressed/dense time               3.11x slower
synthetic sequence storage ratio    207.32x
```

The synthetic ratio was valid for that generated sequence, but the timed query processed only one tiny frame. A fitted real PLY sequence also showed the predictor limit: one fit expanded to 0.79x of dense storage, and a tuned fit reached only 1.70x while the compressed query remained about 3.7x slower than the already-materialized dense frame.

The analysis and corrective design are in [`docs/CURRENT_DEPLOYMENT_ANALYSIS.md`](docs/CURRENT_DEPLOYMENT_ANALYSIS.md).

## New practical deployment: GPS operational orbit seeds

Included files:

```text
data/orbit/source/gps_ops_2026-08-16_omm.csv
data/orbit/gps_ops_2026-08-16_7d_1s.kloc
data/orbit/gps_ops_2026-08-16_52N_5E_pass_events.csv
```

The KLOC1 container contains:

```text
actual OMM source records            32 GPS operational objects
container                            3,809 bytes
orbital seeds                        32 x 64 bytes
hash-linked timeline nodes           7 x 64 bytes
timeline                             7 days at 1-second query spacing
state samples                        604,801
equivalent dense float4 positions    309,658,112 bytes (~295.3 MiB)
horizon-relative ratio               81,296.432659x
```

This is **model-based reconstruction**, not lossless compression of an existing 295 MiB trajectory. The dense baseline materializes the same bundled predictor so the GPU test compares equivalent state/event work.

The included CPU application output is a coarse 52°N, 5°E pass-event schedule with 717 acquisition/loss crossings over 19,353,600 satellite-time intervals. The predictor is a deterministic Kepler solve with pack-time secular J2 rates. CelesTrak GP elements are intended for SGP4, so this deployment is for compression/performance work and coarse scheduling only—not navigation, collision avoidance, safety of flight, or precise antenna pointing.

See [`docs/ORBIT_DEPLOYMENT.md`](docs/ORBIT_DEPLOYMENT.md) and [`docs/FILE_FORMAT_KLOC1.md`](docs/FILE_FORMAT_KLOC1.md).

## Package executables

| Executable | Purpose |
|---|---|
| `klb_orbit` | OMM CSV adapter, KLOC1 inspect/verify, sampled state export, and coarse pass-event generation |
| `klb_orbit_bench` | sustained direct-seed versus dense-materialization CUDA benchmark |
| `klb_pack` | original PLY/KLB37 packer |
| `klb_bench` | original continuous 37-bit decode benchmark |
| `klb_seedchain` | original KLSC1 point-sequence create/fit/inspect/export tool |
| `klb_seedchain_bench` | original point-sequence direct-compressed versus dense-frame query benchmark |

## RTX 5070 Ti Laptop build target

CMake defaults to:

```text
native cubin                 sm_120
PTX fallback                 compute_120
```

Requirements:

- current NVIDIA driver;
- CUDA Toolkit 12.8 or newer;
- CMake 3.24 or newer;
- Visual Studio 2022 x64 on Windows, or a CUDA-supported GCC/Clang host compiler on Linux.

The benchmark reads the actual device name, compute capability, global memory, L2 size, SM count and memory-bus width at runtime rather than hard-coding laptop performance.

## Windows: build and run the useful application

Open an **x64 Native Tools Command Prompt for Visual Studio 2022** in the extracted directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\demo_orbit_windows.ps1
```

The demo:

1. validates the KLOC1 payload and hash chain;
2. regenerates the 7-day coarse pass-event schedule on the CPU;
3. runs the actual 7-day GPU horizon with direct seed, dense materialization, dense query, end-to-end dense, and compact-event modes;
4. writes `orbit_file_results.csv`.

A longer sustained workload with about 512 MiB of dense float4 positions:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stress_orbit_windows.ps1 -Preset laptop
```

Optional approximately 2 GiB dense baseline:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stress_orbit_windows.ps1 -Preset vram
```

The `vram` preset stays well below 12 GB but should still be run with other GPU-heavy applications closed.

## Linux

```bash
./scripts/build_linux.sh
./scripts/demo_orbit_linux.sh
./scripts/stress_orbit_linux.sh ./build laptop
```

CPU-only configuration remains available:

```bash
cmake -S . -B build-cpu -DCMAKE_BUILD_TYPE=Release -DKLB_BUILD_CUDA=OFF
cmake --build build-cpu -j
ctest --test-dir build-cpu --output-on-failure
```

## Manual orbit commands

Inspect and verify:

```bash
./build/klb_orbit inspect data/orbit/gps_ops_2026-08-16_7d_1s.kloc
./build/klb_orbit verify  data/orbit/gps_ops_2026-08-16_7d_1s.kloc
```

Generate a useful pass-event CSV without CUDA:

```bash
./build/klb_orbit passes data/orbit/gps_ops_2026-08-16_7d_1s.kloc \
  --lat 52 --lon 5 --alt-km 0.05 \
  --elevation-deg 10 --crossing-band-deg 0.25 \
  --hours 168 --step-seconds 1 \
  --output pass_events.csv
```

Sample reconstructed ECI positions:

```bash
./build/klb_orbit sample data/orbit/gps_ops_2026-08-16_7d_1s.kloc \
  --seconds 3600 --output orbit_positions_1h.csv
```

Pack a manually downloaded OMM CSV:

```bash
./build/klb_orbit pack-omm-csv gps_ops.csv gps_ops.kloc \
  --horizon-hours 168 --step-seconds 1 --tile-hours 24
```

The official query used by the included snapshot is:

```text
https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=CSV
```

Dependency-free fetch helpers are included. They refuse to overwrite an existing snapshot unless explicitly forced, so they do not silently poll CelesTrak:

```bash
./scripts/fetch_gps_ops_linux.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\fetch_gps_ops_windows.ps1
```

Respect CelesTrak's usage policy and retrieve only when a refreshed snapshot is actually needed.

## Sustained benchmark modes

`klb_orbit_bench` reports four separate decisions:

| Mode | What is timed |
|---|---|
| `query_seed_direct` | reconstruct two adjacent states when needed and evaluate support/guard directly |
| `materialize_dense` | generate the full dense float4 position working set |
| `query_dense` | query an already-materialized dense working set |
| `materialize_plus_query` | end-to-end dense comparison |

Optional `compact_seed_events` and `compact_dense_events` use warp-aggregated event append and compare sorted event payloads.

Presets:

| Preset | Epochs/intervals | Candidates | Dense crossing positions |
|---|---:|---:|---:|
| `smoke` | 65,536 | 2,097,152 | ~32 MiB |
| `file` | 604,800 | 19,353,600 | ~295.3 MiB |
| `laptop` | 1,048,576 | 33,554,432 | ~512 MiB |
| `vram` | 4,194,304 | 134,217,728 | ~2 GiB |

Each distribution sample is automatically repeated until it reaches at least 150 ms by default. Results include p50, p95, p99, mean, inner-repeat count, candidate rate, counters, event yield and logical dense traffic.

The `laptop` and `vram` presets repeat the bounded seven-day timeline to create load; this is explicitly reported and must not be interpreted as a longer physical prediction.

## First-run acceptance

The first GPU run should report:

```text
CPU/GPU oracle prefix       exact counters
Direct/dense counters       equal
Compacted event-set match   equal, when --write-events is enabled
Event output truncated      no
```

A mismatch is a failed run. A high storage ratio is not an acceptance criterion by itself.

## Nsight Compute

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\profile_orbit_windows.ps1
```

or:

```bash
./scripts/profile_orbit_linux.sh
```

Inspect:

- register count and achieved occupancy;
- special-function/transcendental pressure from trigonometric evaluation;
- DRAM and L2 traffic for the dense path;
- constant-cache behavior for the seed path;
- warp stalls and block-counter atomics;
- compact-event contention;
- direct seed versus materialize-plus-query crossover.

## Original KLB37/KLSC1 path retained

The original point-sequence work remains available for datasets that really are explained by its grammar/predictor and sparse novelty model:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_seedchain_windows.ps1
```

Documentation:

- [`docs/ARCHITECTURE_MAPPING.md`](docs/ARCHITECTURE_MAPPING.md)
- [`docs/SEEDCHAIN_DEPLOYMENT.md`](docs/SEEDCHAIN_DEPLOYMENT.md)
- [`docs/FILE_FORMAT_KLSC1.md`](docs/FILE_FORMAT_KLSC1.md)

Do not apply the synthetic 207x ratio to arbitrary PLY animations. The uploaded fitted-sequence results are retained under `benchmarks/rtx5070ti_v0.2/` precisely because they show the failure boundary.

## Integrity, identity and authorship boundaries

- KLSC1 and KLOC1 use FNV-1a64 for deterministic corruption detection. It is not a cryptographic signature.
- Compact lineage values are routing/validation checksums, not durable identity.
- Durable identity requires the source record, stable identifier, model/schema version, ordered node history and external updates.
- The user-supplied conceptual attribution appears only in [`AUTHORSHIP_NOTICE.md`](AUTHORSHIP_NOTICE.md) and is not independently verified.
- The package does not claim that VRAM is physically topological, that one bit is complete state, or that compression has zero cost.

## Validation boundary

Completed here:

- clean CPU build with GCC 14.2 and CMake 3.31;
- all original and new CPU tests passed;
- actual OMM snapshot packed, saved, reloaded and hash-validated;
- full 19,353,600-candidate CPU pass schedule generated;
- all shell scripts syntax-checked;
- CUDA source passed host/device syntax parsing.

Not completed here:

- native `nvcc` `sm_120` compilation;
- execution of the new sustained orbit benchmark on the target laptop;
- Nsight Compute and power/thermal measurements;
- SGP4 error comparison.

See [`docs/VALIDATION.md`](docs/VALIDATION.md).
