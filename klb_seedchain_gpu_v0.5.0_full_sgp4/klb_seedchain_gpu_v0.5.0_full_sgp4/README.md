# KLB SeedChain GPU 0.5.0 — Full SGP4/SDP4 working release

This directory is the actual source snapshot produced from the earlier KLB37,
KLSC1, KLOC1, and UGTS launchpad work. Version 0.5.0 replaces the coarse
Kepler-plus-J2 orbit predictor with a complete Vallado/CSSI-style SGP4/SDP4
computational path and a new compact `KSGP1` seed container.

The package is intended for an NVIDIA RTX 5070 Ti Laptop GPU with 12 GB VRAM.
The CUDA build target is native `sm_120` plus `compute_120` PTX, requiring CUDA
Toolkit 12.8 or newer.

## Delivered components

The full-SGP4 portion is implemented in the following files:

```text
include/klb/sgp4.hpp             host/device propagation core and KSGP1 ABI
include/klb/sgp4_gpu_compat.hpp  CUDA benchmark compatibility layer
src/sgp4.cpp                     OMM adapter, KSGP1 I/O, initialization, CPU tools
src/sgp4_main.cpp                pack/inspect/verify/sample/pass CLI
src/sgp4_bench.cu                direct-seed GPU SGP4, dense baseline, event benchmark
tests/test_sgp4.cpp              Vallado/CSSI reference and container tests
data/sgp4/*.ksgp                 packed 32-object GPS operational test container
```

The earlier architecture tests remain available:

```text
KLB37  continuous 37-bit log-spherical point records
KLSC1  chain-linked seed/predictor/checkpoint/novelty sequences
KLOC1  legacy coarse orbital-seed deployment for direct comparison
KSGP1  full-SGP4 mean-element seeds plus hash-linked timeline metadata
```

## What “full SGP4” means here

The propagation implementation contains the complete near-Earth and deep-space
calculation path used by the Vallado/CSSI reference family, including:

- mean-element initialization and un-Kozai correction;
- atmospheric drag through `BSTAR`;
- secular gravity and drag terms;
- short- and long-period corrections;
- deep-space solar/lunar terms;
- synchronous resonance (`irez = 1`);
- half-day resonance (`irez = 2`);
- TEME position and velocity output;
- GMST plus configurable DUT1 for the bundled TEME-to-PEF ground query.

Polar motion and full Earth-orientation-parameter handling are not included.
The pass-query output is therefore an engineering workload and not a certified
navigation product.

## Validation completed in the preparation environment

A clean GCC/C++20 build passed all three CPU suites:

```text
klb_cpu_tests    passed
klb_orbit_tests  passed
klb_sgp4_tests   passed
```

The full-SGP4 tests compare five reference cases covering every important
branch. Observed vector differences were:

```text
00005 near-Earth               dr=6.81921e-09 km  dv=6.38035e-10 km/s
04632 deep-space non-resonant  dr=5.88957e-09 km  dv=4.97538e-10 km/s
08195 half-day resonance       dr=4.22097e-09 km  dv=5.46560e-10 km/s
14128 synchronous resonance    dr=6.28263e-09 km  dv=5.22710e-10 km/s
28129 GPS-like deep-space      dr=5.29870e-09 km  dv=2.15794e-10 km/s
```

The included `KSGP1` file also passed its payload and parent/self hash-chain
checks and propagated 160 sampled object/time combinations without error. The
regenerated seven-day, one-second CPU workload produced 717 acquisition/loss
events from 19,353,600 candidate intervals with zero propagation failures.

Exact logs are under:

```text
benchmarks/sgp4_reference/cpu_reference_tests.txt
benchmarks/sgp4_reference/ctest_output.txt
benchmarks/sgp4_reference/gps_container_inspect.txt
benchmarks/sgp4_reference/gps_container_verify.txt
```


## Included full-SGP4 artifacts

```text
data/sgp4/gps_ops_2026-08-16_7d_1s.ksgp
  SHA-256: 188c754b69f4d87ba3db077515330c19570718633bab26ead4e0019a63718f7a

data/sgp4/gps_ops_2026-08-16_52N_5E_full_sgp4_pass_events.csv
  SHA-256: 4722b35b76c04b2e6a39b767f1427c72c015b0d47d0635ea55bf264d4bc196d1

data/sgp4/gps_ops_2026-08-16_coarse_vs_full_sgp4.csv
  SHA-256: afe551f851f80edfb140d10190251c2bcff5240d248ac57a23e47b7586746b22
```

The coarse-versus-full comparison found an RMS position difference of
18.083609 km and a maximum of 50.072351 km across 928 matched samples. That
quantifies why the v0.3 Kepler-plus-J2 surrogate was not suitable as the
reference orbit model; it is not an error estimate for full SGP4.

## Important CUDA status

The complete CUDA benchmark source is included. Clang 17 host/device syntax
checks pass for all four CUDA translation units, including the full-SGP4
benchmark. This preparation container does not contain NVIDIA `nvcc` or an
NVIDIA GPU, so the following still
has to be performed on the laptop:

