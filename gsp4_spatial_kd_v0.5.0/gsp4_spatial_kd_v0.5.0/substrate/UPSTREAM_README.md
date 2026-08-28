# UGTS-GN 1.1 - GPU-Native Geometric-Topological Substrate Addendum

This package is the GPU-native and physical-device revision of the unified substrate. It removes Unity/Godot adapters and makes the authoritative target a direct Vulkan/SPIR-V compute path or a measured hardware device.

## What is included

- `report/`: complete synthesis report and report source.
- `spec/`: 203-mechanism knowledge catalog, typed schema, ABI/state layout, metric definitions and claims ledger.
- `gpu/`: twelve Vulkan compute-shader sources, twenty-six named execution variants plus twenty-six optimized SPIR-V counterparts, the direct Vulkan runtime, and native CUDA `sm_120` L2 cycle/concurrency, texture-object, dense-packed-LUT and sparse-residency controls with build/run scripts.
- `reference/`: dependency-free CPU oracle and binary packers.
- `tests/`: executable reference tests.
- `benchmarks/`: raw and derived benchmark data, plots and named metrics.
- `hardware/`: fixed-function device architecture, register map, measurement plan and Q16.16 RTL reference gate.
- `sources/`: privacy-safe source manifest and source-by-source extraction notes.
- `examples/`: exchange-format and custom-encoder examples.

## Quick validation

```bash
python -m unittest discover -s tests -v
bash gpu/scripts/run_all_validation.sh
```

The original portable baseline in `benchmarks/vulkan_native_run/` selected SwiftShader, a CPU/software Vulkan device. A local Windows physical-GPU validation is now recorded in [`benchmarks/PHYSICAL_GPU_REPORT_RTX_5070_TI_LAPTOP.md`](benchmarks/PHYSICAL_GPU_REPORT_RTX_5070_TI_LAPTOP.md), with a human-readable [`yield, compression and limits report`](benchmarks/YIELD_COMPRESSION_LIMITS_RTX_5070_TI_LAPTOP.md). Raw and aggregate data is under `benchmarks/windows_native_run/`, `benchmarks/windows_integrated_lut_run/`, `benchmarks/windows_lut_cache_run/`, `benchmarks/lut_path_control/`, `benchmarks/lut_pair/`, `benchmarks/sg_compact/`, `benchmarks/bounded_compact/`, `benchmarks/capacity_sweep/`, `benchmarks/prethreshold/`, `benchmarks/hot_log_lut/`, `benchmarks/hot_log_control/`, `benchmarks/l2_boundary_hot/`, `benchmarks/cold_lineage_isolated/`, `benchmarks/l2_latency_isolated/`, `benchmarks/cuda_l2_clock_isolated/`, `benchmarks/cuda_l2_mlp_isolated/`, `benchmarks/cuda_texture_lut_isolated/`, `benchmarks/cuda_packed_log_lut_isolated/`, `benchmarks/cuda_l2_stride_isolated/`, and `benchmarks/windows_physical_gpu_aggregate/`.

On Windows with Visual Studio Build Tools, run the device-local Vulkan path directly:

```powershell
& .\gpu\scripts\run_windows_vulkan_benchmarks.ps1
& .\gpu\scripts\run_windows_lut_benchmarks.ps1
& .\gpu\scripts\run_windows_lut_pair_benchmarks.ps1
& .\gpu\scripts\run_windows_compact_benchmarks.ps1
& .\gpu\scripts\run_windows_prethreshold_benchmarks.ps1
& .\gpu\scripts\run_windows_hot_log_lut_benchmarks.ps1
& .\gpu\scripts\run_windows_cold_lineage_benchmarks.ps1
& .\gpu\scripts\run_windows_l2_latency.ps1
& .\gpu\scripts\run_windows_cuda_l2_clock.ps1
& .\gpu\scripts\run_windows_cuda_packed_log_lut.ps1
& .\gpu\scripts\run_windows_cuda_l2_stride.ps1
```

The benchmark modules use the fixed reference query sheet=1, orientation=0, compatibility-mask bit=2; production modules should parameterize or version this convention.

The compact runner accepts `-CapacityRatio 0.0625` for a real one-slot-per-16-candidates output allocation. The GPU append counter records total demand, writes are bounded by the descriptor length, and overflow fails validation unless `-AllowOverflow` is explicitly selected for diagnostics.

The optional pre-threshold compact profile stores `min(guard_epsilon, -log2(confidence_floor)/32)` in the second guard half. It resolves the monotonic confidence predicate with a distance comparison and materializes confidence only for retained events. This changes the G32 field contract and therefore remains a separately named profile.

