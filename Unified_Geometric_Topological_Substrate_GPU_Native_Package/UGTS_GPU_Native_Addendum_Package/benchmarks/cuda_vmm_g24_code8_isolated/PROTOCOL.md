# Native G24 code-8 packed-LUT compression protocol

Date: 2026-08-15  
Device: NVIDIA GeForce RTX 5070 Ti Laptop GPU, CUDA compute capability 12.0  
Driver: 591.59  
Reported L2: 37,748,736 bytes (36 MiB)  
CUDA compiler: 12.8.61  
Compute Sanitizer: 2025.1.0.0, zero reported errors

## Question

If the current G24 producer's confidence threshold is externalized into the proposed dense packed 6-bit LUT, does a driver-confirmed generic-compressible CUDA allocation extend its throughput-equivalent L2 capacity?

This is narrower than a claim about arbitrary knowledge.  It tests the exact threshold-code stream emitted by the package's current synthetic G24 workload, not a production distribution and not the complete interleaved 24-byte G24 state record.

## Exact mapping

The current producer sets `confidence_floor = 0.70` for every candidate.  Binary16 storage yields 0.7001953125.  The declared G24 transform

```text
round((-log2(binary16(confidence_floor)) / 32) / 0.125 * 63)
```

produces code 8.  Sixteen code-8 values occupy exactly twelve bytes:

```text
0x08208208  0x82082082  0x20820820
```

The group has sixteen set bits in 96 physical bits.  This is the same bit density as packed `const1`, but a different three-word phase pattern.  By contrast, sixteen code-63 values produce three `0xFFFFFFFF` words.  This distinction makes the experiment a test of physical packing, not merely logical entropy or alphabet size.

## Native execution

The exact source, executable, aggregator and summarizer are frozen under `artifacts/`; their sizes and SHA-256 values are in `provenance.json`.  Native disassembly of the timed 512-step kernels records:

| Path | Native load | Registers | Stack/local/shared |
|---|---|---:|---:|
| Raw global, L1 bypass | `LDG.E.STRONG.GPU` | 22 | 0 / 0 / 0 bytes |
| CUDA linear texture object | `TLD.LZ` | 18 | 0 / 0 / 0 bytes |

Both kernels read `SR_CLOCKLO` around the timed dependent loop and reach the queried ceiling of 24 one-warp blocks per SM: 1,104 warps across 46 SMs.  Every timed lookup decodes the packed value and checks it against the independent `code_for` reconstruction.

Four isolated processes use order `0,1,0,1`.  Each covers 4, 28, 32, 36, 38, 40, 48, 64, 96, 128, 160, 192, 208, 224, 240 and 248 MiB, both native paths, both compression modes, two warmup sets and ten measured sets.  Compression modes alternate inside every sample and share the same lookup sequence.  A 256 MiB independent eviction allocation precedes cold measurements.

## Result

| Evidence | Result |
|---|---:|
| Raw/valid rows | 256 / 256 |
| Validated payloads | 271,319,040 |
| Timed native lookups | 92,610,232,320 |
| Invalid rows / decoded mismatches | 0 / 0 |
| Median generic/non-compressible hot ratio, all 32 size/path pairs | 0.999993x |
| Minimum / maximum paired ratio | 0.994175x / 1.012212x |
| 99%-of-best endpoint, raw global, both compression modes | 36 MiB |
| 99%-of-best endpoint, texture, both compression modes | 36 MiB |
| Packed codes at that endpoint | 50,331,648 |

The 36-to-40 MiB hot-rate loss is 38.53%/38.96% for non-compressible/generic global access and 44.69%/45.05% for non-compressible/generic texture access.  Generic compression therefore does not move the current G24 code stream past the nominal L2 boundary.  The texture path also provides no extra capacity tier.

At 38 MiB, generic texture is 1.0122x its paired non-compressible control while generic global is 0.9957x.  Both fall below the declared 99%-of-best endpoint and both collapse at 40 MiB, so this small transition effect is not a capacity extension.

Some cross-process absolute rates below and at L2 vary substantially as the laptop changes clock/performance state; the maximum aggregate repetition range is 60.28%.  The causal comparison survives because compression modes alternate within samples: every one of the 32 paired medians remains within 2% of unity.  Absolute cross-size medians must not be presented without this caveat.

## Interpretation

- A uniform semantic threshold is not enough to obtain useful hardware-compression capacity after dense 6-bit packing.
- Hardware compressibility depends on the physical packed word pattern.  Code 8 becomes a repeating three-word pattern, whereas code 63 becomes uniform all-one words and previously reached the independent 240 MiB address limit.
- Software packing still provides its exact 2.667x code-density gain.  The result rejects an additional hardware-compression multiplier for this current G24 stream on this GPU.
- The result does not measure compressed physical bytes, cache hit rate, cache-sector traffic, DRAM traffic or a portable compressor format.

## Reproduction and validation

The four production runs were launched with `run_windows_cuda_vmm_compression_lut.ps1` using `-SkipBuild`, pattern `ugts_g24_floor70_code8`, 1,104 warps, both paths, the sixteen sizes above, 256 MiB eviction, two warmups and ten samples.  Rebuild from the frozen source if exact executable reproduction is required.

Regenerate the derived summary:

```powershell
python benchmarks\cuda_vmm_g24_code8_isolated\artifacts\summarize.py `
  benchmarks\cuda_vmm_g24_code8_isolated\aggregate\cuda_vmm_compression_lut_aggregate.json `
  --output benchmarks\cuda_vmm_g24_code8_isolated\aggregate\g24_code8_summary.json
```

Validate frozen hashes, all raw rows, aggregate totals and derived conclusions with:

```powershell
python gpu\tools\validate_cuda_vmm_g24_code8.py
```