1. compile `klb_sgp4_bench` with CUDA 12.8+ for `sm_120`;
2. execute the CPU/GPU reference-vector comparison;
3. compare direct-seed and dense event streams;
4. collect p50/p95/p99, register, occupancy, L2, DRAM, and warp-stall results.

Do not treat the package as GPU-validated until those checks pass. The CPU
propagator and file implementation are validated; the physical RTX execution is
the next acceptance stage.

## Windows build

Open **x64 Native Tools Command Prompt for Visual Studio 2022** in the extracted
package directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

This configures:

```text
CUDA architecture: 120-real;120-virtual
Configuration:      Release
CUDA required:      yes
```

The expected executables are:

```text
build\Release\klb_pack.exe
build\Release\klb_seedchain.exe
build\Release\klb_orbit.exe
build\Release\klb_sgp4.exe
build\Release\klb_bench.exe
build\Release\klb_seedchain_bench.exe
build\Release\klb_orbit_bench.exe
build\Release\klb_sgp4_bench.exe
```

## First full-SGP4 run

Inspect and verify the included seed container:

```powershell
.\build\Release\klb_sgp4.exe inspect `
  .\data\sgp4\gps_ops_2026-08-16_7d_1s.ksgp

.\build\Release\klb_sgp4.exe verify `
  .\data\sgp4\gps_ops_2026-08-16_7d_1s.ksgp
```

Run the CUDA reference and workload benchmark:

```powershell
.\build\Release\klb_sgp4_bench.exe `
  .\data\sgp4\gps_ops_2026-08-16_7d_1s.ksgp `
  --preset smoke `
  --repeats 7 `
  --min-ms 150 `
  --validation-only
```

Then run the included seven-day workload:

```powershell
.\build\Release\klb_sgp4_bench.exe `
  .\data\sgp4\gps_ops_2026-08-16_7d_1s.ksgp `
  --preset file `
  --repeats 7 `
  --min-ms 150 `
  --expected-events .\data\sgp4\gps_ops_2026-08-16_52N_5E_full_sgp4_pass_events.csv `
  --csv sgp4_file_results.csv
```

The sustained laptop preset uses 1,048,576 time intervals per object:

```powershell
.\build\Release\klb_sgp4_bench.exe `
  .\data\sgp4\gps_ops_2026-08-16_7d_1s.ksgp `
  --preset laptop `
  --repeats 7 `
  --min-ms 150 `
  --csv sgp4_laptop_results.csv
```

## Acceptance criteria for the RTX run

The run is accepted only when all of the following hold:

```text
GPU propagation error codes equal CPU error codes
GPU branch/method flags equal CPU branch/method flags
CPU/GPU TEME position and velocity remain inside the declared tolerance
Direct-seed and dense counters match
Sorted direct-seed and dense acquisition/loss event sets match
No compact-event buffer truncation occurs
```

The benchmark should report the actual device name, compute capability, memory,
register use, and timing. A storage ratio by itself is not a correctness or
performance result.

## Packing a refreshed OMM CSV

The adapter is dependency-free. Given a CelesTrak-style OMM CSV:

```powershell
.\build\Release\klb_sgp4.exe pack-omm-csv `
  .\data\orbit\source\gps_ops_2026-08-16_omm.csv `
  refreshed.ksgp `
  --horizon-hours 168 `
  --step-seconds 1 `
  --tile-hours 24 `
  --gravity wgs72 `
  --elevation-deg 10
```

The compact file stores 128 bytes per source mean-element seed and 64 bytes per
hash-linked timeline tile. The much larger initialized SGP4 coefficient state is
compiled at load time and is not stored in the container.

## CPU pass query

Generate a deterministic acquisition/loss schedule from the full predictor:

```powershell
.\build\Release\klb_sgp4.exe passes `
  .\data\sgp4\gps_ops_2026-08-16_7d_1s.ksgp `
  --lat 52 `
  --lon 5 `
  --alt-km 0.05 `
  --elevation-deg 10 `
  --hours 168 `
  --step-seconds 1 `
  --output full_sgp4_pass_events.csv
```

## Linux CPU-only build used for validation

When CUDA is not installed, build the CPU tools explicitly:

```bash
cmake -S . -B build-cpu \
  -DCMAKE_BUILD_TYPE=Release \
  -DKLB_BUILD_CUDA=OFF
cmake --build build-cpu -j
ctest --test-dir build-cpu --output-on-failure
```

## Source and attribution boundary

The conceptual substrate attribution supplied by the requester is recorded in
`AUTHORSHIP_NOTICE.md`. The SGP4 mathematics follow the Vallado/CSSI reference
family; provenance and license notes are in `NOTICE_SGP4.md` and
`THIRD_PARTY_DATA.md`.

The 32-bit/64-bit lineage values and FNV hashes are deterministic integrity and
routing aids, not cryptographic signatures or proof of identity.
