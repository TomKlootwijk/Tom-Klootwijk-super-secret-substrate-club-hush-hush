# UGTS-GN 1.1 — GPU-Native Geometric–Topological Substrate

## 1. Scope

UGTS-GN 1.1 is the GPU-native and physical-device addendum to the unified geometric–topological substrate. It deliberately removes game-engine adapters from the target architecture. The authoritative interfaces are:

1. a typed state and event ABI;
2. SPIR-V compute modules and a direct Vulkan runtime;
3. a fixed-function hardware mapping for FPGA/ASIC implementations; and
4. a bounded optofluidic/waveguide endpoint using the same support–compatibility–guard–commit semantics.

The substrate is query-first. It evaluates local support, compatibility and relation guards, commits verified transitions, and retains lineage plus irreducible novelty. Rendering, display and print remain optional downstream projections.

## 2. Corpus normalization rule

A source motif enters the technical core only when it can be expressed as one of:

- a typed field or unit;
- a coordinate/chart transform;
- a support predicate;
- a relation or event surface;
- a compatibility predicate;
- a transition/routing map;
- a lineage/invariant rule;
- a calibrated physical transfer function; or
- a measurable performance, error, energy or memory quantity.

Metaphors that cannot be typed or measured are kept in the claims ledger as hypotheses, analogies or rejected claims.

## 3. Canonical state

A conceptual state is

```text
q = (x, t, phase, sheet, orientation, address, branch, policy, uncertainty)
```

The bundled compute profile implements the hot subset needed for a spherical-support event query:

```text
position xyz
query time t
support axis xyz
radial reach R
angular threshold cos(alpha)
phase
relation guard epsilon
confidence floor
sheet
orientation
compatibility mask
lineage seed
```

### 3.1 G64 authoritative record

`G64State` is 64 bytes and preserves float32 geometric fields.

| Offset | Bytes | Field | Meaning |
|---:|---:|---|---|
| 0 | 16 | `position_time` | x, y, z, t |
| 16 | 16 | `axis_radius` | axis x, y, z, radial reach |
| 32 | 16 | `phase_guard` | cone cosine, phase, guard epsilon, confidence floor |
| 48 | 16 | `meta` | sheet, orientation, compatibility mask, lineage seed |

### 3.2 G32 packed record

`G32State` is 32 bytes. Six pairs of float values are stored as IEEE binary16; topology fields are packed into one word. This profile halves dense state-plus-event traffic but requires a quantization contract. It must not be used where the guard band is smaller than the accumulated coordinate/normal/radius error.

### 3.3 Event records

`E32Event` is a 32-byte diagnostic event. `E16Event` is a 16-byte compact event. Both carry a verified bit, route, lineage hash and state flags. E16 packs guard and confidence as binary16.

A lineage hash is a compact checksum, not a cryptographic identity. Durable identity requires the full generative address and ordered event record.

## 4. Reference query

For candidate `i`:

```text
r              = length(position)
cos_to_axis    = dot(position/r, normalize(axis))
in_support     = (r <= R) and (cos_to_axis >= cone_cos)
compatible     = mode_bit and sheet==target_sheet and orientation==target_orientation
sdf            = r - R
guard           = abs(sdf) - epsilon
confidence      = 2^(-32*abs(sdf))
verified        = in_support and compatible and guard<=0 and confidence>=floor
route           = orientation xor verified
lineage_hash    = mix32(lineage_seed xor candidate_index)
```

The confidence law is a reproducible synthetic benchmark function, not a universal statistical model.

## 5. Native compiler pipeline

```text
finite grammar / typed query
        ↓
UGTS hot-state ABI (G64 or G32)
        ↓
GLSL 450 compute source
        ↓
SPIR-V 1.4 module
        ↓
Vulkan shader module + pipeline layout
        ↓
compute pipeline + vendor pipeline cache
        ↓
GPU dispatch → E32/E16 results → optional verified-event compaction
```

The package contains twenty-six named SPIR-V execution variants generated from twelve shader sources, plus twenty-six `spirv-opt -O` counterparts:

