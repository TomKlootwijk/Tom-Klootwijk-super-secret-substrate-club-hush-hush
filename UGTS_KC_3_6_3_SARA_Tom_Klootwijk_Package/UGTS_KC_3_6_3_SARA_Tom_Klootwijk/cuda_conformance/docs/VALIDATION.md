# Validation record - 2026-08-18

## Outcome

Overall conformance passed on the NVIDIA GeForce RTX 5070 Ti Laptop GPU (compute capability 12.0), using CUDA 12.8 and native plus virtual `sm_120` code.

## Correctness gates

- Published BIP39 seed on CPU: PASS
- Published BIP39 seed on GPU: PASS
- All six official BIP32 vector-1 nodes on CPU: PASS
- All six official BIP32 vector-1 nodes on GPU: PASS
- 65,536 BIP39 outputs in each of seven large timed runs: PASS
- 4,096 complete BIP32 paths in each of seven large timed runs: PASS
- Byte-for-byte repeatability: PASS
- CMake/CTest native quick test: 1/1 PASS
- Targeted original `tests/test_sara363.py`: 42/42 PASS
- Independent fixed-vector execution through the unchanged literal `sara363.py`: PASS
- Rejected input-surface check (`--mnemonic PUBLIC_TEST_ONLY`): PASS; unknown option, exit 1

The broad unscoped `pytest` discovery command is not a valid package result in the available Miniconda environment: it lacks the installed `ugts36` package path and recursively collects duplicate test modules under the pre-existing `tmp/pristine_zip`. The relevant original SARA test module was rerun explicitly with `src` on `PYTHONPATH` and passed 42/42.

## Primary large-batch metrics

Configuration: 65,536 BIP39 operations, 4,096 complete BIP32 vector-1 paths, seven timed runs.

| Metric | Result |
|---|---:|
| CPU BIP39 mean | 1.995 ms/operation |
| CPU complete BIP32 path mean | 3.513 ms/path |
| GPU BIP39 batch mean | 1,705.628 ms |
| GPU BIP39 throughput | 38,423.4 operations/s |
| GPU PBKDF2 round throughput | 78,691,102.2 rounds/s |
| GPU BIP32 batch mean | 26.268 ms |
| GPU complete BIP32 path throughput | 155,933.3 paths/s |
| GPU BIP32 CKD edge throughput | 779,666.7 edges/s |
| BIP39 throughput vs this single CPU implementation | 76.6x |
| BIP32 throughput vs this single CPU implementation | 547.8x |

## Single-item latency

| Metric | Result |
|---|---:|
| One GPU BIP39 operation | 61.425 ms |
| One GPU complete BIP32 path | 26.174 ms |
| CPU BIP39 mean in that run | 1.994 ms |
| CPU complete BIP32 path mean in that run | 3.498 ms |

The GPU implementation is therefore a parallel-throughput accelerator, not a low-latency accelerator.

## Compiler resource report

| Kernel | Registers/thread | Stack/thread | Spill report |
|---|---:|---:|---:|
| BIP39 batch | 254 | 4,304 bytes | 128-byte stores and 128-byte loads |
| BIP32 batch | 253 | 4,080 bytes | 0 |
| BIP32 conformance | 232 | 4,080 bytes | 0 |

These measurements support the documented optimization gap: the baseline is correct but resource-heavy and occupancy-limited. Timing is specific to one laptop state and is not a guarantee for other devices.
