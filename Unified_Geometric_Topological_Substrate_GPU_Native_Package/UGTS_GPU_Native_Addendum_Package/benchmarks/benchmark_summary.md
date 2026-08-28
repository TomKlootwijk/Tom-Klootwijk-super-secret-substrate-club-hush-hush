# UGTS GPU-Native Benchmark Summary

Validation device: **SwiftShader Device (Subzero)** (Vulkan 1.3.0; physical GPU claim: `false`).
Largest batch: **1,048,576 candidates**.

## Named performance metrics

| Name | Symbol | Value | Unit | Scope |
|---|---:|---:|---|---|
| Candidate Evaluation Rate | CER | 83.6999 | million candidates/s | G64_E32 evaluate, N=1048576 |
| Spherical Event Throughput | SET | 4.1125 | million verified events/s | G64_E32 evaluate, N=1048576 |
| Effective Substrate Bandwidth | ESB | 8.0352 | GB/s | G64_E32 evaluate, N=1048576 |
| Support Rejection Gain | SRG | 1.8982 | x | G64_E32 deterministic corpus |
| Compatibility Rejection Gain | CRG | 6.0019 | x | G64_E32 deterministic corpus |
| Event Yield | EY | 4.9134 | % | G64_E32 deterministic corpus |
| State Compression Ratio | SCR | 2.0000 | x | N=1048576 |
| Event Compaction Ratio | ECR | 21.0228 | x | G32_E16 evaluate, N=1048576 |
| State-plus-Novelty Compression | SNC | 2.9303 | x | N=1048576 |
| Commit Cost Factor | CCF | 1.7531 | x | G64_E32, N=1048576 |
| Packed Compute Penalty | PCP | 1.0622 | x | N=1048576; software Vulkan device |

## Memory configurations

| Configuration | Memory | Fraction of G64 dense | Retention |
|---|---:|---:|---|
| G64_E32 dense | 96.000 MiB | 100.000% | all states + dense outputs |
| G32_E16 dense | 48.000 MiB | 50.000% | all packed states + dense outputs |
| G32 state + compact E16 novelty log | 32.761 MiB | 34.126% | all packed states + verified events only |
| G32 compact E16 novelty log only | 779.344 KiB | 0.793% | verified events only; state must be rebuildable |

## Interpretation boundary

These measurements validate native Vulkan shader-module creation, compute-pipeline creation, pipeline-cache reload, descriptor/buffer binding, device-timestamped dispatch, and GPU-written output validation on the device named above. They do not establish physical-GPU, ASIC, FPGA, photonic, or optofluidic performance.