- G64 evaluate;
- G64 evaluate plus atomic commit counters;
- G32 evaluate; and
- G32 evaluate plus atomic commit counters;
- G32 evaluate and commit variants with a packed uniform-texel-buffer confidence LUT;
- G32 evaluate and commit variants with one packed endpoint pair per LUT interval, requiring one texture fetch per interpolated value;
- G32 verified-only per-lane atomic append, with and without all rejection-stage counters;
- G32 subgroup/workgroup compact append, with and without workgroup-reduced counters;
- G32 pre-threshold subgroup compact append, with and without workgroup-reduced counters; and
- fixed-query G24 subgroup compact append with a direct 6-bit log-threshold decoder, with and without workgroup-reduced counters;
- fixed-query G24 subgroup compact append with a 128-byte packed uniform-texel-buffer log-threshold LUT, with and without workgroup-reduced counters; and
- fixed-query G20 hot-state subgroup compact append with lineage in a separate cold storage buffer, with and without workgroup-reduced counters; and
- paired packed 16-bit log-code uniform-texel-buffer and SSBO probes for sequential and random access; and
- a zero-step device-clock control and 512-step dependent SSBO pointer chase; and
- native CUDA slot16 and densely packed 6-bit log-code lookup controls through both global and texture-object paths; and
- a native CUDA sparse-stride dependent chase that bounds effective isolated-word L2 residency.

The runtime descriptor layout reserves set 0, bindings 0-2 for state, event and counters, binding 3 for the confidence LUT where used, and binding 4 for the optional cold-lineage stream. Evaluate-only modules may optimize unused bindings out of the final SPIR-V interface. The local workgroup is 256x1x1. `gpu/spirv/spirv_manifest.json` records hashes, instruction counts, entry points, local size and descriptor decorations.

The direct runtime is `ugts_vulkan_bench`. ANGLE/SwiftShader appears only as a reproducible bootstrap compiler in this container; it is not the target runtime. Production targets compile the Vulkan GLSL with glslang/DXC or another conformant tool and execute the SPIR-V through the vendor Vulkan driver.

The two confidence-LUT encodings deliberately expose a cache/compute trade. The 8,196-byte adjacent-sample layout packs 4,097 binary16 samples two per `R32_UINT` texel and evaluates two sample fetches per interpolation. The 16,384-byte interval-pair layout duplicates interior endpoints so one texel contains both values needed for one interpolation. Both use a uniform texel buffer and fall back to direct `exp2` outside the tabulated interval. On the named RTX 5070 Ti Laptop GPU, the one-fetch layout recovers some small/mid-size lookup overhead but does not establish a stable throughput advantage over direct `exp2`; selecting a LUT is therefore a target-specific benchmark decision, not a semantic requirement.

A byte-identical cache-path control reads the same packed `uint` table with the same hash/index/output operations through either a uniform texel buffer or an SSBO. Four sequentially isolated, order-balanced processes report random texture/SSBO throughput ratios of 0.989x, 1.002x, 1.000x and 1.000x at 16, 32, 64 and 128 MiB. Both paths lose about 79.36% of random throughput from 32 to 64 MiB. This rules out an extra effective texture-cache capacity for this workload on the named device; it does not claim that the two descriptor paths have identical front-end hardware.

The native shader-clock control surrounds 512 strictly dependent SSBO loads with device-scope `OpReadClockKHR` operations. Four isolated, order-balanced processes find random control-subtracted chain time flat through the exact 36 MiB reported L2 size, 1.242x higher at 38 MiB, 2.134x at 40 MiB, 4.714x at 64 MiB, and 6.295x at 128 MiB relative to 36 MiB. Sequential time rises only 3.57% between 36 and 128 MiB. This is a saturated scheduler-exposed cache-boundary metric on the named device: the clock unit is implementation-defined and the result must not be renamed raw single-load latency, cycles, nanoseconds, or a measured cache-hit rate.

