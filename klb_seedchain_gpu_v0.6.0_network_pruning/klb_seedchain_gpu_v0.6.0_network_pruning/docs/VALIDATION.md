# Validation report — KLB SeedChain GPU 0.6.0

## Preparation environment

```text
Compiler                    GCC 14.2
Language                    C++20
CUDA frontend check         Clang 17
CUDA compiler               nvcc unavailable here
Physical NVIDIA GPU         unavailable here
```

## Clean CPU build

Four CTest targets passed:

```text
klb_cpu_tests               PASS
klb_orbit_tests             PASS
klb_sgp4_tests              PASS
klb_network_tests           PASS
```

The network suite checks source parsing, all four orbit classes, station-policy
loading, support and compatibility reduction, and event identity between the
all/support/active relation sets.

## Full-SGP4 baseline retained

The 0.5.0 reference coverage remains unchanged:

| Object | Regime | Branch | Position difference | Velocity difference |
|---|---|---:|---:|---:|
| 00005 | near-Earth | `n/0` | 6.81921e-09 km | 6.38035e-10 km/s |
| 04632 | deep non-resonant | `d/0` | 5.88957e-09 km | 4.97538e-10 km/s |
| 08195 | half-day resonance | `d/2` | 4.22097e-09 km | 5.46560e-10 km/s |
| 14128 | synchronous resonance | `d/1` | 6.28263e-09 km | 5.22710e-10 km/s |
| 28129 | GPS-like deep space | `d/0` | 5.29870e-09 km | 2.15794e-10 km/s |

The uploaded RTX 5070 Ti 0.5.0 evidence also showed CPU/GPU agreement,
independent Python-SGP4 agreement, sanitizer success, and stable sustained
execution. Those artifacts are retained as text/CSV evidence; bulky profiler
binary reports are intentionally excluded from this smaller release.

## Mixed KSGP1 container

```text
Path                         data/network/celestrak_mixed_58obj_7d_60s.ksgp
Objects                      58
Container bytes              9,581
Compact seed state           58 × 128 bytes
Compiled coefficient state   82,592 bytes at load time, not stored
Timeline nodes               7
Duration                     604,800 seconds
Step                         60 seconds
Near/deep/sync/half-day      11/36/11/0
Payload hash                 valid
Parent/self/terminal chain   valid
SHA-256                      7142a16be1f7c64c6df9d69b91afc961be9987dc1ae567031026379db0031a20
```

The separate Vallado fixture continues to cover the half-day branch.

## Static plan validation

```text
Objects/stations              58/16
All pairs                     928
Support pairs                 711
Active pairs                  438
Support gain                  1.305204x
Compatibility gain            1.623288x
Total relation reduction      2.118721x
```

The support envelope is conservative relative to the runtime maximum-slant-
range predicate. The test requires the support mode to retain exactly the same
runtime support survivors as the all-pairs mode.

## Seven-day CPU oracle

```text
Intervals                     10,080
Object propagations           584,640
All relations                 9,354,240
Support relations             7,166,880
Active relations              4,415,040
Runtime support survivors     5,932,861
Compatible survivors          3,970,997
Visible endpoints             1,101,511
AOS/LOS                       4,653/4,682
Events                        9,335
Propagation failures          0
```

```text
all/support event identity    PASS
all/active event identity     PASS
support survivor equality     PASS
active compatible equality    PASS
```

## CUDA source validation

`src/network_bench.cu` passed:

```text
Clang CUDA host syntax        PASS
Clang CUDA device syntax      PASS
device-only LLVM generation   PASS
```

This proves source parseability and device-code generation through the Clang
frontend. It does not prove `nvcc` compilation or physical RTX execution.

## SP3 adapter validation

The parser/comparison tool was exercised with a synthetic SP3 fixture generated
from package PEF samples. It verified gzip/plain parsing, epoch extraction, GPS
PRN matching, CLI invocation, and result generation. This fixture is a software
self-test, not independent physical-orbit evidence.

## Physical acceptance sequence

1. Build with CUDA Toolkit 12.8+ and architecture 120.
2. Run all four CTest targets.
3. Run `demo_network_windows.ps1 -Preset file`.
4. Require all pair/CPU/grouped/dense validation lines to pass.
5. Run `stress_network_windows.ps1`.
6. Compare `pair_active` against `grouped_active` to quantify propagation reuse.
7. Compare `grouped_active` against materialize+dense and resident dense query.
8. Profile registers, occupancy, branch efficiency, FP64 pipelines, L2, DRAM,
   and event append contention.
9. Record power, temperature, clocks, and throttling for sustained execution.
10. Run the external SP3 challenge with overlapping products.

## Kill criteria

Do not promote the network result when:

- support and compatibility filters fail to remove enough relations;
- grouping overhead or divergence erases the avoided propagation work;
- event density or atomic append dominates;
- dense materialization plus reuse is cheaper for the real query count;
- coordinate/frame error changes event ordering beyond budget;
- stale mean elements dominate the SP3 comparison;
- a conventional implementation is cheaper, faster, or more accurate at equal
  error.
