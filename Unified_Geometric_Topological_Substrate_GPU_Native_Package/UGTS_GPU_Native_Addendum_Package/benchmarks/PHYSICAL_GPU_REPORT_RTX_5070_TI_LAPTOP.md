# UGTS-GN physical GPU validation - RTX 5070 Ti Laptop GPU

Run date: 2026-08-15 (Europe/Amsterdam)  
Status: physical discrete-GPU execution verified; direct hardware performance-counter access unavailable.

## Result

The UGTS compute path ran through the NVIDIA Vulkan driver on the local NVIDIA GeForce RTX 5070 Ti Laptop GPU. Storage buffers were allocated from `VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT`; host-visible coherent buffers were used only for explicit upload/readback staging. GPU timestamps surround the compute dispatch, not transfer or CPU-oracle work.

This is the closest native path available in the installed Windows environment: direct Vulkan/SPIR-V with no Unity, Godot, browser, ANGLE, or SwiftShader layer. It is not strict bare metal because Windows WDDM, the NVIDIA driver, dynamic laptop clocks, and the OS scheduler remain active.

The selected device also exposes `VK_KHR_shader_clock` with device-scope clocks. A four-process, order-balanced 512-step dependent SSBO chase is flat through the exact 36 MiB reported L2 capacity, rises 1.242x at 38 MiB and 2.134x at 40 MiB, then reaches 4.714x at 64 MiB and 6.295x at 128 MiB relative to 36 MiB. These are implementation-defined shader-clock ticks under a saturated workload, not claimed hardware cycles or nanoseconds.

An independent CUDA 12.8 `sm_120` control uses per-SM `clock64()` cycles and L1-bypassing `ld.global.cg` loads. Across 4-128 MiB tables, a one-warp immediate-hot repeat measures 399.57 cycles per dependent step at the median of sizes, while the same chain after a 256 MiB L2-eviction pass measures 1,087.79 cycles: a 2.722x post-eviction penalty. Complete-kernel CUDA-event time corresponds to 153.4 ns and 401.8 ns per step respectively. Native SASS and zero-spill compiler output verify the intended instruction path. This is exposed warp-step latency, not one scalar transaction's latency.

A second native CUDA matrix scales the same dependent `ld.global.cg` path from one warp to the occupancy-query ceiling of 1,104 warps (24 per SM). At full measured occupancy, immediate-hot requested throughput is 43.215 Gload/s for the exact 36 MiB table and 23.683 Gload/s at 40 MiB, a 45.20% loss for 4 MiB of excess allocation. It falls to 9.357 Gload/s at 64 MiB and 7.524 Gload/s at 128 MiB. This reproduces the capacity boundary in native cycle/throughput measurements and quantifies the scheduling and memory-queue amplification hidden by the one-warp control.

A matched CUDA texture-object control then binds the same table allocation through native `TLD.LZ` and `LDG.E.STRONG.GPU` paths. At full occupancy the texture/global hot-rate ratio is 0.99949x at the median of eight table sizes. Global and texture throughput fall 45.159% and 45.246% respectively from 36 to 40 MiB. At one warp texture is 13.65% slower. This instruction-level control rejects an additional effective texture-cache capacity tier for the random dependent LUT.

A native dense-packing control closes the remaining theoretical gap. At the same 36 MiB physical budget, texture slot16 holds 18,874,368 codes at 43.192 Glookup/s while texture packed6 holds 50,331,648 at 42.594 Glookup/s: the full 2.667x capacity for only 1.39% saturated-rate loss. Packed texture falls 45.05% at 40 MiB, so packing moves logical capacity without moving the cache boundary.

A sparse-stride CUDA control bounds one locality endpoint. Full-occupancy active-node capacity scales 4:2:1 for 32-, 64- and 128-byte spacing, and 256-byte spacing tracks the 128-byte curve despite twice the allocation. This is consistent with a 128-byte effective residency unit per isolated **dependent pointer** on this workload, but it is not a universal per-code cache charge.

A new packed-LUT line-occupancy control maps the missing continuum with independently schedulable random lookups. It varies 1-170 useful packed6 codes inside aligned 128-byte regions and probes the exact 42/43, 85/86 and 128/129 code boundaries. Every layout sustains 42.437-43.010 Glookup/s at 36 MiB. At 40 MiB, texture throughput declines progressively from 42.800 Glookup/s with one useful code to 23.514 Glookup/s with 170; at 48 MiB the range is 28.104-12.628 Glookup/s. A newly entered 32-byte address region has only 1/43, 1/86 or 1/129 access probability, explaining why boundary crossings are gradual rather than cliffs. This corrects the earlier temptation to treat the dependent pointer-chase result as a universal 128-byte LUT residency cost.

A final independent sparse-address matrix separates the competing limits. At the same 40 MiB allocation and 327,680 aligned 128-byte lines, requesting four, two or one 32-byte portions per line sustains 23.343, 38.505 and 42.802 Glookup/s. At the same 12 MiB of requested 32-byte data, spreading addresses over 98,304, 196,608 and 393,216 containing lines changes texture throughput from 43.214 through 43.207 to 28.119 Glookup/s. Doubling address span without changing data volume or line count adds a smaller, strongest-near-transition penalty. The defensible model therefore needs separate resident-data, containing-line-address and address-span terms; the timing evidence cannot identify undocumented NVIDIA sectors, tags, sets, partitions or TLB behavior.

The address-span term is now independently bounded. With useful words and containing test-line count fixed, non-power-of-two strides retain full throughput at a 252 MiB span and slow between 252 and 256 MiB. Exact 4-KiB spacing falls from 42.590/41.784 Glookup/s at 128 MiB to 34.315/34.451 at 256 MiB on global/texture, then converges near 15.2 Glookup/s by 1 GiB. A separate ±32-byte control proves that exact 512- and 1,024-byte pitches also cause severe native texture-path address aliasing below that general span boundary. At a 7 MiB target, 992/1,024/1,056-byte texture strides give 42.802/28.621/43.007 Glookup/s while global remains near 42.8. The result supports practical padding/skew, not an undocumented TLB or cache-set declaration.

A VMM physical-backing control makes the general span result materially stronger. Every virtual slot aliases the same 2 MiB allocation—18x smaller than reported L2—and both native paths share each mapping. Throughput stays near 42.9 Glookup/s through 240 MiB virtual reach, then global/texture fall together to 39.523/39.539 at 248 MiB, 35.663/35.687 at 252 MiB and 34.439/34.456 at 256 MiB. Fixed-alias pitch sweeps reproduce the loss without changing physical payload. Address distribution/reach is therefore causal for this kernel; page size, TLB structure and page-walk counters remain unobserved.

Explicit generic-compression VMM allocations are now verified and performance-tested. The driver returns effective compression enum 1 and successful mapped readback. Periodic and entropy-dense packed6 LUTs nevertheless show essentially 1.000x generic/non-compressible throughput and the same 36-40 MiB cliff. All-zero and independently checked all-one constant-word controls expand: global throughput stays near 38.6 Glookup/s through 240 MiB, equivalent to 6.667x nominal L2 allocation capacity, before the independent 248 MiB address-reach loss. This proves content-sensitive hardware compression exists, while rejecting any automatic compression gain for an ordinary information-bearing log LUT.

The exact externalized threshold-code stream from the current synthetic G24 producer is also negative. Its constant floor 0.70 quantizes to code 8 and packs as three alternating words rather than uniform words. Four balanced native processes validate 256 rows and 92.610 billion timed global/texture lookups; the median generic/non-compressible ratio is 0.999993x, and both modes end at the same 36 MiB 99%-rate boundary. Semantic uniformity therefore does not imply physically compressible packed words.

An exhaustive raw-global follow-on enumerates all 64 uniform codes and finds a complete physical-word classification. Only codes 0, 21, 42 and 63 pack into three identical `u32` words, and only those four extend beyond 36 MiB. Zero/all-one words remain full through 240 MiB; `0x55555555`/`0xAAAAAAAA` have a balanced 70 MiB endpoint; the other 60 codes remain at 36 MiB. Eight balanced processes validate 3,616 rows and 1.308 trillion timed lookups. This is exact for the tested domain, layout and GPU without asserting an undocumented compressor format.

A balanced code-0/code-63 follow-on proves the capacity effect can survive a mixed table, while sharply bounding its dependence on spatial organization. Pseudorandom selection per 12-byte group and alternating 12-96-byte runs reach a 72 MiB balanced endpoint; 192-byte runs reach 88 MiB; every tested 384-12,288-byte run remains full through the independently address-bounded 240 MiB endpoint. Eight processes validate 2,064 rows, 2.188 billion payloads and 746.670 billion timed raw-global lookups. This is a deterministic two-symbol workload result, not arbitrary-data compression or proof of a 384-byte hardware block.

A stricter four-symbol follow-on uses all four uniform packed codes that individually compress: 0, 21, 42 and 63. Sixteen order-balanced processes validate 3,560 rows, 3.773 billion payloads and 1.288 trillion timed raw-global lookups. Hashed/12-192-byte symbol runs have balanced endpoints from 40 to 82 MiB; tested 384-12,288-byte runs range from 120 to 168 MiB. The strongest measured case holds 234,881,024 codes in a 168 MiB allocation, 4.667 times nominal L2, but longer runs regress non-monotonically. This expands the proven synthetic mixture class while rejecting a general compression ratio or simple run-length law.

The packed G32 kernel was also run end to end with confidence supplied through Vulkan uniform texel-buffer LUTs. Both an 8,196-byte adjacent-sample layout and a 16,384-byte one-fetch interval-pair layout are semantically valid. Neither provides a stable end-to-end advantage over native `exp2` for this kernel on this GPU: LUT lookup is slower while arithmetic latency is exposed and effectively tied once state/output traffic dominates. A byte-identical SSBO control additionally shows that large random texture-buffer and SSBO reads share the same cache-capacity cliff.

Verified-only G32 event compaction is now implemented and measured. A subgroup-ballot/workgroup-reservation path writes only the 4.75% verified events and reduces all four global counters per workgroup. At 4,194,304 candidates it is 1.528x faster than dense evaluation and 1.869x faster than dense evaluation with per-lane global counters across the original balanced job-order set. A second balanced run uses a bounded 6.25%-capacity event FIFO: it retains every event with zero overflow, reduces the actual output allocation from 64 MiB to 4 MiB (16x), and measures 0.219 ms at the four-process median.

An optional pre-threshold profile removes the per-candidate exponential from the verification predicate and computes confidence only for retained events. It improves append-only medians by 1.0-4.5% at smaller/mid sizes, but converges to +0.03% at 4,194,304 and does not materially improve the counted path. It is therefore a declared alternate G32 ABI, not the default.

A fixed-query G24 hot-state profile then removes fields that the benchmark query does not consume and stores a 6-bit log-distance threshold code. With the same 6.25%-capacity output allocation, this reduces resident state-plus-output allocation from 132 MiB to 100 MiB at 4,194,304 candidates. The direct-decoder control measures 0.168 ms, 1.306x faster than G32 append, and 0.168 ms with reduced counters, 1.312x faster than G32. A separate 128-byte, one-fetch texture-LUT decoder is effectively tied with the direct decoder once bandwidth-bound and slower below L2. The measured win therefore comes from the 24-byte record footprint and shifted cache boundary, not from the LUT itself.

A follow-on G20 experiment splits the 4-byte lineage seed from the five-word hot geometry record and reads it only after verification. Total state storage remains 24 bytes per candidate, but the declared always-hot state-plus-output allocation falls from 100 MiB to 84 MiB at 4,194,304 candidates. Six balanced, sequentially isolated processes measure 1.108x higher append throughput and 1.110x higher counted-path throughput than G24 at that size, with identical counts and validated retained payloads. This is a locality win rather than additional storage compression; the dedicated [yield/compression/limits report](YIELD_COMPRESSION_LIMITS_RTX_5070_TI_LAPTOP.md) gives the human-readable accounting and bounds.

## Hardware and run conditions

| Item | Value |
|---|---:|
| GPU | NVIDIA GeForce RTX 5070 Ti Laptop GPU (Blackwell) |
| CUDA compute capability / SMs | 12.0 / 46 |
| VRAM | 12,227 MiB reported by `nvidia-smi` |
| L2 cache | 37,748,736 bytes (36 MiB), CUDA device-properties query |
| Vulkan | 1.4.325, discrete device, vendor `0x10DE`, device `0x2F18` |
| Driver | NVIDIA 591.59, WDDM |
| Timestamp | 1 ns period, 64 valid bits |
| Vulkan subgroup | 32 lanes; compute basic + ballot supported (8 subgroups per 256-thread workgroup) |
| OS / CPU | Windows 11 build 26200 / Intel Core Ultra 7 255HX |

The direct baseline aggregate covers six independent processes: the three stabilized direct-only runs and three new direct-plus-LUT runs. Cases used a 500-750 ms minimum warmup and 100-200 measured dispatches. The original paired direct/LUT comparison uses the three new processes. A second comparison of direct, adjacent-sample LUT and interval-pair LUT uses four independent processes, two in forward and two in reverse mode order. The G24 attribution control uses six independent processes, three in each job order. The primary G20 comparison likewise uses six processes, but they were explicitly run one at a time; the earlier partially concurrent corpus is retained and excluded. The uniform-texel/SSBO control uses four sequentially isolated processes, two in each program order. The Vulkan shader-clock study adds four sequentially isolated processes, two forward and two reverse, with 750 ms minimum warmup and 100 timed submissions per case. The CUDA cycle study adds four isolated processes, two ascending and two descending table orders, with 50 measured cold/hot pairs after five warmup pairs per table. The CUDA concurrency study adds four sequential processes, reverses both table and warp order, and retains 15 cold/hot pairs after three warmups for each of 60 table/warp cases. The CUDA texture/global study uses four sequential processes, balances path order 2/2, reverses table/warp order 2/2, and retains 12 pairs after three warmups for each matched case. The packed-log study adds four sequential processes using four Latin path/representation orders, reverses logical-entry and warp order 2/2, and retains 12 cold/hot sets after three warmups. Reported latency and rates are medians of process-level device-timestamp, shader-clock, or CUDA cycle p50 values; ranges expose cross-process WDDM and clock variation.

Each timed case repeatedly dispatches against the same resident device-local buffers. Values at or below L2 capacity are therefore intentional cache-hot steady-state measurements, not cold one-pass streaming numbers.

## Core metrics at 4,194,304 candidates