An independent CUDA 12.8 control compiles to native `sm_120`, brackets 512 dependent steps with the per-SM `clock64()` counter, and uses `ld.global.cg.u32` to bypass L1. Four isolated ascending/descending-order processes measure a median of table-size medians of 399.569 cycles per immediate-hot dependent warp step and 1,087.789 cycles after a 256 MiB L2-eviction pass, a 2.722x ratio. Complete-kernel CUDA-event time corresponds to 153.414 ns and 401.820 ns per step. Native SASS contains `CS2R SR_CLOCKLO` and `LDG.E.STRONG.GPU`; the control has no load, and both kernels use 17 registers with zero spills. The measurement includes thread time slicing and each warp step may request up to 32 random sectors, so it is not a scalar transaction-latency constant or a direct counter-based hit/miss classification.

The flat CUDA state-forced costs and the Vulkan capacity cliff are complementary. The Vulkan 128/36 MiB saturated ratio of 6.295x exceeds the CUDA post-eviction/hot ratio of 2.722x, demonstrating that the saturated value includes material queuing and scheduler exposure. Implementations must not invert these two latency constants into a cache-hit estimate without an independently validated concurrency model or hardware counters.

A native CUDA concurrency control supplies that missing scheduler/queue curve. It launches one 32-lane warp per block, retains 512 strictly dependent `ld.global.cg.u32` steps per lane, and scales from one total warp to the occupancy-query ceiling of 1,104 warps (24 per SM). Four isolated forward/reverse matrices validate 74,678,400 payloads representing 25,490,227,200 dependent loads. At full measured occupancy, immediate-hot requested throughput is 43.215 Gload/s at the exact 36 MiB L2 size, 23.683 at 40 MiB, 9.357 at 64 MiB and 7.524 at 128 MiB. The 36-to-40 MiB loss is 45.20%. Requested Gload/s and logical GiB/s are logical scalar requests, not cache-sector traffic, DRAM bandwidth or counter-derived hit rates.

The concurrency result makes the engineering rule concrete: the named device can sustain the 4 MiB control rate for a hot 36 MiB random table, but nominal capacity leaves no margin. A production hot LUT/state budget should reserve room for other lines and system activity; the package report uses 28 MiB as a conservative target, not a universal hardware constant. Texture-buffer placement does not add another effective capacity tier on this device.

A matched native CUDA texture-path control removes the remaining descriptor/instruction ambiguity. The same `cudaMalloc` bytes and dependent pointer sequence are read through a linear texture object and through `ld.global.cg.u32`, with independent 256 MiB eviction and balanced path order. Native `sm_120` SASS contains `TLD.LZ` for the texture chase and `LDG.E.STRONG.GPU` for the global chase; both use 16 registers, zero spills and the same 24 one-warp-blocks/SM occupancy ceiling. Four matrices validate 98,426,880 payloads representing 33,596,375,040 dependent loads.

At 1,104 warps, the median texture/global hot-rate ratio across eight 4-128 MiB table sizes is 0.99949x. From 36 to 40 MiB, global throughput falls 45.159% and texture throughput falls 45.246%. At one warp, texture is 13.65% slower and exposes 17.55% more cycles per step. Thus the native texture instruction does not provide another effective cache-capacity tier or a throughput advantage for this random dependent LUT. Packing remains beneficial because it keeps bytes below the shared L2 boundary.

A separate native packing control implements sixteen 6-bit log codes in three `u32` words (0.75 bytes/code) and compares it with two 16-bit code slots per word (2 bytes/code). Four Latin-order-balanced matrices exercise both `TLD.LZ` and `LDG.E.STRONG.GPU`, reach the same 24 one-warp-blocks/SM occupancy ceiling, and validate 270,673,920 payloads representing 92,390,031,360 individual code checks. Packed extraction uses one word for 14/16 offsets and a second predicated word for 2/16 offsets; all four kernels have zero spills.

