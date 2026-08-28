# Release notes — 0.6.0 mixed-orbit network pruning challenge

## Added

- `klb_network`, a CPU plan/oracle/verification CLI.
- `klb_network_bench`, a CUDA pair-expanded/grouped/dense comparison.
- 58-object mixed LEO/MEO/GEO/HEO KSGP1 dataset.
- 16-station typed benchmark policy network.
- Conservative support envelope and orbit/service/route compatibility planner.
- Audited 928-row object-station pair table.
- Seven-day, 60-second CPU event oracle containing 9,335 transitions.
- TLE/3LE-to-OMM CSV adapter.
- Dependency-free OMM merge utility.
- External SP3 comparison adapter.
- Explicit native-command and expected-binary checks in the Windows build script.
- CPU test coverage for mixed orbit classification, plan reduction, and event identity.

## Changed

- Package version is now 0.6.0.
- The principal challenge is no longer a one-station GPS scan. It is a mixed
  relation network designed to exercise support and compatibility pruning.
- The preferred CUDA implementation reconstructs each object/time state once
  and reuses it across selected stations.

## Preserved

- KLB37 packed-point test.
- KLSC1 chain-linked sequence test.
- KLOC1 obsolete coarse-orbit baseline.
- KSGP1 full SGP4/SDP4 implementation and prior RTX 5070 Ti evidence.
- Vallado near/deep/synchronous/half-day/GPS-like reference cases.

## Preparation-environment result

```text
CTest                           4/4 passed
Objects/stations                58/16
All/support/active pairs        928/711/438
Relation work reduction         2.118721x
Seven-day active events         9,335
All/active event identity       PASS
Propagation failures            0
CUDA host/device syntax         PASS
CUDA device LLVM generation     PASS
```

Native CUDA 12.8+ compilation and execution of `klb_network_bench` on the RTX
5070 Ti Laptop GPU remain the physical acceptance step.
