# Native CUDA VMM physical-backing control

## Question

The ordinary CUDA sparse-LUT sweep loses throughput when a fixed number of requested words is distributed across roughly 252-256 MiB of allocation. That result cannot by itself distinguish physical data residency, address reach, translation state, or an address-index interaction. This control asks a narrower question:

> Does the same transition survive when the physical allocation and accessed physical payload remain exactly 2 MiB while only the number and placement of virtual aliases changes?

## Controlled mapping

The CUDA Driver API reports a 2,097,152-byte minimum allocation granularity for pinned device-local VMM on this RTX 5070 Ti Laptop GPU. The benchmark creates exactly one physical allocation of that size. Every 2 MiB virtual slot in the reserved range maps that same allocation handle, so the entire virtual resource is backed but all slots alias the same physical bytes.

Each lookup independently selects:

1. one tested virtual alias; and
2. one pseudorandom `u32` offset inside the shared 2 MiB physical allocation.

The code at a given offset is identical through every alias. The global and texture paths, and both tested warp loads, share the exact same mapping within each case and process. All four primary processes received virtual base address `0x204C00000`. Consequently:

- physical allocation: **2 MiB** in every case;
- accessed physical payload: **2 MiB** in every case;
- measured device L2: **36 MiB**, or 18 times the physical payload;
- virtual span: 64-510 MiB;
- virtual/physical reach ratio: 32x-255x.

The 2 MiB VMM granularity is a driver allocation property. This protocol does not relabel it as a hardware page size and does not infer an undocumented TLB, cache set, or bank.

## Native execution

The benchmark is `gpu/src/ugts_cuda_vmm_alias_bench.cu`:

- source SHA-256: `CED83455B2DC1BFC6F36C7D7996A031B09DBA54D1CB77070D9C639F5C5B42D01`;
- native executable SHA-256: `5337F4E45ADE275BE5787D70A7D868F2F7CCFE85DA60CB46C7E5FCB3120B204E`;
- aggregation tool SHA-256: `C4FED77926A59D84DE8849CF459E9DF22FE568111E30E09D302ADDE83A178E3C`;
- target: native `sm_120`, CUDA 12.8;
- timed kernel resource use: 18 registers, no stack, local memory, shared memory, or spills;
- occupancy: 24 blocks/SM for both timed paths;
- global instruction: one `LDG.E.STRONG.GPU` in the loop body;
- texture instruction: one `TLD.LZ` in the loop body;
- timing: two `CS2R ... SR_CLOCKLO` reads per timed kernel. A third `CS2R ... SRZ` initializes a zero register and is not a clock read.

Each thread performs 512 indexed lookups. A 256 MiB path-matched eviction allocation supplies the cold control; the immediately repeated kernel supplies the hot measurement. Four separate processes use forward/reverse case and path order (`f1`, `r1`, `f2`, `r2`), 184 and 1,104 warps, two warm-up sets, and ten measured sets.

## Validation coverage

All **368 raw rows** and 92 four-run aggregates validate:

- 353,280 CPU-replayed result payloads;
- 227,512,320 complete GPU payloads with zero decoded-code mismatches;
- **77,657,538,560 timed GPU lookups** across cold and hot kernels;
- four repetitions per case/path/load;
- paired mapping equality verified within every process;
- worst four-run hot-throughput range below 2% of the median after replacing one visibly low-clock diagnostic replicate.

Compute Sanitizer memcheck separately covered paired global/texture cases at 64, 254, 256, and 510 MiB virtual spans and reported `ERROR SUMMARY: 0 errors`. Sanitizer timings are excluded.

## Isolated virtual-reach transition

The high-occupancy 2 MiB-pitch sweep holds physical backing and physical payload at 2 MiB:

| Aliases | Virtual span | Global hot | Texture hot | Texture/global |
|---:|---:|---:|---:|---:|
| 32 | 64 MiB | 42.976 Glookup/s | 42.879 Glookup/s | 0.9977x |
| 64 | 128 MiB | 42.979 Glookup/s | 42.863 Glookup/s | 0.9973x |
| 96 | 192 MiB | 42.973 Glookup/s | 42.870 Glookup/s | 0.9976x |
| 112 | 224 MiB | 42.975 Glookup/s | 42.799 Glookup/s | 0.9959x |
| 120 | 240 MiB | 42.975 Glookup/s | 42.838 Glookup/s | 0.9968x |
| 124 | 248 MiB | 39.523 Glookup/s | 39.539 Glookup/s | 1.0004x |
| 126 | 252 MiB | 35.663 Glookup/s | 35.687 Glookup/s | 1.0006x |
| 127 | 254 MiB | 34.842 Glookup/s | 34.879 Glookup/s | 1.0011x |
| 128 | 256 MiB | 34.439 Glookup/s | 34.456 Glookup/s | 1.0005x |
| 129 | 258 MiB | 34.183 Glookup/s | 34.294 Glookup/s | 1.0032x |
| 130 | 260 MiB | 34.224 Glookup/s | 34.189 Glookup/s | 0.9990x |
| 132 | 264 MiB | 31.942 Glookup/s | 31.943 Glookup/s | 1.0001x |
| 136 | 272 MiB | 30.298 Glookup/s | 30.298 Glookup/s | 1.0000x |
| 144 | 288 MiB | 27.917 Glookup/s | 27.907 Glookup/s | 0.9996x |
| 160 | 320 MiB | 24.901 Glookup/s | 24.913 Glookup/s | 1.0005x |
| 192 | 384 MiB | 21.568 Glookup/s | 21.565 Glookup/s | 0.9999x |

