# ARM NEON backend contract

The NEON backend is a specified target, not a measured result in this package.

- Load four `uint32x4_t` words.
- Extract the 4-bit operator slot, then `family = slot >> 1` and `kappa = slot & 1`.
- Sign-extend `delta_rho` from the extracted byte.
- Expand `kappa` with `vnegq_u32(kappa)` so each lane is either `0x00000000` or `0xffffffff` before `vbslq_u32` selection.
- Verify per-node parity with a tested byte-popcount/XOR fold or with the scalar oracle; reading bit 31 alone is not a parity check.
- Compare every backend result to the scalar `PackedNode32` oracle under the same codebook, chart and quantization header.