| Profile | Mode | Replicates | Device p50 | Candidate rate | Cross-run rate range | Verified-event rate | Logical bandwidth |
|---|---|---:|---:|---:|---:|---:|---:|
| G64_E32 | evaluate | 6 | 0.746 ms | 5.684 Gcandidate/s | 5.085-6.279 G/s | 278.201 Mevent/s | 545.683 GB/s |
| G64_E32 | evaluate + commit | 6 | 0.822 ms | 5.100 Gcandidate/s | 5.085-6.288 G/s | 249.612 Mevent/s | 489.608 GB/s |
| G32_E16 direct | evaluate | 6 | 0.335 ms | 12.519 Gcandidate/s | 10.206-12.569 G/s | 594.522 Mevent/s | 600.932 GB/s |
| G32_E16 direct | evaluate + commit | 6 | 0.411 ms | 10.206 Gcandidate/s | 7.144-10.242 G/s | 484.669 Mevent/s | 489.894 GB/s |
| G32_E16 LUT | evaluate | 3 | 0.335 ms | 12.526 Gcandidate/s | 12.525-12.567 G/s | 594.834 Mevent/s | 601.248 GB/s |
| G32_E16 LUT | evaluate + commit | 3 | 0.411 ms | 10.195 Gcandidate/s | 10.194-10.199 G/s | 484.140 Mevent/s | 489.360 GB/s |

"Logical bandwidth" is declared input-record bytes plus output-record bytes divided by device time. It is not measured DRAM traffic and can include cache reuse. At this batch size the direct packed G32_E16 path is 2.202x faster than G64_E32 for evaluation and 2.001x faster with atomic commit.

GPU-observed event counts at this size were:

| Profile | Supported | Support + compatible | Verified | Event yield |
|---|---:|---:|---:|---:|
| G64_E32 | 2,213,528 | 368,801 | 205,281 | 4.8943% |
| G32_E16 direct and LUT | 2,085,336 | 346,957 | 199,179 | 4.7487% |

## Inner-working verification

The harness reads back and checks every output record. It verifies scalar distance, guard, confidence, event time where present, support/compatibility/verified flags, route, lineage hash, and state flags. For commit variants it independently derives counts from output flags and requires the four GPU atomic counters to match exactly.

The dispatched SPIR-V performs the complete kernel natively: unpack G32 half pairs where applicable; compute radial length and normalized-axis dot product; apply radial/angular support; apply the sheet/orientation/mask compatibility predicate; evaluate sphere SDF and guard; produce confidence; resolve the verified event and route; hash lineage; write E32/E16 output; and, for commit variants, atomically accumulate the four counters.

The LUT variants replace `exp2(-32 * abs(sdf))` only inside `abs(sdf) < 0.125`. The adjacent-sample layout linearly interpolates 4,097 binary16 confidence samples packed two per `R32_UINT` texel. It occupies 8,196 bytes, or 0.0217% of the 36 MiB L2 cache, and evaluates two sample lookups. The interval-pair layout stores both binary16 endpoints of each of 4,096 intervals in one `R32_UINT` texel. It duplicates interior endpoints, occupies 16,384 bytes or 0.0434% of L2, and requires one lookup per interpolated value. Both use binding 3 as a Vulkan `UNIFORM_TEXEL_BUFFER`; values outside the interval use direct `exp2`, preserving the function's domain.

The compiler produces twenty-six named execution variants and twenty-six `spirv-opt -O` counterparts. All 52 bundled SPIR-V artifacts pass `spirv-val --target-env vulkan1.2`; the native harness measurements use the named non-`.opt` files. Disassembly shows two dynamic calls to the adjacent-sample fetch routine in the named module (two static `OpImageFetch` instructions after optimization), one `OpImageFetch` in the interval-pair module, and one in the G24 log-threshold LUT module. The paired cache probe has one `OpImageFetch` on the uniform-texel path and storage-buffer `OpLoad` instructions on its byte-identical SSBO path. Both shader-clock modules contain two device-scope `OpReadClockKHR` operations; only the 512-step module retains the dependent SSBO-load loop. The one-warp CUDA compiler control uses 17 registers; the concurrency and sparse-stride chases use 16. The CUDA packing kernels use 15/21 registers for global slot16/packed6 and 14/18 for texture slot16/packed6. The line-occupancy timed kernels use 26/22 registers for global/texture and their matched controls use 18. The sparse-address timed global/texture kernels both use 22 registers and their matched controls use 18. All report no stack and no spills. Native `sm_120` SASS shows two `CS2R SR_CLOCKLO` reads and `LDG.E.STRONG.GPU` in global chases; texture chases instead contain `TLD.LZ ..., 1D`. Packed extraction adds a second predicated native load for straddling offsets, while zero-step controls have no load. The sparse-stride timed loop has one static `LDG.E.STRONG.GPU`; its control has no load. The line-occupancy kernels have one unconditional plus one predicated `LDG.E.STRONG.GPU` or `TLD.LZ`; their timed controls contain no table load. The sparse-address kernels contain exactly one timed global or texture table load; their controls contain none. The G24 direct and G20 controls have no `OpImageFetch`. Both G24 modules declare a 24-byte state-array stride; G20 declares a 20-byte stride plus storage binding 4 for lineage, and the optimized module loads lineage after the non-verified early return. Representative NVIDIA pipeline evidence comes from integrated `replicate_1`, with interval-pair rows from `lut_pair/f1`, pre-threshold rows from `prethreshold/f1`, G24 rows from `hot_log_control/f1`, and G20 rows from `cold_lineage_isolated/f1`:

Compute Sanitizer reports zero errors on the instrumented CUDA concurrency, texture, packing, stride, line-occupancy, sparse-address, padded-stride and 4-KiB-stride controls, including the 1-GiB allocation endpoint. Sanitizer timings are excluded from performance aggregates.

| Program | SPIR-V | NVIDIA pipeline cache | Cache-reloaded creation |
|---|---:|---:|---:|
| G64_E32 evaluate | 4,888 B | 10,068 B | 0.046 ms |
| G64_E32 evaluate + commit | 5,508 B | 11,015 B | 0.095 ms |
| G32_E16 direct evaluate | 5,528 B | 10,001 B | 0.054 ms |
| G32_E16 LUT evaluate | 8,068 B | 12,090 B | 0.149 ms |
| G32_E16 interval-pair LUT evaluate | 7,456 B | 11,345 B | 0.063 ms |
| G32_E16 direct evaluate + commit | 6,148 B | 11,009 B | 0.055 ms |
| G32_E16 LUT evaluate + commit | 8,548 B | 13,085 B | 0.085 ms |
| G32_E16 interval-pair LUT evaluate + commit | 7,936 B | 12,458 B | 0.143 ms |
| G32_E16 pre-threshold subgroup append | 8,660 B | 13,984 B | 0.071 ms |
| G32_E16 pre-threshold subgroup append + counts | 10,328 B | 15,991 B | 0.178 ms |
| G24_E16 direct-threshold subgroup append | 8,824 B | 14,579 B | 0.358 ms |
| G24_E16 direct-threshold subgroup append + counts | 10,492 B | 16,514 B | 0.185 ms |
| G24_E16 log-LUT subgroup append | 9,364 B | 15,065 B | 0.098 ms |
| G24_E16 log-LUT subgroup append + counts | 11,032 B | 16,957 B | 0.087 ms |
| G20_E16 cold-lineage subgroup append | 9,028 B | 14,641 B | 0.071 ms |
| G20_E16 cold-lineage subgroup append + counts | 10,696 B | 16,594 B | 0.086 ms |

The six isolated processes also captured driver-native executable statistics. Values were identical across all six captures:

| Program | Subgroup | Registers | Shared memory | Executable binary |
|---|---:|---:|---:|---:|
| G24 direct append | 32 | 22 | 2,052 B | 3,456 B |
| G20 cold-lineage append | 32 | 22 | 2,052 B | 3,456 B |
| G24 direct append + counts | 32 | 40 | 5,124 B | 4,736 B |
| G20 cold-lineage append + counts | 32 | 39 | 5,124 B | 4,864 B |

These are compiler metadata from `VK_KHR_pipeline_executable_properties`, not performance counters. In particular, the append kernels have identical reported compute-resource use, strengthening the attribution to data locality. NVIDIA reports `Local Memory Size = 68,719,476,736` bytes for every executable, an implausible per-thread value that is preserved in the machine-readable output but explicitly excluded from occupancy claims. The driver returned no internal representation or ISA blob.

Validation volume was 112,529,408 dense semantic outputs in the original baseline aggregate, 167,510,016 in the three integrated performance runs, 25,165,824 in the large semantic-hash audit, 570,425,344 outputs in the two dedicated LUT-cache runs, 58,488,372 dense/compact records in the per-lane append sweep, 122,280,144 in the six counterbalanced subgroup runs, 213,909,504 in the four counterbalanced interval-pair LUT runs, 78,075,696 in the four bounded-capacity compaction runs, 27,430,348 retained/dense records in the capacity sweep, 78,075,696 in the four pre-threshold runs, 103,335,456 in the first four G24 log-LUT runs, 161,725,896 in the six direct-versus-LUT G24 controls, 122,192,592 in the four narrow L2-boundary runs, 290,199,888 in the six cold-lineage runs, and 2,281,701,376 in the four texture/SSBO cache-path controls: **4,413,045,560 checked GPU output records** in the reported aggregates. The Vulkan shader-clock study separately validates 12,582,912 invocation payloads representing 3,221,225,472 dependent SSBO loads. The one-warp CUDA cycle study validates another 153,600 payloads representing 52,428,800 dependent loads. The full-occupancy CUDA concurrency matrix validates 74,678,400 payloads representing 25,490,227,200 dependent loads. The matched CUDA texture/global matrix validates 98,426,880 payloads representing 33,596,375,040 dependent loads. The dense-packing matrix validates 270,673,920 payloads; its 180,449,280 timed lookup payloads represent 92,390,031,360 individually checked decoded codes. The sparse-stride matrix validates 3,336,192 CPU payloads across 1,448 raw rows; 2,224,128 timed endpoints replay 1,138,753,536 links, and the complete kernels execute 366,678,638,592 dependent loads. The line-occupancy matrix validates 2,064,384 CPU payloads across 1,792 raw rows; 1,376,256 timed endpoints replay 704,643,072 code checks, and the complete kernels execute 453,790,138,368 GPU code lookups. The sparse-address matrix validates 1,622,016 CPU payloads across 1,408 raw rows; 1,081,344 endpoints replay 553,648,128 code checks, and the timed kernels execute 356,549,394,432 GPU lookups. The one-code transition refinement adds 165,888 CPU payloads, 56,623,104 CPU checks and 36,465,278,976 GPU lookups across 144 valid rows. Page-span, page-stride and non-power-of-two skew controls add 2,985,984 CPU payloads and 1,019,215,872 replayed code checks across 2,592 valid rows; their timed kernels execute **656,375,021,568 GPU lookups**. Compact validation additionally proves that no non-boundary verified source is missing whenever capacity is sufficient.

At 4,194,304 G32 candidates, direct and both LUT layouts, in evaluate and commit modes, all produced the same 64-bit discrete semantic digest, `1284104115210413112`. The digest covers SDF, guard, topology flags, verified/route state, and lineage while deliberately excluding confidence. Confidence is checked numerically instead: direct G32 maximum absolute error was 0.000262 and both LUT layouts measured 0.000479, inside the declared 0.002 G32 tolerance. Mean absolute errors were 0.000122 and 0.000147 respectively.

The deterministic corpus contains values exactly on `r == radius` and `guard == 0`. NVIDIA and the CPU oracle do not always choose the same side after their different floating-point evaluation paths:

| Profile at N=4,194,304 | CPU/GPU topology divergences | Fraction | Boundary handling |
|---|---:|---:|---|
| G64_E32 | 5,219 | 0.12443% | all inside the explicit `5e-5` predicate-boundary band |
| G32_E16 direct and both LUT layouts | 321 | 0.00765% | all inside the explicit `5e-5` predicate-boundary band |

These are not silently treated as exact agreement. Validation requires exact GPU self-consistency and exact atomic-counter agreement; CPU/GPU topology disagreement is accepted only inside the recorded boundary band. Production semantics that require cross-device bit identity must define fixed-point predicates or explicit hysteresis/interval rules instead of comparing floating-point boundary values directly.

## L2 and texture-buffer findings

The core sweep places declared input-plus-output working sets on both sides of the 36 MiB L2 size:

| Profile / mode | Working set | L2 fraction | Median candidate rate | Change past L2 |
|---|---:|---:|---:|---:|
| G64_E32 evaluate | 36 MiB | 1.00x | 14.047 G/s | - |
| G64_E32 evaluate | 48 MiB | 1.33x | 7.541 G/s | -46.3% |
| G32_E16 evaluate | 36 MiB | 1.00x | 35.708 G/s | - |
| G32_E16 evaluate | 48 MiB | 1.33x | 12.876 G/s | -63.9% |

The G32 value at the exact cache-size boundary showed severe run-to-run variation, including WDDM/power-state outliers, so this is evidence of a capacity transition rather than a measured cache hit rate.

The dedicated cache probe stores two unsigned 16-bit log codes per `R32_UINT` texel and reads them through a Vulkan uniform texel buffer. SPIR-V disassembly confirms `OpTypeImage ... Buffer` and `OpImageFetch`, rather than SSBO loads. Two independent runs produced:

| Access | Packed table | L2 fraction | Median lookup rate | Cross-run range |
|---|---:|---:|---:|---:|
| random | 32 MiB | 0.89x | 41.224 Glookup/s | 41.111-41.336 G/s |
| random | 64 MiB | 1.78x | 7.261 Glookup/s | 7.260-7.263 G/s |
| random | 128 MiB | 3.56x | 6.922 Glookup/s | 6.922-6.922 G/s |
| sequential | 32 MiB | 0.89x | 68.103 Glookup/s | 62.482-73.724 G/s |
| sequential | 64 MiB | 1.78x | 74.407 Glookup/s | 74.399-74.415 G/s |
| sequential | 128 MiB | 3.56x | 75.138 Glookup/s | 75.134-75.141 G/s |

Random lookup throughput falls 82.39% (5.677x slower) from 32 MiB to 64 MiB. Sequential/coalesced access does not suffer that capacity cliff. A packed log LUT is therefore viable when its hot random-access footprint remains below roughly 32 MiB on this 36 MiB-L2 GPU, or when accesses are reordered/coalesced. A larger randomly accessed LUT should be tiled, mip-partitioned, or split into a compact hot index plus colder payload.

