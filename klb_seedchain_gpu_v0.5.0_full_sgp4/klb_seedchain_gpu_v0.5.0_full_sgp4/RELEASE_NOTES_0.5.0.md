# KLB SeedChain GPU 0.5.0 release notes

## Primary correction

The v0.3 orbit workload used a deliberately simplified Kepler-plus-secular-J2
predictor. Version 0.5.0 replaces it with the full Vallado/CSSI-style SGP4/SDP4
calculation path, including the deep-space branch and both resonance families.
The old KLOC1 predictor remains only for measured comparison.

## New deliverables

- `KSGP1` compact mean-element seed format.
- Full CPU and host/device SGP4 implementation.
- CUDA direct-seed query and dense materialization benchmark.
- Five-regime verification-vector test suite.
- 32-object GPS Operational seed container.
- Seven-day, one-second full-SGP4 acquisition/loss event schedule.
- Coarse-versus-full position-error report.
- Windows/Linux build, demo, and Nsight Compute scripts.

## Fresh validation result

```text
CPU test suites                3/3 passed
CUDA translation units        4/4 host syntax passed
CUDA translation units        4/4 device syntax passed
KSGP1 hash verification       passed
KSGP1 reference evaluations   160
KSGP1 propagation failures    0
Seven-day event count          717
```

## Remaining boundary

No `nvcc` compiler or physical NVIDIA GPU was available in the preparation
environment. The RTX 5070 Ti Laptop acceptance run is therefore intentionally
not claimed as completed. Run the bundled smoke validation first, then the file
preset with the included expected-event CSV.
