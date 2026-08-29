# RTX 5070 Ti Laptop memory and kernel plan

The profile is dynamic. Query the physical device and allocate from currently free VRAM; do not assume the nominal 12 GB is fully available.

Recommended upper bound:

```
usable = min(0.72 * free_vram, free_vram - 2 GiB)
```

Within `usable`, the default planner assigns 62% to the content-addressed transposition/proof cache, 18% to frontier records, 12% to fixed move buffers and 8% to scratch plus safety headroom. Allocation failure or thermal instability must reduce the batch rather than weaken proof checks.

The 64-byte `PackedPosition` is an exchange/debug record. Production kernels may use a smaller structure-of-arrays hot layout when a versioned decoder reconstructs every required field. A move uses 16 bits: six source bits, six target bits and three promotion bits. Up to 256 moves are reserved per input in the simple correctness-first kernel.

The bundled CUDA mover assigns one position to one thread. It is intentionally simple for differential validation. Later optimization may use warp-cooperative attack generation, prefix sums and compacted move output, but must preserve exact output and deterministic record order.