For an integrated production kernel, a safer hot-LUT target is about 28 MiB: 14,680,064 codes in 16-bit slots or 39,146,832 measured whole-group 6-bit codes, leaving L2 space for state lines, output writes, descriptors, and other workloads. This is an engineering margin inferred from this device, not a universal cache rule.

The stricter cache-path control uses identical device-local bytes, packed-code math, index hashes and output writes; only the read descriptor/instruction changes between `UNIFORM_TEXEL_BUFFER`/`OpImageFetch` and `STORAGE_BUFFER`/`OpLoad`. Four isolated processes, two in each program order, produced these random-access medians:

| Packed table | L2 fraction | Texture p50 | SSBO p50 | Paired texture/SSBO rate |
|---:|---:|---:|---:|---:|
| 16 MiB | 0.44x | 0.436240 ms | 0.430776 ms | 0.989x |
| 32 MiB | 0.89x | 0.414680 ms | 0.414840 ms | 1.002x |
| 64 MiB | 1.78x | 4.019752 ms | 4.019576 ms | 0.99995x |
| 128 MiB | 3.56x | 9.694880 ms | 9.694648 ms | 0.99998x |

From 32 to 64 MiB, random texture throughput falls 79.368% (4.847x slower) and SSBO throughput falls 79.359% (4.845x slower). The matching latency and cliff show that `texelFetch` does not provide an additional effective capacity tier for this workload. The result is compatible with different front-end paths converging on the same lower cache/memory bottleneck; without counters it does not prove a specific undocumented NVIDIA cache topology. Small/coalesced cases remain clock/order-sensitive, and the texture path does not show a stable advantage there either.

### Device-clock dependent-load sweep

The sharper native probe surrounds 512 strictly dependent `next[index]` SSBO loads with device-scope realtime-clock reads. A zero-step module measures the clock and surrounding instruction overhead. Four sequentially isolated processes use 65,536 invocations per row, two forward and two reverse program/pattern orders:

| Table | L2 fraction | Random net ticks/load | Relative to 36 MiB | Sequential net ticks/load | Random/sequential |
|---:|---:|---:|---:|---:|---:|
| 4 MiB | 0.111x | 1,383.469 | 0.992x | 1,256.000 | 1.101x |
| 32 MiB | 0.889x | 1,393.234 | 0.999x | 1,311.891 | 1.062x |
| 34 MiB | 0.944x | 1,393.656 | 0.999x | 1,305.063 | 1.068x |
| 36 MiB | 1.000x | 1,394.531 | baseline | 1,303.328 | 1.070x |
| 38 MiB | 1.056x | 1,732.516 | 1.242x | 1,319.859 | 1.313x |
| 40 MiB | 1.111x | 2,976.516 | 2.134x | 1,320.781 | 2.254x |
| 48 MiB | 1.333x | 5,230.516 | 3.751x | 1,314.406 | 3.979x |
| 64 MiB | 1.778x | 6,574.063 | 4.714x | 1,347.547 | 4.879x |
| 128 MiB | 3.556x | 8,777.938 | 6.295x | 1,349.828 | 6.503x |

Random-chain time is statistically flat from 4 through 36 MiB, rises at 38 MiB, and becomes sharply miss-dominated by 40 MiB. Sequential-chain time rises only 3.57% between 36 and 128 MiB because adjacent cache lines retain spatial locality. This locates the effective saturated random-working-set boundary much more tightly than the earlier 32/64 MiB throughput sweep and aligns with the independent 36 MiB device-property result.

The absolute unit remains deliberately unnamed: `VK_KHR_shader_clock` specifies an implementation-defined clock, and 65,536 in-flight chains expose warp scheduling as well as memory stalls. These are control-subtracted, scheduler-exposed ticks per dependent load, not raw single-load latency, GPU cycles, or nanoseconds. The retained invocation-count control shows that a single repeated warp rapidly makes its small traversed subset hot even when the allocation is larger than L2; it therefore cannot answer the capacity question by itself.

### CUDA `clock64` L2/global-path control

The independent CUDA kernel addresses the unit ambiguity without pretending to replace the capacity sweep. It compiles natively for `sm_120`, uses one warp, bypasses L1 with `ld.global.cg.u32`, and brackets 512 dependent steps with `clock64()`. A 256 MiB L2 eviction kernel precedes the cold chain; the hot chain immediately repeats the exact links and seed.

The timer and cache-path interpretation follows NVIDIA's [CUDA `clock64()` definition](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/cpp-language-support.html#clock-and-clock64) and [PTX cache-operator specification](https://docs.nvidia.com/cuda/parallel-thread-execution/#cache-operators).

| Table | Post-eviction cycles/step | Immediate-hot cycles/step | Post-eviction/hot |
|---:|---:|---:|---:|
| 4 MiB | 1,078.912 | 399.856 | 2.698x |
| 16 MiB | 1,087.917 | 399.741 | 2.721x |
| 32 MiB | 1,088.028 | 399.523 | 2.723x |
| 36 MiB | 1,086.832 | 399.575 | 2.721x |
| 38 MiB | 1,087.941 | 399.415 | 2.724x |
| 40 MiB | 1,087.654 | 399.560 | 2.722x |
| 64 MiB | 1,087.661 | 399.562 | 2.722x |
| 128 MiB | 1,089.004 | 399.577 | 2.725x |

The median of table-size medians is 1,087.789 post-eviction cycles and 399.569 hot cycles per dependent step, a 2.722x ratio and approximately 688 exposed cycles of additional cost. Cross-size hot medians span only 399.415-399.856 cycles; post-eviction medians span 1,078.912-1,089.004. The immediate repeated footprint is deliberately small enough to fit in L2 at every allocation size, explaining why these values do not show the 36-40 MiB capacity cliff.

CUDA-event timing for the complete one-warp kernels gives 153.414 ns per hot step and 401.820 ns per post-eviction step at the median of sizes. These human-time conversions include kernel prologue, result stores, and scheduling; the control-subtracted `clock64()` values are the in-loop cycle metric.

This is a stronger latency control than the Vulkan clock because NVIDIA defines `clock64()` in cycles, but its boundary remains explicit: a warp step may generate up to 32 random sector requests, and elapsed thread time includes scheduling. It is not one scalar cache transaction's latency. The `ld.global.cg` cache operator is also a performance hint, although native SASS confirms `LDG.E.STRONG.GPU` in both the chase and 256 MiB eviction loops.

The CUDA state-forced costs remain flat while the saturated Vulkan chain rises beyond 36 MiB. This is mutually consistent: table size changes the share and concurrency of lower-memory service, not the intrinsic hot/cold step costs. It also rules out a naive two-latency hit-rate inversion. The saturated Vulkan 128/36 MiB ratio is 6.295x, greater than the CUDA post-eviction/hot ratio of 2.722x, so memory queuing and warp scheduling must contribute materially to the saturated result.

### CUDA warp-concurrency and MLP sweep

The second CUDA probe keeps every lane's 512 loads strictly dependent but increases the number of independent one-warp blocks. It tests 1-1,104 total warps over 4, 36, 40, 64 and 128 MiB allocations. A CUDA occupancy query reports that this 16-register, zero-spill kernel can host at most 24 one-warp blocks per SM; the measurement reaches that exact ceiling. Four isolated processes reverse both dimensions, and all 240 rows validate every returned endpoint through an independent CPU affine transform.

| Table | Hot Gload/s at 1 warp | Hot Gload/s at 46 warps | Hot Gload/s at 184 warps | Hot Gload/s at 1,104 warps | Full-occupancy exposed cycles/step | Full-occupancy hot slowdown vs 4 MiB |
|---:|---:|---:|---:|---:|---:|---:|
| 4 MiB | 0.208 | 9.582 | 36.472 | 43.216 | 2,214.9 | baseline |
| 36 MiB | 0.208 | 8.291 | 23.564 | 43.215 | 2,212.2 | 1.000x |
| 40 MiB | 0.208 | 3.948 | 13.826 | 23.683 | 4,060.7 | 1.825x |
| 64 MiB | 0.208 | 3.842 | 8.209 | 9.357 | 10,428.3 | 4.618x |
| 128 MiB | 0.208 | 3.499 | 6.963 | 7.524 | 12,984.4 | 5.744x |

At one warp every hot allocation reports about 400 cycles/step because the repeated path's logical footprint is only about 64 KiB. Increasing independent warps expands coverage and exposes the full allocation: 36 MiB still reaches the 4 MiB saturation rate, but 40 MiB loses 45.20%, 64 MiB loses 78.35%, and 128 MiB loses 82.59%. The result directly joins the two earlier controls: capacity changes service mix, while concurrency turns that mix into queueing and scheduler delay.

At 1,104 warps the 4 and 36 MiB requested-load rates are about 43.22 billion `u32` loads/s, or 161.0 logical GiB/s. The word "logical" is essential: a random warp instruction can generate many larger cache-sector transactions, so this is neither physical L2 bandwidth nor DRAM bandwidth. Exact sector/DRAM counters remain unavailable. Compute Sanitizer reports zero errors on the instrumented control, whose timings are excluded.

### CUDA native texture-object path control

The matched CUDA control binds the same `cudaMalloc` allocation both as a raw global pointer and as a one-dimensional linear texture object. The address chain, 512 strictly dependent loads per lane, launch shape, validation transform, table bytes and cache-eviction work are otherwise matched. Native `sm_120` SASS distinguishes the paths: the global chase contains `LDG.E.STRONG.GPU`, while the texture chase contains `TLD.LZ ..., 1D`. Both use 16 registers, no stack, no spills, and reach the queried ceiling of 24 one-warp blocks per SM. Four isolated processes balance path order 2/2 and reverse table and warp orders 2/2; all 256 raw rows validate.

| Table | Global hot Gload/s at 1,104 warps | Texture hot Gload/s at 1,104 warps | Texture/global rate | Global drop vs 36 MiB | Texture drop vs 36 MiB |
|---:|---:|---:|---:|---:|---:|
| 4 MiB | 43.220 | 43.430 | 1.0049x | - | - |
| 32 MiB | 43.312 | 43.231 | 0.9982x | - | - |
| 36 MiB | 43.220 | 43.209 | 0.9998x | baseline | baseline |
| 38 MiB | 39.526 | 39.362 | 0.9959x | 8.55% | 8.90% |
| 40 MiB | 23.702 | 23.658 | 0.9985x | 45.16% | 45.25% |
| 48 MiB | 12.649 | 12.646 | 0.9998x | 70.73% | 70.73% |
| 64 MiB | 9.352 | 9.353 | 1.0000x | 78.36% | 78.35% |
| 128 MiB | 7.527 | 7.521 | 0.9992x | 82.59% | 82.59% |

At full occupancy the median texture/global hot-rate ratio across the eight sizes is 0.99949x. The two native instruction paths therefore have the same practical residency boundary and lower-memory saturation curve for this random dependent LUT. Texture fetch is not a second effective-capacity tier: it is 13.65% slower at one warp, 7.39% slower at one warp per SM, 5.26% slower at four warps per SM, and converges only at 24 warps per SM as the shared lower bottleneck dominates. This rejects an extra texture-cache capacity benefit for this access pattern; it does not claim that all texture workloads share the same behavior.

### CUDA native dense 6-bit log-code packing

The packing control compares the current two-16-bit-slots-per-word representation (2 bytes/code) with sixteen 6-bit codes in exactly three words (0.75 bytes/code). Every lane makes 512 pseudorandom lookups over the same logical code indices. Every returned code is checked inside the timed kernel against `index mod 64`, and the CPU independently validates the final index-generator state. Four isolated Latin-order processes cover `LDG`/`TLD` and slot16/packed6 without changing logical work. All four kernels reach 24 one-warp blocks per SM, use 14-21 registers, and have no stack or spills. SASS contains one slot load and an additional predicated packed load for the 2/16 code offsets that straddle words.

| Capacity point | slot16 codes / bytes | packed6 codes / bytes | Global slot16 | Global packed6 | Texture slot16 | Texture packed6 |
|---|---:|---:|---:|---:|---:|---:|
| Small control | 2,097,152 / 4 MiB | 2,097,152 / 1.5 MiB | 43.231 | 38.321 | 43.432 | 43.212 |
| Conservative budget | 14,680,064 / 28 MiB | 39,146,832 / 28 MiB - 4 B | 43.398 | 38.505 | 43.397 | 42.804 |
| Nominal L2 ceiling | 18,874,368 / 36 MiB | 50,331,648 / 36 MiB | 43.219 | 38.492 | 43.192 | 42.594 |
| Post-L2 endpoint | 20,971,520 / 40 MiB | 55,924,048 / 40 MiB - 4 B | 23.539 | 23.466 | 23.531 | 23.406 |

Rates are full-occupancy hot Glookup/s at each representation's stated physical endpoint. Dense packing realizes exactly 2.667x as many codes at 36 MiB while the native texture path preserves 98.61% of slot16 throughput. At 28 MiB it stores 2.667x as many whole-group codes and preserves 98.63%. From 36 to 40 MiB, slot16 loses 45.54%/45.52% on global/texture and packed6 loses 39.04%/45.05%. The cleaner texture-packed result reproduces the same cache boundary.

For 50,331,648 logical codes, slot16 requires 96 MiB and reaches only 7.970/7.968 Glookup/s on global/texture. Packed6 requires 36 MiB and reaches 38.492/42.594, or 4.829x/5.346x the equal-capacity slot rate. This is a residency gain, not a free decoder: when both representations are tiny, packed extraction costs 2-6% at low/mid concurrency, while saturated global packed remains 11.36% below global slot. Texture packed is within 0.48% of texture slot at saturated small-table occupancy and is 1.107x faster than global packed at 36 MiB. The earlier byte-identical chase proves that this packed texture advantage is instruction-schedule-specific, not extra texture-cache capacity.

### CUDA sparse-stride effective-residency bound

The dense-packing ceiling assumes useful neighboring codes occupy fetched cache regions. To measure the opposite locality extreme, the stride control stores one consumed `u32` pointer every 4-256 bytes, fills all unused words with deterministic mixed data, and follows a nonlinear cycle-walked permutation. Every lane performs 512 dependent `ld.global.cg.u32` loads; the CPU independently replays every link for the first 64 lanes per sample. Four primary and four supplemental order-balanced processes cover the capacity knees at 184 and 1,104 warps.

