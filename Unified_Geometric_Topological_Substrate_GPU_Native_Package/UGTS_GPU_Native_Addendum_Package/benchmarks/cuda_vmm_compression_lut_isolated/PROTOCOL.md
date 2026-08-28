# Native CUDA VMM compression versus packed6 LUT protocol

## Question

CUDA confirms that this GPU can grant generic-compressible VMM allocations, but the property alone does not say whether a packed/log-encoded LUT benefits. This experiment compares the same dense packed6 decoder through explicit non-compressible and driver-confirmed generic-compressible allocations.

Three content regimes bracket useful information density:

- `zero6`: every logical code is zero; this is a zero-entropy upper control, not a useful information-bearing LUT;
- `periodic6`: code `index mod 64`, matching the existing packed-LUT validation pattern and repeating every 48 packed bytes;
- `entropy6`: deterministic mixed 6-bit codes, densely filling the available 6 bits/code.

Sixteen codes occupy exactly three words (0.75 byte/code) in every regime. Each lookup selects a random logical code, executes the native packed decoder, and validates the returned value inside the timed kernel.

## Strict native pairing

For each size and pattern, one effective mode-0 and one effective mode-1 allocation coexist. Both contain identical logical codes. Compression modes alternate order on every warm-up and measured sample with the same lookup seed; global and texture paths share each mapping. Forward/reverse processes also reverse size, pattern and path order. This replaces an earlier diagnostic block-ordered corpus whose nonzero ratios inverted with laptop clock state; only the per-sample-paired corpus is used for claims.

The primary matrix covers 4, 28, 32, 36, 38, 40, 48, 64, 96 and 128 MiB, 184/1,104 warps, all three patterns and both paths. The zero-only span supplement covers 160, 192, 224, 240, 248, 252, 254, 256, 260, 264, 288, 320, 384 and 512 MiB at 1,104 warps. Each corpus has four independent forward/reverse processes, two warm-up sets and ten measured sets.

## Native instruction audit

- exact timed source: `artifacts/ugts_cuda_vmm_compression_lut_bench_C8B68006.cu` (the working source has since gained additional semantic controls);
- source SHA-256: `C8B68006404278DE9C01F394E9A4A5571335D16A8858FA9403512CC04BEC06C6`;
- executable SHA-256: `9ECD2C4785B3836A2FC1B2342BC4F8268E2E67B6FF50F87488C3125EB8C0E057`;
- aggregation tool SHA-256: `8F9EFE2A235E0DC24BE7509C0778D541AB1E48F4E43213C8EA4E8C17FFED9C83`;
- native target: `sm_120`, CUDA 12.8;
- global timed kernel: 22 registers, zero stack/local memory/spills;
- texture timed kernel: 19 registers, zero stack/local memory/spills;
- occupancy: 24 blocks/SM for both paths;
- active packed decode: one unconditional and one predicated straddle load through `LDG.E.STRONG.GPU` or `TLD.LZ`;
- timing: two `SR_CLOCKLO` reads around each timed loop.

The texture compiler specializes the runtime pattern branches into separate loop bodies. The zero branch retains real texture loads; it is not a dead-load benchmark.

## Allocation property verification

Every raw row records requested and effective compression. All non-compressible rows return effective enum 0; every generic-compressible row returns effective enum 1. Both modes use the same 2 MiB VMM allocation granularity and complete read/write mappings.

## Information-bearing packed6 result

At full occupancy, the median generic/non-compressible hot-rate ratio across the ten primary sizes is:

| Pattern | Global | Texture |
|---|---:|---:|
| Periodic packed6 | 0.99999x | 1.00001x |
| Entropy-dense packed6 | 1.00003x | 1.00005x |

The compression hint does not move the 36-40 MiB capacity boundary for either information-bearing pattern. At 38 MiB there is a small localized 0.6-1.2% paired improvement, but by 40 MiB the modes are effectively tied and both follow the same post-L2 curve. A 48-byte repeating packed pattern is therefore insufficient to assume useful hardware compression on this device; the engine's supported pattern class is not equivalent to arbitrary dictionary or run-length compression.

## Zero-entropy upper control

The global path supplies the clean monotonic capacity curve:

