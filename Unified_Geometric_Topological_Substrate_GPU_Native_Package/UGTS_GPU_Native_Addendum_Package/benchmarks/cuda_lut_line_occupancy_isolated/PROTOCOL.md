# Native CUDA packed-LUT line-occupancy protocol

## Question

The dense packed6 benchmark establishes the storage ceiling, while the sparse-stride dependent pointer chase establishes an opposite workload endpoint. This control asks what happens between them when a random LUT uses only part of each aligned 128-byte region. It specifically tests whether the prior 128-byte dependent-pointer result can be treated as a universal per-code residency cost, and whether crossing a 32-byte address boundary causes a discrete performance cliff.

## Device and executable

- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- CUDA target: `sm_120`, CUDA 12.8
- Reported L2: 37,748,736 bytes (36 MiB)
- SMs: 46
- Source: `gpu/src/ugts_cuda_lut_line_occupancy_bench.cu`
- Source SHA-256: `F7713E9E15A8781AC25197A750F838DF35263DFB569AE9452F8AB36989D3386E`
- Executable: `gpu/build-windows/ugts_cuda_lut_line_occupancy_bench.exe`
- Executable bytes: 637,440
- Executable SHA-256: `DCBB29C5837B860C519A02A0ACF7BAAF3E79B348449404B9CE71600588921051`

`ptxas` reports 26 registers for the timed global kernel, 22 for timed texture, and 18 for both timing controls, with no stack or spills. The CUDA occupancy query reports 24 one-warp blocks per SM for both paths, or 1,104 warps over 46 SMs. Native `cuobjdump --dump-sass` confirms one unconditional plus one predicated `LDG.E.STRONG.GPU` in global packed extraction and the corresponding `TLD.LZ` instructions in texture extraction. Each timed path has two `CS2R ..., SR_CLOCKLO` reads; controls contain the clock reads and no table load. Compute Sanitizer reports zero errors at `K = 1, 8, 170`; those smoke timings are excluded.

## Layout and lookup construction

The allocation is divided into aligned 128-byte regions. Each region stores `K` useful 6-bit codes contiguously from byte zero and fills every remaining word with deterministic mixed nonzero data. This prevents zero-filled gaps or driver compression from trivially explaining the result. `K` ranges from one useful code through the 170-code whole-block maximum; 170 codes consume 1,020 of 1,024 bits.

Every lane independently advances a 32-bit LCG, chooses a pseudorandom region, and then chooses a uniformly random useful slot within that region. The global path uses an L1-bypassing CUDA global load; the texture path binds the same `cudaMalloc` bytes as a one-dimensional linear texture object. Both paths perform identical code extraction, checksum, generator, launch, warmup, sample, eviction and output work.

The first word is always loaded. A second word is loaded under a predicate only when the 6-bit value straddles a 32-bit word. Slots 42 and 85 also straddle 32-byte address-region boundaries. Slot 128 starts exactly at byte 96, introducing the fourth 32-byte address region without straddling.

## Validation

Every returned code is checked inside the timed GPU kernel against its deterministic expected value. The CPU independently regenerates every code and checksum for the first 32 lanes of the control, cold and hot kernels for every measured sample. Final generator state, checksum, error count, lookup count and monotonic clock interval must match.

Across eight isolated processes, all 1,792 raw rows and 448 aggregate cases validate. The matrix contains 2,064,384 CPU-validated payloads, 1,376,256 CPU-replayed timed endpoints, 704,643,072 CPU-replayed code checks, and 453,790,138,368 timed GPU code lookups.

## Run matrix

Four primary processes cover `K = 1, 2, 4, 8, 16, 32, 64, 128, 170`; four supplemental processes cover the exact boundaries `K = 42, 43, 85, 86, 129`. Both groups use:

- allocations of 28, 32, 36, 37, 38, 39, 40 and 48 MiB;
- 184 and 1,104 warps;
- global and texture paths;
- three discarded warmup sets and twelve measured sets;
- two ascending and two descending table/occupancy traversals;
- two executions in each path order.

Processes run sequentially so they do not compete for the GPU.
The schema-1.1 aggregator rejects the corpus unless each occupancy set has exactly four repetitions and a 2/2 balance for path order and ascending/descending table, occupancy, and warp traversal.

## Full-occupancy result