| Spacing | Target point | Active nodes | Physical allocation | Hot rate at 1,104 warps |
|---:|---:|---:|---:|---:|
| 32 B | 36 MiB | 1,179,648 | 36 MiB | 42.990 Gload/s |
| 64 B | 18 MiB | 589,824 | 36 MiB | 42.982 Gload/s |
| 128 B | 9 MiB | 294,912 | 36 MiB | 43.004 Gload/s |
| 256 B | 9 MiB | 294,912 | 72 MiB | 42.985 Gload/s |

The active-node plateau scales exactly 4:2:1 for 32/64/128-byte spacing. Doubling spacing again to 256 bytes doubles allocation but leaves the pre-cliff rate curve essentially unchanged: its paired 256/128 ratio is 0.9995x at the 294,912-node anchor. After the cliff it remains within roughly 3-4%, rather than suffering the 2x capacity shift that a 256-byte unit would predict. Conversely, a 64-byte unit is too small: 589,824 nodes at 128-byte spacing would model 36 MiB, yet deliver only 14.176 Gload/s, 0.3296x the 294,912-node anchor.

This bounds isolated-word effective residency above 64 and at or below 128 bytes among the tested powers of two: **consistent with 128 bytes on this workload**. It is not a declaration of NVIDIA's physical line, sector, associativity or transaction format. The practical capacity implication is large:

| Useful organization | Effective storage/useful entry | 36 MiB entries | 28 MiB entries |
|---|---:|---:|---:|
| Dense packed6 | 0.75 B average | 50,331,648 | 39,146,837 arithmetic |
| Dense slot16 | 2 B | 18,874,368 | 14,680,064 |
| One isolated random word/region | 128 B effective | 294,912 | 229,376 |

Dense packed6 therefore spans 170.667x more useful codes than the dependent-pointer endpoint at the same nominal cache budget. That ratio is a contrast between two measured workloads, not a universal LUT compression factor. The next control maps intermediate independent-lookup behavior and shows why.

### CUDA packed-LUT line occupancy

The intermediate control allocates aligned 128-byte regions, fills every unused word with deterministic mixed data, and packs `K` useful 6-bit codes at the front of each region. Each lane independently selects a pseudorandom region and a uniformly random useful slot. This retains the exact packed decoder while separating physical allocation, useful-code density, 32-byte address-region demand, and dependency structure.

Four primary and four boundary-refinement processes balance ascending/descending table order and global/texture path order. They cover 28, 32, 36, 37, 38, 39, 40 and 48 MiB, 184 and 1,104 warps, and `K = 1, 2, 4, 8, 16, 32, 42, 43, 64, 85, 86, 128, 129, 170`. All 1,792 raw rows validate. The table gives full-occupancy texture medians:

| K / 128 B | Bytes/useful code | Exact 32-byte touch probabilities | 36 MiB | 40 MiB | 48 MiB |
|---:|---:|---|---:|---:|---:|
| 1 | 128.000 | 100% | 43.010 G/s | 42.800 G/s | 28.104 G/s |
| 42 | 3.0476 | 100% | 43.009 G/s | 42.599 G/s | 28.093 G/s |
| 43 | 2.9767 | 100% + 2.33% | 42.491 G/s | 41.978 G/s | 26.491 G/s |
| 64 | 2.0000 | 67.19% + 34.38% | 42.590 G/s | 37.848 G/s | 18.385 G/s |
| 85 | 1.5059 | 50.59% + 50.59% | 42.677 G/s | 37.366 G/s | 17.900 G/s |
| 86 | 1.4884 | 50.00% + 51.16% + 1.16% | 42.437 G/s | 36.139 G/s | 17.583 G/s |
| 128 | 1.0000 | 33.59% + 34.38% + 33.59% | 42.591 G/s | 28.645 G/s | 14.399 G/s |
| 129 | 0.9922 | 33.33% + 34.11% + 33.33% + 0.78% | 42.588 G/s | 27.939 G/s | 14.237 G/s |
| 170 | 0.7529 | 25.29% + 25.88% + 25.29% + 24.71% | 42.592 G/s | 23.514 G/s | 12.628 G/s |

The percentages may sum slightly above 100% because slots 42 and 85 straddle a 32-byte boundary and request both neighboring regions. These are exact requested-address calculations, not measured NVIDIA cache sectors. Codes 43, 86 and 129 introduce a new address region on only 2.33%, 1.16% and 0.78% of lookups. Their 40 MiB slowdowns versus 42, 85 and 128 codes are only 1.46%, 3.28% and 2.47%; demand changes smoothly with access probability.

The strongest result is the correction it forces. With one useful code in each 128-byte region, the 40 MiB allocation retains 99.02% of the 28 MiB texture rate. A fixed 128-byte-per-code throughput model therefore fails for this independent random lookup. At 48 MiB the same layout retains only 65.02%, despite requesting just one 32-byte part per region, so requested bytes alone fail too. This observation does not erase the containing-line effect; the controlled stride decomposition below measures both effects separately.

The block-aligned dense endpoint stores 170 codes in 128 bytes: 0.752941 byte/code and 99.609% bit utilization. It holds 50,135,040 useful codes in 36 MiB, 196,608 fewer than a boundary-free continuous 6-bit stream. Thus the exact theoretical encoding floor, practical block ceiling, and measured cache behavior remain separate quantities.

### CUDA sparse-LUT data, line-address, and span decomposition

The control places one useful packed6 code in each region's first word, fills all gaps with mixed nonzero data, independently selects regions with an LCG, and runs matched global and texture paths. Its target unit is a requested 32-byte portion rather than physical allocation. Four primary and four supplemental processes balance both table direction and path order; 1,408 raw rows and 352 aggregate cases validate.

At 40 MiB physical allocation, the 32-, 64- and 128-byte strides have exactly the same 327,680 containing aligned 128-byte lines but request four, two and one 32-byte portions per line:

| Stride | Requested data | Lines | Allocation | Texture rate |
|---:|---:|---:|---:|---:|
| 32 B | 40 MiB | 327,680 | 40 MiB | 23.343 Glookup/s |
| 64 B | 20 MiB | 327,680 | 40 MiB | 38.505 Glookup/s |
| 128 B | 10 MiB | 327,680 | 40 MiB | 42.802 Glookup/s |

This rejects allocation or line count as a sufficient single-variable model. At a fixed 12 MiB requested data span, the converse matrix rejects requested bytes as sufficient:

| Stride | Requested data | Lines | Allocation | Texture rate |
|---:|---:|---:|---:|---:|
| 32 B | 12 MiB | 98,304 | 12 MiB | 43.214 Glookup/s |
| 64 B | 12 MiB | 196,608 | 24 MiB | 43.207 Glookup/s |
| 128 B | 12 MiB | 393,216 | 48 MiB | 28.119 Glookup/s |
| 256 B | 12 MiB | 393,216 | 96 MiB | 24.783 Glookup/s |

The one-sector-per-line 128-byte-stride curve is 43.008 Glookup/s at 9 MiB requested/36 MiB allocation, 42.802 at 10/40, 38.337 at 11/44 and 28.119 at 12/48. The separate exact-`K=1` refinement tightens the containing-line-address transition: texture throughput is 41.785 Glookup/s at 43 MiB line-equivalent allocation (352,256 lines) and 38.330 at 44 MiB (360,448 lines). This is a broad transition, not an exact hard capacity.

Strides 128 and 256 have equal requested data and line count but the latter doubles address span. Their paired texture-rate ratios are 0.990, 0.945, 0.804 and 0.881 at 9-12 MiB requested; the all-target median is 0.976. The strongest extra penalty occurs near the transition. Thus **resident requested data + containing-line-address pressure + address span** is the smallest model supported by all controls. It is timing evidence consistent with sub-line residency inside a wider line-address grouping, not a counter-derived statement of NVIDIA sector size, tag capacity, associativity, set mapping, memory partitioning or TLB reach.

### CUDA page-spaced reach and exact-stride aliasing

The same one-code kernel now accepts 32-byte-multiple strides through 4 KiB. Every gap remains allocated and filled with mixed data. For any target, all strides at or above 128 bytes retain identical useful codes, requested words and containing 128-byte test-line count; only address span changes. Four primary page-stride runs, four intermediate-span runs and four non-power-of-two skew runs are independently order balanced.

At exact 4-KiB spacing:

| Useful words | Allocation/address span | Global | Texture |
|---:|---:|---:|---:|
| 32,768 | 128 MiB | 42.590 Glookup/s | 41.784 Glookup/s |
| 65,536 | 256 MiB | 34.315 Glookup/s | 34.451 Glookup/s |
| 98,304 | 384 MiB | 21.470 Glookup/s | 21.506 Glookup/s |
| 131,072 | 512 MiB | 18.424 Glookup/s | 18.462 Glookup/s |
| 262,144 | 1,024 MiB | 15.166 Glookup/s | 15.139 Glookup/s |

At 65,536 useful words the distinct requested `u32` data is only 256 KiB and the containing-line model is 8 MiB, well below their L2 transitions. A fine non-power-of-two bracket fixes 131,072 useful words and gives:

| Stride | Span | Global | Texture |
|---:|---:|---:|---:|
| 2,016 B | 252 MiB | 42.178 Glookup/s | 42.194 Glookup/s |
| 2,048 B | 256 MiB | 34.318 Glookup/s | 34.454 Glookup/s |
| 2,080 B | 260 MiB | 32.546 Glookup/s | 32.778 Glookup/s |

This bounds a general full-rate address-span transition between 252 and 256 MiB. Both paths agree and the padded 2,080-byte case remains slow, so this component is not solely exact-power-of-two aliasing.

The second component is path-specific. At target 7 MiB, global rates remain 42.792/42.792/42.807 Glookup/s for 992/1,024/1,056-byte pitch, while texture gives 42.802/28.621/43.007. At target 8 MiB, texture gives 42.805/26.494/42.775 at 480/512/544-byte pitch. A one-region ±32-byte skew fully removes the 512-byte loss and removes the 1,024-byte loss below the general span knee. This is address-index alias evidence; counters are unavailable, so no set, bank or partition mapping is asserted.

The CUDA driver reports VMM support, generic-compression capability and 2 MiB minimum/recommended pinned device-local VMM allocation granularity. The preceding page-spaced benchmarks use `cudaMalloc`, so that queried granularity is not their established page size or a TLB-entry denominator. Explicit compressible VMM allocations are isolated separately below.

### CUDA VMM constant-physical-backing control

The VMM control creates one 2 MiB device-local allocation, then maps that same handle into every 2 MiB virtual slot. Each lookup selects a tested alias and a random word inside the shared physical object. Global and texture paths, plus both warp loads, use the same mapping per case. All four primary processes received base `0x204C00000`.

| Aliases | Virtual span | Physical bytes | Global at 1,104 warps | Texture at 1,104 warps |
|---:|---:|---:|---:|---:|
| 32 | 64 MiB | 2 MiB | 42.976 Glookup/s | 42.879 Glookup/s |
| 64 | 128 MiB | 2 MiB | 42.979 Glookup/s | 42.863 Glookup/s |
| 96 | 192 MiB | 2 MiB | 42.973 Glookup/s | 42.870 Glookup/s |
| 120 | 240 MiB | 2 MiB | 42.975 Glookup/s | 42.838 Glookup/s |
| 124 | 248 MiB | 2 MiB | 39.523 Glookup/s | 39.539 Glookup/s |
| 126 | 252 MiB | 2 MiB | 35.663 Glookup/s | 35.687 Glookup/s |
| 127 | 254 MiB | 2 MiB | 34.842 Glookup/s | 34.879 Glookup/s |
| 128 | 256 MiB | 2 MiB | 34.439 Glookup/s | 34.456 Glookup/s |
| 132 | 264 MiB | 2 MiB | 31.942 Glookup/s | 31.943 Glookup/s |
| 160 | 320 MiB | 2 MiB | 24.901 Glookup/s | 24.913 Glookup/s |
| 192 | 384 MiB | 2 MiB | 21.568 Glookup/s | 21.565 Glookup/s |

From 240 to 248 MiB, global throughput loses 8.0%; by 252 and 256 MiB it loses 17.0% and 19.9%. This occurs with a physical payload one eighteenth of L2. At fixed 32 aliases, increasing pitch extends virtual span from 64 to 250 MiB and lowers global throughput from 42.976 to 33.717 Glookup/s. At fixed 64 aliases, 128 to 254 MiB lowers it from 42.979 to 34.561. The close 250-256 MiB rates across different alias/pitch combinations identify span as the leading term while leaving alias count and address-bit layout as secondary terms.

The paired texture/global ratio remains within about 0.5% across the high-occupancy span sweep. Texture binding therefore neither bypasses nor adds a separate penalty to the general reach boundary. This is distinct from the exact 512/1,024-byte texture-only alias in the ordinary allocation experiment.

All 368 VMM rows validate across four order-balanced processes. The CPU replays 353,280 payloads; all 227,512,320 complete GPU payloads have zero code mismatches; timed cold/hot kernels execute 77,657,538,560 lookups. SASS contains one native `LDG.E.STRONG.GPU` or `TLD.LZ` in each 18-register timed loop with no stack/local memory or spills. Compute Sanitizer reports zero errors through a 510 MiB paired mapping. The full protocol and hashes are in `benchmarks/cuda_vmm_alias_isolated/PROTOCOL.md`.

### CUDA VMM generic-compression packed-LUT control

The allocation probe establishes the exact driver state before timing: non-compressible request 0 returns effective 0; generic request 1 returns effective 1. Both 2 MiB handles create, map, accept a complete fill and verify their first/last words. The effective property proves that the driver granted the hint, but exposes no achieved compression ratio or compressed-byte counter.

The performance control uses identical dense packed6 decoding for zero, 48-byte-periodic and entropy-dense code streams. A follow-on global-only control adds all-one words (`ones6`, every logical code 63). Both allocation modes coexist and alternate on every sample with the same random code indices. At 1,104 warps, median generic/non ratios across 4-128 MiB are:

| Pattern | Global ratio | Texture ratio | Result |
|---|---:|---:|---|
| Periodic packed6 | 0.99999x | 1.00001x | No capacity benefit |
| Entropy-dense packed6 | 1.00003x | 1.00005x | No capacity benefit |

Both information-bearing patterns retain the same 36-40 MiB cliff. The generic property is therefore not a substitute for the exact 2.667x software packing, and a repeating log-code sequence cannot be assumed hardware-compressible without measuring its real distribution.

