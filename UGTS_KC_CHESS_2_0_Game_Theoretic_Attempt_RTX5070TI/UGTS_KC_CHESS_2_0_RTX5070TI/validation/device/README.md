# Physical RTX 5070 Ti evidence — 2026-08-29

This directory records a local Windows 11 run on an NVIDIA GeForce RTX 5070
Ti Laptop GPU (compute capability 12.0, 46 SMs, 12,820,480,000 reported
bytes). The active power plan was Balanced. CUDA 12.8.61 compiled real
`sm_120` cubins; the driver was 591.59.

## Current gates

- `ctest-rtx5070ti.txt`: 3/3 native tests passed.
- `python-tests.txt`: 244/244 Python tests passed with the CUDA executable
  enabled, including v1 overlay commitments, unified v2 fact-journal
  corruption/recovery checks, and both portable and compact one-hop
  propagation adversarial coverage.
- `python-tests-cpu-concurrent.txt`: after the deterministic worklist was added,
  255/256 tests passed and the one live-device protocol test was deliberately
  skipped. This CPU-only run includes all 11 worklist tests, including restart
  convergence after failures before propagation commit and after durable commit
  but before parent scheduling. The GPU was left to a concurrent Go-solving
  task, so this file is not new device or timing evidence.
- `campaign-verify.json`: valid campaign, 20 obligations, 0 verified,
  classical root `UNKNOWN`.
- `campaign-snapshot.json`: portable event/job checkpoint whose SHA-256 is
  recorded as
  `0dc3ef0dfef1068d3d0d7814c8e6dabbcf17bfb46002396aeba6e0f963e28383`
  in `campaign-export.json`. Publish or sign that digest separately to create
  an external tamper anchor; the adjacent hash file is not independent.
- `gpu-movegen-qualification-1024.json`: v2 exact-binary profile, 1,040
  positions, 5/5 CUDA batches, no fallback, backend/header/hash evidence
  consistent, and zero move-set mismatches. The retained record passed schema,
  structural, artifact, fresh-device and fresh exact-binary replay checks.
- `gpu-movegen-qualification-4096.json`: 4,112 positions (4,088 unique),
  v2 exact-binary profile, 9/9 CUDA batches, no fallback,
  backend/header/hash evidence consistent, zero move-set mismatches. Corpus SHA-256:
  `4f9f418f553e69793728c53c6d7d7945f7bc794f81faecaa0bedaee8418323bc`.
- `throughput-v4/benchmark-131072.json`: immutable-input v4 evidence bound to executable SHA-256
  `5fac510a7f8f80cb0797849cc4062b1864e0a4c0a02db5acf017d2a744895f77`
  and input SHA-256
  `40fc2db41d438f7b254702c7ecb94ecc0909bf7a3ebe526affef4a2c5689463f`.
  CPU and CUDA outputs have the same counts and all 256 move slots for all
  131,072 positions. Native-timer p50 was about 1.434 million positions/s on
  CUDA versus 0.329 million on CPU (4.35× for this large-batch microbenchmark).
  Exclusive GPU access was not enforced, concurrent workloads were not
  monitored by the runner, and another project thread was using shared compute;
  treat this timing as contention-affected.
- The two retained v2 qualification records were freshly replayed again before
  the compact fact-journal integration, including a fresh device probe and fresh
  execution of every retained batch. Both passed. This replay was slow under
  concurrent local work, so its elapsed time is not performance evidence.

The benchmark can be reproduced with:

```powershell
$env:PYTHONPATH = "src"
python scripts/benchmark_rtx5070ti.py --output-dir validation/device/throughput-v4
```

The runner refuses to overwrite retained evidence unless `--force` is passed.

## Claim boundary

These files validate the recorded corpora and exact binary; they do not prove
all possible chess states or independently attest physical GPU execution.
Native timing is a packed move-expansion
microbenchmark, not playing strength. No sustained 5/15/30-minute thermal,
clock, power, battery, peak-VRAM, host-RAM, or storage-per-verified-node claim
has been established. The generic v1 qualification and `throughput/`,
`throughput-v3/` files are retained historical evidence and do not satisfy the
current v2 qualification/v4 benchmark profiles. Most importantly, none of
this changes the classical root from `UNKNOWN`.
