# Native CUDA one-code line-address refinement

## Purpose

This is the exact `K = 1` continuation of the packed-LUT line-occupancy study. It samples 40 through 48 MiB in one-MiB steps to tighten the broad transition for one independently selected packed6 code in each aligned 128-byte region. “Line” and “line-equivalent” describe the controlled layout; they are not a performance-counter declaration of NVIDIA hardware.

## Device and executable

- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- CUDA target: `sm_120`, CUDA 12.8
- Reported L2: 37,748,736 bytes (36 MiB)
- Source: `gpu/src/ugts_cuda_lut_line_occupancy_bench.cu`
- Source SHA-256: `F7713E9E15A8781AC25197A750F838DF35263DFB569AE9452F8AB36989D3386E`
- Executable: `gpu/build-windows/ugts_cuda_lut_line_occupancy_bench.exe`
- Executable bytes: 637,440
- Executable SHA-256: `DCBB29C5837B860C519A02A0ACF7BAAF3E79B348449404B9CE71600588921051`

The native instruction/occupancy audit is inherited from the parent protocol: 26 registers for the global timed kernel, 22 for texture, 18 for controls, zero stack/spills, and 24 resident one-warp blocks per SM. Timed SASS contains one unconditional plus one predicated `LDG.E.STRONG.GPU` or `TLD.LZ`; controls contain no table load.

## Run design and validation

Four isolated processes (`f1`, `r1`, `f2`, `r2`) cover 40-48 MiB, `K = 1`, 184 and 1,104 warps, both native paths, three discarded warmup sets and twelve measured sets. Two processes traverse tables/warps ascending, two descending; global/texture path order is balanced 2:2.

All 144 raw rows and 36 aggregate cases validate. The CPU validates 165,888 payloads and replays 56,623,104 code checks. Timed kernels execute 36,465,278,976 GPU lookups. The common source/executable hashes above and per-run JSON hashes are recorded in the aggregate.

## Full-occupancy result

| Line-equivalent allocation | Aligned 128-byte lines | Requested 32-byte span | Texture rate | Retention versus 40 MiB |
|---:|---:|---:|---:|---:|
| 40 MiB | 327,680 | 10.00 MiB | 42.997 Glookup/s | 100.00% |
| 41 MiB | 335,872 | 10.25 MiB | 42.794 Glookup/s | 99.53% |
| 42 MiB | 344,064 | 10.50 MiB | 42.401 Glookup/s | 98.61% |
| 43 MiB | 352,256 | 10.75 MiB | 41.785 Glookup/s | 97.18% |
| 44 MiB | 360,448 | 11.00 MiB | 38.330 Glookup/s | 89.15% |
| 45 MiB | 368,640 | 11.25 MiB | 35.002 Glookup/s | 81.40% |
| 46 MiB | 376,832 | 11.50 MiB | 32.275 Glookup/s | 75.06% |
| 47 MiB | 385,024 | 11.75 MiB | 30.004 Glookup/s | 69.78% |
| 48 MiB | 393,216 | 12.00 MiB | 28.137 Glookup/s | 65.44% |

The first measured point below 95% of the 40 MiB rate is 44 MiB. The strongest adjacent change is therefore bounded between 43 and 44 MiB, or 352,256 and 360,448 controlled line addresses. The decline remains broad after that point, so this is an empirical transition band rather than an exact cache-tag capacity.

## Artifacts and bounds

Raw results are in `f1/`, `r1/`, `f2/`, and `r2/`; machine-readable aggregate and CSV tables are in `aggregate/`. Exact L2 hits, sector traffic, tag occupancy, associativity, set mapping and TLB events remain unavailable because NVIDIA performance-counter permission is blocked. Rates are logical decoded-code throughput under WDDM, not physical transactions or strict bare-metal measurements.
