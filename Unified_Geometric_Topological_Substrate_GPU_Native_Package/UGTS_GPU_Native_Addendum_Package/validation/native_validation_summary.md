# Native validation summary

- Runtime: Vulkan compute
- Device: SwiftShader Device (Subzero) (Vulkan 1.3.0)
- physical_gpu_claim: `false`
- Benchmark cases: 16
- Counter validation: `true`
- Sample validation: `true`
- Largest batch: 1,048,576

| Profile | Mode | Device p50 ms | CER M/s | SET M/s | ESB GB/s | Verified |
|---|---|---:|---:|---:|---:|---:|
| G64_E32 | evaluate | 12.528 | 83.700 | 4.113 | 8.035 | 51,521 |
| G64_E32 | evaluate_commit | 21.963 | 47.743 | 2.346 | 4.583 | 51,521 |
| G32_E16 | evaluate | 13.307 | 78.798 | 3.748 | 3.782 | 49,878 |
| G32_E16 | evaluate_commit | 19.172 | 54.693 | 2.602 | 2.625 | 49,878 |

This is a direct Vulkan API validation on a software/CPU Vulkan device, not a physical-GPU performance claim.
