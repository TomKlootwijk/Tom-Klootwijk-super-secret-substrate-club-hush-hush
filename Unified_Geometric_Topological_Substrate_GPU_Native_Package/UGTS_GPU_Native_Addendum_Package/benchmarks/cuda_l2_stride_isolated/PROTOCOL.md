# Native CUDA sparse-stride L2 residency protocol

## Question

Dense 6-bit packing can place 50,331,648 logical codes in this GPU's reported 36 MiB L2 capacity, but that ceiling assumes useful neighboring codes share every fetched cache unit. This experiment asks how much effective L2 capacity remains when each dependent random lookup consumes only one `u32` from a progressively wider spacing. It is designed to bound the workload-level residency amplification, not to name an undocumented NVIDIA cache-sector or physical line size.

## Device and executable

- GPU: NVIDIA GeForce RTX 5070 Ti Laptop GPU
- CUDA target: `sm_120`, CUDA 12.8
- Reported L2: 37,748,736 bytes (36 MiB)
- SMs: 46
- Source: `gpu/src/ugts_cuda_l2_stride_bench.cu`
- Source SHA-256: `DF73B381E5C66532D1ABBD88FCE4F1736ACA443B2270E11FECEB35369145D17B`
- Executable: `gpu/build-windows/ugts_cuda_l2_stride_bench.exe`
- Executable bytes: 554,496
- Executable SHA-256: `B0D753D30D513364CDE2CE1F6CAF56CB8FEFA1EEA219F1E48522F5BC90574A1D`

`ptxas` reports 16 registers, no stack and no spills for both the timed chase and clock-only control. The CUDA occupancy query reports 24 one-warp blocks per SM, or 1,104 warps across 46 SMs. Native `cuobjdump --dump-sass` confirms one static `LDG.E.STRONG.GPU` in the timed loop and two `CS2R ..., SR_CLOCKLO` reads; the zero-step control has the clock reads and no table load. Compute Sanitizer reports zero errors on the final rebuilt executable using 4-, 128- and 256-byte spacing; those smoke timings are excluded.

## Workload construction and validation

One logical node is stored at byte offset `node * stride`, with strides of 4, 8, 16, 32, 64, 128 and 256 bytes. Each node points to the next node in a nonlinear cycle-walked permutation over the exact node count. This avoids the modular resonances and memory-partition camping possible with a simple affine link function. Every unused word between nodes is first filled with deterministic mixed, incompressible-looking data, preventing zero-filled gaps from spuriously improving residency.

Every lane performs 512 strictly dependent, L1-bypassing `ld.global.cg.u32` loads. A 256 MiB global pass evicts L2 before the cold chain; the identical path is repeated immediately for the hot chain. A zero-step kernel supplies the clock-control interval. Complete kernels are timed with CUDA events, while `clock64()` measures exposed in-kernel cycles.

For every measured sample, the CPU independently regenerates and replays the complete 512-link path for the first 64 output lanes of the control, cold and hot kernels. Final node, checksum, seed, step count and monotonic clock interval must all match. All gaps remain part of the physical allocation even though only the pointer word is logically consumed.

## Run matrix

The primary matrix contains four sequentially isolated processes: two traverse target sizes, strides and warp counts in ascending order, and two use the exact reverse. Each covers target values of 4, 8-12, 16-24, 28, 32, 36-40, 48, 56 and 64 MiB; all seven strides; and 184 or 1,104 warps. Four supplemental processes, two in each order, add target values 13, 14 and 15 MiB for 128- and 256-byte strides. Each case uses three discarded warmup sets and twelve measured sets.

The target value defines `node_count * min(stride, 32)`. Consequently, target is the tested effective-footprint hypothesis, while the recorded node count, spacing and allocation bytes are the authoritative physical values. The eight runs contain 1,448 valid rows and aggregate to 362 four-run cases. They validate 3,336,192 CPU payloads, replay 2,224,128 timed endpoints spanning 1,138,753,536 dependent links, and execute **366,678,638,592 measured dependent GPU loads**.

## Full-occupancy capacity result

At 1,104 warps, the following differently spaced node sets all contain the number of active nodes predicted by a 36 MiB footprint at a 128-byte saturation unit, and all retain approximately 43.0 billion logical loads/s:

