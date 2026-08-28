# Native CUDA packed-LUT sparse-address protocol

## Question

The earlier controls established two facts that were individually valid but incomplete: dense packed6 storage approaches 0.75 byte/code, while a strictly dependent sparse pointer chase behaved as though one active pointer occupied a 128-byte residency unit. The packed-LUT line-occupancy sweep then showed that one independently selected code per 128-byte region remained fast beyond 36 MiB of allocation. This experiment separates three quantities that those endpoints conflate:

1. the number of distinct requested 32-byte address regions;
2. the number of aligned 128-byte lines containing those regions;
3. the total allocation/address span, including unused mixed filler.

It does not assume that 32 or 128 bytes is a documented hardware unit. Those sizes are controlled address layouts used to test which model predicts measured throughput.

## Device and executable

- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- CUDA target: `sm_120`, CUDA 12.8
- Reported L2: 37,748,736 bytes (36 MiB)
- SMs: 46
- Source: `gpu/src/ugts_cuda_lut_sparse_address_bench.cu`
- Source SHA-256: `1F6D50F63F55934F96CBC2245ABD0FB52BF58453730E0DCF118491B7293C2BB9`
- Executable: `gpu/build-windows/ugts_cuda_lut_sparse_address_bench.exe`
- Executable bytes: 590,848
- Executable SHA-256: `07712EC7EE16831AE4F29B389C371A4FCCB784682D43AD10F432620E6040CC49`

`ptxas` reports 22 registers for both timed paths and 18 for both controls, with zero stack and spills. CUDA reports 24 resident one-warp blocks per SM for both paths. Native SASS contains two clock-register reads and exactly one static `LDG.E.STRONG.GPU` in the global timed loop or one `TLD.LZ` in texture; controls contain the clock reads and no table load. Compute Sanitizer reports zero errors over 32-, 128- and 256-byte spacing; instrumented timings are excluded.

## Construction

Each logical region contains one useful 6-bit code in the low bits of its first `u32`. Regions are spaced by 32, 64, 128 or 256 bytes. Every unused word is filled with deterministic mixed nonzero data before the code is inserted, so gaps remain real device allocation and are not zero-filled.

Every lane independently advances an LCG for 512 iterations, maps each state uniformly to a region with multiply-high reduction, loads the code word, checks the decoded code inside the timed kernel, and updates a checksum. There is no load-to-load address dependency. Global and texture variants use the same allocation, indices, decoder, launch shape, warmups, samples, eviction work and output contract.

`target_mib` is defined as `region_count * 32 bytes`. It is a convenient count of distinct 32-byte address regions, not a claim about physical sectors. Actual allocation is `region_count * stride`. For aligned regions, the number of distinct hypothetical 128-byte lines is:

| Stride | Requested regions per aligned 128 B | Allocation relative to target | Distinct 128 B lines |
|---:|---:|---:|---:|
| 32 B | 4 | 1x | regions / 4 |
| 64 B | 2 | 2x | regions / 2 |
| 128 B | 1 | 4x | regions |
| 256 B | 1, with one skipped line | 8x | regions |

The 128/256 pair has the same useful words, requested 32-byte-region count and hypothetical 128-byte-line count. Only allocation/address span doubles, bounding the remaining address-translation, set-mapping or related cost.

## Run matrix and validation

Four primary isolated processes cover targets 4, 8-16, 18, 20, 24, 28, 32, 36, 40 and 48 MiB. Four supplemental processes add 19 and 37-39 MiB. Each group contains two ascending and two descending target/stride/warp traversals and two executions in each global/texture path order. Both 184 and 1,104 warps are measured with three discarded warmup sets and twelve measured sets.

All **1,408 raw rows** and 352 four-run aggregate cases validate. The CPU validates 1,622,016 payloads and replays 553,648,128 individual code checks. The timed GPU kernels execute **356,549,394,432 code lookups**. The aggregator rejects incomplete replication or a traversal/path imbalance.

## Data-capacity boundary with dense 32-byte use

At 32-byte spacing, every 32-byte part of the allocation contains a useful code and is selected. Full-occupancy texture throughput follows the nominal 36 MiB L2 boundary:

| Target/allocation | Unique aligned 128 B lines | Texture rate | Retention versus 4 MiB |
|---:|---:|---:|---:|
| 36 MiB | 294,912 | 43.004 Glookup/s | 99.27% |
| 37 MiB | 303,104 | 42.591 Glookup/s | 98.32% |
| 38 MiB | 311,296 | 38.254 Glookup/s | 88.31% |
| 39 MiB | 319,488 | 28.732 Glookup/s | 66.33% |
| 40 MiB | 327,680 | 23.343 Glookup/s | 53.89% |

This reproduces the earlier 36-40 MiB boundary while using one independently selected packed6 code per region. The transition begins between 37 and 38 MiB and is broad rather than a binary hit/miss step.

## Same allocation and line count, different useful portions

The decisive control fixes physical allocation at 40 MiB and fixes the number of aligned 128-byte lines at 327,680. Only the number of independently useful 32-byte portions per line changes:

| Stride | Useful 32-byte portions per line | Requested 32-byte span | Texture rate |
|---:|---:|---:|---:|
| 32 B | 4 | 40 MiB | 23.343 Glookup/s |
| 64 B | 2 | 20 MiB | 38.505 Glookup/s |
| 128 B | 1 | 10 MiB | 42.802 Glookup/s |