At the exact 36 MiB physical endpoint, slot16 holds 18,874,368 codes while packed6 holds 50,331,648, exactly 2.667x as many. At full occupancy the texture rates are 43.192 and 42.594 Glookup/s, so dense packing preserves 98.61% of slot throughput. At the conservative 28 MiB endpoint, measured packed capacity is 39,146,832 codes, five below the mathematical floor because the test packs whole 16-code groups, versus 14,680,064 slot codes. Packed texture falls 45.05% from 36 to 40 MiB, confirming that packing moves logical capacity without moving the physical cache boundary. Glookup/s counts decoded logical codes, not physical cache transactions.

The current synthetic G24 producer fixes `confidence_floor = 0.70`; binary16 rounding and the declared log-distance quantizer produce code 8. If externalized as a dense packed6 stream, sixteen codes become the three words `0x08208208 0x82082082 0x20820820`. Four balanced native CUDA VMM processes validate 256 rows, 271,319,040 payloads and 92,610,232,320 timed global/texture lookups. The median generic-compressible/non-compressible hot-rate ratio across all 32 size/path pairs is 0.999993x, and both allocation modes retain 99% of their best rate only through 36 MiB on both paths. Thus semantic uniformity does not grant a hardware-compression multiplier when dense packing produces nonuniform physical words. This result covers the externalized threshold stream only, not the complete interleaved G24 state or a production distribution.

An exhaustive native global/L2 control enumerates all 64 uniform logical 6-bit values after dense packing. Because each 32-bit boundary advances two places through the repeated six-bit motif, exactly codes 0, 21, 42 and 63 form three identical words (`0x00000000`, `0x55555555`, `0xAAAAAAAA` and `0xFFFFFFFF`); these are also exactly the four codes that extend beyond the nominal 36 MiB L2 boundary. Under the declared balanced 99%-of-best rule, codes 0 and 63 remain full through the independently address-bounded 240 MiB endpoint, codes 21 and 42 reach 70 MiB and fall below full rate at 72 MiB, and the other sixty codes end at 36 MiB. Eight isolated processes validate 3,616 rows, 3,832,381,440 payloads and 1,308,119,531,520 timed lookups with zero mismatches. This is an exhaustive input/output map for the declared layout and named GPU, not a reverse-engineered compressor format or physical byte ratio. The parameterized texture branch is excluded: 24 nonzero sentinel rows produce 424,112,712 decoded mismatches while eight zero-code rows falsely validate, and its timed `TLD.LZ` target is `RZ` in SASS.

A native global/L2 block-mixture control combines the two highly compressible uniform values rather than storing only one. Each packed 12-byte group contains sixteen code-0 or code-63 values, and deterministic approximately balanced sequences vary the selection pseudorandomly per group or alternate it in power-of-two runs. The balanced 99%-of-best endpoint is 72 MiB for hashed selection and 12-96-byte runs, 88 MiB for 192-byte runs, and the independently address-bounded 240 MiB for all tested 384-12,288-byte runs. Eight isolated processes validate 2,064 rows, 2,187,509,760 payloads and 746,669,998,080 timed lookups with zero mismatches. The first tested run span reaching 240 MiB is 384 bytes, but intermediate spans are unmeasured and no compressor-block, arbitrary-data or physical-ratio claim follows.

A stricter native global/L2 control chooses among all four individually compressible uniform values 0, 21, 42 and 63 in approximately balanced deterministic group sequences. Sixteen isolated order-balanced processes validate 3,560 rows, 3,773,030,400 payloads and 1,287,861,043,200 timed lookups with zero mismatches. Under the declared within-refinement 99%-of-best rule, hashed/12-192-byte symbol runs end at 40-82 MiB and tested 384-12,288-byte runs end at 120-168 MiB; a 768-byte run is strongest at 168 MiB, or 4.667x nominal L2 allocation. Longer runs are non-monotonic, so no run-length law, compressor block, arbitrary-data behavior or physical byte ratio is inferred. The retained path is raw global only because the parameterized texture branch was independently rejected by nonzero semantic sentinels.

