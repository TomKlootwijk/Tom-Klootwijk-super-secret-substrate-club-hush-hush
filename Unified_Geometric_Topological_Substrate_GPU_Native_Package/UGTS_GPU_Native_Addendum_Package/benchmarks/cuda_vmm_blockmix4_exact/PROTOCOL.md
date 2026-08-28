# Exact native packed6 four-symbol block-mixture map

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU, CUDA compute capability 12.0  
Driver: 591.59  
Reported L2: 37,748,736 bytes (36 MiB)  
CUDA compiler: 12.8.61  
Compute Sanitizer: 2025.1.0.0, zero errors on retained global sentinels

## Question

How much of the generic-compression capacity benefit survives when every packed group chooses among all four uniform packed6 codes previously shown to compress individually: 0, 21, 42 and 63? How does the spatial run length change the result?

This control carries two declared symbolic bits per 16-code group and is stricter than the two-symbol code-0/63 experiment. It is still deterministic synthetic data, not general binary entropy or a chemical, biological or database encoding.

## Exact layout

Sixteen identical 6-bit codes occupy three 32-bit words, or 12 bytes:

| Logical code | Three repeated packed words |
|---:|---|
| 0 | `0x00000000` |
| 21 | `0x55555555` |
| 42 | `0xAAAAAAAA` |
| 63 | `0xFFFFFFFF` |

The cyclic controls hold each symbol for a declared number of complete groups, then advance `0 -> 21 -> 42 -> 63`:

| Pattern | Codes per symbol run | Bytes per symbol run | Four-symbol cycle |
|---|---:|---:|---:|
| `g1` | 16 | 12 | 48 bytes |
| `g2` | 32 | 24 | 96 bytes |
| `g4` | 64 | 48 | 192 bytes |
| `g8` | 128 | 96 | 384 bytes |
| `g16` | 256 | 192 | 768 bytes |
| `g32` | 512 | 384 | 1,536 bytes |
| `g64` | 1,024 | 768 | 3,072 bytes |
| `g128` | 2,048 | 1,536 | 6,144 bytes |
| `g256` | 4,096 | 3,072 | 12,288 bytes |
| `g512` | 8,192 | 6,144 | 24,576 bytes |
| `g1024` | 16,384 | 12,288 | 49,152 bytes |

`blockmix6_0_21_42_63_hash` instead derives an approximately uniform four-way choice for each 16-code/12-byte group. The timed kernel independently derives the expected code for every lookup, so a wrong read cannot pass simply because the returned value belongs to the four-symbol alphabet.

## Native protocol

The frozen `sm_120` executable uses paired non-compressible and driver-confirmed generic-compressible CUDA VMM allocations, raw `LDG.E.STRONG.GPU`, 1,104 one-warp blocks, a 256 MiB eviction allocation, two warmup sets and ten measured sets. Compression modes alternate within each sample. Every corpus contains four isolated processes with order `0,1,0,1`, reversing size and pattern order in the reverse processes.

The capacity screen covers all twelve patterns at 36, 40, 48, 64, 72, 80, 88, 96, 112, 128, 160, 192, 224, 240 and 248 MiB. The short refinement covers hash and `g1/g2/g4/g8/g16` every 2 MiB from 36 through 84 MiB. The long refinement covers `g32/g64/g128/g256/g512/g1024` every 4 MiB from 96 through 160 MiB. A dedicated `g64` extension covers 160-192 MiB plus 200, 208, 224 and 240 MiB. Endpoint normalization stays within the selected four-process refinement corpus to avoid mixing independent GPU clock states.

| Evidence | Screen | Short refine | Long refine | `g64` extension | Combined |
|---|---:|---:|---:|---:|---:|
| Isolated processes | 4 | 4 | 4 | 4 | 16 |
| Raw/valid rows | 1,440 / 1,440 | 1,200 / 1,200 | 816 / 816 | 104 / 104 | 3,560 / 3,560 |
| Validated payloads | 1,526,169,600 | 1,271,808,000 | 864,829,440 | 110,223,360 | 3,773,030,400 |
| Timed native lookups | 520,932,556,800 | 434,110,464,000 | 295,195,115,520 | 37,622,906,880 | 1,287,861,043,200 |
| Invalid rows / decoded mismatches | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |

## Capacity result

`Full rate` means at least 99% of the best balanced-median generic-compressible hot rate for that pattern inside its selected refinement corpus.

