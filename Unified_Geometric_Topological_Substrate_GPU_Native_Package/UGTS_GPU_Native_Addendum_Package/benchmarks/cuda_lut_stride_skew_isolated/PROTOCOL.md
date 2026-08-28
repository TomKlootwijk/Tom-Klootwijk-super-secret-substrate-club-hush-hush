# Native CUDA sparse-LUT stride-skew protocol

## Question

Power-of-two strides in the page-span sweep produced path-specific, non-monotonic losses. This control offsets the 512-, 1,024-, 2,048- and 4,096-byte layouts by one 32-byte address region where allocation limits allow. It asks whether those losses follow total address span smoothly or depend on exact address-bit alignment.

## Common native path

This corpus uses the exact source/executable documented by the page-stride protocol: source SHA-256 `1F6D50F63F55934F96CBC2245ABD0FB52BF58453730E0DCF118491B7293C2BB9`, executable SHA-256 `07712EC7EE16831AE4F29B389C371A4FCCB784682D43AD10F432620E6040CC49`. The one-load `LDG.E.STRONG.GPU`/`TLD.LZ` SASS, occupancy, validation and sanitizer bounds are unchanged.

Four isolated, fully order-balanced runs cover targets 3-8 MiB, 184/1,104 warps and strides 480/512/544, 992/1,024/1,056, 2,016/2,048/2,080, and 4,064/4,096 bytes. All **1,056 raw rows** and 264 aggregate cases validate. The CPU validates 1,216,512 payloads and replays 415,236,096 code checks; timed kernels execute **267,412,045,824 GPU lookups**.

## Power-of-two texture alias

At target 7 MiB, useful code count, requested data and containing test-line count are identical. All spans remain below the general 252-256 MiB transition:

| Stride | Allocation span | Global | Texture | Texture/global |
|---:|---:|---:|---:|---:|
| 992 B | 217 MiB | 42.792 G/s | 42.802 G/s | 1.0002x |
| 1,024 B | 224 MiB | 42.792 G/s | 28.621 G/s | 0.6688x |
| 1,056 B | 231 MiB | 42.807 G/s | 43.007 G/s | 1.0047x |

Adding or subtracting a single 32-byte region restores the complete texture rate while leaving the global rate unchanged. This is direct timing evidence for harmful exact-power-of-two address-index aliasing on the native texture path. It is not a reverse-engineered set or bank number.

The 512-byte case is even sharper at target 8 MiB:

| Stride | Allocation span | Global | Texture |
|---:|---:|---:|---:|
| 480 B | 120 MiB | 42.797 G/s | 42.805 G/s |
| 512 B | 128 MiB | 42.586 G/s | 26.494 G/s |
| 544 B | 136 MiB | 42.743 G/s | 42.775 G/s |

The exact 512-byte layout loses 38.1% versus either padded texture layout even though the padded allocation is larger on one side. A monotonic page-count or allocation-capacity model is decisively rejected for this loss.

## General span knee remains real

Padding does not remove the separate transition near 256 MiB. At target 4 MiB, 2,016/2,048/2,080-byte strides span 252/256/260 MiB and deliver 42.178/34.318/32.546 Glookup/s globally and 42.194/34.454/32.778 through texture. Both paths agree and the slow 2,080-byte case is not a power of two. The model therefore needs both **total address-span reach** and **stride/index aliasing** terms.

## Engineering consequence

For sparsely accessed packed LUTs on this GPU, avoid exact 512- and 1,024-byte power-of-two pitch when equivalent padding is legal. A 32-byte skew can recover full native texture throughput below the general address-span transition. This recommendation is device/workload-specific and must be remeasured on other architectures.

Raw results are in `f1/`, `r1/`, `f2/`, and `r2/`; aggregates and paired CSV tables are under `aggregate/`.