A native sparse-stride control establishes the locality bound for applying those capacity figures. One nonlinear dependent `u32` pointer is consumed at each 4-256 byte spacing, and every gap word is filled with deterministic mixed data. At 1,104 warps, hot active-node capacity scales 4:2:1 for 32-, 64- and 128-byte spacing: 1,179,648, 589,824 and 294,912 nodes respectively at the approximately 43.0 Gload/s plateau. A 256-byte-spaced version with the same 294,912 nodes uses 72 MiB but remains at 42.985 Gload/s versus 43.004 at 128-byte spacing/36 MiB. Conversely, 589,824 nodes at 128-byte spacing reach only 14.176 Gload/s, rejecting a 64-byte effective unit.

The measured conclusion is that isolated random `u32` entries have an effective residency unit consistent with 128 bytes for this workload. It is not a counter-derived physical cache-line, sector or transaction-size claim. Consequently the 36 MiB useful-capacity range is 50,331,648 dense packed6 codes versus 294,912 isolated active entries; the 28 MiB range is 39,146,837 arithmetic dense codes versus 229,376 isolated entries. Packing realizes its 2.667x representation density only when accesses reuse neighboring codes within the effective region.

### 5.1 Reference query convention

The bundled benchmark modules use a fixed query convention: target sheet 1, target orientation 0, and compatibility-mask bit 2. The portable JSON schema and CPU oracle support explicit query values. A production native module should expose those values through specialization constants, push constants or a query buffer, or compile a versioned fixed-query variant.

## 6. Compute/commit split

### Evaluate

Every invocation independently writes an event record. No global atomics are required. This is the maximum-throughput diagnostic path.

### Evaluate + commit

The same event evaluation additionally increments four global counters: candidates, support survivors, compatibility survivors and verified events. Atomic contention makes this path slower. A production system should use subgroup/local reductions or verified-event compaction when global counts are required at scale.

## 7. Event compaction

The benchmark retains dense output as a diagnostic baseline and implements verified-only E16 output through both per-lane atomic append and subgroup/workgroup range reservation:

```text
predicate → subgroup ballot → block prefix → global block offsets → compact E16/E32 append
```

Every compact record is validated by scalar/topology payload and collision-bucketed lineage, and non-boundary completeness is checked against the CPU oracle. On the named RTX 5070 Ti Laptop GPU at N=4,194,304 and 4.7488% event yield, subgroup compaction reduced logical E16 writes 21.058x and measured 1.528x faster than dense evaluation across the original six forward/reverse-order processes. With all four counters reduced per workgroup it measured 1.869x faster than dense per-lane commit at the paired median.

Compact descriptors may instead expose an explicit bounded capacity. The shader advances the authoritative append-demand counter for every verified event but writes only when `slot < events.length()`. With capacity set to 6.25% of candidates, the named device retained all 199,179 events at N=4,194,304, reported zero overflow, reduced the actual event allocation from 64 MiB to 4 MiB (16x), and preserved the approximately 0.219 ms subgroup time across four balanced processes. A deliberate 1% run validated exact overflow demand and safe truncation. Overflow is a validation failure by default; callers may explicitly allow it only for bounded-loss diagnostics. A two-pass count/allocate/write design remains required when lossless operation has no conservative capacity contract.

An optional pre-threshold G32 profile replaces the stored confidence floor with `min(guard_epsilon, -log2(confidence_floor)/32)`. The subgroup predicate then uses a distance comparison, and `exp2` executes only for verified lanes whose confidence must be materialized in E16. The profile is algebraically valid for the declared monotonic confidence function but is a distinct ABI: producers must precompute the field and consumers must not interpret its high half as a raw confidence floor. On the named device it improved append-only paired medians by 1.0-4.5% in the smaller/mid-size cases, converged to +0.03% at N=4,194,304, and produced no consistent counted-path advantage.

