# Exact native packed6 code-0/63 block-mixture map

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU, CUDA compute capability 12.0  
Driver: 591.59  
Reported L2: 37,748,736 bytes (36 MiB)  
CUDA compiler: 12.8.61  
Compute Sanitizer: 2025.1.0.0, zero errors on retained global sentinels

## Question

Does the generic-compression capacity benefit survive when a packed6 table carries both of the proven highly compressible values, code 0 and code 63, instead of one uniform value? How does the spatial run length change the result?

This is a stricter information-bearing control than the uniform-zero or uniform-all-one cases. It still is not arbitrary application data: every sequence is deterministic and approximately balanced between two values.

## Exact layout

Sixteen identical code-0 values pack into three `0x00000000` words. Sixteen identical code-63 values pack into three `0xFFFFFFFF` words. One packed group therefore contains 16 logical codes in 12 physical bytes.

The alternating controls switch value after a declared number of complete packed groups:

| Pattern | Codes per run | Physical bytes per run |
|---|---:|---:|
| `g1` | 16 | 12 |
| `g2` | 32 | 24 |
| `g4` | 64 | 48 |
| `g8` | 128 | 96 |
| `g16` | 256 | 192 |
| `g32` | 512 | 384 |
| `g64` | 1,024 | 768 |
| `g128` | 2,048 | 1,536 |
| `g256` | 4,096 | 3,072 |
| `g512` | 8,192 | 6,144 |
| `g1024` | 16,384 | 12,288 |

`blockmix6_0_63_hash` instead chooses code 0 or 63 pseudorandomly for each 16-code/12-byte group. The timed kernel independently derives the expected logical code for every lookup, so a wrong read cannot pass merely because both symbols are legal.

## Native protocol

The frozen `sm_120` executable uses paired non-compressible and driver-confirmed generic-compressible CUDA VMM allocations, raw `LDG.E.STRONG.GPU`, 1,104 one-warp blocks, a 256 MiB eviction allocation, two warmup sets and ten measured sets. Compression modes alternate within each sample. Four isolated processes use order `0,1,0,1`, reversing size and pattern order in the reverse processes.

The coarse screen covers all twelve patterns at 36, 40, 48, 64, 80, 96, 112, 128, 160, 192, 224, 240 and 248 MiB. The refinement covers hash and `g1/g2/g4/g8/g16` every 2 MiB from 64 through 96 MiB. Endpoint normalization stays within the appropriate four-process corpus to avoid mixing independent GPU clock states.

| Evidence | Screen | Refinement | Combined |
|---|---:|---:|---:|
| Isolated processes | 4 | 4 | 8 |
| Raw/valid rows | 1,248 / 1,248 | 816 / 816 | 2,064 / 2,064 |
| Validated payloads | 1,322,680,320 | 864,829,440 | 2,187,509,760 |
| Timed native lookups | 451,474,882,560 | 295,195,115,520 | 746,669,998,080 |
| Invalid rows / decoded mismatches | 0 / 0 | 0 / 0 | 0 / 0 |

## Capacity result

`Full rate` means at least 99% of the best balanced-median generic-compressible hot rate for that pattern in its endpoint corpus.

| Spatial organization | 99%-rate endpoint | First below | Allocation / nominal L2 | Logical codes at endpoint |
|---|---:|---:|---:|---:|
| Hashed choice per 12-byte group | 72 MiB | 74 MiB | 2.000x | 100,663,296 |
| Alternating 12-96-byte runs (`g1-g8`) | 72 MiB | 74 MiB | 2.000x | 100,663,296 |
| Alternating 192-byte runs (`g16`) | 88 MiB | 90 MiB | 2.444x | 123,032,912 |
| Alternating 384-12,288-byte runs (`g32-g1024`) | 240 MiB | 248 MiB | 6.667x | 335,544,320 |

At 74 MiB, the short-run controls retain 74.91-86.89% of best and the hashed control retains 92.91%. At 90 MiB, the 192-byte run retains 96.87%. Every tested 384-byte-or-longer run remains near 38.5 Glookup/s through 240 MiB and falls to 74.72-74.76% at 248 MiB, matching the separately established VMM address-reach boundary.

The first tested run span that remains full through 240 MiB is therefore 384 bytes, or 32 packed groups/512 logical codes. This does **not** establish an undocumented 384-byte compressor block. Intermediate 193-383-byte spans were not measured, and workload-level endpoints do not expose the internal compression format.

## Native-code evidence and exclusions

The retained global timed kernel compiles with 25 registers, zero stack/local/shared bytes, 24 one-warp blocks per SM, an unconditional plus predicated straddle `LDG.E.STRONG.GPU`, and `SR_CLOCKLO` reads around the 512-step loop. Compute Sanitizer reports zero errors for nonzero `g1` and hashed sentinels; instrumented rates are excluded.

No texture result enters this corpus. The earlier parameterized uniform texture branch fails nonzero semantic sentinels and compiles its timed `TLD.LZ` targets to `RZ`, so extending that branch to block mixtures would not produce admissible evidence.

## Interpretation

- The capacity benefit is not limited to a table containing only one logical value.
- It survives a roughly balanced 0/63 population even when the choice changes pseudorandomly every 12-byte group, but only to 72 MiB under this access pattern.
- Longer same-value regions materially increase retained capacity; among tested powers of two there is a large change between 192-byte and 384-byte runs.
- The 240 MiB result is address-limited. It does not prove that the compressed working set would stop there.
- These are throughput-equivalent allocation bounds, not achieved physical compression ratios, cache-hit rates, sectors, DRAM bytes or portable guarantees.
- Arbitrary binary, chemical, biological or database payloads are not represented by this synthetic two-symbol control and require their own encoded-distribution measurements.

## Reproduction and validation

The exact source, executable, aggregator and summarizer are frozen under `artifacts/`, with hashes and all eight raw-run hashes in `provenance.json`. Regenerate the aggregate files with the frozen aggregator, regenerate `blockmix063_map.json` with:

```powershell
python benchmarks\cuda_vmm_blockmix063_exact\artifacts\summarize.py `
  --screen benchmarks\cuda_vmm_blockmix063_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --refinement benchmarks\cuda_vmm_blockmix063_refinement_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --output benchmarks\cuda_vmm_blockmix063_exact\blockmix063_map.json
```

Validate frozen hashes, every raw row, mapping properties, counts and all derived endpoints with:

```powershell
python gpu\tools\validate_cuda_vmm_blockmix063.py
```
