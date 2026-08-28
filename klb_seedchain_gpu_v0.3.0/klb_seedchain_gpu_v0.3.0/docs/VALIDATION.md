# Validation report

## Completed in the preparation environment

### CPU build and tests

```text
Compiler                    GCC 14.2
CMake                       3.31
Language                    C++20
CPU test suites             2
Result                      all passed
```

Validated behavior includes:

- original KLB37 continuous 37-bit packing and boundary cases;
- KLSC1 node/hash/reconstruction tests;
- quoted OMM CSV parsing;
- KLOC1 pack, save, load, canonical offsets and hash chain;
- deterministic orbital propagation sanity range;
- station support/elevation evaluation;
- corruption detection;
- KLOC1 inspect, verify, sample and pass-event commands.

### Included data

The CelesTrak GPS Operational source snapshot was packed and reloaded successfully.

```text
source bytes                4,852
source records              32
KLOC1 bytes                 3,809
nodes                       7
source SHA-256              f45d43705e1cdc9121eb17d15baa3bc0ad0d97e0c21e94a78c44d4ddd6ddb8fb
KLOC1 SHA-256               fe0036df05ad0f4036f8cfcf489a3d371557924bd8868f00c8e525cf6d2c6f73
payload hash                0x4b0bdd3e929c3d08
terminal chain hash         0x2ccf05789110dcd6
```

`klb_orbit verify` sampled every seed at four times and reported finite ECI radii from approximately 26,071.4 to 27,048.3 km.

### Full CPU application run

The included 52°N, 5°E, 10° elevation-mask schedule was regenerated over the complete seven-day, one-second horizon:

```text
intervals                   604,800
candidate intervals         19,353,600
support survivors           19,214,155
compatible survivors        19,214,155
visible samples             5,498,030
acquisition/loss events     717
```

This validates internal determinism and file/query plumbing under the bundled coarse predictor. It does not validate orbital accuracy against SGP4.

### CUDA source validation

The CUDA sources passed host-side and device-side Clang CUDA syntax parsing using a local declaration stub. The parser target was not the deployment target and produced no runnable binary. The actual target remains native `sm_120` plus `compute_120` PTX.

## Not completed here

- native `nvcc` compilation for `sm_120`;
- execution of `klb_orbit_bench` on the RTX 5070 Ti Laptop GPU;
- p50/p95/p99 sustained orbit results;
- Nsight Compute DRAM, L2, occupancy, register and warp-stall measurements;
- power and thermal steady-state measurements;
- comparison with SGP4 or precise ephemerides;
- error-bound certification for real antenna, navigation or safety applications.

## Target-laptop acceptance commands

Build:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

Actual included seven-day horizon:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\demo_orbit_windows.ps1
```

Sustained laptop workload:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stress_orbit_windows.ps1 -Preset laptop
```

Optional approximately 2 GiB dense baseline:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\stress_orbit_windows.ps1 -Preset vram
```

## Required acceptance checks

1. Device name and compute capability report the intended GPU and 12.0.
2. CPU, direct GPU and dense GPU counters match exactly for the oracle prefix.
3. Direct and dense compact event sets match when `--write-events` is enabled.
4. No event output truncation occurs.
5. p50, p95 and p99 are recorded for each mode.
6. The test runs long enough that `inner_repeats` or the raw dispatch itself reaches the minimum sample duration.
7. The dense allocation remains within the benchmark safety margin.
8. Results are interpreted with the coarse-predictor boundary.
9. A later SGP4 reference establishes an event-order/error budget before operational use.

## Kill criteria

Reject the deployment for a workload when:

- seed reconstruction plus guard evaluation is slower than the avoided materialization/storage cost at equal accuracy;
- event/branch density or compaction contention dominates;
- the predictor error changes acquisition/loss ordering beyond budget;
- the data is not closed/reconstructible and external novelty becomes dense;
- register pressure or transcendental throughput collapses occupancy;
- a conventional dense or SGP4 CPU/GPU path is cheaper, faster or more accurate at the required error.
