# Exact-binary sparse packed6 VMM-compression protocol

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU, CUDA compute capability 12.0  
Driver: 591.59  
CUDA compiler: 12.8.61  
Compute Sanitizer: 2025.1.0.0  
Reported L2: 37,748,736 bytes (36 MiB)  
Multiprocessors: 46  
Measured occupancy: 24 one-warp blocks/SM, 1,104 total warps

## Question

Does an explicitly requested CUDA generic-compressible device-local VMM allocation give a packed 6-bit log-code LUT more throughput-equivalent cache capacity when most codes are zero but a controlled number of codes are nonzero?

This is a workload question.  The experiment does not expose compressed physical bytes, compressor blocks, L2 hit rate, cache-sector traffic, or a physical compression ratio.

## Exact executable

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `benchmarks/cuda_vmm_sparse_exact/artifacts/bench.cu` | 43,304 | `93FFA4524F519E05E740F0034C6EB139881C3781627A38C7CE9539CEA0EFCAEF` |
| `benchmarks/cuda_vmm_sparse_exact/artifacts/bench.exe` | 687,104 | `E4F685BB73046A4B4D4F79D634CDB211698FF9E2A2C13AA74CDAEED6884AA194` |
| `benchmarks/cuda_vmm_sparse_exact/artifacts/aggregate.py` | 10,961 | `8858D4A8CDD0D90407E9DBD4D9DA5B1572CCA5B0202056A7DB2FF48F91A73D54` |
| `benchmarks/cuda_vmm_sparse_exact/artifacts/summarize.py` | 8,644 | `5EA58CCA4CEF4829E2693C29A27A993AB1AE6E7B2E1C33F8CAFBE67ED9289DA2` |

The saved source and executable freeze the exact pair used by every run below.  At capture time the saved executable was byte-identical to `gpu/build-windows/ugts_cuda_vmm_compression_lut_bench.exe`.  Native disassembly and resource evidence for this executable records `LDG.E.STRONG.GPU` for the global path, `TLD.LZ` for the texture path, two `SR_CLOCKLO` reads around the timed dependent loop, 22/19 registers for global/texture, zero stack/local/spill bytes, and the same 24-blocks/SM occupancy ceiling.

## Layout and patterns

Sixteen logical 6-bit codes occupy three adjacent `u32` words, exactly 0.75 byte/code.  Sparse pattern `sparse1_K` stores code 1 when `index mod K == 0` and code 0 elsewhere.  All tested sparse intervals are multiples of 16, so the exception is the first code in its 12-byte packed group.

`const1` stores code 1 everywhere.  `binary1` stores a deterministic mixed 0/1 stream.  They are controls showing that a small alphabet or a repeated logical value alone does not guarantee a useful hardware-compression result for its packed physical words.

Each timed endpoint is checked against the host reconstruction.  Every case creates paired non-compressible and generic-compressible VMM handles, queries the effective allocation property, initializes both on the GPU, alternates compression-mode order on each sample, and shares the same random lookup sequence.  Forward/reverse process order is `0,1,0,1`.

## Exact-binary corpora

| Corpus | Runs | Raw rows | Patterns | Paths | Validated payloads | Timed GPU lookups | Invalid/mismatched rows |
|---|---:|---:|---:|---|---:|---:|---:|
| Main sparse content | 4 | 1,224 | 9 | global + texture | 1,297,244,160 | 442,792,673,280 | 0 |
| Interpolation | 4 | 312 | 3 | global | 330,670,080 | 112,868,720,640 | 0 |
| Format-threshold refinement | 4 | 336 | 7 | global | 356,106,240 | 121,550,929,920 | 0 |
| **Combined exact binary** | **12** | **1,872** | **16 sparse intervals plus controls** | mixed as declared | **1,984,020,480** | **677,212,323,840** | **0** |

The main corpus alone is the earlier reported 1,224-row / 1.297-billion-payload / 442.793-billion-lookup result.  The combined row count is larger because the exact-binary interpolation and format refinements add measurements and intentionally repeat some cases.  The summary merges duplicate pattern/size cases by the median of their independently aggregated medians; it does not count duplicates as new thresholds.

## Full-rate definition

