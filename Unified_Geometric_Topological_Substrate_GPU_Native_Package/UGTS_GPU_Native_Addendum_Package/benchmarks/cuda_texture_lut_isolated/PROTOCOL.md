# Native CUDA texture-object versus L2/global LUT protocol

## Purpose

This experiment tests the texture-cache hypothesis directly. The exact same random pointer table is bound simultaneously as a CUDA linear texture object and as a raw global pointer. Identical dependent chains compare native texture instructions against L1-bypassing L2/global loads without changing bytes, indices, output work, concurrency or validation.

## Named device and binary

- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- CUDA compute capability / compile target: 12.0 / `sm_120`
- Streaming multiprocessors: 46
- Reported L2: 37,748,736 bytes (36 MiB)
- CUDA compiler: 12.8.61
- Source: `gpu/src/ugts_cuda_texture_lut_bench.cu`
- Source SHA-256: `D9DE5FF5D63B15786142846E1002B846AC7B187109B45EF023F2FD9038EDC574`
- Local executable: `gpu/build-windows/ugts_cuda_texture_lut_bench.exe`
- Executable size: 579,584 bytes
- Executable SHA-256: `24752CFDB55E89994BE7F532D9F7316A7F4533C39CC3C5758F7FF82A712CA9C5`

`ptxas` reports 16 registers, no stack and no spills for both 512-step chase kernels and both zero-step controls. CUDA occupancy queries report 24 resident one-warp blocks per SM for both paths. Native `cuobjdump --dump-sass` proves that the matched paths are not compiler aliases:

- Global chase: `LDG.E.STRONG.GPU`
- Texture-object chase: `TLD.LZ ..., 1D`
- Both timed chases: two `CS2R ..., SR_CLOCKLO` clock reads
- Zero-step controls: clock reads but no `LDG` or `TLD`
- Global/texture eviction kernels: `LDG.E.STRONG.GPU` / `TLD.LZ`

## Workload and controls

Each block contains one 32-lane warp. Every lane executes 512 strictly dependent pointer steps through a full-period affine permutation. Table sizes are 4, 32, 36, 38, 40, 48, 64 and 128 MiB. Concurrency is 1, 46, 184 and 1,104 total warps: approximately 0.022, 1, 4 and 24 warps per SM.

The global path uses inline `ld.global.cg.u32`, which requests the L2/global path while bypassing L1. The texture path uses integer `tex1Dfetch<uint32_t>` from a linear texture object backed by the same `cudaMalloc` allocation.

Every path receives its own cache-state sequence. Global measurements follow a 256 MiB `ld.global.cg` eviction. Texture measurements follow both that global eviction and a 256 MiB texture-object eviction, preventing a retained texture-front-end working set from being mislabeled cold. The hot kernel immediately repeats the exact cold seeds and links. CUDA events measure complete kernels and `clock64()` measures in-kernel exposed cycles.

Every returned control, cold and hot endpoint is independently recomputed on the CPU with affine-transform exponentiation. Four processes ran sequentially:

- `f1`: ascending table/warp order, global path first
- `r1`: descending table/warp order, texture path first
- `f2`: ascending table/warp order, texture path first
- `r2`: descending table/warp order, global path first

Each process discards three warmup pairs and retains 12 measured pairs per path/case. Compute Sanitizer instrumentation is excluded from timings.

## Validation volume

- Raw rows: 256
- Aggregate native-path cases: 64
- Aggregate matched pairs: 32
- Validated payloads: 98,426,880
- Dependent loads represented by validated cold/hot endpoints: 33,596,375,040
- Path-order balance: 2 global-first / 2 texture-first
- Compute Sanitizer memcheck: 0 errors
- All raw validation flags: true

## Result

At full occupancy (1,104 warps / 24 warps per SM):

| Table | L2 fraction | Global hot Gload/s | Texture hot Gload/s | Texture/global |
|---:|---:|---:|---:|---:|
| 4 MiB | 0.111x | 43.220 | 43.430 | 1.0049x |
| 32 MiB | 0.889x | 43.312 | 43.231 | 0.9982x |
| 36 MiB | 1.000x | 43.220 | 43.209 | 0.9998x |
| 38 MiB | 1.056x | 39.526 | 39.362 | 0.9959x |
| 40 MiB | 1.111x | 23.702 | 23.658 | 0.9985x |
| 48 MiB | 1.333x | 12.649 | 12.646 | 0.9998x |
| 64 MiB | 1.778x | 9.352 | 9.353 | 1.0000x |
| 128 MiB | 3.556x | 7.527 | 7.521 | 0.9992x |

The median texture/global hot ratio across sizes is 0.99949x, with a 0.99591-1.00490x range. From 36 to 40 MiB, global throughput falls 45.159% and texture throughput falls 45.246%. Their boundary is the same within repeatability; the native texture path does not expose additional effective capacity beyond L2 for this workload.

At one warp, the texture/global hot-rate ratio is 0.86346x at the median of sizes: texture is 13.65% slower. Its exposed-cycle ratio is 1.17546x, or 17.55% more cycles per dependent step. At 46, 184 and 1,104 warps the median rate ratios are 0.92608x, 0.94741x and 0.99949x. The paths converge only when lower-cache/memory service becomes the dominant bottleneck.

This agrees with the earlier Vulkan uniform-texel-buffer versus SSBO control, but is stronger instruction-level evidence: native SASS explicitly uses `TLD.LZ` versus `LDG.E.STRONG.GPU`. The result is therefore not caused by Vulkan descriptors compiling to the same instruction.

## Interpretation boundary

`Gload/s` counts requested scalar `u32` values. Random warp accesses may fetch larger cache sectors or lines, so it is not physical texture-cache bandwidth, L2 bandwidth, DRAM bandwidth or a transaction count. `clock64()` includes warp scheduling. Direct cache-sector counters remain permission-blocked.

The conclusion is specific and negative: moving this random dependent table onto the native texture path does not create more usable cache capacity and does not improve saturated throughput. Compacting a log LUT remains valuable because fewer bytes stay below the shared 36 MiB boundary—not because the texture path supplies another large cache tier.

Primary raw results are in `f1/`, `r1/`, `f2/` and `r2/`. The checked aggregate is `aggregate/cuda_texture_lut_aggregate.json`; the flat paired table is `aggregate/cuda_texture_lut_aggregate.csv`.