The zero-entropy global control measures the positive bound:

| Allocation | Packed-code capacity | Non-compressible | Generic compressible |
|---:|---:|---:|---:|
| 36 MiB | 50,331,648 | 38.498 Glookup/s | 38.645 Glookup/s |
| 40 MiB | 55,924,048 | 20.092 Glookup/s | 38.591 Glookup/s |
| 64 MiB | 89,478,480 | 8.691 Glookup/s | 38.525 Glookup/s |
| 128 MiB | 178,956,960 | 7.006 Glookup/s | 38.507 Glookup/s |
| 192 MiB | 268,435,456 | 7.125 Glookup/s | 38.593 Glookup/s |
| 240 MiB | 335,544,320 | 7.005 Glookup/s | 38.650 Glookup/s |
| 248 MiB | 346,729,120 | 6.990 Glookup/s | 28.823 Glookup/s |
| 256 MiB | 357,913,936 | 6.976 Glookup/s | 28.196 Glookup/s |
| 320 MiB | 447,392,416 | 6.887 Glookup/s | 4.748 Glookup/s |
| 512 MiB | 715,827,872 | 6.770 Glookup/s | 1.386 Glookup/s |

The all-one global control independently reproduces the constant-content boundary:

| Allocation | Non-compressible | Generic compressible | Paired ratio |
|---:|---:|---:|---:|
| 36 MiB | 38.492 Glookup/s | 38.652 Glookup/s | 1.003x |
| 40 MiB | 23.492 Glookup/s | 38.603 Glookup/s | 1.641x |
| 64 MiB | 9.312 Glookup/s | 38.635 Glookup/s | 4.149x |
| 128 MiB | 7.482 Glookup/s | 38.645 Glookup/s | 5.165x |
| 192 MiB | 7.126 Glookup/s | 38.651 Glookup/s | 5.424x |
| 240 MiB | 7.004 Glookup/s | 38.611 Glookup/s | 5.512x |
| 248 MiB | 6.991 Glookup/s | 28.834 Glookup/s | 4.125x |
| 320 MiB | 6.891 Glookup/s | 5.961 Glookup/s | 0.865x |

Full rate through 240 MiB gives a **6.667x throughput-equivalent allocation-capacity lower bound** for constant content, not a 6.667x measured physical byte ratio. Zero and repeated code-63 tables both carry no useful information and represent a supported constant-pattern upper control. The 248 MiB loss is consistent with the independently measured virtual-reach transition; at 320 MiB compression becomes counterproductive. Data compression and address reach are separate limits.

The all-zero texture curve is now semantically rejected. A fine 174-210 MiB sweep found an exact three-MiB rate rhythm, and trimming one 12-byte group collapsed the high regime by up to 19.2x. However, an all-one control gives zero valid timed texture payloads while all-one global and periodic/entropy texture paths validate. Explicit mismatch totals find 35,893,872 wrong codes out of 36,175,872 checks at 4 MiB and 22,609,920 out of 36,175,872 at 192 MiB. The zero checker can accept an incorrect zero return, so none of the fast zero-texture rates are capacity or throughput evidence. Periodic and entropy texture rows remain valid and show no compression gain.

### Sparse information-bearing VMM-compression map

A follow-on exact-binary study fills the gap between dense information-bearing patterns and zero-information constants. Pattern `sparse1_K` stores code 1 at every `K`th logical packed6 position and code 0 elsewhere. At 1,104 warps, the highest allocation retaining at least 99% of each pattern's best median generic-compressible global rate is:

| Interval K | Nonzero-code share | Packed spacing | Last full-rate allocation |
|---:|---:|---:|---:|
| 64 | 1.562500% | 48 bytes | 64 MiB |
| 128 | 0.781250% | 96 bytes | 64 MiB |
| 256 | 0.390625% | 192 bytes | 64 MiB |
| 512 | 0.195313% | 384 bytes | 128 MiB |
| 544 | 0.183824% | 408 bytes | 160 MiB |
| 576 | 0.173611% | 432 bytes | 192 MiB |
| 608/640 | 0.164474/0.156250% | 456/480 bytes | 208 MiB |
| 672/704 | 0.148810/0.142045% | 504/528 bytes | 224 MiB |
| 736-4,096 | 0.135870-0.024414% | 552-3,072 bytes | 240 MiB tested ceiling |

The six non-power-of-two 544-704 cases place 411,207-478,298 code-1 exceptions at the last full-rate point, median 460,208.5. This is an observed boundary for the exact packed layout, not a physical compressor capacity. Constant logical code 1 and deterministic mixed binary codes retain generic/non-compressible ratios near 1.000x and gain no capacity, demonstrating that low alphabet size alone is not sufficient.

The >=736 rows become address-reach limited: all fall at 248 MiB, while the independent VMM-alias control already proves that the 240-248 MiB loss survives with only 2 MiB physical backing. Sparse compression capacity beyond 240 MiB is therefore unresolved on this device.

The frozen `sm_120` executable has SHA-256 `E4F685BB73046A4B4D4F79D634CDB211698FF9E2A2C13AA74CDAEED6884AA194`. Twelve exact-binary forward/reverse processes contribute 1,872 valid rows, 1,984,020,480 validated payloads and 677,212,323,840 timed GPU lookups with zero mismatches. The protocol and frozen executable are under `benchmarks/cuda_vmm_sparse_exact/`; the machine-readable threshold table is under `benchmarks/cuda_vmm_compression_sparse_summary/`.

### Current G24 externalized threshold-code control

The G24 benchmark producer fixes `confidence_floor = 0.70`. Binary16 rounding yields 0.7001953125, the declared log-distance quantizer yields code 8, and sixteen externalized packed codes become `0x08208208 0x82082082 0x20820820`. This pattern contains sixteen set bits per 96-bit group, the same count as packed code 1 but a different phase. It is not equivalent to the all-one code-63 control, which produces three `0xFFFFFFFF` words.

Four order-balanced processes cover sixteen 4-248 MiB sizes, 1,104 warps, both native paths and both VMM allocation properties. All 256 rows validate; 271,319,040 payloads and 92,610,232,320 timed lookups have zero decoded mismatches. The paired generic/non-compressible hot-rate median across all 32 size/path cases is 0.999993x, with a 0.994175-1.012212x range. The 99%-of-best endpoint is 36 MiB / 50,331,648 codes for both properties on both paths. From 36 to 40 MiB, global loses 38.53% without compression and 38.96% with it; texture loses 44.69% and 45.05%. Generic texture's 1.0122x effect at transitional 38 MiB does not move the full-rate endpoint and disappears at 40 MiB.

Some absolute per-size rows have up to 60.28% repetition range because of laptop clock/performance-state changes. The compression result uses within-sample alternating allocation modes, and every paired median remains within 2% of unity. Frozen source/executable hashes, exact SASS/resource facts, machine-readable summary and this limitation are in `benchmarks/cuda_vmm_g24_code8_isolated/PROTOCOL.md`.

### Exhaustive uniform-code physical-word map

The parameterized global control enumerates every logical value 0-63. A repeated 6-bit motif advances two positions at each 32-bit boundary, so the three packed words are identical only for code 0 (`0x00000000`), 21 (`0x55555555`), 42 (`0xAAAAAAAA`) and 63 (`0xFFFFFFFF`). The other 60 codes produce three distinct words.

The all-code screen measures every code at 36, 40, 64, 128, 240 and 248 MiB. Codes 0/63 retain 99% of best through 240 MiB; codes 21/42 reach 64 MiB in the screen; all other codes end at 36 MiB. A second 2 MiB-step refinement places both 21/42 balanced-median endpoints at 70 MiB, with first sub-99% results at 72 MiB. Forward/reverse behavior diverges through this transition, so 70-72 MiB is a direction-sensitive workload boundary rather than a physical compressor-capacity measurement.

The codes producing identical words exactly equal the codes extending beyond nominal L2. This is a complete correlation across the 64-value domain, but word value still changes the magnitude: zero/all-one reaches the independent 240 MiB address ceiling, alternating-bit words reach 70 MiB, and three-word patterns gain nothing. Eight processes validate all 3,616 rows, 3,832,381,440 payloads and 1,308,119,531,520 timed global lookups.

The parameterized uniform texture path is rejected rather than timed: codes 1, 8 and 63 produce 24 invalid rows and 424,112,712 decoded mismatches, while eight zero-code rows falsely validate. Timed constant-branch `TLD.LZ` targets `RZ` in SASS. The frozen evidence and full per-code map are under `benchmarks/cuda_vmm_uniform6_exact/`; the invalid sentinel corpus is under `benchmarks/cuda_vmm_uniform6_texture_rejection/`.

### Balanced code-0/code-63 spatial mixtures

The next raw-global control stores both proven highly compressible extremes in one dense table. Every 12-byte group contains sixteen code-0 values and therefore three `0x00000000` words, or sixteen code-63 values and therefore three `0xFFFFFFFF` words. The sequences are approximately balanced. One family chooses the symbol pseudorandomly for each group; the other alternates after 1-1,024 groups, spanning 12-12,288 bytes or 16-16,384 logical codes per run.

Four order-balanced screen processes cover all twelve patterns at thirteen 36-248 MiB allocations. Four more refine hash and 1-16-group runs every 2 MiB from 64 through 96 MiB. All 2,064 rows validate with zero decoded mismatches, covering 2,187,509,760 payloads and 746,669,998,080 timed lookups.

| Spatial organization | 99%-rate endpoint | First below | Logical codes at endpoint |
|---|---:|---:|---:|
| Hashed per 12-byte group | 72 MiB | 74 MiB | 100,663,296 |
| Alternating 12-96-byte runs | 72 MiB | 74 MiB | 100,663,296 |
| Alternating 192-byte runs | 88 MiB | 90 MiB | 123,032,912 |
| Alternating 384-12,288-byte runs | 240 MiB address-limited | 248 MiB | 335,544,320 |

At the first failing point, hashed selection retains 92.91% of best, the short runs retain 74.91-86.89%, the 192-byte run retains 96.87%, and all six 384-byte-or-longer cases retain 74.72-74.76% at the independently proven address-reach transition. Thus the benefit is not restricted to a uniform zero-information allocation, but organization remains decisive. The first tested span reaching 240 MiB is 384 bytes; intermediate 193-383-byte spans and arbitrary symbol sequences remain unmeasured, so this is not an internal compressor-block claim. Frozen source, executable, map, provenance and exact limitations are under `benchmarks/cuda_vmm_blockmix063_exact/`.

### Balanced code-0/21/42/63 spatial mixtures

The four-symbol control chooses among the complete set of uniform packed6 values that individually extend beyond 36 MiB. A 12-byte group holds sixteen copies of one code and becomes three repeated `0x00000000`, `0x55555555`, `0xAAAAAAAA` or `0xFFFFFFFF` words. Cyclic patterns hold each symbol for 1-1,024 groups (12-12,288 bytes); a hashed pattern derives an approximately uniform four-way choice per group. The timed kernel independently recomputes every expected logical code.

Four screen, four short-refinement, four long-refinement and four `g64`-extension processes use balanced order and within-corpus normalization. All **3,560 rows**, **3,773,030,400 validated payloads** and **1,287,861,043,200 timed lookups** pass with zero decoded mismatches.

| Pattern | Symbol-run bytes | 99%-rate endpoint | First below | Allocation / nominal L2 |
|---|---:|---:|---:|---:|
| `g1` | 12 | 40 MiB | 42 MiB | 1.111x |
| hash | n/a | 52 MiB | 54 MiB | 1.444x |
| `g2` | 24 | 60 MiB | 62 MiB | 1.667x |
| `g4` | 48 | 70 MiB | 72 MiB | 1.944x |
| `g8` | 96 | 72 MiB | 74 MiB | 2.000x |
| `g16` | 192 | 82 MiB | 84 MiB | 2.278x |
| `g32` | 384 | 120 MiB | 124 MiB | 3.333x |
| `g64` | 768 | 168 MiB | 172 MiB | 4.667x |
| `g128` | 1,536 | 140 MiB | 144 MiB | 3.889x |
| `g256` | 3,072 | 148 MiB | 152 MiB | 4.111x |
| `g512` | 6,144 | 120 MiB | 124 MiB | 3.333x |
| `g1024` | 12,288 | 124 MiB | 128 MiB | 3.444x |

The long-run ordering is strongly non-monotonic, so the result does not support “longer run means more effective cache.” Packed word values, cycle length, address distribution and undocumented hardware behavior remain entangled. Several transition points are also close to the declared 99% threshold. The 168 MiB result is a throughput-equivalent allocation bound, not measured physical compressed bytes. Frozen source, executable, sixteen raw hashes, map, provenance and exact limitations are under `benchmarks/cuda_vmm_blockmix4_exact/`.

Native `sm_120` SASS retains one unconditional and one predicated straddle load per active packed decode through `LDG.E.STRONG.GPU` or `TLD.LZ`; the frozen sparse binary uses 22/19 global/texture registers, the later code-8 binary uses 22/18, the uniform global binary uses 23, the two-symbol block-mixture global binary uses 25 and the four-symbol binary uses 26. All retained kernels have no stack/local memory/spills and reach 24 blocks/SM. The original primary/zero-span checker accepts **830,914,560 payloads** across **1,184 rows** and times **283,618,836,480 lookups**, but its zero-texture subset is superseded by the nonzero semantic control. The all-one global corpus adds **96 fully valid rows**, **101,744,640 validated payloads** and **34,728,837,120 timed lookups**; the code-8 corpus adds **256 fully valid rows**, **271,319,040 validated payloads** and **92,610,232,320 timed lookups**; the uniform map adds 3,616 rows and 1.308 trillion lookups; the two-symbol mixture adds 2,064 rows and 746.670 billion lookups; the four-symbol mixture adds 3,560 rows and 1.288 trillion lookups. Compute Sanitizer reports zero errors for all-one global mappings at 40, 240 and 320 MiB, the code-8 global/texture smoke, parameterized uniform codes 0/1/8/63 on global, nonzero two-symbol `g1`/hashed sentinels and four-symbol hashed/`g32` sentinels; instrumented timings are excluded. Full protocols are in the correspondingly named VMM benchmark directories.

## Integrated direct-versus-LUT result

The following ratios are paired inside each process before taking the median. Positive delta means LUT faster; negative means LUT slower.

