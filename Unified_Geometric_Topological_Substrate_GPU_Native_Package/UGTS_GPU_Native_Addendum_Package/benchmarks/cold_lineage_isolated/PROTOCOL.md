# Isolated cold-lineage benchmark protocol

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU  
Execution: direct Vulkan compute, sequential host processes

This directory is the primary cold-lineage timing corpus. The six benchmark
processes were launched one at a time, and each process exited successfully
before the next process started. The order was `f1`, `r1`, `f2`, `r2`, `f3`,
`r3`; `f*` uses forward program order and `r*` uses `--compact-reverse`.

All six runs used the same native harness executable:

- path: `gpu/build-windows/ugts_vulkan_bench.exe`
- size: 482,816 bytes
- SHA-256: `4E3C2D6E1FF5D8660CDF83ABC7337401BBEE823C29B25826747A8ED08B0B8C54`
- result schema: `UGTS-VK-BENCH-1.7`

Shared parameters:

- candidate counts: 1,310,720; 1,441,792; 1,474,560; 1,507,328;
  1,540,096; 1,572,864; 1,638,400; 1,703,936; 1,769,472;
  1,835,008; 2,097,152; 4,194,304
- 10 untimed warmups plus at least 750 ms of warmup
- 200 timestamped dispatches per case
- output capacity: 6.25% of candidates
- six programs and 72 benchmark rows per process

All 432 rows passed payload, counter, completeness, and overflow validation;
all pipeline-cache reloads succeeded; no row overflowed. Each process captured
native NVIDIA pipeline-executable statistics through
`VK_KHR_pipeline_executable_properties`.

The earlier `benchmarks/cold_lineage_hot/` corpus is retained for audit but is
excluded from the primary aggregate because four of its processes overlapped in
wall-clock time. The isolated aggregate does not cherry-pick timings. In `f1`,
the largest G24 counted case took 0.206496 ms rather than the roughly 0.168 ms
seen in the other five processes; that observation remains in the raw data and
the reported min/max, while the cross-process median limits its influence.