Neither allocation size nor line count alone predicts the result. Reducing useful/requested portions per line preserves throughput even though the full 40 MiB allocation remains present and mixed. This is strong timing evidence for independently resident subregions within a larger line/tag grouping on this workload.

## Same requested 32-byte span, different line count

The converse control fixes 12 MiB of distinct requested 32-byte regions and varies how many aligned 128-byte lines contain them:

| Stride | Distinct hypothetical 128 B lines | Allocation | Texture rate |
|---:|---:|---:|---:|
| 32 B | 98,304 | 12 MiB | 43.214 Glookup/s |
| 64 B | 196,608 | 24 MiB | 43.207 Glookup/s |
| 128 B | 393,216 | 48 MiB | 28.119 Glookup/s |
| 256 B | 393,216 | 96 MiB | 24.783 Glookup/s |

A pure requested-byte or 32-byte-sector-capacity model predicts equal rates and is rejected. The number and distribution of containing line addresses matters materially even though the useful/requested byte count is held constant.

## One requested portion per 128-byte line

At 128-byte spacing, one 32-byte part of each aligned line can be requested. The native texture curve is:

| Requested 32-byte span | Allocation / line-equivalent span | Line addresses | Texture rate |
|---:|---:|---:|---:|
| 9 MiB | 36 MiB | 294,912 | 43.008 Glookup/s |
| 10 MiB | 40 MiB | 327,680 | 42.802 Glookup/s |
| 11 MiB | 44 MiB | 360,448 | 38.337 Glookup/s |
| 12 MiB | 48 MiB | 393,216 | 28.119 Glookup/s |

The separate one-code refinement tightens the boundary in one-MiB allocation increments. Its texture rate is 42.997 Glookup/s at 40 MiB, 42.794 at 41, 42.401 at 42, 41.785 at 43, and 38.330 at 44. Thus **352,256 line addresses / 10.75 MiB of requested 32-byte regions retain 97.18% of the 40 MiB rate, while 360,448 / 11 MiB retain 89.15%**. This bounds an effective line-address/tag/set transition between those measured counts; it does not identify a privileged tag-array capacity.

## Extra address-span effect

Moving from 128- to 256-byte spacing preserves useful words, requested 32-byte span and hypothetical line count but doubles allocation and page/address span. The texture 256/128 rate ratios are:

| Requested span | 128 B spacing | 256 B spacing | Ratio |
|---:|---:|---:|---:|
| 9 MiB | 43.008 G/s | 42.584 G/s | 0.9901x |
| 10 MiB | 42.802 G/s | 40.446 G/s | 0.9449x |
| 11 MiB | 38.337 G/s | 30.831 G/s | 0.8042x |
| 12 MiB | 28.119 G/s | 24.783 G/s | 0.8813x |

Across all measured targets the median ratio is 0.97562x. The extra address span costs most near the line-address transition and only a few percent once both paths are fully miss/queue dominated. This bounds a real address-span effect, but timing alone cannot divide it among TLB reach, page walks, cache-set mapping, memory partitions or replacement policy.

## Engineering interpretation

The measured behavior needs at least two residency resources plus an address-span modifier:

- **resident data portions:** densely using all 32-byte portions exhausts the reported 36 MiB data capacity around 37-38 MiB;
- **containing line addresses:** using one portion per aligned 128-byte line postpones the transition until roughly 352,256-360,448 distinct line addresses even though only 10.75-11 MiB of 32-byte regions are requested;
- **address span:** doubling 128-byte spacing to 256 bytes further reduces rate near the transition without changing the first two counts.

This reconciles the earlier results. Dense packing gives exact storage compression. A dependent pointer chase can exhibit a 128-byte workload-level effective cost. Independent sparse codes can retain more line addresses than a dense 36 MiB/128 arithmetic count because only one portion per line is resident, but their tag/address footprint eventually becomes limiting. Therefore 0.75 bytes/code, 32 bytes/request and 128 bytes/dependent pointer are all valid only in their declared scopes.

Texture and global paths converge at full occupancy throughout the capacity curves. Native texture instructions do not create a second capacity tier; packing and access locality remain the effective levers.

## Bounds and artifacts

Exact L2 hit rate, physical sector traffic, tag occupancy, TLB events and DRAM bytes remain unavailable because NVIDIA performance-counter permission is blocked. The words “portion,” “line address” and “line-equivalent” describe tested layouts and predictive models, not undocumented hardware declarations. CUDA event rates are complete-kernel logical lookup rates; `clock64()` values include scheduler exposure.

Primary raw results are in `f1/`, `r1/`, `f2/`, and `r2/`; 19/37-39 MiB refinements are in `s1/`, `sr1/`, `s2/`, and `sr2/`. Machine-readable aggregates and diagnostic tables are under `aggregate/`. The separate exact one-code line boundary is under `benchmarks/cuda_lut_line_occupancy_k1_refinement/`.

The same source was extended to accept 32-byte-multiple strides through 4 KiB without changing the kernel. This original corpus was rerun with the exact updated executable above. Page-stride, intermediate-span and non-power-of-two alias controls are under `benchmarks/cuda_lut_page_stride_isolated/`, `benchmarks/cuda_lut_page_span_isolated/`, and `benchmarks/cuda_lut_stride_skew_isolated/`.