The table reports median hot native texture throughput. The demand percentages are calculated directly from packed addresses: each is the probability that one uniformly random lookup asks for that 32-byte part of its selected 128-byte region. Percentages can sum above 100% when a code crosses a boundary. They are not hardware-counter-derived cache sectors.

| K / 128 B | Bytes/useful code | 32-byte touch probabilities | Useful codes at 36 MiB | 36 MiB | 40 MiB | 48 MiB |
|---:|---:|---|---:|---:|---:|---:|
| 1 | 128.000 | 100% | 294,912 | 43.010 G/s | 42.800 G/s | 28.104 G/s |
| 42 | 3.0476 | 100% | 12,386,304 | 43.009 G/s | 42.599 G/s | 28.093 G/s |
| 43 | 2.9767 | 100% + 2.33% | 12,681,216 | 42.491 G/s | 41.978 G/s | 26.491 G/s |
| 64 | 2.0000 | 67.19% + 34.38% | 18,874,368 | 42.590 G/s | 37.848 G/s | 18.385 G/s |
| 85 | 1.5059 | 50.59% + 50.59% | 25,067,520 | 42.677 G/s | 37.366 G/s | 17.900 G/s |
| 86 | 1.4884 | 50.00% + 51.16% + 1.16% | 25,362,432 | 42.437 G/s | 36.139 G/s | 17.583 G/s |
| 128 | 1.0000 | 33.59% + 34.38% + 33.59% | 37,748,736 | 42.591 G/s | 28.645 G/s | 14.399 G/s |
| 129 | 0.9922 | 33.33% + 34.11% + 33.33% + 0.78% | 38,043,648 | 42.588 G/s | 27.939 G/s | 14.237 G/s |
| 170 | 0.7529 | 25.29% + 25.88% + 25.29% + 24.71% | 50,135,040 | 42.592 G/s | 23.514 G/s | 12.628 G/s |

Layouts from 1 through 42 useful codes request only the first 32-byte address region and share effectively the same curve. Crossing the tested boundaries is gradual because the newly reachable region is rarely requested: 43 versus 42 is 1.46% slower at 40 MiB, 86 versus 85 is 3.28% slower, and 129 versus 128 is 2.47% slower.

As demand balances across more parts of every region, the post-L2 loss grows. Relative to each layout's 28 MiB rate, the 40 MiB texture retention is 98.55% at `K=42`, 88.43% at `K=64`, 66.92% at `K=128`, and 54.93% at `K=170`. The corresponding 48 MiB retention is 65.00%, 42.96%, 33.64%, and 29.50%.

## The correction and limits

The dependent pointer-chase result is not a fixed throughput cost for independent packed LUT codes. With one useful code per 128-byte region, a 40 MiB allocation retains 99.02% of its 28 MiB texture rate. A single-variable 128-byte-per-code throughput model is therefore contradicted here.

A simple requested-byte model is also insufficient. At `K=1`, only the first 32-byte part of each region is requested, yet the rate falls to 65.02% at a 48 MiB allocation even though the nominal requested-address span is only 12 MiB. The follow-on sparse-address matrix resolves the apparent conflict: requested data portions and containing line-address count are separately limiting, while doubling total address span at equal values of both adds a smaller penalty. Exact one-code refinement places the broad line-address transition between 352,256 and 360,448 aligned test lines. Without performance counters, these remain predictive layout terms rather than physical cache-sector, tag-array, set, partition or TLB measurements.

The correct engineering bounds are:

- exact storage follows encoding: 0.75 byte/code is the information floor for 64 states;
- the 170-code block layout achieves 0.752941 byte/code and 99.609% bit use;
- effective cache residency follows the measured probability-weighted access pattern, not storage bytes alone;
- dependence changes exposure: the 128-byte result remains valid for the sparse dependent chain that measured it;
- texture uses native `TLD.LZ` but supplies no extra L2-sized capacity tier in the matched controls.

Primary raw results are in `f1/`, `r1/`, `f2/`, and `r2/`; exact-boundary refinements are in `s1/`, `sr1/`, `s2/`, and `sr2/`. The checked schema-1.1 aggregate is `aggregate/cuda_lut_line_occupancy_aggregate.json`; flat, path-paired, and full-occupancy CSV tables are beside it.

The follow-on decomposition and one-code refinement are documented in `benchmarks/cuda_lut_sparse_address_isolated/PROTOCOL.md` and `benchmarks/cuda_lut_line_occupancy_k1_refinement/PROTOCOL.md`.
