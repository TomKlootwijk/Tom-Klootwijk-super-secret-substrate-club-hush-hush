# Physical RTX 5070 Ti evidence — 2026-08-29

This directory records a local Windows 11 run on an NVIDIA GeForce RTX 5070
Ti Laptop GPU (compute capability 12.0, 46 SMs, 12,820,480,000 reported
bytes). The active power plan was Balanced. CUDA 12.8.61 compiled real
`sm_120` cubins; the driver was 591.59.

## Current gates

- `ctest-rtx5070ti.txt`: 3/3 native tests passed.
- `python-tests.txt`: 142/142 Python tests passed with the CUDA executable
  enabled.
- `campaign-verify.json`: valid campaign, 20 obligations, 0 verified,
  classical root `UNKNOWN`.
- `campaign-snapshot.json`: portable event/job checkpoint whose SHA-256 is
  recorded as
  `169727632af362c0fc0a61ef68893b01a4b91a269271d9a656289fd325130c54`
  in `campaign-export.json`. Publish or sign that digest separately to create
  an external tamper anchor; the adjacent hash file is not independent.
- `gpu-movegen-qualification-1024.json`: 1,040 positions, 5/5 CUDA batches,
  no fallback, backend/header/hash evidence consistent, zero move-set
  mismatches.
- `gpu-movegen-qualification-4096.json`: 4,112 positions (4,088 unique),
  9/9 CUDA batches, no fallback, backend/header/hash evidence consistent,
  zero move-set mismatches. Corpus SHA-256:
  `4f9f418f553e69793728c53c6d7d7945f7bc794f81faecaa0bedaee8418323bc`.
- `throughput/benchmark-131072.json`: bound to executable SHA-256
  `5fac510a7f8f80cb0797849cc4062b1864e0a4c0a02db5acf017d2a744895f77`
  and input SHA-256
  `40fc2db41d438f7b254702c7ecb94ecc0909bf7a3ebe526affef4a2c5689463f`.
  CPU and CUDA outputs have the same counts and all 256 move slots for all
  131,072 positions. Native-timer p50 was about 1.386 million positions/s on
  CUDA versus 0.332 million on CPU (4.18× for this large-batch microbenchmark).

The benchmark can be reproduced with:

```powershell
$env:PYTHONPATH = "src"
python scripts/benchmark_rtx5070ti.py
```

The runner refuses to overwrite retained evidence unless `--force` is passed.

## Claim boundary

These files validate the recorded corpora and this binary; they do not prove
all possible chess states. Native timing is a packed move-expansion
microbenchmark, not playing strength. No sustained 5/15/30-minute thermal,
clock, power, battery, peak-VRAM, host-RAM, or storage-per-verified-node claim
has been established. `throughput/comparison-131072.json` and
`throughput/latency-131072.json` are earlier numerically consistent but
unbound measurements; the v2 benchmark above is authoritative. Most
importantly, none of this changes the classical root from `UNKNOWN`.
