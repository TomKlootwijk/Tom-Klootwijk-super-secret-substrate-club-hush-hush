# Native CUDA L2 clock-cycle protocol

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU, compute capability 12.0  
Compiler: CUDA 12.8.61, native `sm_120` target  
Reported L2: 37,748,736 bytes (36 MiB), returned by `cudaGetDeviceProperties`

## Purpose

This control complements the saturated Vulkan shader-clock sweep with a
cycle-domain measurement. NVIDIA defines `clock64()` as a per-multiprocessor
counter that increments every clock cycle, while warning that elapsed thread
time can include time slicing. NVIDIA defines `ld.global.cg` as bypassing L1
and caching at the global/L2 level, although cache operators remain performance
hints. Primary references are the
[CUDA Programming Guide clock64 section](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/cpp-language-support.html#clock-and-clock64)
and the
[PTX ISA cache-operator section](https://docs.nvidia.com/cuda/parallel-thread-execution/#cache-operators).

## Method

One 32-thread warp follows 512 strictly dependent random links. Inline
`ld.global.cg.u32` forces the intended L2/global load path. Before the cold
chain, 2,048 blocks read a separate 256 MiB allocation through the same cache
operator, more than seven times the reported L2 capacity. The hot chain then
immediately repeats the identical links and seed. A separately instantiated
zero-step kernel measures the two `clock64()` reads and surrounding code.

Every measured pair uses a new deterministic seed. Each thread writes its two
64-bit clocks, final index, checksum, seed, and step count. The host recomputes
all 512 links and validates the endpoint. The endpoint check represents the
executed chain; it does not observe every intermediate load independently.

The four isolated processes ran sequentially: `f1` and `f2` used ascending
table order, while `r1` and `r2` used descending order. Each table used five
discarded warmup pairs and 50 measured cold/hot pairs. Sizes are 4, 16, 32, 36,
38, 40, 64, and 128 MiB.

Representative commands:

```powershell
& .\gpu\scripts\build_windows_cuda_l2_clock.ps1

& .\gpu\build-windows\ugts_cuda_l2_clock_bench.exe `
  --out-dir .\benchmarks\cuda_l2_clock_isolated\f1 `
  --table-mib 4,16,32,36,38,40,64,128 `
  --eviction-mib 256 --warmup 5 --samples 50

python .\gpu\tools\aggregate_cuda_l2_clock.py `
  --runs .\benchmarks\cuda_l2_clock_isolated\f1 `
          .\benchmarks\cuda_l2_clock_isolated\r1 `
          .\benchmarks\cuda_l2_clock_isolated\f2 `
          .\benchmarks\cuda_l2_clock_isolated\r2 `
  --out-dir .\benchmarks\cuda_l2_clock_isolated\aggregate `
  --executable .\gpu\build-windows\ugts_cuda_l2_clock_bench.exe
```

## Binary and native-instruction evidence

The 527,872-byte executable SHA-256 is
`0FD243F0AFF55B0400C5F9602BB5473790B7DB21E4FF810F43A660587BF0712C`.
The CUDA source SHA-256 used for these runs is
`4081EA761F1FE417EA1DF743A2A64D48E01DE9DC88A79EC2B7CBCB18CDC2D854`.

`ptxas -v` reports 17 registers, zero stack bytes and zero spills for both the
control and 512-step chase; the eviction kernel uses 16 registers with zero
spills. `cuobjdump --dump-sass` verifies:

- chase512: two `CS2R ..., SR_CLOCKLO` reads and one static
  `LDG.E.STRONG.GPU` inside the retained loop;
- control: two clock reads and no `LDG.E.STRONG.GPU`;
- eviction: one static `LDG.E.STRONG.GPU` in its loop.

This establishes native Blackwell SASS execution rather than relying only on
source intent or virtual PTX.

CUDA Compute Sanitizer `memcheck` completed the 4 MiB control/chase path with
zero errors. Its instrumented timing is excluded from every performance row.

## Validation and interpretation boundary

All 32 aggregate rows pass. The four processes validate 153,600 result
payloads. The cold and hot endpoints represent 52,428,800 executed dependent
loads.

The reported value is cycles per dependent warp step after subtracting the
zero-step median. Each random warp instruction may request up to 32 cache
sectors, and `clock64()` includes any time slicing. It is therefore an exposed
one-warp L2/global-path latency, not the latency of one scalar memory
transaction and not an architecture-independent constant.

CUDA events independently bracket the complete chase kernels. At the median
of table-size medians, their durations divided by 512 are 153.414 ns per hot
step and 401.820 ns per post-eviction step. These values include prologue,
result stores and scheduling, so the control-subtracted cycle interval remains
the preferred in-loop metric.

The immediate hot repeat traverses only about 16,384 link visits and is
intended to fit in L2 regardless of total allocation. That is why its roughly
400-cycle result is flat from 4 through 128 MiB; table size is not being used
as a capacity test here. The separately documented saturated Vulkan sweep is
the capacity experiment.
