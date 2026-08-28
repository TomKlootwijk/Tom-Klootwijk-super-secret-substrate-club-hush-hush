# Delivery status — 0.5.0 full-SGP4/SDP4 release candidate

This directory is the deliverable source snapshot. It is not a placeholder.

## Completed and re-verified in the preparation environment

- Complete Vallado/CSSI-style SGP4/SDP4 CPU propagation path.
- Near-Earth, deep-space non-resonant, synchronous-resonance, half-day-resonance,
  and GPS-like branch tests against published verification vectors.
- Immutable host/device propagation core in `include/klb/sgp4.hpp`.
- CUDA direct-seed propagation, dense-materialization baseline, support/guard
  query, compact acquisition/loss events, and CPU/GPU acceptance checks in
  `src/sgp4_bench.cu`.
- OMM CSV parser and compact KSGP1 packer.
- KSGP1 payload, node-parent, self-hash, and terminal-chain validation.
- TEME state output and GMST+DUT1 TEME-to-PEF ground-query conversion.
- A 32-object GPS Operational KSGP1 seed container and a regenerated seven-day,
  one-second full-SGP4 pass-event schedule.
- Clean GCC 14.2/C++20 build with all three CPU test suites passing.
- Clang 17 host/device CUDA syntax checks passing for all four `.cu` files.
- Clang CUDA device-only LLVM IR generation passing for `src/sgp4_bench.cu`.
  These are frontend/code-generation checks only, not an `nvcc` build or GPU execution result.
- Earlier KLB37, KLSC1, and KLOC1 tools, data, and RTX 5070 Ti results retained.

## Included full-SGP4 data results

```text
KSGP1 bytes                  5,793
Objects                      32
Declared timeline            604,800 seconds at 1-second spacing
Candidate intervals          19,353,600
Acquisition/loss events      717
Propagation failures         0
KSGP1 SHA-256                188c754b69f4d87ba3db077515330c19570718633bab26ead4e0019a63718f7a
Event CSV SHA-256            4722b35b76c04b2e6a39b767f1427c72c015b0d47d0635ea55bf264d4bc196d1
```

The horizon-relative storage ratios are avoided-materialization comparisons,
not claims that a pre-existing dense trajectory file was losslessly compressed.

## Target-laptop acceptance still required

- Native CUDA 12.8+ compilation for `sm_120`.
- Execution on the RTX 5070 Ti Laptop GPU.
- CPU/GPU SGP4 vector agreement within the benchmark tolerance.
- Direct-seed versus dense counter and sorted event-stream equality.
- Nsight Compute register, occupancy, L2, DRAM, SFU, and warp-stall results.
- Steady-state power and thermal measurements.

The CPU implementation, KSGP1 container, and generated CPU event schedule are
accepted. The CUDA source is delivered and syntax-checked, but the physical GPU
run remains the next acceptance gate.
