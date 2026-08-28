# Native CUDA packed 6-bit log-LUT protocol

## Question

The package previously reported that replacing the native two-16-bit-slots-per-word representation with a densely packed 6-bit code stream would increase ideal cache capacity by 2.667x, while explicitly leaving decode cost unmeasured. This experiment implements that exact packing on the local GPU and tests whether the density survives native decode, cache residency and texture-path costs.

## Device and executable

- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- CUDA target: `sm_120`, CUDA 12.8
- Reported L2: 37,748,736 bytes (36 MiB)
- SMs: 46
- Source: `gpu/src/ugts_cuda_packed_log_lut_bench.cu`
- Source SHA-256: `207F7975F162EA3FFE7C5998BAE8955FC9F4166DCD92BE28C662373F9592AB1B`
- Executable: `gpu/build-windows/ugts_cuda_packed_log_lut_bench.exe`
- Executable bytes: 629,248
- Executable SHA-256: `C30126EE2D6C9FF2792FBDBB0E0BCE39814EE9288BDC91F0857B4084CA498FE5`

`ptxas` reports no stack and no spills. The timed global slot16, global packed6, texture slot16 and texture packed6 kernels use 15, 21, 14 and 18 registers respectively. CUDA occupancy queries report the same ceiling for all four: 24 one-warp blocks per SM, or 1,104 warps over 46 SMs.

Native `cuobjdump --dump-sass` confirms the intended paths:

- global slot16: one static `LDG.E.STRONG.GPU` in the loop;
- global packed6: one unconditional and one predicated `LDG.E.STRONG.GPU`;
- texture slot16: one static `TLD.LZ`;
- texture packed6: one unconditional and one predicated `TLD.LZ`;
- every timed kernel: two `CS2R ..., SR_CLOCKLO` reads; and
- zero-step controls: two clock reads and no table load.

The second packed load is executed only when a 6-bit value straddles a 32-bit word. This occurs for 2 of every 16 code offsets, giving 1.125 logical `u32` word requests per decoded packed code versus one for slot16. Compute Sanitizer reports zero errors on the instrumented smoke control; its timings are excluded.

## Representation and validation

`slot16` places two unsigned 6-bit codes in the low six bits of two 16-bit fields in each `u32`, using exactly 2 bytes/code. `packed6` places sixteen codes in three `u32` words, using exactly 0.75 bytes/code. Both encode the full 0-63 code range uniformly as `code = logical_index mod 64`.

Every lane performs 512 pseudorandom lookups. The LCG state determines the next logical index but does not depend on the loaded code, making this a random lookup-throughput test rather than a pointer-latency chase. Every loaded value is compared inside the timed native kernel with the independently computable code for that index; a per-lane mismatch count must remain zero. The CPU separately advances the LCG algebraically and validates every final state, seed, step count and clock interval. The table initialization is not timed.

Each measurement path receives a 256 MiB L2/global eviction; texture paths additionally receive a 256 MiB texture-object eviction. A cold kernel is followed immediately by an identical hot kernel. CUDA events time complete kernels, while `clock64()` measures exposed in-kernel cycles.

## Run matrix

Four sequentially isolated processes use Latin orders 0, 1, 2 and 3:

1. global slot16, global packed6, texture slot16, texture packed6;
2. the exact reverse;
3. global packed6, global slot16, texture packed6, texture slot16; and
4. the exact reverse.

Two processes use ascending entry/warp order and two use descending order. Each case uses three discarded warmup sets and twelve measured sets. Concurrency is 1, 46, 184 and 1,104 warps. Logical entry counts include exact or nearest-lower 28, 36 and 40 MiB physical endpoints for both encodings.

The four runs contain 704 valid raw rows and aggregate to 176 path/representation/entry/concurrency cases. They validate 270,673,920 returned payloads. The 180,449,280 cold/hot lookup payloads represent **92,390,031,360 individual code checks**.

## Full-occupancy results

Rates below are medians across four isolated processes and count decoded logical codes, not physical cache transactions.