| Allocation / packed6 capacity | Non-compressible | Generic compressible | Paired generic/none |
|---:|---:|---:|---:|
| 36 MiB / 50,331,648 codes | 38.498 Glookup/s | 38.645 Glookup/s | 1.004x |
| 38 MiB / 53,127,840 codes | 32.764 Glookup/s | 38.659 Glookup/s | 1.204x |
| 40 MiB / 55,924,048 codes | 20.092 Glookup/s | 38.591 Glookup/s | 1.975x |
| 48 MiB / 67,108,864 codes | 8.945 Glookup/s | 38.653 Glookup/s | 4.313x |
| 64 MiB / 89,478,480 codes | 8.691 Glookup/s | 38.525 Glookup/s | 4.455x |
| 128 MiB / 178,956,960 codes | 7.006 Glookup/s | 38.507 Glookup/s | 5.522x |
| 160 MiB / 223,696,208 codes | 7.260 Glookup/s | 38.577 Glookup/s | 5.323x |
| 192 MiB / 268,435,456 codes | 7.125 Glookup/s | 38.593 Glookup/s | 5.415x |
| 224 MiB / 313,174,688 codes | 7.039 Glookup/s | 38.583 Glookup/s | 5.483x |
| 240 MiB / 335,544,320 codes | 7.005 Glookup/s | 38.650 Glookup/s | 5.517x |
| 248 MiB | 6.990 Glookup/s | 28.823 Glookup/s | 4.124x |
| 256 MiB | 6.976 Glookup/s | 28.196 Glookup/s | 4.043x |
| 288 MiB | 6.929 Glookup/s | 23.968 Glookup/s | 3.459x |
| 320 MiB | 6.887 Glookup/s | 4.748 Glookup/s | 0.689x |
| 384 MiB | 6.836 Glookup/s | 2.427 Glookup/s | 0.355x |
| 512 MiB | 6.770 Glookup/s | 1.386 Glookup/s | 0.205x |

Generic compression preserves the pre-cliff global rate through a 240 MiB zero table: a **6.667x throughput-equivalent allocation-capacity lower bound** relative to the 36 MiB L2 and exactly 335,544,320 packed codes. This is not a measured 6.667x physical compression ratio. The actual compressed bytes and metadata are unavailable.

At 248 MiB the generic path loses 25.4% from its 240 MiB rate, matching the separately isolated virtual-address reach transition. At 320 MiB the generic allocation becomes slower than the non-compressible control. Compression can therefore expand effective physical data capacity dramatically for the supported zero/sparse pattern, but cannot bypass—and can interact badly with—the independent virtual-address limit.

## Texture qualification and erratum

Information-bearing periodic/entropy texture results match their non-compressible controls, so explicit generic compression does not improve a normal packed LUT. The all-zero texture path originally appeared exceptionally fast and non-monotonic with allocation size. A later 174-210 MiB alignment sweep reproduced an exact three-MiB rhythm, and removing one 12-byte packed group collapsed the high regime.

That curve is now **semantically disqualified**, not merely qualified. An all-one packed control validates through global loads, while every all-one texture row has zero valid timed payloads; a mismatch-total probe records 35,893,872 wrong decoded codes out of 36,175,872 at 4 MiB and 22,609,920 out of 36,175,872 at 192 MiB. Periodic and entropy texture controls remain mismatch-free. The all-zero checker can mask this failure because zero is its expected return. Therefore no all-zero texture rate is used as capacity, compression or decoded-throughput evidence. The full erratum is in `../cuda_vmm_compression_zero_texture_alignment_isolated/PROTOCOL.md`.

## Validation

The primary and zero-span corpora contain **1,184 raw rows**, **830,914,560 payloads accepted by the original checker**, and **283,618,836,480 timed GPU lookups**. Periodic/entropy rows and the global zero curve retain semantic support; zero-valued texture rows do not, because their checker cannot distinguish a correct zero from the later observed texture semantic failure. Compute Sanitizer reports zero memory-access errors through 512 MiB, but memory safety does not repair a wrong returned value. The separate allocation probe verifies complete endpoint readback for effective modes 0 and 1.

No NVIDIA cache/DRAM performance counters are available under the current system permission. The experiment therefore reports logical decoded lookups, allocation-property state and throughput-equivalent bounds—not hardware compressed-byte ratios, cache hit rates, DRAM bytes, compressor format or metadata overhead.

## Reproduction

```powershell
& gpu/scripts/build_windows_cuda_vmm_compression_lut.ps1
& gpu/scripts/run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory benchmarks/cuda_vmm_compression_lut_isolated/f1 `
  -SizeMiB '4,28,32,36,38,40,48,64,96,128' -Warps '184,1104' `
  -Patterns 'zero6,periodic6,entropy6' -EvictionMiB 256 `
  -Warmup 2 -Samples 10 -Order 0
& gpu/scripts/run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory benchmarks/cuda_vmm_compression_zero_span_isolated/f1 `
  -SizeMiB '160,192,224,240,248,252,254,256,260,264,288,320,384,512' `
  -Warps '1104' -Patterns 'zero6' -EvictionMiB 256 `
  -Warmup 2 -Samples 10 -Order 0
```

Repeat each command with `r1/f2/r2` output directories and balanced orders `1/0/1`. Aggregate each four-process corpus with `gpu/tools/aggregate_cuda_vmm_compression_lut.py`. Raw and aggregate JSON/CSV artifacts are in `cuda_vmm_compression_lut_isolated/` and `cuda_vmm_compression_zero_span_isolated/`.