The G24 fixed-query hot profile goes further: it removes unused time/phase fields, replaces the dynamic compatibility mask with a producer-computed bit, and stores a 6-bit log-distance threshold code. Its direct decoder is the recommended variant on the measured RTX 5070 Ti Laptop GPU. The bundled 128-byte uniform-texel-buffer decoder validates the texture-cache form, but the balanced control shows that the large-case gain comes from the 24-byte state footprint, not the LUT. A four-process narrow sweep independently moves the counted-path cache cliff from the G32 allocation's 0.974-1.003x-L2 interval to the G24 allocation's 0.977-0.998x interval. A second four-process control reads identical packed log-code bytes through `texelFetch` and an SSBO: random-path ratios are 0.989x, 1.002x, 1.000x and 1.000x at 16, 32, 64 and 128 MiB, and both paths share the same 32-to-64 MiB cliff. The texture-buffer path therefore does not provide extra effective cache capacity on this device.

A native `VK_KHR_shader_clock` control plus 512-step dependent SSBO chase samples the L2 boundary in 2 MiB increments. Four isolated, balanced processes are flat through the exact 36 MiB reported capacity, rise 1.242x at 38 MiB and 2.134x at 40 MiB, and reach 4.714x at 64 MiB relative to 36 MiB. The raw unit is deliberately reported as implementation-defined shader-clock ticks under scheduler load, not invented GPU cycles or nanoseconds.

An independent CUDA 12.8 control compiles directly to `sm_120`, bypasses L1 with `ld.global.cg`, and reads the per-SM `clock64()` cycle counter. Four isolated runs measure a cross-size median of 399.57 cycles per immediate-hot dependent warp step and 1,087.79 cycles after a 256 MiB L2-eviction pass, a 2.722x penalty. Complete-kernel CUDA-event timing corresponds to approximately 153.4 ns and 401.8 ns per step. `cuobjdump` confirms `CS2R SR_CLOCKLO` and `LDG.E.STRONG.GPU`; `ptxas` reports 17 registers and zero spills. The metric still includes warp time slicing and up to 32 random sector requests per step, so it is not labelled scalar transaction latency.

A second native CUDA control scales independent one-warp blocks from one warp to the occupancy-query ceiling of 1,104 warps (24 per SM) while preserving each lane's 512-step dependency chain. Four balanced processes validate 74,678,400 payloads representing 25.49 billion loads. At full measured occupancy, hot requested throughput is 43.215 Gload/s for a 36 MiB table and 23.683 Gload/s at 40 MiB, a 45.20% boundary loss; 64 and 128 MiB reach only 9.357 and 7.524 Gload/s. This confirms that packed random-access state should remain below nominal L2 and quantifies the memory-queue/scheduler amplification behind the saturated cliff.

A third native CUDA control binds the same bytes as a linear texture object and a raw global pointer. SASS proves `TLD.LZ` versus `LDG.E.STRONG.GPU`, so the paths are genuinely different. Across four path/order-balanced matrices, the full-occupancy texture/global hot-rate ratio is 0.99949x at the median of eight table sizes; both paths lose about 45.2% from 36 to 40 MiB. At one warp the texture path is 13.65% slower and exposes 17.55% more cycles. Texture hardware therefore supplies no extra effective capacity tier for this random dependent LUT on the named GPU.

A fourth native CUDA control implements the previously theoretical dense 6-bit code stream: sixteen codes occupy three words instead of two 16-bit slots per word. At the 36 MiB L2 endpoint, texture slot16 holds 18,874,368 codes at 43.192 billion decoded lookups/s; texture packed6 holds 50,331,648 codes at 42.594 billion/s. The full 2.667x capacity gain therefore costs only 1.39% saturated texture throughput. Packed texture still loses 45.05% at 40 MiB, so packing moves logical capacity rather than the physical cache boundary. Four Latin-order-balanced matrices validate 92.39 billion individual decoded codes.

A fifth native CUDA control measures one locality endpoint. It places one consumed `u32` at 4-256 byte spacing, fills all gaps with mixed data, and replays nonlinear dependent paths. Full-occupancy hot capacity scales 4:2:1 for 32-, 64- and 128-or-more-byte spacing, while a 256-byte-spaced allocation tracks the same curve as 128 bytes despite using 2x storage. This bounds the **dependent pointer chase** at an effective 128 bytes per active entry for that workload. It is not a universal per-code or physical-cache-line claim; all 1,448 raw rows and 366.68 billion dependent GPU loads validate.