| Mode | State + event set | L2 fraction | Direct p50 | LUT p50 | LUT rate delta | Cross-run ratio range |
|---|---:|---:|---:|---:|---:|---:|
| evaluate | 12 MiB | 0.33x | 0.007936 ms | 0.009856 ms | -19.22% | 0.791-0.808x |
| evaluate | 36 MiB | 1.00x | 0.022000 ms | 0.021984 ms | -2.85% | 0.723-1.004x |
| evaluate | 96 MiB | 2.67x | 0.167728 ms | 0.167744 ms | -0.01% | 1.000-1.001x |
| evaluate | 192 MiB | 5.33x | 0.335008 ms | 0.334848 ms | +0.05% | 1.000-1.004x |
| evaluate + commit | 12 MiB | 0.33x | 0.022368 ms | 0.023776 ms | -5.92% | 0.935-0.941x |
| evaluate + commit | 36 MiB | 1.00x | 0.059648 ms | 0.061232 ms | -2.59% | 0.973-0.996x |
| evaluate + commit | 192 MiB | 5.33x | 0.410288 ms | 0.411408 ms | -0.28% | 0.995-0.998x |

The conclusion is critical rather than promotional: for the current confidence function, the table does not improve end-to-end throughput. Native `exp2` wins while the shader is compute-sensitive; once the dense state/output stream becomes the bottleneck, the LUT cost is hidden and both paths converge. The recommended implementation for this exact kernel on this GPU is therefore direct `exp2`.

The integrated table stores decoded binary16 confidence values, not log codes. A true log code would have to be decoded with another exponential before writing the existing E16 confidence field, eliminating the reason to replace `exp2`; alternatively, keeping the code in log form would change the output contract. The separate probe still establishes the cache behavior of the user's proposed two-per-texel log-code layout. A log-domain production design becomes attractive only if downstream stages also consume the log code or compare thresholds in log space without decoding.

### One-fetch interval-pair refinement

The interval-pair experiment tests whether the original LUT's second dynamic texture fetch was masking a useful cache-resident path. Each ratio below is paired within a process before taking the median across two forward-order and two reverse-order processes. Because clock states can differ between modes in the same process, a paired ratio need not equal the ratio of the two cross-process median p50 values.

| Mode | Candidates | Direct p50 | Two-fetch p50 | One-fetch p50 | One-fetch vs direct rate | One-fetch vs two-fetch rate |
|---|---:|---:|---:|---:|---:|---:|
| evaluate | 262,144 | 0.007920 ms | 0.009840 ms | 0.009768 ms | -18.85% | +0.82% |
| evaluate | 524,288 | 0.011944 ms | 0.013576 ms | 0.013056 ms | -8.27% | +4.52% |
| evaluate | 786,432 | 0.018520 ms | 0.022416 ms | 0.021072 ms | -7.10% | +11.40% |
| evaluate | 1,048,576 | 0.079328 ms | 0.072872 ms | 0.074816 ms | -1.63% | -1.34% |
| evaluate | 2,097,152 | 0.167944 ms | 0.167848 ms | 0.167704 ms | +0.13% | +0.09% |
| evaluate | 4,194,304 | 0.334520 ms | 0.334888 ms | 0.410248 ms | -18.20% | -9.25% |
| evaluate + commit | 262,144 | 0.022304 ms | 0.023712 ms | 0.022792 ms | -2.00% | +3.96% |
| evaluate + commit | 524,288 | 0.040680 ms | 0.041024 ms | 0.040928 ms | -0.61% | +0.23% |
| evaluate + commit | 786,432 | 0.060728 ms | 0.061024 ms | 0.060488 ms | +0.56% | +0.82% |
| evaluate + commit | 1,048,576 | 0.088848 ms | 0.092112 ms | 0.085296 ms | +3.07% | +0.94% |
| evaluate + commit | 2,097,152 | 0.205032 ms | 0.248920 ms | 0.226400 ms | -8.76% | -0.67% |
| evaluate + commit | 4,194,304 | 0.409824 ms | 0.409824 ms | 0.409944 ms | -0.03% | -0.07% |

One fetch recovers part of the two-fetch overhead in several small and mid-size cases, but it does not reverse the result against direct `exp2`: evaluate remains 7.10-18.85% slower than direct through 786,432 candidates. At 4,194,304, its evaluate/direct paired-rate range is 0.813-1.000x, exposing the same clock-state split seen elsewhere; evaluate+commit is effectively tied, with 1.000x median against direct and a 1.000-1.006x range. Removing a fetch is real, but the measured benefit is neither monotonic nor robust enough to justify doubling the table. Direct `exp2` remains the recommended path for this exact confidence function on this device.

## Native verified-event compaction

Two G32 compaction implementations were tested:

- Per-lane atomic append: every verified lane reserves one E16 slot with `atomicAdd`; its full-count variant retains per-lane candidate/support/compatibility atomics.
- Subgroup/workgroup append: subgroup ballots produce lane ranks, one invocation reserves a contiguous range for the whole 256-candidate workgroup, and the full-count variant reduces all four counts to at most four global atomics per workgroup.

SPIR-V disassembly confirms `GroupNonUniform` and `GroupNonUniformBallot` capabilities, four ballot/bit-count reductions, workgroup-shared count/offset arrays, and four `OpAtomicIAdd` sites in the full-count variant. It also contains a second `OpArrayLength` for event-buffer capacity and a conditional store, establishing that the append-demand counter advances even when a bounded output descriptor is full. Local `vulkaninfo` reports a fixed 32-lane NVIDIA subgroup with compute basic and ballot operations, so each 256-thread workgroup contains eight subgroups on this device.

Every compact record is read back, matched to a candidate using lineage plus scalar/topology payload, checked for duplicates and unexpected entries, and validated with the same boundary policy as dense output. The verifier also proves that every CPU-verified non-boundary candidate appears in the compact stream. Append counts and full reduced counters match exactly.

Six independent subgroup processes - three forward job order and three reverse - produced:

| Candidates | Dense eval p50 | Subgroup compact p50 | Paired speedup | Dense full-count p50 | Subgroup compact + counts p50 | Paired speedup |
|---:|---:|---:|---:|---:|---:|---:|
| 262,144 | 0.007856 ms | 0.009536 ms | 0.828x | 0.022352 ms | 0.009968 ms | 2.246x |
| 524,288 | 0.011976 ms | 0.012848 ms | 0.950x | 0.040752 ms | 0.013984 ms | 2.921x |
| 786,432 | 0.021768 ms | 0.016528 ms | 1.284x | 0.060304 ms | 0.018160 ms | 3.315x |
| 1,048,576 | 0.064728 ms | 0.020608 ms | 3.126x | 0.088064 ms | 0.022512 ms | 3.930x |
| 2,097,152 | 0.186616 ms | 0.112464 ms | 1.659x | 0.206056 ms | 0.114352 ms | 1.797x |
| 4,194,304 | 0.334464 ms | 0.218888 ms | 1.528x | 0.410344 ms | 0.219424 ms | 1.869x |

At the largest case, the paired subgroup/dense evaluate ratio is tightly grouped at 1.524-1.535x even after reversing job order. The full-count ratio is 1.517-2.753x because first-job clock ramp and one slow dense baseline widen the range; 1.869x is the process-paired median across the balanced order set. The subgroup barriers and scan lose to dense output at small evaluate-only sizes, with the crossover in this corpus between 524,288 and 786,432 candidates. Reducing counters per workgroup wins even at the smallest measured size.

At 4,194,304 candidates, event yield is 4.7488%. Dense E16 output is 64 MiB and the logical compact stream is 3,186,864 bytes (3.04 MiB), a 21.058x output-stream reduction. Including the 128 MiB G32 input state, state plus logical output falls from 192 MiB to 131.04 MiB, a 1.465x reduction.

The original six-process timing set used worst-case `N * 16` output capacity. A second implementation bounds the allocation to one E16 slot per 16 candidates (6.25% capacity) and guards every write against `events.length()`. The append counter remains the total demand, so `max(demand - capacity, 0)` is an exact GPU-visible overflow count. Two forward and two reverse processes produced:

| Candidates | Capacity | Verified | Overflow | Dense eval p50 | Bounded subgroup p50 | Paired speedup | Dense commit p50 | Bounded subgroup + counts p50 | Paired speedup |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 262,144 | 16,384 | 12,454 | 0 | 0.007904 ms | 0.009536 ms | 0.829x | 0.022288 ms | 0.010024 ms | 2.227x |
| 524,288 | 32,768 | 24,905 | 0 | 0.011920 ms | 0.013512 ms | 0.883x | 0.040680 ms | 0.014104 ms | 2.884x |
| 786,432 | 49,152 | 37,350 | 0 | 0.017984 ms | 0.016512 ms | 1.066x | 0.061216 ms | 0.018192 ms | 3.355x |
| 1,048,576 | 65,536 | 49,798 | 0 | 0.071400 ms | 0.020568 ms | 3.477x | 0.092208 ms | 0.022544 ms | 3.891x |
| 2,097,152 | 131,072 | 99,597 | 0 | 0.167744 ms | 0.112432 ms | 1.491x | 0.227352 ms | 0.114136 ms | 2.003x |
| 4,194,304 | 262,144 | 199,179 | 0 | 0.333872 ms | 0.218952 ms | 1.525x | 0.410992 ms | 0.219824 ms | 1.876x |

At the largest case the bounded output allocation is 4 MiB, a real 16x allocation reduction; state plus allocated output is 132 MiB, 1.455x below the 192 MiB dense layout. The 4 MiB allocation leaves 62,965 unused slots (0.96 MiB) above the observed stream. Relative to the earlier worst-case-capacity medians, large append changes from 0.218888 to 0.218952 ms (+0.03%) and append+counts from 0.219424 to 0.219824 ms (+0.18%); these are separate run sets, so they establish practical parity rather than a causal cost estimate.

A capacity sweep at 4,194,304 candidates isolates the memory/risk trade. Signed headroom is capacity minus the exact 199,179-event GPU demand:

| Capacity ratio | Slots | Allocation | Allocation reduction | Headroom | Overflow | Subgroup append p50 |
|---:|---:|---:|---:|---:|---:|---:|
| 4.00% | 167,773 | 2,684,368 B | 25.000x | -31,406 | 31,406 | 0.218896 ms |
| 4.75% | 199,230 | 3,187,680 B | 21.053x | 51 | 0 | 0.219072 ms |
| 5.00% | 209,716 | 3,355,456 B | 20.000x | 10,537 | 0 | 0.219040 ms |
| 6.25% | 262,144 | 4,194,304 B | 16.000x | 62,965 | 0 | 0.218952 ms (four-run median) |

The 4.75% setting is lossless only by 51 records in this deterministic corpus and is too brittle as a production default. The 5% setting gives 5.29% headroom relative to observed events; 6.25% gives 31.61% event headroom and a power-of-two capacity rule with no measurable large-case throughput cost. The report therefore uses 6.25% as the conservative measured setting, while still requiring callers to size from their own worst-case event distribution.

A deliberate 1% capacity run independently exercised the failure path. At 262,144 candidates all four compact variants reported 12,454 demanded, 2,622 retained and 9,832 overflow events. Every retained payload validated, each demand counter exactly matched the dense GPU result, no out-of-range write occurred, and the harness rejected the run unless `--allow-compact-overflow` was supplied. This validates both safe truncation and fail-closed default behavior. A two-pass count/allocate/write pipeline remains preferable when lossless operation is required but no conservative capacity contract is available.

### Pre-threshold confidence predicate

The benchmark state stores binary16 guard epsilon `0.0100021362` and confidence floor `0.7001953125`. For `confidence = exp2(-32 * distance)`, that floor permits distance through `0.0160678341`; the guard is therefore strictly tighter, and every guard-crossing lane already has confidence at least `0.8010319`. Computing `exp2` before verification is redundant for this corpus.

The optional pre-threshold profile stores `min(guard_epsilon, -log2(confidence_floor)/32)` in the high half of the guard word. The GPU uses that effective distance for verification and materializes confidence only after the non-verified lanes return. SPIR-V disassembly places `Exp2` before the verification branch in the original subgroup module and after the early-return region in the pre-threshold module. Four processes, two in each job order, produced:

| Candidates | Original append p50 | Pre-threshold p50 | Paired rate change | Original + counts p50 | Pre-threshold + counts p50 | Paired rate change |
|---:|---:|---:|---:|---:|---:|---:|
| 262,144 | 0.009624 ms | 0.009488 ms | +1.01% | 0.009920 ms | 0.009944 ms | -0.32% |
| 524,288 | 0.013600 ms | 0.013032 ms | +4.47% | 0.014064 ms | 0.014032 ms | +0.11% |
| 786,432 | 0.017096 ms | 0.016440 ms | +4.14% | 0.018160 ms | 0.018256 ms | -0.57% |
| 1,048,576 | 0.020648 ms | 0.020552 ms | +0.98% | 0.022528 ms | 0.022624 ms | -0.32% |
| 2,097,152 | 0.112464 ms | 0.112480 ms | +0.01% | 0.114224 ms | 0.113464 ms | +0.67% |
| 4,194,304 | 0.219000 ms | 0.218928 ms | +0.03% | 0.220032 ms | 0.219936 ms | +0.04% |

All original/pre-threshold GPU counts match, every retained payload validates, and all runs are complete with zero overflow at 6.25% capacity. The large append ratio range is 1.000-1.234x because one original-path job entered a slow clock state; the balanced median is 1.0003x. The conclusion is narrow: pre-thresholding helps append-only work by roughly 1-4.5% before the stream becomes state-bandwidth dominated, but it does not materially improve the large case or the workgroup-counted path. Unlike a texture LUT it adds no cache footprint, but it changes the G32 field contract and is justified only when the producer can declare and precompute the monotonic threshold.

### G24 fixed-query hot state and 128-byte log-threshold LUT

The G24 profile specializes the declared fixed benchmark query rather than pretending to be a general replacement for G32. Its six 32-bit words retain position, cone threshold, axis, radius, guard epsilon and lineage. Time and phase are dropped, the full compatibility mask is reduced to a producer-computed compatible bit, and sheet/orientation plus a 6-bit confidence-distance code occupy the high 16 bits of the guard word. SPIR-V declares `ArrayStride 24`, so this is a real 24-byte storage-buffer record rather than a host-only packing claim.

The code represents the log-domain threshold `-log2(confidence_floor)/32` over `[0, 0.125]`. The LUT version expands its 64 codes to binary16 distances with one `OpImageFetch` from 32 `R32_UINT` texels: 128 bytes total, or 0.00034% of local L2. The direct control uses the identical G24 layout and subgroup algorithm but decodes `code * (0.125/63)` arithmetically; disassembly contains no image fetch. Both compute confidence with `exp2` only for retained E16 events. Six processes, three in each job order, produced:

