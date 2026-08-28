# Exact native uniform packed6 compression map

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU, CUDA compute capability 12.0  
Driver: 591.59  
Reported L2: 37,748,736 bytes (36 MiB)  
CUDA compiler: 12.8.61  
Compute Sanitizer: 2025.1.0.0, zero errors on the retained global path

## Question

Which of all 64 uniform logical 6-bit values gain throughput-equivalent cache capacity when sixteen values are densely packed into three `u32` words and stored in a driver-confirmed generic-compressible CUDA VMM allocation?

The earlier controls established four points: code 0 and code 63 expand, while code 1 and the current G24 producer's code 8 do not. Calling all four merely “constant” obscures the physical packed pattern, so this experiment enumerates the complete logical alphabet.

## Exact layout result

A repeated 6-bit motif crosses a 32-bit word boundary with phase advance `32 mod 6 = 2` bits. The three words in one 96-bit group are identical only when the motif is invariant under two-bit rotation. Exactly four codes satisfy that condition:

| Code | Repeated six-bit motif | Packed word, repeated three times | Source period |
|---:|---|---|---:|
| 0 | `000000` | `0x00000000` | 1 |
| 21 | `010101` | `0x55555555` | 2 |
| 42 | `101010` | `0xAAAAAAAA` | 2 |
| 63 | `111111` | `0xFFFFFFFF` | 1 |

The other sixty codes all produce three distinct packed words. The complete word triples, bit counts and rate curves are in `uniform6_map.json`.

## Native screen

The frozen native binary accepts `uniform6_0` through `uniform6_63`. Four isolated processes use order `0,1,0,1`, 1,104 one-warp blocks, raw `LDG.E.STRONG.GPU`, paired non-compressible/generic-compressible VMM mappings, 256 MiB eviction, two warmups and ten measured sets. Every code is measured at 36, 40, 64, 128, 240 and 248 MiB.

| Evidence | Screen result |
|---|---:|
| Processes | 4 |
| Raw/valid rows | 3,072 / 3,072 |
| Paired size/code comparisons | 384 |
| Validated payloads | 3,255,828,480 |
| Timed native lookups | 1,111,322,787,840 |
| Invalid rows / decoded mismatches | 0 / 0 |

Using `full rate = at least 99% of that code's best median generic-compressible hot rate`, the screen separates exactly three classes:

| Physical packed class | Codes | Last full screen size | Result |
|---|---|---:|---|
| Uniform zero/all-one words | 0, 63 | 240 MiB | 6.667x nominal-L2 allocation bound, then address-reach loss at 248 MiB |
| Uniform alternating-bit words | 21, 42 | 64 MiB screen point | Capacity extends, but fails by 128 MiB |
| Three distinct packed words | Remaining 60 codes | 36 MiB | No hardware-compression capacity extension |

No code retains full rate at 248 MiB. Codes 0 and 63 fall to 74.84% and 74.83% of their 36 MiB rates there, matching the independently proven VMM address-reach boundary.

## Code 21/42 refinement

A second four-process `0,1,0,1` matrix tests codes 0, 21, 42 and 63 at 36, 40, 64, every 2 MiB from 66 through 84, then 88, 96, 112 and 128 MiB.

| Evidence | Refinement result |
|---|---:|
| Raw/valid rows | 544 / 544 |
| Paired comparisons | 68 |
| Validated payloads | 576,552,960 |
| Timed native lookups | 196,796,743,680 |
| Invalid rows / decoded mismatches | 0 / 0 |

The balanced-median 99%-of-best endpoint is **70 MiB**, or 1.944x nominal L2, for both code 21 and code 42. At 72 MiB, code 21 retains 91.38% and code 42 retains 98.63%; at 74 MiB they retain 87.52% and 84.94%. Forward processes stay closer to full rate at 72 MiB while reverse processes slow, so 70 MiB is a workload-level balanced endpoint rather than a counter-derived physical compression ratio. The defensible transition lies between 70 and 72 MiB under the declared 99% rule.

Combined, the two corpora contain **3,616 valid rows, 3,832,381,440 checked payloads and 1,308,119,531,520 timed native GPU lookups**.

## Native-code evidence

The retained global timed kernel compiles to native `sm_120` with 23 registers, zero stack/local/shared bytes, an unconditional plus predicated straddle `LDG.E.STRONG.GPU`, and `SR_CLOCKLO` reads around the 512-step loop. The occupancy query remains 24 one-warp blocks per SM. Compute Sanitizer reports zero errors for uniform codes 0, 1, 8 and 63 on this path.

The parameterized uniform texture branch is explicitly rejected. In the saved sentinel run, all 24 nonzero texture rows for codes 1, 8 and 63 are invalid, totaling 424,112,712 decoded mismatches, while eight zero-code texture rows falsely validate. SASS directs the timed constant-branch `TLD.LZ` results to `RZ`, consistent with the already documented zero-texture false positive. Those texture rows are stored under `benchmarks/cuda_vmm_uniform6_texture_rejection/` and contribute no throughput or capacity evidence.

## Interpretation

- Logical constancy is not a sufficient compression model.
- For this packed layout, extending beyond nominal L2 correlates exactly with producing identical 32-bit words: codes 0, 21, 42 and 63, and no others.
- The word value still matters. Zero/all-one words remain full through 240 MiB, while `0x55555555`/`0xAAAAAAAA` reach only the balanced 70 MiB endpoint.
- The correlation does not reveal an NVIDIA compressor format or physical compressed-byte ratio. It is an exhaustive input/output map for one layout, access path and GPU.
- Software packing remains exactly 2.667x denser than 16-bit slots for every code. Hardware compression is an additional conditional effect, never a portable multiplier.

## Reproduction and validation

The exact source, executable, aggregator and summarizer are frozen under `artifacts/`, with hashes in `provenance.json`. Regenerate the map with:

```powershell
python benchmarks\cuda_vmm_uniform6_exact\artifacts\summarize.py `
  --screen benchmarks\cuda_vmm_uniform6_code_sweep_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --refinement benchmarks\cuda_vmm_uniform6_midpattern_refinement_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --output benchmarks\cuda_vmm_uniform6_exact\uniform6_map.json
```

Validate the frozen hashes, all eight raw corpora, row coverage, payload/lookup totals, packing mathematics and derived classes with:

```powershell
python gpu\tools\validate_cuda_vmm_uniform6.py
```
