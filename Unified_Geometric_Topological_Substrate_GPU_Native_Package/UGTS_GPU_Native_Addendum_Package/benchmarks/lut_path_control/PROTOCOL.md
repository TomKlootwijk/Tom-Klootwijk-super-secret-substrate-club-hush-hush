# Uniform-texel-buffer versus SSBO control protocol

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU  
Execution: direct Vulkan compute, sequential host processes

This experiment isolates the read path. Both shaders consume the same
device-local buffer bytes, two packed unsigned 16-bit log codes per `uint`, and
execute the same mask read, sequential or `mix32` random index, code extraction,
output hash, and storage-buffer write. The experimental shader reads binding 0
through `UNIFORM_TEXEL_BUFFER`/`OpImageFetch`; the control reads binding 2
through `STORAGE_BUFFER`/`OpLoad`.

The processes ran one at a time in order `f1`, `r1`, `f2`, `r2`. Forward order
is texture-sequential, SSBO-sequential, texture-random, SSBO-random. Reverse
order is the exact reverse. Each process exited successfully before the next
started.

All four used one executable:

- path: `gpu/build-windows/ugts_vulkan_lut_bench.exe`
- size: 351,744 bytes
- SHA-256: `C6A142C9C10F44812831CC2EA726C64135A52230E911AEB78231AA4FA3AD39DD`
- result schema: `UGTS-VK-LUT-CACHE-1.1`

Shared parameters:

- logical entries: 2,048; 16,384; 131,072; 1,048,576; 8,388,608;
  16,777,216; 33,554,432; 67,108,864
- packed table sizes: approximately 4 KiB through 128 MiB
- minimum candidates: 4,194,304; larger tables use one candidate per logical
  entry so each warmed dispatch covers the declared address range
- 10 untimed warmups plus at least 750 ms of warmup
- 200 timestamped dispatches per case
- external L2 size: 37,748,736 bytes

All 128 result rows validated every output, totaling 2,281,701,376 checked GPU
outputs. No process or row was filtered from the paired aggregate. Small cases
show WDDM/laptop clock-order variation, so the aggregate preserves process-level
min/max ratios and uses the median of within-process texture/SSBO ratios.