| Candidates | G32 append p50 | G24 direct p50 | G24 LUT p50 | Direct/G32 paired rate | LUT/direct paired rate | Direct/G32 + counts | LUT/direct + counts |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 262,144 | 0.009528 ms | 0.008208 ms | 0.009744 ms | 1.163x | 0.841x | 1.003x | 0.991x |
| 524,288 | 0.013536 ms | 0.012064 ms | 0.013808 ms | 1.122x | 0.873x | 1.001x | 0.997x |
| 786,432 | 0.016568 ms | 0.016096 ms | 0.017872 ms | 1.027x | 0.903x | 1.005x | 0.987x |
| 1,048,576 | 0.020592 ms | 0.020112 ms | 0.021856 ms | 1.023x | 0.923x | 1.014x | 0.932x |
| 1,310,720 | 0.071536 ms | 0.024288 ms | 0.025904 ms | 2.947x | 0.937x | 2.792x | 0.929x |
| 1,572,864 | 0.085840 ms | 0.037040 ms | 0.038536 ms | 2.318x | 0.981x | 2.196x | 0.951x |
| 2,097,152 | 0.112464 ms | 0.086792 ms | 0.087808 ms | 1.296x | 0.982x | 1.303x | 0.997x |
| 4,194,304 | 0.218976 ms | 0.167664 ms | 0.187216 ms | 1.306x | 0.995x | 1.312x | 0.999x |

At 1,310,720 candidates, G32 state plus its bounded output allocation is 41.25 MiB (1.146x L2), while G24 is 31.25 MiB (0.868x L2); the sharp 2.947x append gain is therefore aligned with shifting the hot allocation back below the measured 36 MiB cache boundary. At 4,194,304, the corresponding allocations are 132 MiB and 100 MiB, exactly a 1.32x reduction, close to the stable full-counter speedup of 1.312x. This is strong cache-capacity/traffic evidence, but it is not a direct L2-hit or DRAM-transaction measurement because NVIDIA counters remain permission-blocked.

The append-only LUT rows were bimodal at the largest size: job order alternated approximately 0.168 and 0.207 ms states, so the cross-process LUT p50 above is 0.187 ms even though the within-process paired LUT/direct rate median is 0.995x. The counted kernels were stable: direct was 0.168 ms, LUT was 0.168 ms, and LUT/direct was 0.999x. Below L2, the LUT costs 6-16% against the direct decoder in append-only mode. The critical conclusion is therefore unambiguous: use the 24-byte fixed-query layout where its reduced semantics are acceptable, but keep direct threshold decoding for this 64-entry mapping. The texture-cache LUT is validated and essentially free only after state traffic dominates; it is not the source of the speedup.

#### Narrow L2-boundary sweep

Four additional processes, two in each job order, densely sampled the calculated residency crossings using the more stable full-counter subgroup kernels. All output payloads, dense-GPU demand cross-checks, reduced counters, completeness checks and overflow checks passed.

| Candidates | G32 allocation / L2 | G32 + counts p50 | G24 direct allocation / L2 | G24 direct + counts p50 | G24 LUT + counts p50 |
|---:|---:|---:|---:|---:|---:|
| 1,081,344 | 0.9453x | 0.024288 ms | 0.7161x | 0.022288 ms | 0.024304 ms |
| 1,114,112 | 0.9740x | 0.024400 ms | 0.7378x | 0.023760 ms | 0.024264 ms |
| 1,146,880 | 1.0026x | 0.032792 ms | 0.7595x | 0.024296 ms | 0.025312 ms |
| 1,179,648 | 1.0313x | 0.042144 ms | 0.7813x | 0.024256 ms | 0.027488 ms |
| 1,310,720 | 1.1458x | 0.073568 ms | 0.8681x | 0.026352 ms | 0.028256 ms |
| 1,441,792 | 1.2604x | 0.081344 ms | 0.9549x | 0.028448 ms | 0.030552 ms |
| 1,474,560 | 1.2891x | 0.082016 ms | 0.9766x | 0.029504 ms | 0.030624 ms |
| 1,507,328 | 1.3177x | 0.083952 ms | 0.9983x | 0.033928 ms | 0.035792 ms |
| 1,540,096 | 1.3464x | 0.085936 ms | 1.0200x | 0.038736 ms | 0.039152 ms |
| 1,572,864 | 1.3750x | 0.086968 ms | 1.0417x | 0.041216 ms | 0.042600 ms |

G32 candidate rate falls 23.4% on the step from 0.9740x to 1.0026x L2 and another 19.6% at 1.0313x, a cumulative 38.4% across those two steps. G24 remains flat across the same candidate counts because its allocation is only 0.738-0.781x L2. Its own rate falls 11.1% on the step from 0.9766x to 0.9983x and another 10.4% at 1.0200x, a cumulative 20.3%. The first G24 degradation begins with only 64 KiB of nominal L2 headroom, which is consistent with code, descriptors, counters, cache-line granularity and other GPU activity also competing for cache. The two cliffs move by almost exactly the 32/24-byte state-footprint ratio, materially strengthening the L2-capacity attribution while still not constituting a direct hit-rate measurement.

### G20 hot geometry with cold lineage

The next profile splits G24 into a 20-byte geometry/meta storage-buffer record and a separate 4-byte lineage storage buffer. The shader checks support, compatibility and verification from the hot record; non-verified lanes return before the lineage load. The 4.7488% retained lanes fetch lineage, compute the same hash and emit the same E16 contract. This preserves the complete 24-byte state allocation, so the experiment tests locality rather than claiming extra compression.

Six sequentially isolated processes, three in each job order, cover twelve sizes with 750 ms minimum warmup and 200 measured dispatches. All 432 rows have zero overflow and pass payload, count, completeness and pipeline-cache reload checks. Representative paired results are:

| Candidates | G24 append p50 | G20 append p50 | G20/G24 paired append rate | G24 + counts p50 | G20 + counts p50 | G20/G24 paired counted rate |
|---:|---:|---:|---:|---:|---:|---:|
| 1,310,720 | 0.035400 ms | 0.024680 ms | 1.437x | 0.026328 ms | 0.028432 ms | 0.926x |
| 1,507,328 | 0.030440 ms | 0.030720 ms | 0.996x | 0.032024 ms | 0.033720 ms | 0.948x |
| 1,769,472 | 0.073600 ms | 0.067416 ms | 1.092x | 0.075248 ms | 0.067680 ms | 1.112x |
| 2,097,152 | 0.087568 ms | 0.078784 ms | 1.111x | 0.087920 ms | 0.079712 ms | 1.103x |
| 4,194,304 | 0.167560 ms | 0.151256 ms | 1.108x | 0.168016 ms | 0.151392 ms | 1.110x |

The median per-size paired gain across all twelve sizes is 1.118x append and 1.025x append + counts. Small counted cases can regress, so the split is not an unconditional latency win. At 4,194,304 candidates, the declared always-hot state plus bounded output is 84 MiB rather than G24's 100 MiB, but the separately allocated 16 MiB lineage buffer keeps total allocation at 100 MiB. A pure 25/21 byte traffic model would permit at most 1.190x; retained-lane reads and cache-sector amplification narrow the observed gain. Exact sector traffic remains unmeasured because counters are permission-blocked. The full isolation protocol records the retained clock-state outlier and the common executable SHA-256.

The compaction audit exposed a separate identity problem. For the structured benchmark seed `lineage_seed = i * 2654435761`, the pre-mix expression `lineage_seed ^ i` has only 4,146,164 unique values over 4,194,304 candidates: 47,898 collision keys and 48,140 extra candidates. `mix32` is bijective over 32-bit words, so it cannot remove those collisions. The verifier therefore buckets equal lineage values and disambiguates with the rest of the event payload. Production logs that need unique source identity should carry a source index or a wider lineage identifier; the current 32-bit lineage is not a unique key.

## Important implementation boundaries

- G64 remains dense. G32 now has dense, per-lane atomic compact, and subgroup/workgroup compact paths. Compact buffers support either worst-case capacity or an explicit fractional bound with GPU-visible overflow demand; overflow fails validation unless deliberately allowed.
- G24 is a fixed-query compact ABI, not a lossless G32 encoding. It omits time and phase and replaces the compatibility mask with a precomputed bit; callers needing dynamic queries must retain G32 or define another versioned layout.
- G20 is the same fixed-query semantics with lineage split into a separate cold buffer. It is not a 20-byte total state format: total state allocation remains 24 bytes per candidate.
- Query compatibility remains fixed to sheet 1, orientation 0, and mask bit 2 in the benchmark shaders.
- G32 half packing changes numerical predicates and therefore event counts; it is a lossy performance profile, not a bit-identical substitute for G64.
- Subgroup compaction requires Vulkan subgroup basic/ballot support. It is verified on this NVIDIA Vulkan 1.4 device but must be capability-checked before use on another target.

## Profiling boundary

Nsight Systems reported `ERR_NVGPUCTRPERM`: GPU performance-counter sampling requires a privilege not enabled on this machine. An attempted Vulkan trace produced a report file but no Vulkan API rows, so it is not used as evidence. A validated native Vulkan capability probe against the selected NVIDIA device reports `pipeline_executable_capture = true` and `performance_query_extension_present = false`. No L2 hit-rate, sector count, or raw DRAM-byte claim is made. The cache conclusion is an inference from a controlled working-set sweep, the independently queried 36 MiB L2 size, and repeatable throughput behavior. Native driver compiler statistics are available through `VK_KHR_pipeline_executable_properties`; they do not substitute for L2/DRAM counters.

The same selected device reports `shaderDeviceClock = true` through `VK_KHR_shader_clock`, allowing the dependent-chain intervals above to be measured inside native GPU execution. This closes the host-timestamp-only observability gap but still does not expose cache hit classifications or define the clock unit.

CUDA `clock64()` provides a per-SM cycle counter and the `ld.global.cg` controls bypass L1, but neither substitutes for privileged cache-sector and DRAM-transaction counters. The hot/post-eviction labels are controlled cache-state interpretations, not direct hardware hit/miss classifications. The concurrency sweep adds a measured queue/scheduler response and logical requested-load throughput; it still cannot label physical transactions or exact hits. The matched `TLD.LZ`/`LDG.E.STRONG.GPU` studies establish relative native texture/global behavior and practical packed-code capacity, but they likewise cannot expose undocumented cache routing. Packed Glookup/s is decoded-code throughput; the 1.125 expected word requests/code and random cache-sector amplification are not physical transaction counts. The stride experiment bounds a workload-level effective residency unit through capacity scaling, not an undocumented physical line/sector size.

Device timestamps remove host submission latency from the metric but cannot remove dynamic-clock, power-state, or WDDM scheduling variation.

A separate 100 ms `nvidia-smi` telemetry run sampled 212 complete rows while the six large G32 modes ran with 2,000 ms warmup and 400 dispatches each. P-state occupancy was P0/P2/P4/P5/P8 = 80/4/107/9/12 samples. Across 109 samples with nonzero GPU utilization, graphics clock ranged from 630 to 2,782 MHz (2,060 MHz mean), memory clock from 9,001 to 14,001 MHz, power from 12.99 to 118.32 W, and temperature from 54 to 65 C. Dense evaluation landed in its slower 0.532 ms state while subgroup append remained 0.219 ms. Because sampling is asynchronous and not phase-labelled, this run is causal context for the observed clock hysteresis, not part of the performance aggregate.

## Reproduction

```powershell
# Build the direct Vulkan executables with Visual Studio Build Tools.
& .\gpu\scripts\build_windows_vulkan.ps1

# Semantic core plus integrated G32 texture-LUT sweep.
& .\gpu\scripts\run_windows_vulkan_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\windows_integrated_lut_run\new_run `
  -Sizes '262144,393216,524288,786432,1048576,2097152,4194304' `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 200

# Packed log-code texture-cache sweep.
# The current harness also runs a byte-identical SSBO control; repeat with
# -ReverseOrder for a counterbalanced process.
& .\gpu\scripts\run_windows_lut_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\windows_lut_cache_run\new_run `
  -Warmup 10 -WarmupMilliseconds 500 -Iterations 100

# Direct versus two-fetch and one-fetch confidence-LUT sweep.
# Repeat with -ReverseOrder for a counterbalanced process.
& .\gpu\scripts\run_windows_lut_pair_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\lut_pair\new_run `
  -Sizes '262144,524288,786432,1048576,2097152,4194304' `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 200

# Dense, per-lane atomic, and subgroup/workgroup compact G32 sweep.
& .\gpu\scripts\run_windows_compact_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\sg_compact\new_run `
  -Sizes '262144,393216,524288,786432,1048576,2097152,4194304' `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 200

# Same kernel with a real 6.25%-capacity output allocation.
& .\gpu\scripts\run_windows_compact_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\bounded_compact\new_run `
  -Sizes '262144,524288,786432,1048576,2097152,4194304' `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 200 `
  -CapacityRatio 0.0625

# Original versus pre-threshold subgroup predicate, same bounded allocation.
& .\gpu\scripts\run_windows_prethreshold_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\prethreshold\new_run `
  -Sizes '262144,524288,786432,1048576,2097152,4194304' `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 200 `
  -CapacityRatio 0.0625

# G32 versus G24 direct and one-fetch log-threshold LUT controls.
# Repeat with -ReverseOrder for a counterbalanced process.
& .\gpu\scripts\run_windows_hot_log_lut_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\hot_log_control\new_run `
  -Sizes '262144,524288,786432,1048576,1310720,1572864,2097152,4194304' `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 200 `
  -CapacityRatio 0.0625

# Narrow G32/G24 state-plus-output residency crossings.
& .\gpu\scripts\run_windows_hot_log_lut_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\l2_boundary_hot\new_run `
  -Sizes '1081344,1114112,1146880,1179648,1310720,1441792,1474560,1507328,1540096,1572864' `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 200 `
  -CapacityRatio 0.0625

# G24 versus 20-byte hot geometry plus a separate cold-lineage stream.
# Repeat with -ReverseOrder for a counterbalanced process.
& .\gpu\scripts\run_windows_cold_lineage_benchmarks.ps1 `
  -OutputDirectory .\benchmarks\cold_lineage_isolated\new_run `
  -Sizes '1310720,1441792,1474560,1507328,1540096,1572864,1638400,1703936,1769472,1835008,2097152,4194304' `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 200 `
  -CapacityRatio 0.0625

