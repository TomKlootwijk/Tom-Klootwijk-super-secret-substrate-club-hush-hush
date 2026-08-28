# Delivery status — 0.6.0 network-pruning challenge

This directory is a complete source-and-data challenge package.

## Completed in the preparation environment

- Full v0.5 SGP4/SDP4 implementation retained.
- 58-object mixed-orbit KSGP1 file built from 32 GPS and 26 TDRSS-group records.
- 16 typed station-policy profiles loaded from CSV.
- Static support envelope and compatibility plan generated for all 928 pairs.
- CPU all/support/active relation oracles implemented.
- Seven-day, 60-second active event schedule generated.
- All/support/active event-identity checks passed.
- Four CTest suites passed in a clean C++20 build.
- CUDA network benchmark passed Clang host/device syntax checks.
- CUDA network benchmark passed device-only LLVM IR generation.
- Windows build script now checks native exit codes and required executables.
- SP3 comparison adapter and synthetic parser fixture included.

## Included CPU acceptance result

```text
All pairs                      928
Support pairs                  711
Active pairs                   438
Relation reduction             2.118721x
Intervals                      10,080
Object propagations            584,640
All relation intervals         9,354,240
Active relation intervals      4,415,040
AOS events                     4,653
LOS events                     4,682
Total events                   9,335
Propagation failures           0
All/active event identity      PASS
```

## Physical RTX acceptance still required

- Native CUDA 12.8+ `sm_120` compilation.
- Pair-all GPU versus CPU event identity.
- Pair-active GPU versus CPU event identity.
- Pair-active versus grouped-active event and counter equality.
- Grouped-active versus dense-active event and counter equality.
- p50/p95/p99 timings for pair, grouped, materialize, and dense modes.
- Register pressure, occupancy, branch efficiency, and DRAM/L2 measurements.
- Thermal and power telemetry for a sustained run.

No GPU performance result for the new network challenge is claimed until the
laptop produces those outputs.