For each sparse pattern, `full rate` is the highest tested allocation whose median generic-compressible global rate retains at least 99% of that pattern's best measured rate.  It is a throughput-equivalent allocation boundary, not a physical-byte compression ratio.

| Exception interval | Nonzero codes | Packed exception spacing | Last full-rate allocation | Nominal-L2 multiple |
|---:|---:|---:|---:|---:|
| 64 | 1.562500% | 48 bytes | 64 MiB | 1.778x |
| 128 | 0.781250% | 96 bytes | 64 MiB | 1.778x |
| 256 | 0.390625% | 192 bytes | 64 MiB | 1.778x |
| 512 | 0.195313% | 384 bytes | 128 MiB | 3.556x |
| 544 | 0.183824% | 408 bytes | 160 MiB | 4.444x |
| 576 | 0.173611% | 432 bytes | 192 MiB | 5.333x |
| 608 | 0.164474% | 456 bytes | 208 MiB | 5.778x |
| 640 | 0.156250% | 480 bytes | 208 MiB | 5.778x |
| 672 | 0.148810% | 504 bytes | 224 MiB | 6.222x |
| 704 | 0.142045% | 528 bytes | 224 MiB | 6.222x |
| 736 | 0.135870% | 552 bytes | 240 MiB | 6.667x tested bound |
| 768 | 0.130208% | 576 bytes | 240 MiB | 6.667x tested bound |
| 896 | 0.111607% | 672 bytes | 240 MiB | 6.667x tested bound |
| 1,024 | 0.097656% | 768 bytes | 240 MiB | 6.667x tested bound |
| 2,048 | 0.048828% | 1,536 bytes | 240 MiB | 6.667x tested bound |
| 4,096 | 0.024414% | 3,072 bytes | 240 MiB | 6.667x tested bound |

The non-power-of-two 544-704 refinement supplies six observed cliffs below the separate 240-248 MiB address-reach boundary.  Their last full-rate allocations contain 411,207-478,298 nonzero exceptions, median 460,208.5.  That band is descriptive for this exact packed layout.  It is not a universal exception budget or a reverse-engineered compressor capacity.

Patterns at interval 736 and above remain full rate at 240 MiB but fall at 248 MiB.  The independently proven VMM-alias experiment shows that this 240-248 MiB loss survives with only 2 MiB of physical backing, so those rows are address-reach limited; they do not locate the sparse compression boundary beyond 240 MiB.

## Interpretation

- The driver grants the requested generic-compressible property and sparse zero-dominant packed6 content can gain substantial throughput-equivalent allocation capacity.
- The usable boundary is sharply content- and layout-dependent.  `const1`, deterministic `binary1`, periodic6, and entropy6 do not gain useful capacity merely because an allocation is marked compressible.
- The exact software packing gain remains 2.667x on every target.  The additional sparse hardware-compression behavior must be remeasured on the real production distribution and GPU.
- Capacity planning must keep encoded allocation, nonzero-exception distribution, neighborhood layout, and virtual-address reach as separate variables.
- No row establishes compressed byte count, compressor format, cache hit rate, DRAM traffic, or a portable result for another GPU.

## Machine-readable evidence

- Main aggregate: `benchmarks/cuda_vmm_compression_sparse_content_isolated/aggregate/cuda_vmm_compression_lut_aggregate.json`
- Exact interpolation aggregate: `benchmarks/cuda_vmm_sparse_interp_exact/aggregate/cuda_vmm_compression_lut_aggregate.json`
- Format aggregate: `benchmarks/cuda_vmm_compression_sparse_format_threshold_isolated/aggregate/cuda_vmm_compression_lut_aggregate.json`
- Threshold summary: `benchmarks/cuda_vmm_compression_sparse_summary/sparse_compression_thresholds.json`

Aggregate SHA-256 values are recorded in `provenance.json`.  The PowerShell runner now rejects a run when either expected result file is absent; this closes a Windows long-path evidence-loss case discovered during the exact-binary interpolation rerun.

Validate the frozen hashes, every raw row, aggregate totals and derived summary with:

```powershell
python gpu\tools\validate_cuda_vmm_sparse_exact.py
```
