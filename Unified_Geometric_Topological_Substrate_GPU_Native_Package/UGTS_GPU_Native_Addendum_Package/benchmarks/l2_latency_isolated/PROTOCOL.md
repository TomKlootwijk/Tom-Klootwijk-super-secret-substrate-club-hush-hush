# Native shader-clock L2 latency protocol

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU  
Reported L2: 37,748,736 bytes (36 MiB), from the local CUDA device-properties query  
API path: direct Vulkan compute with `VK_KHR_shader_clock` and device-local SSBOs

## Isolation and ordering

Four processes ran sequentially, never concurrently: `f1`, `r1`, `f2`, and
`r2`. Forward processes execute the control before the 512-load chain and the
sequential ring before the random full-period chain. Reverse processes invert
both orders. The executable was not rebuilt between these four processes.

Each case used 65,536 shader invocations, at least 10 warmup submissions and
750 ms of warmup, followed by 100 device-timestamped submissions. The table
sizes were 4, 16, 24, 28, 32, 34, 36, 38, 40, 48, 64, and 128 MiB. Thus the
sweep samples both the exact reported L2 capacity and 2 MiB increments around
it.

The common executable was 373,248 bytes with SHA-256
`DE76C6B8815256B61E5C2375F8695D313DEA699D130B110C342AC599C0E7E277`.
The named control SPIR-V SHA-256 is
`8100BA7178DB26DD0165A0E191B85C415C8249A46D5695BF7D90A7C6A5050E57`;
the named 512-step SPIR-V SHA-256 is
`65603A3F61F2A0D62AEDAC6ED2E5CC9E2D7AACB116E219F6451B2DF672BB1914`.

Representative commands, with `-ReverseOrder` added for `r1` and `r2`:

```powershell
& .\gpu\scripts\run_windows_l2_latency.ps1 `
  -OutputDirectory .\benchmarks\l2_latency_isolated\f1 `
  -SkipBuild

python .\gpu\tools\aggregate_l2_latency.py `
  --runs .\benchmarks\l2_latency_isolated\f1 `
          .\benchmarks\l2_latency_isolated\r1 `
          .\benchmarks\l2_latency_isolated\f2 `
          .\benchmarks\l2_latency_isolated\r2 `
  --out-dir .\benchmarks\l2_latency_isolated\aggregate `
  --executable .\gpu\build-windows\ugts_vulkan_lut_bench.exe
```

## What is measured

Each invocation starts from a deterministic mixed index and follows 512
strictly dependent `next[index]` SSBO loads. The random table uses a
Hull-Dobell full-period affine permutation for each table length, so it forms
one cycle even for the non-power-of-two 34, 36, 38, and 40 MiB cases. The
sequential table is a single adjacent-index ring.

The shader reads the device-scope realtime clock immediately before and after
the chain. A separately compiled zero-step shader measures clock-read and
surrounding instruction overhead. Every invocation writes both 64-bit clock
values, its final dependent index, a checksum, a magic value, and its compile-
time step count. Host validation recomputes all 512 links and checks every
payload before a row is accepted.

Optimized SPIR-V contains two device-scope `OpReadClockKHR` instructions in
both modules, while only the 512-step module contains the loop and dependent
SSBO `OpLoad`. All named and optimized modules pass `spirv-val` for Vulkan 1.2.

## Interpretation boundary

`VK_KHR_shader_clock` deliberately leaves clock units implementation-defined.
The reported control-subtracted ticks per load are therefore not labelled GPU
cycles or nanoseconds. With 65,536 chains in flight, they also include warp-
scheduler exposure. They are a saturated dependent-chain metric suitable for
relative cache-boundary comparisons, not an isolated single-load latency.

An invocation-count control at 32, 64, 256, 1,024, and 4,096 invocations is
retained under `benchmarks/l2_latency_occupancy/`. It demonstrates why a
single-warp hot repetition cannot answer the capacity question: its 512-link
subset becomes cache-resident regardless of total table allocation. The
65,536-invocation sweep covers 33,554,432 dependent accesses per chase row,
enough to exercise the complete large-table working set, at the cost of the
explicit scheduler-exposure caveat.

## Validation volume

The four primary processes contain 192 valid rows and 12,582,912 validated
invocation payloads including controls. Validated chase endpoints represent
3,221,225,472 executed dependent SSBO loads; validation checks each chain's
final index rather than observing every intermediate load separately. No row was dropped. Per-run JSON hashes
and forward/reverse flags are recorded in
`aggregate/l2_latency_aggregate.json`.
