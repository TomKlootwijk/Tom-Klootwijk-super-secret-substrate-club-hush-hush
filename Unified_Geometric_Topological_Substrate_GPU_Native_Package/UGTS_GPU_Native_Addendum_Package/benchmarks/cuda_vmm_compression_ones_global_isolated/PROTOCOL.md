# Native CUDA all-one generic-compression control

## Purpose

This control asks whether the all-zero VMM result is unique to zero-filled memory or represents a broader constant-pattern class. Every packed 6-bit code is 63, so the three words in each 16-code group are `0xFFFFFFFF`. Unlike a zero-valued checker, this pattern cannot pass if a load silently returns zero.

Only the native global/L2 path is claimed. It executes the same dense packed6 decoder through `LDG.E.STRONG.GPU`, with explicit non-compressible and driver-confirmed generic-compressible VMM allocations coexisting and alternating on every sample. The failed texture constant control is documented separately and is not included in this valid corpus.

## Matrix and pairing

- device: NVIDIA GeForce RTX 5070 Ti Laptop GPU, CUDA compute capability 12.0;
- target: native CUDA 12.8 `sm_120`;
- sizes: 36, 38, 40, 48, 64, 128, 192, 240, 248, 256, 288 and 320 MiB;
- occupancy: 1,104 warps, the queried 24-block/SM ceiling across 46 SMs;
- content: `ones6`, sixteen code-63 values in three words;
- path: `global_cg` only;
- four isolated processes with forward/reverse size order and allocation order 0/1/0/1;
- two warm-up sets and ten measured sets per process.

The four-process aggregate contains 96 valid raw rows, 24 aggregate rows, 12 paired comparisons, 101,744,640 validated payloads and 34,728,837,120 timed GPU lookups. Both requested compression modes return their requested effective properties. A current Compute Sanitizer pass over 40, 240 and 320 MiB reports zero errors; its instrumented timings are excluded.

## Result

| Allocation | Non-compressible | Generic compressible | Paired generic/none |
|---:|---:|---:|---:|
| 36 MiB | 38.492 Glookup/s | 38.652 Glookup/s | 1.003x |
| 40 MiB | 23.492 Glookup/s | 38.603 Glookup/s | 1.641x |
| 64 MiB | 9.312 Glookup/s | 38.635 Glookup/s | 4.149x |
| 128 MiB | 7.482 Glookup/s | 38.645 Glookup/s | 5.165x |
| 192 MiB | 7.126 Glookup/s | 38.651 Glookup/s | 5.424x |
| 240 MiB | 7.004 Glookup/s | 38.611 Glookup/s | 5.512x |
| 248 MiB | 6.991 Glookup/s | 28.834 Glookup/s | 4.125x |
| 256 MiB | 6.978 Glookup/s | 28.217 Glookup/s | 4.044x |
| 288 MiB | 6.928 Glookup/s | 23.971 Glookup/s | 3.461x |
| 320 MiB | 6.891 Glookup/s | 5.961 Glookup/s | 0.865x |

The all-one packed table independently reproduces the all-zero global result: full pre-cliff rate through 240 MiB, loss at the 248 MiB virtual-reach transition and counterproductive compression by 320 MiB. This supports a constant-pattern compression class. It does not establish the achieved physical byte ratio, and a table containing one repeated value carries no useful code information.

## Provenance

- exact timed source SHA-256: `D691610868BD4CA5EB4C4BB919F3B56263F8DB034B4ACC3AA75674E6EEEC6FDC`;
- exact timed executable SHA-256: `A5AA02AB7BB402789F9D3513543ADA8E528C4853232D2C5FC0985BC2296D0759`;
- aggregation tool SHA-256: `8F9EFE2A235E0DC24BE7509C0778D541AB1E48F4E43213C8EA4E8C17FFED9C83`;
- archived exact source: `artifacts/ugts_cuda_vmm_compression_lut_bench_D6916108.cu`;
- timed global kernel: 22 registers, zero stack/local memory/spills, 24 blocks/SM, one unconditional plus one predicated straddle `LDG.E.STRONG.GPU`, and two `SR_CLOCKLO` reads.

The current source adds mismatch-total diagnostics but leaves the timed device loop unchanged. The archived source is the exact version used for this corpus.