| Pattern | Symbol-run bytes | 99%-rate endpoint | First below | First-below retention | Allocation / nominal L2 | Logical codes at endpoint |
|---|---:|---:|---:|---:|---:|---:|
| `g1` | 12 | 40 MiB | 42 MiB | 98.95% | 1.111x | 55,924,048 |
| hash | n/a | 52 MiB | 54 MiB | 98.94% | 1.444x | 72,701,264 |
| `g2` | 24 | 60 MiB | 62 MiB | 98.97% | 1.667x | 83,886,080 |
| `g4` | 48 | 70 MiB | 72 MiB | 88.44% | 1.944x | 97,867,088 |
| `g8` | 96 | 72 MiB | 74 MiB | 93.33% | 2.000x | 100,663,296 |
| `g16` | 192 | 82 MiB | 84 MiB | 97.84% | 2.278x | 114,644,304 |
| `g32` | 384 | 120 MiB | 124 MiB | 95.17% | 3.333x | 167,772,160 |
| `g64` | 768 | 168 MiB | 172 MiB | 95.46% | 4.667x | 234,881,024 |
| `g128` | 1,536 | 140 MiB | 144 MiB | 98.55% | 3.889x | 195,734,176 |
| `g256` | 3,072 | 148 MiB | 152 MiB | 91.80% | 4.111x | 206,918,992 |
| `g512` | 6,144 | 120 MiB | 124 MiB | 86.46% | 3.333x | 167,772,160 |
| `g1024` | 12,288 | 124 MiB | 128 MiB | 79.43% | 3.444x | 173,364,560 |

The hashed/12-192-byte-run controls span 40-82 MiB. The tested 384-12,288-byte-run controls span 120-168 MiB. The strongest observed case is `g64`: a 168 MiB allocation, 4.667 times the nominal 36 MiB L2 allocation, at the declared 99% threshold.

The long-run results are strongly non-monotonic: increasing a run from 768 bytes to 1,536 bytes reduces the reported endpoint from 168 to 140 MiB, and still longer runs do not restore the two-symbol result. This prevents a simple “longer run means more effective cache” rule. Packed word values, cycle length, address distribution and undocumented hardware behavior can all contribute. The threshold-adjacent `g1`, hash, `g2`, `g16` and `g128` first-below points are especially sensitive to choosing 99% rather than a nearby threshold.

## Native-code evidence and exclusions

The retained global timed kernel compiles with 26 registers, zero stack/local/shared bytes, 24 one-warp blocks per SM, an unconditional plus predicated straddle `LDG.E.STRONG.GPU`, and `SR_CLOCKLO` reads around the 512-step loop. Compute Sanitizer reports zero errors for nonzero hashed and `g32` sentinels; instrumented rates are excluded.

No texture result enters this corpus. The earlier parameterized uniform texture branch fails nonzero semantic sentinels and compiles its timed `TLD.LZ` targets to `RZ`; extending that branch to four-symbol mixtures would not be admissible evidence.

## Interpretation

- A generic-compression capacity benefit survives after expanding the deterministic alphabet from two to four values.
- The benefit is materially smaller than for the two-symbol code-0/63 controls, whose 384-byte-or-longer runs stayed full through the 240 MiB address boundary.
- Spatial organization matters, but run length alone does not predict the endpoint.
- These values are throughput-equivalent allocation bounds, not achieved physical compression ratios, cache-hit rates, sectors, DRAM bytes or portable guarantees.
- No undocumented compressor block size or monotonic run-length law is claimed.
- A real chemical, biological or database encoding requires its own schema, correctness oracle, value distribution and native measurements. This synthetic four-symbol control cannot substitute for that validation.

## Reproduction and validation

The exact source, executable, aggregator and summarizer are frozen under `artifacts/`, with hashes and all sixteen raw-run hashes in `provenance.json`. Regenerate `blockmix4_map.json` with:

```powershell
python benchmarks\cuda_vmm_blockmix4_exact\artifacts\summarize.py `
  --screen benchmarks\cuda_vmm_blockmix4_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --short-refinement benchmarks\cuda_vmm_blockmix4_short_refinement_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --long-refinement benchmarks\cuda_vmm_blockmix4_long_refinement_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --g64-extension benchmarks\cuda_vmm_blockmix4_g64_extension_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --output benchmarks\cuda_vmm_blockmix4_exact\blockmix4_map.json
```

Validate the frozen hashes, every raw row, mapping properties, counts and all derived endpoints with:

```powershell
python gpu\tools\validate_cuda_vmm_blockmix4.py
```