A sixth native CUDA control maps intermediate packed-LUT neighborhood use and corrects that endpoint's scope. It varies 1-170 useful packed6 codes per aligned 128-byte region and probes exact 32-byte address boundaries. All layouts sustain 42.437-43.010 Glookup/s at 36 MiB; at 40 MiB the texture path ranges progressively from 42.800 Glookup/s for one useful code to 23.514 Glookup/s for 170. New regions are requested only on 1/43, 1/86 or 1/129 lookups at the tested crossings, so changes are gradual. With one useful code, 40 MiB retains 99.02% of the 28 MiB rate, showing that the dependent chase's 128-byte endpoint is not a complete throughput model for independently scheduled codes. The eight order-balanced processes validate all 1,792 rows and execute 453.79 billion timed GPU code lookups.

A seventh CUDA control separates useful data portions, containing line addresses and total address span. At the same 40 MiB allocation and 327,680 aligned 128-byte lines, requesting four, two or one 32-byte portions per line produces 23.343, 38.505 and 42.802 Glookup/s. Conversely, holding requested 32-byte span at 12 MiB while increasing containing-line count from 98,304 to 393,216 lowers texture rate from 43.214 to 28.119 Glookup/s. A one-code refinement locates the sparse line-address transition between 352,256 and 360,448 lines; doubling spacing from 128 to 256 bytes adds a separate address-span penalty. This supports a sectorized data-plus-line-address model without claiming undocumented physical cache structures. All 1,408 matrix rows and 356.55 billion timed lookups validate.

An eighth native CUDA study expands that independent sparse lookup to 4-KiB spacing and adds ±32-byte stride controls. With requested words and containing test-line count fixed, full throughput persists at a 252 MiB span but drops between 252 and 256 MiB; exact 4-KiB spacing falls from 42.590/41.784 Glookup/s at 128 MiB to 34.315/34.451 at 256 MiB on global/texture. Separately, exact 512- and 1,024-byte pitches create severe texture-path aliasing that disappears when pitch is shifted by one 32-byte region. At target 7 MiB, texture reaches 42.802, 28.621 and 43.007 Glookup/s for 992-, 1,024- and 1,056-byte strides while global remains near 42.8 throughout. This yields two actionable terms—general address-span reach and exact stride/index aliasing—without labeling either as a measured TLB or cache-set structure. The three page/span/skew corpora add 2,592 valid rows and 656.38 billion timed GPU lookups.

A ninth native CUDA control removes physical-capacity ambiguity with VMM aliasing. Every virtual slot maps the same single 2 MiB device-local allocation, 18x smaller than the 36 MiB L2, and global/texture paths share the exact mapping. At 1,104 warps both stay near 42.9 Glookup/s through 240 MiB virtual reach, then global falls to 39.523/35.663/34.439 Glookup/s at 248/252/256 MiB while texture agrees within about 0.5%. Holding alias count fixed reproduces the loss: 32 aliases fall from 42.976 at 64 MiB to 33.717 Glookup/s at 250 MiB. Thus virtual address distribution/reach is causal even with constant physical backing; the timing does not identify an undocumented page size or TLB. Four balanced processes validate 368 rows and 77.66 billion timed lookups.

A tenth CUDA VMM control explicitly requests generic-compressible memory and verifies the effective handle property. It finds a sharp content limit: periodic and entropy-dense packed6 LUTs retain generic/non-compressible median ratios of essentially 1.000x and keep the same 36-40 MiB cliff, so hardware compression adds no usable capacity to an ordinary information-bearing packed LUT. All-zero and independently validated all-one global controls remain at about 38.6 Glookup/s through 240 MiB—6.667x nominal L2 allocation capacity and 335,544,320 packed codes—but drop at 248 MiB with the independent address-reach limit. This is a throughput-equivalent bound for constant, zero-information data, not a measured physical compression ratio. A nonzero sentinel also invalidates the spectacular zero-texture curve: its zero checker masked wrong returned values, while periodic/entropy texture and all-one global paths remain valid. The all-one corpus contributes 96 valid rows and 34.73 billion timed lookups; the zero-texture rows remain only as an explicit erratum.

An eleventh exact-binary VMM study maps useful sparse content between those endpoints. For one code 1 every 64-256 packed codes, the generic-compressible global path retains 99% of its best rate only through 64 MiB; interval 512 reaches 128 MiB; non-power-of-two intervals 544-704 move the boundary through 160-224 MiB; and intervals 736-4,096 reach the independent 240 MiB address ceiling. Six observable format-series cliffs contain 411,207-478,298 nonzero exceptions at their last full-rate point, a descriptive layout-specific band rather than a physical compressor capacity. A uniform logical code 1 and deterministic mixed 0/1 stream gain no capacity, so low alphabet size alone is insufficient. Across the main, interpolation and format-refinement corpora, the frozen `sm_120` executable validates all 1,872 rows, 1.984 billion payloads and 677.212 billion timed lookups. The protocol and binary are under `benchmarks/cuda_vmm_sparse_exact/`.