The fixed-query G24 profile uses six scalar `uint` words with a verified 24-byte `std430` array stride. It retains position, cone threshold, support axis, radius, guard epsilon, sheet, orientation and lineage, but omits time and phase and replaces the full compatibility mask with a producer-computed compatible bit. A 6-bit code represents `-log2(confidence_floor)/32` over `[0, 0.125]`. One variant decodes it arithmetically; the other fetches one of 64 binary16 thresholds from a 128-byte packed `R32_UINT` uniform texel buffer. This is a distinct fixed-query ABI, not a lossless G32 encoding.

At N=4,194,304 with a 6.25%-capacity E16 buffer, G24 reduces state-plus-output allocation from 132 MiB to 100 MiB. Across six balanced native runs, the direct-decoder append path measured a 1.306x paired speedup over G32, and its reduced-counter path measured 1.312x. The LUT/direct ratios were 0.995x and 0.999x respectively; below L2 the LUT was slower. The record footprint, not the 128-byte LUT, is therefore the supported cause of the large-case gain. Exact L2 hit rate and DRAM traffic remain unmeasured because hardware counters were permission-blocked.

A separate four-process boundary sweep sampled 32,768-candidate increments around both calculated residency crossings. G32 candidate rate fell 23.4% between 0.974x and 1.003x L2 and another 19.6% at 1.031x; G24 stayed flat at those sizes, then fell 11.1% between 0.977x and 0.998x of L2 and another 10.4% at 1.020x. The displacement of the cliff is consistent with the 32-to-24-byte state reduction and strengthens, but does not replace, the working-set-based cache attribution.

The G20 cold-lineage profile splits the identical fixed-query state into five hot scalar words and one separately allocated lineage word. Non-verified lanes return before binding 4 is loaded. Total state allocation remains 24 bytes per candidate, while the declared always-hot state plus 6.25%-capacity E16 output falls from 25 to 21 bytes per candidate. At N=4,194,304, six balanced, sequentially isolated native runs measured 1.108x higher append throughput and 1.110x higher counted throughput than G24. All counts and retained payloads match. Driver-native executable metadata reports identical registers, shared memory and binary size for the G24/G20 append kernels, supporting a locality rather than compute-resource explanation. This is a locality optimization, not a 20-byte total-storage claim; cache-sector amplification remains unmeasured.

## 8. Native performance vocabulary

| Symbol | Name | Definition |
|---|---|---|
| CER | Candidate Evaluation Rate | candidates evaluated / device time |
| SET | Spherical Event Throughput | verified events / device time |
| SDT | Saturated Dependent-load Ticks | control-subtracted device-clock ticks / dependent load under the declared invocation count |
| CDL | CUDA Dependent-step Latency | control-subtracted per-SM clock cycles / one dependent warp step under the declared cache-state protocol |
| CMLP | CUDA Memory-Level Parallelism | requested dependent loads / complete-kernel time at a declared total warp count; logical request throughput, not physical memory traffic |
| CTP | CUDA Texture Path ratio | paired texture-object requested-load rate / L1-bypassing global requested-load rate for byte-identical chains |
| CPL | CUDA Packed Lookup ratio | packed6 decoded-code rate / slot16 decoded-code rate at the same logical entry count, path and concurrency |
| EIR | Effective Isolated Residency | workload-inferred cache bytes per isolated useful word from stride-dependent capacity scaling; not a physical line/sector declaration |
| ESB | Effective Substrate Bandwidth | logical state+event bytes / device time; not external DRAM bandwidth |
| SRG | Support Rejection Gain | candidates / supported |
| CRG | Compatibility Rejection Gain | supported / compatible |
| EY | Event Yield | verified / candidates |
| CPC | Cold Pipeline Compilation | first `vkCreateComputePipelines` latency |
| CPH | Cache-Seeded Pipeline Hydration | pipeline creation with persisted cache data |
| NPF | Native Program Footprint | SPIR-V bytes and driver cache/binary bytes |
| SCR | State Compression Ratio | G64/E32 dense bytes / G32/E16 dense bytes |
| ECR | Event Compaction Ratio | dense output bytes / verified-only output bytes |
| SNC | State-plus-Novelty Compression | G64/E32 dense / (G32 state + compact E16 events) |
| CCF | Commit Cost Factor | evaluate+commit p50 / evaluate p50 |
| PCP | Packed Compute Penalty | G32 evaluate p50 / G64 evaluate p50 on a named target |

