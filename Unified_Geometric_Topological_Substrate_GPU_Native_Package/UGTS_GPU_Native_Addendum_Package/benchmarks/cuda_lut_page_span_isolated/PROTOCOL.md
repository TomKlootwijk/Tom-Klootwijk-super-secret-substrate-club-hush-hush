# Native CUDA sparse-LUT intermediate-span protocol

This four-process order-balanced matrix bridges the original 128/256-byte address-span comparison and the 4-KiB page-stride control. It holds target at 1-12 MiB while varying 128/256/512/1,024-byte spacing and 184/1,104 warps through matched global and texture instructions.

All 768 raw rows and 192 aggregate cases validate. The CPU checks 884,736 payloads and 301,989,888 decoded codes; timed kernels execute 194,481,487,872 lookups. Source/executable hashes and native SASS are identical to `benchmarks/cuda_lut_page_stride_isolated/PROTOCOL.md`.

The matrix exposes two distinct effects:

- at 1,024-byte spacing, global and texture remain near 42 Glookup/s through target 7 MiB, then the global path enters the broader address-span transition at target 8 MiB/256 MiB allocation;
- at exact 512- and 1,024-byte spacing, texture can degrade earlier and non-monotonically even while global remains hot. The ±32-byte skew matrix proves this component is address-index aliasing rather than a monotonic span/page-count limit.

At targets 11-12 MiB, the previously measured containing-line-address transition overlaps the span effects. Those rows are retained as interaction evidence but are not used to locate the independent 252-256 MiB span boundary.

Raw results are in `f1/`, `r1/`, `f2/`, and `r2/`; machine-readable outputs are under `aggregate/`.
