# Native CUDA L2 concurrency and memory-level-parallelism protocol

## Purpose

This experiment separates single-warp dependent-path cost from the throughput and scheduling effects that appear when many independent warps access a random table concurrently. It tests whether the large saturated working-set penalty seen by the Vulkan probe persists in native CUDA and whether packing a random LUT at or below the reported L2 capacity has a measurable concurrency benefit.

## Named device and native path

- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- CUDA compute capability: 12.0; native compile target: `sm_120`
- Streaming multiprocessors: 46
- Reported L2: 37,748,736 bytes (36 MiB)
- CUDA compiler: 12.8.61
- Source: `gpu/src/ugts_cuda_l2_mlp_bench.cu`
- Source SHA-256: `214162512CE96C83501882396A2169EA889C4782247A9B088B060993B3000060`
- Local executable: `gpu/build-windows/ugts_cuda_l2_mlp_bench.exe`
- Executable size: 534,016 bytes
- Executable SHA-256: `FA545B7C9D0F778BF05A4BD11827AE356B4E1B2250659132C7677866011F6694`

`ptxas` reports 16 registers, no stack, no spills and no barriers for both the 512-step chase and zero-step clock control. Native `cuobjdump --dump-sass` output contains two `CS2R ..., SR_CLOCKLO` reads and one static `LDG.E.STRONG.GPU` in the chase loop. The control contains the two clock reads and no global load. The eviction kernel contains `LDG.E.STRONG.GPU`. CUDA's occupancy query reports a ceiling of 24 resident one-warp blocks per SM for this kernel.

## Workload

Each block contains exactly one 32-lane warp. Every lane begins at a seed-dependent index and performs 512 strictly dependent pointer loads. The pointer table is a full-period affine permutation over the allocation. Inline PTX `ld.global.cg.u32` requests the L2/global path while bypassing L1.

The tested table allocations are 4, 36, 40, 64 and 128 MiB. Concurrency is 1, 2, 4, 8, 16, 32, 46, 92, 184, 368, 736 and 1,104 total warps, reaching the occupancy-query ceiling of 24 one-warp blocks per SM. Adding blocks adds independent warp-level memory parallelism; it does not add instruction-level parallelism within a dependent chain.

For every measured pair:

1. A separate 256 MiB allocation is read through `ld.global.cg.u32` to evict L2 state.
2. A zero-step kernel records `clock64()` control overhead.
3. The cold kernel executes the dependent chains.
4. The hot kernel immediately repeats the exact seeds and paths.
5. CUDA events measure complete cold/hot kernel duration.
6. Every returned endpoint and metadata record is recomputed independently on the CPU using affine-transform exponentiation.

Each process discards three warmup pairs and retains 15 measured pairs per table/concurrency case. Four processes were executed sequentially: `f1` and `f2` use ascending table and warp order; `r1` and `r2` reverse both orders. Instrumented Compute Sanitizer timings are excluded from performance aggregates.

## Validation volume

- Raw rows: 240 (60 cases × 4 isolated processes)
- Aggregate cases: 60
- Validated result payloads: 74,678,400
- Dependent loads represented by validated cold/hot endpoints: 25,490,227,200
- Compute Sanitizer memcheck control: 0 errors
- All raw validation flags: true

## High-concurrency result

At 1,104 warps (the 24-warps/SM occupancy-query ceiling), process-median requested throughput is:

| Table | L2 fraction | Hot Gload/s | Hot logical GiB/s | Hot slowdown vs 4 MiB | Cold Gload/s |
|---:|---:|---:|---:|---:|---:|
| 4 MiB | 0.111x | 43.216 | 160.99 | 1.000x | 43.083 |
| 36 MiB | 1.000x | 43.215 | 160.99 | 1.000x | 35.610 |
| 40 MiB | 1.111x | 23.683 | 88.23 | 1.825x | 21.595 |
| 64 MiB | 1.778x | 9.357 | 34.86 | 4.618x | 9.292 |
| 128 MiB | 3.556x | 7.524 | 28.03 | 5.744x | 7.513 |

The immediate-hot throughput falls 45.20% from 36 to 40 MiB. The 4 and 36 MiB hot paths are indistinguishable at full measured occupancy, while 128 MiB retains only 17.41% of their requested-load rate. Cross-process hot ranges at this ceiling are 43.211-43.218, 43.188-43.215, 23.655-23.714, 9.352-9.361 and 7.521-7.527 Gload/s in table order, demonstrating that the cliff is not an order artifact. This independently reproduces a capacity boundary in native CUDA and explains why the saturated Vulkan ratio is much larger than the one-warp hot/post-eviction cycle ratio: many warps add memory-queue and scheduling exposure.

At one warp, the hot path is about 0.208 Gload/s and 400 exposed cycles/step at every allocation size because only that warp's approximately 64 KiB of logical link visits is repeated. At higher concurrency, the repeated footprint covers enough randomly distributed cache lines for total table capacity to matter.

## Interpretation limits

`Gload/s` counts requested scalar `u32` loads. `logical GiB/s` multiplies those requests by four bytes. Neither is physical L2-sector bandwidth, DRAM bandwidth, or a transaction count; random warp loads may fetch larger cache sectors and lines. `clock64()` measures elapsed per-SM cycles and includes warp scheduling/time slicing. The cold/hot labels are controlled state protocols, not counter-derived hit/miss classifications.

The 36-to-40 MiB cliff supports keeping the packed hot LUT/state footprint below nominal L2. It does not establish a universal 36 MiB safe budget: cache associativity, other resident data, code, system activity and WDDM reduce the capacity available to an application. Direct NVIDIA cache-sector counters remain unavailable under the current performance-counter permissions.

Primary raw results are in `f1/`, `r1/`, `f2/` and `r2/`. The checked aggregate is `aggregate/cuda_l2_mlp_aggregate.json`; the flat table is `aggregate/cuda_l2_mlp_aggregate.csv`.
