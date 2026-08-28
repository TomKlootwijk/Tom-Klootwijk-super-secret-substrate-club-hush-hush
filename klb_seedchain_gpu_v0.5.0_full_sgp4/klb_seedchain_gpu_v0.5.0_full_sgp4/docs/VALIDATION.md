# Validation report — KLB SeedChain GPU 0.5.0

## Preparation environment

```text
Compiler                    GCC 14.2
CMake                       3.31
Language                    C++20
CUDA frontend surrogate     Clang 17
CUDA compiler               nvcc unavailable in this container
Physical NVIDIA GPU         unavailable in this container
```

## CPU build and tests

A clean CPU build completed with `KLB_BUILD_CUDA=OFF`. All three CTest targets
passed:

```text
klb_cpu_tests               passed
klb_orbit_tests             passed
klb_sgp4_tests              passed
```

Exact logs are in `validation/CPU_*.txt` and
`benchmarks/sgp4_reference/ctest_output.txt`.

## Full SGP4/SDP4 reference coverage

`tests/test_sgp4.cpp` covers the following Vallado/CSSI verification regimes:

| Object | Regime | Expected branch | Position error | Velocity error |
|---|---|---:|---:|---:|
| 00005 | near-Earth | method `n`, `irez=0` | 6.81921e-09 km | 6.38035e-10 km/s |
| 04632 | deep-space non-resonant | method `d`, `irez=0` | 5.88957e-09 km | 4.97538e-10 km/s |
| 08195 | half-day resonance | method `d`, `irez=2` | 4.22097e-09 km | 5.46560e-10 km/s |
| 14128 | synchronous resonance | method `d`, `irez=1` | 6.28263e-09 km | 5.22710e-10 km/s |
| 28129 | GPS-like deep-space | method `d`, `irez=0` | 5.29870e-09 km | 2.15794e-10 km/s |

The test also checks mutable versus immutable propagation agreement, OMM CSV
packing, KSGP1 save/load, payload and chain hashes, compiled coefficient state,
and a TEME-to-PEF radius-preservation invariant. Exact output is in
`validation/FULL_SGP4_REFERENCE_TESTS.txt`.

## CUDA source validation

All four CUDA translation units passed both Clang CUDA host-only and device-only
syntax checks with a minimal local CUDA-runtime declaration stub:

```text
src/bench.cu             PASS host / PASS device
src/seedchain_bench.cu   PASS host / PASS device
src/orbit_bench.cu       PASS host / PASS device
src/sgp4_bench.cu        PASS host / PASS device
```

This checks parsing, host/device callability, and template instantiation through
the Clang CUDA frontend. The full-SGP4 CUDA file also completed device-only
LLVM IR generation. These checks do not generate an NVIDIA PTX/cubin, exercise
CUDA 12.8 `sm_120`, or run a physical GPU. Exact records are in
`validation/CUDA_CLANG_SYNTAX.txt` and
`validation/CUDA_SGP4_LLVM_CODEGEN.txt`.

## Included KSGP1 container

```text
Path                        data/sgp4/gps_ops_2026-08-16_7d_1s.ksgp
Reference epoch             2026-08-16T05:33:12.693024Z
Container bytes             5,793
Source mean-element seeds   32 x 128 bytes
Timeline nodes              7 x 64 bytes
Timeline                    604,800 seconds at 1-second declared spacing
Reference frame             TEME
Ground conversion           GMST + configurable DUT1, TEME to PEF
Gravity constants           WGS-72
Compiled coefficient state  45,568 bytes at load time; not stored
SHA-256                     188c754b69f4d87ba3db077515330c19570718633bab26ead4e0019a63718f7a
```

The file passed payload, node-parent, self-hash, and terminal-chain validation.
The verifier evaluated 32 objects at five times, for 160 state evaluations, with
zero propagation failures. Sampled TEME radii ranged from 26,065.952586335 to
27,026.766703343 km; sampled speeds ranged from 3.806459986 to 3.946624679 km/s.

## Regenerated useful workload

A CPU full-SGP4 visibility query was regenerated for a station at 52° N, 5° E,
0.05 km altitude, a 10° elevation guard, one-second sampling, and a seven-day
horizon:

```text
Candidate intervals          19,353,600
Support survivors            19,207,536
Compatible survivors         19,207,536
Visible samples               5,498,429
Acquisition/loss events             717
Propagation failures                    0
Event CSV SHA-256             4722b35b76c04b2e6a39b767f1427c72c015b0d47d0635ea55bf264d4bc196d1
```

The legacy coarse predictor differed from full SGP4 by 18.083609 km RMS and
50.072351 km maximum across 928 matched samples. That comparison demonstrates
why KLOC1 is retained only as an obsolete baseline.

## Frame and operational boundary

SGP4 returns TEME. The bundled ground query applies GMST and DUT1 to obtain a
PEF-like rotating frame. It does not apply polar motion, full IERS Earth
orientation, antenna patterns, signal propagation, clock corrections, or
navigation integrity processing. The output is suitable for the compression and
GPU crossover experiment, not certified navigation or safety operations.

## Target-laptop acceptance sequence

1. Build with CUDA Toolkit 12.8 or newer and CMake architecture `120`.
2. Run all CPU CTest suites.
3. Run `klb_sgp4_bench --preset smoke --validation-only`.
4. Require CPU/GPU error codes and near/deep/resonance branch flags to match.
5. Require TEME position and velocity errors to stay inside the benchmark
   tolerance.
6. Run the file preset with the included `--expected-events` CSV.
7. Require direct-seed and dense counters and sorted event payloads to match.
8. Run the sustained laptop preset and record p50/p95/p99.
9. Profile register pressure, occupancy, L2/DRAM traffic, transcendental stalls,
   and compaction contention.
10. Apply the kill criteria before promoting a speed or compression claim.

## Kill criteria

Reject the deployment for a workload when:

- SGP4 reconstruction plus guard evaluation is slower than the avoided
  materialization/storage cost at equal accuracy;
- register pressure or transcendental throughput collapses occupancy;
- event density or compaction contention dominates;
- packed/converted coordinates change acquisition/loss ordering beyond budget;
- external novelty becomes dense, removing seed-chain benefit;
- frame/EOP error exceeds the declared event margin;
- a conventional dense or CPU/GPU reference path is cheaper, faster, or more
  accurate at the required error.