All metrics are meaningful only when device, batch size, record profile, mode, precision, error budget and timing method are reported.

## 9. Memory formulas

For `N` candidates and `V` verified events:

```text
G64/E32 dense             = N × 96 bytes
G32/E16 dense             = N × 48 bytes
G32 + compact E16 novelty = N × 32 + V × 16 bytes
G24 fixed query + compact = N × 24 + V × 16 bytes
G20 hot + cold lineage     = N × 20 + N × 4 + V × 16 bytes
compact E16 log only      = V × 16 bytes
```

The last configuration is valid only when authoritative state is retained elsewhere or reconstructible from seed, grammar, invariants and event log.

A one-bit support mask is `ceil(N/8)` bytes, but it is only a predicate cache. It is not a replacement for state.

## 10. Physical fixed-function mapping

```text
state SRAM / input stream
   ↓
position norm + support-axis dot product
   ↓
radial and angular comparators
   ↓
sheet/orientation/mode compatibility mask
   ↓
relation function + guard/hysteresis
   ↓
confidence/SNR threshold
   ↓
route + lineage update
   ↓
verified-event FIFO / DMA / actuator command
```

An FPGA/ASIC implementation may use fixed point, block floating point or FP16. The numeric contract must declare range, quantization error and guard margin. The Vulkan ABI supplies the reference behavior and golden vectors.

## 11. Optofluidic/waveguide mapping

```text
bounded radial-angular input
   ↓
liquid lens / overclad tuning
   ↓
mode-overlap coupling
   ↓
waveguide phase/interference
   ↓
mode + policy compatibility
   ↓
balanced detector guard crossing
   ↓
digital B.C.E. commit, confidence, lineage and log
```

Maxwell, coupled-mode theory and fluid mechanics remain authoritative for the physical transfer. The event substrate does not replace those equations. A Klein or Möbius label is permitted only when ports, orientation and transfer matrix are explicitly specified.

## 12. Pythagorean-cup addendum

The source’s trident and Pythagorean-cup imagery is retained as a useful 3-to-1 threshold/reset pattern:

- three channels converge;
- an accumulator rises;
- crossing a crest latches an event;
- a reset path drains or clears the accumulator; and
- hysteresis prevents chatter.

It is not an absolute vacuum, a free-energy device or a topological energy recycler.

## 13. Numeric and physical corrections

- Standard `100%` is 1. The value 36 is produced only by a versioned custom glyph encoder.
- The corpus contains both `100101₂=37` and a later `100100₂=36`. UGTS-GN labels them as encoder variants and makes the latter canonical for this addendum.
- Multiplication by 1.5 is not an integer bit shift. In log-base-2 coordinates its displacement is `log2(1.5) ≈ 0.5849625`.
- Information in bits is not energy in joules without a physical process. At 298.15 K, erasing 0.680 bits has a Landauer lower bound of approximately `1.94×10^-21 J`; actual devices consume more. The source’s 202.74 J figure is rejected.
- Topological closure does not eliminate loss, latency, memory, heat, calibration or noise.

## 14. Reproducibility and acceptance

A run is accepted only when:

1. all SPIR-V modules parse and expose the declared entry point, local size and bindings;
2. native pipeline creation and cache reload succeed;
3. counter totals equal the CPU oracle;
4. at least the first 4096 output records match the CPU oracle;
5. p50/p95/p99 device and host latency are recorded;
6. device name/type/API and timestamp period are recorded; and
7. `physical_gpu_claim` is false when the selected device is software or CPU.

## 15. Kill criteria

Stop or redesign when compatibility pruning is weak, event/branch density explodes, FP16 error exceeds guard margin, atomic commit dominates, calibration cost erases hardware advantage, physical false-event/miss targets fail, or the digital sidecar performs nearly all useful work.
