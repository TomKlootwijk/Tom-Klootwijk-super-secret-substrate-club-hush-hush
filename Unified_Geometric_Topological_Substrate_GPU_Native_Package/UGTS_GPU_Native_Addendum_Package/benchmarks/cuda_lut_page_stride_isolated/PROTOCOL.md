# Native CUDA sparse-LUT page-stride protocol

## Question

The preceding sparse-address matrix separated requested data from containing 128-byte-line-address pressure and found a residual address-span penalty. This control expands the same independently scheduled packed6 lookup from 128-byte spacing through exactly 4 KiB while holding useful code count, requested word count, containing test-line count, decoder, launch shape and instruction path fixed at each target.

The purpose is to bound page-spaced address reach and distinguish it from ordinary L2 data capacity. It does **not** assume that 4 KiB is the GPU translation page size or that a measured knee is a TLB entry count.

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

Native SASS contains two `CS2R SR_CLOCKLO` reads and exactly one static `LDG.E.STRONG.GPU` in the global timed loop or one `TLD.LZ` in texture. Timed kernels use 22 registers; matched controls use 18 and contain no table load. All have zero stack, local memory and spills, and CUDA reports 24 resident one-warp blocks per SM. Compute Sanitizer reports zero errors over 480-, 512-, 992-, 1,024- and 4,096-byte spacing, including a 1 GiB allocation; sanitizer timings are excluded.

## Construction and run matrix

Every logical region contains one checked 6-bit code in its first word. Every unused word is deterministic mixed nonzero filler. Each lane independently selects regions through the same LCG for 512 iterations, so addresses do not depend on prior loads. Global and texture paths use identical bytes and lookup sequences.

`target_mib = region_count * 32 bytes`. For every stride of at least 128 bytes at one target, useful codes, requested words and containing aligned 128-byte test lines are identical; only allocation/address span changes. At 4 KiB spacing each useful word occupies one distinct nominal 4-KiB address span, but “nominal” is address arithmetic rather than a hardware-page claim.

Four isolated processes balance ascending/descending target, stride and warp order and both native path orders. Targets 1-8 MiB, strides 128/256/512/1,024/2,048/4,096 bytes, and 184/1,104 warps produce 768 valid raw rows and 192 aggregate cases. The CPU validates 884,736 payloads and replays 301,989,888 code checks. Timed kernels execute **194,481,487,872 GPU lookups**.

## Exact 4-KiB-spacing curve

The full-occupancy result is:

| Target | Useful words | Allocation span | Nominal 4-KiB positions | Global | Texture |
|---:|---:|---:|---:|---:|---:|
| 1 MiB | 32,768 | 128 MiB | 32,768 | 42.590 G/s | 41.784 G/s |
| 2 MiB | 65,536 | 256 MiB | 65,536 | 34.315 G/s | 34.451 G/s |
| 3 MiB | 98,304 | 384 MiB | 98,304 | 21.470 G/s | 21.506 G/s |
| 4 MiB | 131,072 | 512 MiB | 131,072 | 18.424 G/s | 18.462 G/s |
| 5 MiB | 163,840 | 640 MiB | 163,840 | 16.973 G/s | 17.005 G/s |
| 6 MiB | 196,608 | 768 MiB | 196,608 | 16.107 G/s | 16.135 G/s |
| 7 MiB | 229,376 | 896 MiB | 229,376 | 15.540 G/s | 15.540 G/s |
| 8 MiB | 262,144 | 1,024 MiB | 262,144 | 15.166 G/s | 15.139 G/s |

At the 2-MiB target only 256 KiB of distinct `u32` words are logically requested and the containing-line model is 8 MiB, both comfortably below 36 MiB. Nevertheless, widening the address span from the 8 MiB required by 128-byte spacing to 256 MiB at 4-KiB spacing reduces rate by about 20%. This isolates a real address-distribution cost from L2 data volume.

## Span transition independent of an exact power-of-two stride

The skew control holds target at 4 MiB (131,072 useful words/containing test lines) and brackets the transition with near-2-KiB strides:

| Stride | Allocation span | Global | Texture |
|---:|---:|---:|---:|
| 2,016 B | 252 MiB | 42.178 G/s | 42.194 G/s |
| 2,048 B | 256 MiB | 34.318 G/s | 34.454 G/s |
| 2,080 B | 260 MiB | 32.546 G/s | 32.778 G/s |

The full-rate-to-slow transition is therefore bounded between 252 and 256 MiB for this independent sparse workload. Because 2,080-byte spacing remains slow and both instruction paths agree, the general transition is not solely a power-of-two texture-index conflict.

## Interpretation and bounds

- A separate address-distribution resource becomes limiting while useful words and containing test-line count remain below their L2 knees.
- The broad post-transition curve is governed primarily by total span: global and texture converge from roughly 256 MiB outward.
- Timing alone cannot divide the effect among translation caches, page walks, cache/set mapping, memory partitions or replacement.
- A CUDA driver VMM probe reports a 2 MiB minimum/recommended device-local allocation granularity. That property is not the page size used by these `cudaMalloc` allocations and is not converted into a TLB-entry claim.
- Exact L2 hits, physical sectors, tag occupancy, page translations and DRAM traffic remain unavailable because performance counters are permission-blocked.

Raw results are under `f1/`, `r1/`, `f2/`, and `r2/`; machine-readable aggregate and CSV tables are under `aggregate/`. The fine stride-alias control is documented in `benchmarks/cuda_lut_stride_skew_isolated/PROTOCOL.md`.