| Node spacing | Active nodes | Physical allocation | Modeled active footprint | Hot rate |
|---:|---:|---:|---:|---:|
| 32 B | 1,179,648 | 36 MiB | 36 MiB | 42.990 Gload/s |
| 64 B | 589,824 | 36 MiB | 36 MiB | 42.982 Gload/s |
| 128 B | 294,912 | 36 MiB | 36 MiB | 43.004 Gload/s |
| 256 B | 294,912 | 72 MiB | 36 MiB | 42.985 Gload/s |

The hot active-node capacity therefore scales **4:2:1** for 32-, 64- and 128-or-more-byte spacing. A 256-byte-spaced table has twice the allocation of the 128-byte version but nearly the same rate curve. At targets 4, 8, 9 and 10 MiB, the 256/128 hot-rate ratio is respectively 1.0014x, 1.0000x, 0.9995x and 1.0017x. The 3-4% shortfall after the cliff is a modest address-footprint/TLB cost, not a second 2x capacity loss: ratios are 0.9571-0.9706x from targets 12-18 MiB and approach 0.9920x by target 64 MiB.

The 64-byte hypothesis is rejected by the 128-byte-spaced control. At 589,824 active nodes, a 64-byte-per-node model predicts a 36 MiB hot footprint, but the measured rate is only 14.176 Gload/s—0.3296x the 294,912-node hot anchor. The result therefore bounds isolated-word effective residency above 64 bytes and at or below 128 bytes among the tested power-of-two spacings. The appropriate description is **consistent with a 128-byte effective residency unit for this workload**.

## Boundary shape

Dense 4-, 8-, 16- and 32-byte spacings reproduce the same capacity transition. The full-occupancy dense-4 path supplies 43.130, 42.990, 39.493, 29.089 and 23.566 Gload/s at 36, 37, 38, 39 and 40 MiB. For 64-byte spacing, the same curve moves to 18-22 target MiB: 42.982 Gload/s at 18 target MiB/36 MiB allocation, 40.446 at 20/40 MiB, 29.401 at 21/42 MiB and 23.767 at 22/44 MiB. For 128-byte spacing it moves again to 9-12 target MiB: 43.004 Gload/s at 9 target MiB/36 MiB allocation, 42.653 at 10/40 MiB, 41.021 at 11/44 MiB and 29.637 at 12/48 MiB.

This translation by active-node count is the primary evidence. The exact knee is broadened by cache associativity, address translation, scheduling and replacement behavior, so the result should not be interpreted as a perfectly sharp fully-associative capacity model.

## Human-readable limits

For dense packed6 storage, useful codes share cache residency and the average physical representation remains 0.75 byte/code: 50,331,648 codes fit the nominal 36 MiB and 39,146,837 are the arithmetic 28 MiB ceiling. For the isolated **dependent-pointer** access pattern in this experiment, the workload-level effective unit is 128 bytes: only 294,912 active entries fit 36 MiB and 229,376 fit 28 MiB. That is **170.667x fewer active entries** than a fully utilized packed6 stream at the same nominal byte budget. The ratio contrasts two workload endpoints; it is not a universal LUT compression factor.

The follow-on independent packed-LUT line-occupancy control is decisive: one useful code per 128-byte region retains 99.02% of its 28 MiB texture rate at a 40 MiB allocation. Therefore this dependent-chain result must not be applied as a fixed 128-byte throughput charge to every random code lookup. The later sparse-address matrix shows that containing line-address count still matters separately from resident requested portions, with total address span adding another modifier. Packing realizes its storage density exactly; practical cache behavior also depends on which subregions are requested, their probabilities, dependency, ordering, translation and replacement. See `benchmarks/cuda_lut_line_occupancy_isolated/PROTOCOL.md` and `benchmarks/cuda_lut_sparse_address_isolated/PROTOCOL.md`.

## Bounds

The reported 128 bytes is an end-to-end, workload-level effective residency inference from capacity cliffs for this strictly dependent pointer chase. It is not a privileged counter measurement of NVIDIA's physical cache line, sector, tag granularity, associativity, compression behavior or transaction size, and it is not a universal per-entry LUT charge. `Gload/s` counts logical requested `u32` loads, not physical L2 or DRAM traffic. `clock64()` includes scheduling, CUDA events include full kernel overhead, WDDM and laptop clock state remain possible noise sources, and exact cache-sector/DRAM counters remain permission-blocked.

Primary raw results are in `f1/`, `r1/`, `f2/` and `r2/`; the 13-15 MiB refinements are in `s1/`, `sr1/`, `s2/` and `sr2/`. The checked aggregate is `aggregate/cuda_l2_stride_aggregate.json`; flat results and the paired 128/256-byte comparison are in the same directory.