The global path loses 8.0% from 240 to 248 MiB, 17.0% by 252 MiB, and 19.9% by 256 MiB. The texture path follows the same curve. The transition therefore survives with only 2 MiB of physical storage and cannot be explained by overflowing the 36 MiB L2 with unique physical data.

## Fixed-alias controls

Changing alias count is not required for the loss:

| Fixed aliases | Virtual span | Global hot | Texture hot |
|---:|---:|---:|---:|
| 32 | 64 MiB | 42.976 Glookup/s | 42.879 Glookup/s |
| 32 | 126 MiB | 42.981 Glookup/s | 42.869 Glookup/s |
| 32 | 188 MiB | 42.978 Glookup/s | 42.829 Glookup/s |
| 32 | 250 MiB | 33.717 Glookup/s | 33.776 Glookup/s |
| 64 | 128 MiB | 42.979 Glookup/s | 42.863 Glookup/s |
| 64 | 254 MiB | 34.561 Glookup/s | 34.570 Glookup/s |
| 64 | 380 MiB | 21.889 Glookup/s | 21.892 Glookup/s |
| 64 | 506 MiB | 18.509 Glookup/s | 18.509 Glookup/s |

At fixed 32 aliases, extending virtual pitch from 2 to 8 MiB reduces the global rate 21.5% while every lookup still resolves to the same 2 MiB physical allocation. At fixed 64 aliases, extending the span from 128 to 254 MiB costs 19.6%. This is direct evidence that virtual address distribution/reach is causal for this workload.

The close 250-256 MiB rates obtained from 32 aliases at 8 MiB pitch, 64 aliases at 4 MiB pitch, and 127-128 aliases at 2 MiB pitch show span is the leading term. Their residual differences mean alias count, pitch, or address-bit layout remains a secondary term; the experiment does not claim a pure one-variable hardware model.

## Texture-cache consequence

Once global and texture paths share the exact mapping, their high-occupancy rates agree within about 0.5% throughout the span sweep. The texture object neither avoids nor materially worsens the VMM reach transition. A packed/log-encoded LUT can use the texture path, but physical packing does not by itself remove this independent address-reach ceiling. Keep the active virtual footprint below roughly 240 MiB for full rate on this tested layout, and begin treating 248-256 MiB as the transition zone.

## Reproduction

```powershell
& gpu/scripts/build_windows_cuda_vmm_alias.ps1
& gpu/scripts/run_windows_cuda_vmm_alias.ps1 -SkipBuild -OutputDirectory benchmarks/cuda_vmm_alias_isolated/f1 -Cases '32x2,32x4,32x6,32x8,64x2,64x4,64x6,64x8,96x2,112x2,120x2,124x2,126x2,127x2,128x2,129x2,130x2,132x2,136x2,144x2,160x2,192x2,128x4' -Warps '184,1104' -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 0
& gpu/scripts/run_windows_cuda_vmm_alias.ps1 -SkipBuild -OutputDirectory benchmarks/cuda_vmm_alias_isolated/r1 -Cases '32x2,32x4,32x6,32x8,64x2,64x4,64x6,64x8,96x2,112x2,120x2,124x2,126x2,127x2,128x2,129x2,130x2,132x2,136x2,144x2,160x2,192x2,128x4' -Warps '184,1104' -EvictionMiB 256 -Warmup 2 -Samples 10 -Order 1
# Repeat the preceding two runs as f2/r2 with the same 0/1 orders.
py gpu/tools/aggregate_cuda_vmm_alias.py benchmarks/cuda_vmm_alias_isolated/f1 benchmarks/cuda_vmm_alias_isolated/r1 benchmarks/cuda_vmm_alias_isolated/f2 benchmarks/cuda_vmm_alias_isolated/r2 --out-dir benchmarks/cuda_vmm_alias_isolated/aggregate
```

Raw JSON/CSV results are under `f1/`, `r1/`, `f2/`, and `r2/`. Machine-readable aggregate and paired path tables are under `aggregate/`.