A twelfth native CUDA control tests the exact externalized threshold-code stream from the current synthetic G24 producer. Its uniform confidence floor 0.70 rounds to binary16 0.7001953125 and quantizes to code 8; sixteen codes pack as `0x08208208 0x82082082 0x20820820`. Across four balanced processes, all 256 rows, 271.319 million payloads and 92.610 billion timed global/texture lookups validate. The median generic/non-compressible ratio across 32 size/path pairs is 0.999993x, and both allocation modes retain 99% of their best rate only through 36 MiB on both paths. Thus even this uniform semantic value gains no hardware-compressed cache capacity after physical packing; the exact 2.667x software-density gain remains, while the current stream gets no additional compression multiplier. Frozen evidence and limitations are under `benchmarks/cuda_vmm_g24_code8_isolated/`.

A thirteenth exhaustive native control enumerates all 64 uniform 6-bit values through the valid raw global/L2 path. A 32-bit boundary advances two places through the repeated six-bit motif, so only codes 0, 21, 42 and 63 produce three identical packed words: `0x00000000`, `0x55555555`, `0xAAAAAAAA` and `0xFFFFFFFF`. Those are exactly the four codes that extend beyond 36 MiB. Codes 0/63 remain full through the 240 MiB address limit; codes 21/42 have a balanced 99%-rate endpoint at 70 MiB and fall below it at 72 MiB; the other 60 codes stop at 36 MiB. Eight balanced processes validate 3,616 rows, 3.832 billion payloads and 1.308 trillion timed lookups. A parameterized texture sentinel is rejected separately: 24 nonzero rows produce 424.113 million mismatches while zero falsely validates. Protocol, frozen binary and all-code map are under `benchmarks/cuda_vmm_uniform6_exact/`.

A fourteenth native control asks whether that benefit survives a table containing both compressible extremes rather than one constant. Approximately balanced code-0/code-63 sequences remain fully validated when the value changes pseudorandomly per 12-byte packed group or in controlled runs. The balanced 99%-rate endpoint is 72 MiB for hashed or 12-96-byte runs, 88 MiB for 192-byte runs, and the independently address-bounded 240 MiB for every tested run from 384 through 12,288 bytes. Eight processes validate 2,064 rows, 2.188 billion payloads and 746.670 billion timed raw-global lookups with zero mismatches. This proves a bounded information-bearing two-symbol class, not arbitrary-data compression or a 384-byte hardware block; frozen evidence is under `benchmarks/cuda_vmm_blockmix063_exact/`.

A fifteenth native control expands the same packed table to all four individually compressible uniform codes: 0, 21, 42 and 63. Sixteen order-balanced processes validate 3,560 rows, 3.773 billion payloads and 1.288 trillion timed raw-global lookups with zero mismatches. Under the declared within-corpus 99%-rate rule, hashed/12-192-byte symbol runs have 40-82 MiB endpoints and tested 384-12,288-byte runs have 120-168 MiB endpoints. The strongest case is a 768-byte symbol run at 168 MiB, or 4.667x nominal L2 allocation, but longer runs regress non-monotonically. This proves a broader deterministic mixture class while rejecting any simple run-length law, arbitrary-data claim or physical compression ratio; frozen evidence is under `benchmarks/cuda_vmm_blockmix4_exact/`.

The G20 cold-lineage experiment retains the same 24-byte total state storage but splits it into a 20-byte geometry/meta hot stream plus a 4-byte lineage stream loaded only by verified lanes. Across six isolated balanced processes, at 4,194,304 candidates it measures 1.108x higher append throughput and 1.110x higher counted-path throughput than G24. Native NVIDIA compiler metadata reports identical register, shared-memory, and binary-size values for the two append kernels, strengthening the locality attribution. This is a measured locality improvement, not a claim of 20-byte total storage.

## Core execution path

```text
finite grammar / typed state
  -> radial-angular support
  -> compatibility
  -> relation guard
  -> verified event
  -> route / lineage / novelty log
```

## Source and engineering boundary

The source corpus is treated as a design record. Exact numeric, geometric and topological operators are retained; ambiguous motifs are translated into typed constructs; unsupported physical or totalizing claims are rejected or demoted. Standard `100%` remains 1. The addendum's `100100_2 = 36_10` is an explicitly versioned glyph encoder, not ordinary percentage arithmetic.