| Logical codes | slot16 bytes | packed6 bytes | Global slot16 Glookup/s | Global packed6 Glookup/s | Texture slot16 Glookup/s | Texture packed6 Glookup/s |
|---:|---:|---:|---:|---:|---:|---:|
| 2,097,152 | 4 MiB | 1.5 MiB | 43.231 | 38.321 | 43.432 | 43.212 |
| 14,680,064 | 28 MiB | 10.5 MiB | 43.398 | 38.496 | 43.397 | 42.976 |
| 18,874,368 | 36 MiB | 13.5 MiB | 43.219 | 38.526 | 43.192 | 42.949 |
| 39,146,832 | 74.667 MiB | 28 MiB - 4 B | 8.647 | 38.505 | 8.643 | 42.804 |
| 50,331,648 | 96 MiB | 36 MiB | 7.970 | 38.492 | 7.968 | 42.594 |
| 55,924,048 | 106.667 MiB | 40 MiB - 4 B | 7.778 | 23.466 | 7.779 | 23.406 |
| 67,108,864 | 128 MiB | 48 MiB | 7.527 | 12.575 | 7.521 | 12.591 |

At the nominal L2 capacity, slot16 holds 18,874,368 codes and packed6 holds 50,331,648: exactly 2.667x as many. The texture path supplies 43.192 and 42.594 Glookup/s respectively, so the 2.667x capacity increase costs only 1.39% of full-occupancy throughput. The global path supplies 43.219 and 38.492 Glookup/s, a 10.94% packing cost.

At the conservative 28 MiB budget, slot16 holds 14,680,064 codes. The measured packed endpoint is four bytes below 28 MiB and holds 39,146,832 codes, only five entries below the mathematical floor of 39,146,837. Texture throughput is 43.397 Glookup/s for the 28 MiB slot table and 42.804 Glookup/s for the 28 MiB packed table, a 1.37% difference at 2.667x capacity.

The cache boundary does not move. From the physical 36 MiB endpoint to the nearest-lower 40 MiB endpoint, slot16 loses 45.54% on global and 45.52% on texture. Packed6 loses 39.04% on global and 45.05% on texture. The smaller global percentage occurs because packed decode already limits its 36 MiB rate; the texture path exposes the same approximately 45% residency cliff as the simpler slot representation.

At the same 50,331,648-code logical capacity, packed6 uses 36 MiB while slot16 uses 96 MiB. Packed texture is 5.346x faster than slot texture (42.594 versus 7.968 Glookup/s), while packed global is 4.829x faster (38.492 versus 7.970 Glookup/s). This speedup comes from changing cache residency, not from bit extraction itself.

## Decode and texture interpretation

When both tables are very small, packed decode is not free. At 2,097,152 codes, the packed/slot hot-rate ratios at 1, 46, 184 and 1,104 warps are 0.977, 0.958, 0.958 and 0.886 on the global path, and 0.942, 0.942, 0.961 and 0.995 on the texture path. The extra shifts, predicate and occasional second word fetch are exposed at low concurrency.

The packed texture path is 1.107x the packed global rate at the 36 MiB endpoint, even though the earlier byte-identical pointer chase found no texture advantage. This is not evidence of extra texture-cache capacity: both packed paths fall to about 23.4 Glookup/s at 40 MiB and about 12.6 at 48 MiB. It is evidence that the native texture instruction handles this specific packed extraction/occasional-second-fetch schedule more efficiently at saturated, cache-resident occupancy. The conclusion is instruction-pattern-specific.

## Bounds

`Glookup/s` counts logical decoded codes. `requested_word_gloads/s` in the machine data applies the exact 1.0 or expected 1.125 representation-level word-request multiplier, but neither metric is a cache-sector count, physical L2 bandwidth or DRAM bandwidth. Random warp accesses can transact larger sectors. `clock64()` includes warp scheduling, and CUDA events include complete kernel overhead. Privileged NVIDIA cache-sector and DRAM counters remain unavailable on this machine.

Primary raw results are in `f1/`, `r1/`, `f2/` and `r2/`. The checked aggregate is `aggregate/cuda_packed_log_lut_aggregate.json`; flat aggregate, packing-comparison and texture-comparison tables are in the same directory.