# Device-clock control plus saturated 512-step dependent SSBO chase.
# Repeat twice normally and twice with -ReverseOrder.
& .\gpu\scripts\run_windows_l2_latency.ps1 `
  -OutputDirectory .\benchmarks\l2_latency_isolated\new_run `
  -Warmup 10 -WarmupMilliseconds 750 -Iterations 100

# Native sm_120 one-warp cold/hot cycle control. Repeat in ascending and
# descending table orders in separate processes.
& .\gpu\scripts\run_windows_cuda_l2_clock.ps1 `
  -OutputDirectory .\benchmarks\cuda_l2_clock_isolated\new_run `
  -TableMiB '4,16,32,36,38,40,64,128' `
  -EvictionMiB 256 -Warmup 5 -Samples 50

# Native sm_120 concurrency/MLP sweep. Repeat twice in this order and twice
# with both -TableMiB and -Warps lists reversed in separate processes.
& .\gpu\scripts\run_windows_cuda_l2_mlp.ps1 `
  -OutputDirectory .\benchmarks\cuda_l2_mlp_isolated\new_run `
  -TableMiB '4,36,40,64,128' `
  -Warps '1,2,4,8,16,32,46,92,184,368,736,1104' `
  -EvictionMiB 256 -Warmup 3 -Samples 15

# Matched native texture-object versus global-load chase. Repeat twice in each
# path order and reverse both -TableMiB and -Warps in two isolated processes.
& .\gpu\scripts\run_windows_cuda_texture_lut.ps1 `
  -OutputDirectory .\benchmarks\cuda_texture_lut_isolated\new_run `
  -TableMiB '4,32,36,38,40,48,64,128' `
  -Warps '1,46,184,1104' `
  -EvictionMiB 256 -Warmup 3 -Samples 12

# Matched slot16/packed6 native lookup matrix. Use Latin -Order values 0-3 in
# separate processes and reverse -Entries/-Warps for orders 1 and 3.
& .\gpu\scripts\run_windows_cuda_packed_log_lut.ps1 `
  -OutputDirectory .\benchmarks\cuda_packed_log_lut_isolated\new_run `
  -Entries '2097152,14680064,16777216,18874368,20971520,25165824,33554432,39146832,50331648,55924048,67108864' `
  -Warps '1,46,184,1104' -EvictionMiB 256 -Warmup 3 -Samples 12 -Order 0

# Sparse-stride L2 residency matrix. Repeat twice in this order and twice with
# target/stride/warp lists reversed; add 13-15 MiB for 128/256-byte refinements.
& .\gpu\scripts\run_windows_cuda_l2_stride.ps1 `
  -OutputDirectory .\benchmarks\cuda_l2_stride_isolated\new_run `
  -TargetMiB '4,8,9,10,11,12,16,17,18,19,20,21,22,23,24,28,32,36,37,38,39,40,48,56,64' `
  -StrideBytes '4,8,16,32,64,128,256' -Warps '184,1104' `
  -EvictionMiB 256 -Warmup 3 -Samples 12

# Packed6 neighborhood-use continuum. Run four order-balanced repeats for the
# primary K list, then four for the exact 42/43, 85/86 and 128/129 boundaries.
& .\gpu\scripts\run_windows_cuda_lut_line_occupancy.ps1 `
  -OutputDirectory .\benchmarks\cuda_lut_line_occupancy_isolated\new_run `
  -TableMiB '28,32,36,37,38,39,40,48' `
  -CodesPerLine '1,2,4,8,16,32,42,43,64,85,86,128,129,170' `
  -Warps '184,1104' -EvictionMiB 256 -Warmup 3 -Samples 12 -Order 0

# Independent sparse packed-LUT decomposition. Run four repeats for the
# primary targets and four for 19/37/38/39 MiB, balancing direction/path order.
& .\gpu\scripts\run_windows_cuda_lut_sparse_address.ps1 `
  -OutputDirectory .\benchmarks\cuda_lut_sparse_address_isolated\new_run `
  -TargetMiB '4,8,9,10,11,12,13,14,15,16,18,20,24,28,32,36,40,48' `
  -StrideBytes '32,64,128,256' -Warps '184,1104' `
  -EvictionMiB 256 -Warmup 3 -Samples 12 -Order 0

# Page-spaced address-reach matrix. Run four direction/path-balanced repeats.
& .\gpu\scripts\run_windows_cuda_lut_sparse_address.ps1 `
  -OutputDirectory .\benchmarks\cuda_lut_page_stride_isolated\new_run `
  -TargetMiB '1,2,3,4,5,6,7,8' `
  -StrideBytes '128,256,512,1024,2048,4096' -Warps '184,1104' `
  -EvictionMiB 256 -Warmup 3 -Samples 12 -Order 0

# Exact-power-of-two alias control with one-region pitch skew.
& .\gpu\scripts\run_windows_cuda_lut_sparse_address.ps1 `
  -OutputDirectory .\benchmarks\cuda_lut_stride_skew_isolated\new_run `
  -TargetMiB '3,4,5,6,7,8' `
  -StrideBytes '480,512,544,992,1024,1056,2016,2048,2080,4064,4096' `
  -Warps '184,1104' -EvictionMiB 256 -Warmup 3 -Samples 12 -Order 0

# Native driver VMM capability/allocation-granularity context.
& .\gpu\scripts\run_windows_cuda_vmm_probe.ps1

# Constant-physical-backing VMM alias control. Repeat with Order 0/1.
& .\gpu\scripts\run_windows_cuda_vmm_alias.ps1 `
  -OutputDirectory .\benchmarks\cuda_vmm_alias_isolated\new_run `
  -Cases '32x2,32x4,32x6,32x8,64x2,64x4,64x6,64x8,96x2,112x2,120x2,124x2,126x2,127x2,128x2,129x2,130x2,132x2,136x2,144x2,160x2,192x2,128x4' `
  -Warps '184,1104' -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

# Verify effective compression properties, then run paired packed6 timing.
& .\gpu\scripts\run_windows_cuda_vmm_compression_probe.ps1
& .\gpu\scripts\run_windows_cuda_vmm_compression_lut.ps1 `
  -OutputDirectory .\benchmarks\cuda_vmm_compression_lut_isolated\new_run `
  -SizeMiB '4,28,32,36,38,40,48,64,96,128' `
  -Warps '184,1104' -Patterns 'zero6,periodic6,entropy6' `
  -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

# Nonzero constant semantic control. Repeat four times with balanced order.
& .\gpu\scripts\run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory .\benchmarks\cuda_vmm_compression_ones_global_isolated\new_run `
  -SizeMiB '36,38,40,48,64,128,192,240,248,256,288,320' `
  -Warps '1104' -Patterns 'ones6' -Paths 'global_cg' `
  -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

# Exact externalized threshold-code stream of the current synthetic G24 producer.
& .\gpu\scripts\run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory .\benchmarks\cuda_vmm_g24_code8_isolated\new_run `
  -SizeMiB '4,28,32,36,38,40,48,64,96,128,160,192,208,224,240,248' `
  -Warps '1104' -Patterns 'ugts_g24_floor70_code8' `
  -Paths 'global_cg,texture_object' `
  -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

# Exhaustive uniform6 global/L2 screen. Run four isolated processes with
# -Order 0,1,0,1; refinement repeats only codes 0/21/42/63 at 66-84 MiB.
& .\gpu\scripts\run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory .\benchmarks\cuda_vmm_uniform6_code_sweep_isolated\new_run `
  -SizeMiB '36,40,64,128,240,248' -Warps '1104' `
  -Patterns ((0..63 | ForEach-Object { "uniform6_$_" }) -join ',') `
  -Paths 'global_cg' `
  -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

& .\gpu\scripts\run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory .\benchmarks\cuda_vmm_uniform6_midpattern_refinement_isolated\new_run `
  -SizeMiB '36,40,64,66,68,70,72,74,76,78,80,82,84,88,96,112,128' `
  -Warps '1104' `
  -Patterns 'uniform6_0,uniform6_21,uniform6_42,uniform6_63' `
  -Paths 'global_cg' `
  -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

# Verify frozen hashes, all eight raw processes, every code/size row, packing
# mathematics, endpoint classification and rejection of the texture sentinel.
python .\gpu\tools\validate_cuda_vmm_uniform6.py

# Balanced code-0/code-63 spatial screen. Run four isolated processes with
# -Order 0,1,0,1; refine hash/g1-g16 every 2 MiB from 64 through 96 MiB.
& .\gpu\scripts\run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory .\benchmarks\cuda_vmm_blockmix063_isolated\new_run `
  -SizeMiB '36,40,48,64,80,96,112,128,160,192,224,240,248' `
  -Warps '1104' `
  -Patterns 'blockmix6_0_63_g1,blockmix6_0_63_g2,blockmix6_0_63_g4,blockmix6_0_63_g8,blockmix6_0_63_g16,blockmix6_0_63_g32,blockmix6_0_63_g64,blockmix6_0_63_g128,blockmix6_0_63_g256,blockmix6_0_63_g512,blockmix6_0_63_g1024,blockmix6_0_63_hash' `
  -Paths 'global_cg' -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

& .\gpu\scripts\run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory .\benchmarks\cuda_vmm_blockmix063_refinement_isolated\new_run `
  -SizeMiB '64,66,68,70,72,74,76,78,80,82,84,86,88,90,92,94,96' `
  -Warps '1104' `
  -Patterns 'blockmix6_0_63_g1,blockmix6_0_63_g2,blockmix6_0_63_g4,blockmix6_0_63_g8,blockmix6_0_63_g16,blockmix6_0_63_hash' `
  -Paths 'global_cg' -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

python .\gpu\tools\validate_cuda_vmm_blockmix063.py

# Four-symbol screen; run four isolated processes with -Order 0,1,0,1.
# The exact short/long/g64 refinement matrices are frozen in the protocol.
& .\gpu\scripts\run_windows_cuda_vmm_compression_lut.ps1 -SkipBuild `
  -OutputDirectory .\benchmarks\cuda_vmm_blockmix4_isolated\new_run `
  -SizeMiB '36,40,48,64,72,80,88,96,112,128,160,192,224,240,248' `
  -Warps '1104' `
  -Patterns 'blockmix6_0_21_42_63_g1,blockmix6_0_21_42_63_g2,blockmix6_0_21_42_63_g4,blockmix6_0_21_42_63_g8,blockmix6_0_21_42_63_g16,blockmix6_0_21_42_63_g32,blockmix6_0_21_42_63_g64,blockmix6_0_21_42_63_g128,blockmix6_0_21_42_63_g256,blockmix6_0_21_42_63_g512,blockmix6_0_21_42_63_g1024,blockmix6_0_21_42_63_hash' `
  -Paths 'global_cg' -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0

python .\gpu\tools\validate_cuda_vmm_blockmix4.py
```

The four-symbol aggregate corpora are under `benchmarks/cuda_vmm_blockmix4_isolated/aggregate/`, `benchmarks/cuda_vmm_blockmix4_short_refinement_isolated/aggregate/`, `benchmarks/cuda_vmm_blockmix4_long_refinement_isolated/aggregate/` and `benchmarks/cuda_vmm_blockmix4_g64_extension_isolated/aggregate/`. Frozen source, executable, map, provenance and protocol are under `benchmarks/cuda_vmm_blockmix4_exact/`.

Primary machine-readable results are in `benchmarks/windows_physical_gpu_aggregate/aggregate_metrics.json`, with paired values in `integrated_lut_comparison.csv`, `paired_lut_comparison.csv`, `lut_path_comparison.csv`, `l2_latency_comparison.csv`, `cuda_l2_clock_comparison.csv`, `cuda_l2_mlp_comparison.csv`, `cuda_texture_lut_comparison.csv`, `cuda_l2_stride_comparison.csv`, the `cuda_packed_log_lut_*.csv` tables, `prethreshold_comparison.csv`, `hot_log_lut_comparison.csv`, `hot_log_control_comparison.csv`, `l2_boundary_comparison.csv`, and `cold_lineage_comparison.csv`; native compiler metadata in `pipeline_executable_statistics.csv`; compaction values in `compaction_metrics.csv`, `bounded_compaction_metrics.csv`, and `capacity_sweep_metrics.csv`; and environment metadata in `environment.json`. Newer sparse/cache aggregate and CSV tables are in `benchmarks/cuda_lut_line_occupancy_isolated/aggregate/`, `benchmarks/cuda_lut_line_occupancy_k1_refinement/aggregate/`, `benchmarks/cuda_lut_sparse_address_isolated/aggregate/`, `benchmarks/cuda_lut_page_span_isolated/aggregate/`, `benchmarks/cuda_lut_page_stride_isolated/aggregate/`, `benchmarks/cuda_lut_stride_skew_isolated/aggregate/`, `benchmarks/cuda_vmm_alias_isolated/aggregate/`, `benchmarks/cuda_vmm_compression_lut_isolated/aggregate/`, `benchmarks/cuda_vmm_compression_zero_span_isolated/aggregate/`, `benchmarks/cuda_vmm_compression_ones_global_isolated/aggregate/`, `benchmarks/cuda_vmm_g24_code8_isolated/aggregate/`, `benchmarks/cuda_vmm_uniform6_code_sweep_isolated/aggregate/`, `benchmarks/cuda_vmm_uniform6_midpattern_refinement_isolated/aggregate/`, `benchmarks/cuda_vmm_blockmix063_isolated/aggregate/`, and `benchmarks/cuda_vmm_blockmix063_refinement_isolated/aggregate/`. The exhaustive per-code map, frozen executable and provenance are under `benchmarks/cuda_vmm_uniform6_exact/`; its invalid texture sentinel is preserved separately under `benchmarks/cuda_vmm_uniform6_texture_rejection/`. The balanced two-symbol map, frozen executable and provenance are under `benchmarks/cuda_vmm_blockmix063_exact/`. Driver VMM capability/property results are in `benchmarks/cuda_vmm_granularity_probe/` and `benchmarks/cuda_vmm_compression_probe/`; the earlier texture-zero semantic erratum and alignment controls are in `benchmarks/cuda_vmm_compression_zero_texture_alignment_isolated/`. Raw CUDA/Vulkan corpora and protocols remain under their correspondingly named benchmark directories. The older `benchmarks/cold_lineage_hot/` corpus is retained but excluded because four processes overlapped.
