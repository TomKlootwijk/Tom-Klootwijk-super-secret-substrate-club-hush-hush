# KLB SeedChain GPU 0.2.0

A direct CUDA/C++ implementation of a **chain-linked, seed-based point-sequence codec and event-query substrate** for an NVIDIA GeForce RTX 5070 Ti Laptop GPU.

The practical application is an animated or time-varying point cloud that can be:

1. stored as one compact 37-bit base state;
2. reconstructed from a deterministic seed and finite grammar;
3. corrected by sparse, chain-linked novelty records; and
4. queried on the GPU for bounded cone/sphere events without first loading every frame as dense `float3` data.

This is low-level CUDA C++ using raw device allocations and kernels. It does not depend on PyTorch, TensorRT, OptiX, Vulkan, Unity, Godot, or a mesh-processing framework. It is not driverless hardware bare metal: the NVIDIA driver and CUDA runtime still provide allocation, launch, synchronization, and profiling.

## Launchpad architecture

```text
37-bit log-spherical base stream
            |
            v
96-byte frame node: seed + predictor + grammar/topology state
            |
            +---- parent hash / self hash ----> next node
            |
            v
checkpoint snapshot + bounded parent walk over sparse novelty deltas
            |
            v
parity grammar -> Klein seam route -> swept cone deformation
            |
            +---- materialize one frame as float3/float4
            |
            +---- direct GPU support + compatibility + SDF guard query
                         |
                         v
                 compact verified-event stream
```

The implementation treats the topology as an explicit address/routing rule, not as a physical property of VRAM. It treats a one-bit route as one field in a larger typed state, not as complete state.

## Deliverables

The package contains:

- `klb_pack`: dependency-free PLY-to-KLB37 conversion and synthetic base generation.
- `klb_seedchain`: creates, fits, validates, inspects, and exports KLSC1 chains.
- `klb_bench`: the original 37-bit extraction/log-decode architecture benchmark.
- `klb_seedchain_bench`: the deployment benchmark comparing direct compressed queries with queries over a materialized dense frame.
- `data/procedural_65536.klb`: a 65,536-point base stream.
- `data/procedural_65536_240f.klsc`: a ready-to-run 240-frame chain.
- A PLY reader for ASCII, binary-little-endian, and binary-big-endian vertices.
- Standard-library-only XYZ/CSV and frame-list adapters under `tools/`.
- CPU oracle tests, file/hash validation, Windows/Linux scripts, and Nsight Compute launchers.

The exact binary layout is documented in [`docs/FILE_FORMAT_KLSC1.md`](docs/FILE_FORMAT_KLSC1.md). The deployment design is in [`docs/SEEDCHAIN_DEPLOYMENT.md`](docs/SEEDCHAIN_DEPLOYMENT.md).

## Included no-download demonstration

The included chain has:

```text
points                         65,536
frames                         240
checkpoint stride              16
maximum parent traversal       15 nodes
container                      910,392 bytes
bytes per point-frame          0.057881
ratio versus dense float3      207.321330x
ratio versus dense float4      276.428440x
novelty density                0.232054% of point-frames
terminal integrity hash        0x3431646e6069c6d7
SHA-256                        eb0680b72a3a5f6b2cc9f05a1f60a6a09a858bb6d831f63de275f7b3aa0f4fe9
```

That ratio is valid for this **reconstructible generated sequence**: most state is recovered from the base, seed, grammar, and predictor, while only sparse novelty is retained. It is not a claim that arbitrary animations, meshes, or scans compress by 207×. Use `fit-sequence` and its reconstruction error report on your data before making a compression claim.

## RTX 5070 Ti Laptop target

The CMake default is `sm_120`, the CUDA target used for consumer Blackwell RTX 50-series GPUs. The build emits:

```text
native cubin: sm_120
PTX fallback: compute_120
```

Use:

- a current NVIDIA driver;
- CUDA Toolkit 12.8 or newer;
- CMake 3.24 or newer;
- a CUDA-supported host compiler;
- Visual Studio 2022 x64 on Windows, or a supported GCC/Clang toolchain on Linux.

CUDA 12.8 introduced compiler support for `SM_120`. The RTX 5070 Ti Laptop GPU is an NVIDIA Blackwell laptop GPU with 12 GB GDDR7. The code reads the actual device name, compute capability, global memory, L2 size, SM count, and memory-bus width at runtime instead of hard-coding performance assumptions.

## Windows quick start

Open an **x64 Native Tools Command Prompt for Visual Studio 2022** or a PowerShell session configured for Visual Studio and CUDA:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\demo_seedchain_windows.ps1
```

Equivalent commands:

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 `
  -DKLB_CUDA_ARCH=120 -DKLB_REQUIRE_CUDA=ON
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure

.\build\Release\klb_seedchain.exe inspect `
  .\data\procedural_65536_240f.klsc

.\build\Release\klb_seedchain_bench.exe `
  .\data\procedural_65536_240f.klsc `
  --frame 239 --mode all --repeats 20 `
  --csv seedchain_results.csv
```

Keep the default CPU/GPU verification enabled on the first run. In `--mode all`, the benchmark also downloads and sorts up to 1,048,576 compact events by default, then verifies that compressed and dense paths produce the same point/lineage event set and numerically equivalent SDF/guard values. Use `--verify-events 0` only after the path is established.

## Linux quick start

```bash
./scripts/build_linux.sh
./scripts/demo_seedchain_linux.sh
```

Equivalent commands:

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release \
  -DKLB_CUDA_ARCH=120 -DKLB_REQUIRE_CUDA=ON
cmake --build build -j
ctest --test-dir build --output-on-failure

./build/klb_seedchain inspect data/procedural_65536_240f.klsc
./build/klb_seedchain_bench data/procedural_65536_240f.klsc \
  --frame 239 --mode all --repeats 20 \
  --csv seedchain_results.csv
```

CMake can still build the CPU tools without CUDA when configured with `-DKLB_BUILD_CUDA=OFF`.

## Benchmark modes

`klb_seedchain_bench` provides three deliberately separated measurements:

- `decode`: reconstruct one target frame from the compressed chain into a 16-byte-per-point GPU buffer.
- `seed`: reconstruct each point inside the query kernel, evaluate support/route/SDF guard logic, and compact verified events with an atomic append.
- `dense`: query an already materialized frame. Frame materialization is performed before timing, so this is the query-only baseline.

When both query modes run, the default validation compares the exact compact event identities after sorting by point index. The comparison is outside the timed section.

Run all modes:

```bash
./build/klb_seedchain_bench data/procedural_65536_240f.klsc \
  --frame 239 --mode all --repeats 30
```

A useful deployment result is not merely the highest compression ratio. Measure whether the direct compressed query is fast enough, whether its output yield is sparse, whether the exact event set agrees with the dense path, and whether avoiding dense sequence storage outweighs reconstruction ALU and parent-chain lookup.

## Create a chain from a real static scan

The recommended small manual download is the Stanford Bunny:

```text
Repository:     https://graphics.stanford.edu/data/3Dscanrep/
Direct archive: https://graphics.stanford.edu/pub/3Dscanrep/bunny.tar.gz
Archive size:   about 4.9 MB
PLY path:       bunny/reconstruction/bun_zipper.ply
```

The package includes optional download scripts, but manual download is sufficient. After extracting:

```powershell
.\build\Release\klb_seedchain.exe create-ply `
  .\bunny\reconstruction\bun_zipper.ply `
  bunny_seedchain.klsc `
  --frames 240 --checkpoint 16 --novelty-rate 0.001

.\build\Release\klb_seedchain_bench.exe bunny_seedchain.klsc `
  --frame 239 --mode all --repeats 30
```

This creates a procedural time sequence around real scan geometry. It does not preserve triangle faces, normals, colors, or materials; the PLY adapter uses vertex positions only.

## Fit an actual PLY animation or scan sequence

Create `frames.txt` with one PLY path per line in time order:

```text
frames/frame_0000.ply
frames/frame_0001.ply
frames/frame_0002.ply
```

All frames must have identical vertex counts and stable vertex correspondence. Then run:

```bash
./build/klb_seedchain fit-sequence frames.txt capture.klsc \
  --checkpoint 16 \
  --novelty-quantum 0.0001 \
  --residual-threshold 0.002
```

The current predictor fits a per-frame uniform scale, Y-axis rotation, and translation. Residuals above the declared threshold become sparse quantized novelty records. Checkpoints store a sparse residual snapshot; intervening nodes store deltas relative to the prior frame.

The command verifies the reconstructed sequence by default and reports global RMS error, maximum error, normalized error, and the worst frame/point. For a very large source sequence, add `--no-verify` during fitting and run the verifier separately:

```bash
./build/klb_seedchain verify-sequence frames.txt capture.klsc
```

Generate a frame list without dependencies:

```bash
python tools/make_frame_list.py frames frames.txt --pattern "frame_*.ply"
```

Convert simple XYZ or CSV point data to PLY:

```bash
python tools/xyz_to_ply.py scan.xyz scan.ply
python tools/xyz_to_ply.py scan.csv scan.ply --delimiter "," --skip-lines 1
```

## Export a reconstructed frame

```bash
./build/klb_seedchain export capture.klsc 120 frame_0120_rebuilt.ply
```

Exporting is optional and can consume more disk space than the chain. Direct GPU querying does not require an exported PLY.

## Tune the chain

The most important controls are:

- `--checkpoint`: maximum novelty parent-walk depth. Lower values reduce random-access work but increase snapshot storage.
- `--novelty-quantum`: residual quantization step as a fraction of the base radius. Larger values reduce precision and may increase sparsity.
- `--residual-threshold`: fitted residuals at or below this radius fraction are omitted.
- `--novelty-rate`, `--novelty-impulse`, and `--novelty-lifetime`: generated-chain workload controls.
- `--branch-amplitude`: procedural grammar deformation amplitude for generated chains.

A packed result is accepted only when position error remains below the application’s guard/event margin and event ordering is unchanged.

## Profile on the laptop

Profile the direct compressed query with Nsight Compute:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\profile_seedchain_windows.ps1
```

or:

```bash
./scripts/profile_seedchain_linux.sh
```

Inspect:

- DRAM and L2 traffic;
- global-load efficiency;
- achieved occupancy and register pressure;
- warp stalls from memory dependency, execution dependency, and atomics;
- integer versus transcendental instruction cost;
- compact-event atomic contention;
- direct compressed query time versus dense-frame query time.

The benchmark’s candidate rate is not a raw memory-bandwidth measurement. Use Nsight Compute counters for actual memory behavior.

## Memory behavior on a 12 GB GPU

The included chain is under 1 MiB. A materialized 65,536-point frame is 1 MiB at 16 bytes per point, and the compact event capacity is another 1 MiB. Normal demonstrations use only a few MiB of device memory.

For a fitted sequence with `P` points, `F` frames, `N` novelty records, and `W` embedded base words, approximate container bytes are:

```text
256 + 96*F + 16*N + 4*W
```

Dense `float3` sequence bytes are:

```text
12*P*F
```

The chain wins on storage only when the predictor and grammar explain enough of the sequence that `N` remains sparse.

## Integrity and identity boundaries

- Every node contains `parent_hash` and `self_hash`, producing an ordered integrity chain from the embedded base payload.
- The current hash is FNV-1a 64-bit. It detects accidental corruption and makes deterministic testing easy, but it is not a cryptographic signature or proof of authorship.
- The 32-bit reconstructed lineage value is a compact routing/check value, not durable identity.
- Durable identity requires the base/generative address, ordered node history, schema version, and external novelty records.

## Validation status

In the preparation environment:

- GCC 14.2 and CMake 3.31 built the CPU implementation from a clean directory.
- All CPU tests passed.
- The included KLSC1 file was generated, saved, reloaded, hash-validated, and inspected.
- Both CUDA translation units passed Clang 17 host-side and device-side CUDA syntax checks using a local declaration stub and `sm_90` solely as a parser target.
- No NVIDIA GPU or `nvcc` was available, so native CUDA 12.8+/`sm_120` compilation and RTX 5070 Ti Laptop timing remain to be run on the target laptop.

See [`docs/VALIDATION.md`](docs/VALIDATION.md) for exact commands and boundaries.

## Interpretation and kill criteria

Do not promote the codec for a workload when any of these conditions holds:

- fitted novelty is no longer sparse;
- checkpoint snapshots dominate the file;
- reconstruction or quantization error crosses the event guard margin;
- compressed decoding is slower than the storage/transfer it avoids;
- compact-event atomics dominate query time;
- point correspondence is unstable or topology changes require dense remapping;
- a conventional geometry/video/point-cloud codec is smaller, faster, or more accurate at the required error.

## Authorship and source provenance

The conceptual attribution requested for this package is recorded in [`AUTHORSHIP_NOTICE.md`](AUTHORSHIP_NOTICE.md). It is reproduced as user-supplied provenance, not as an independently verified legal or identity claim. Source-document hashes and engineering boundaries are in [`docs/SOURCE_REGISTER.md`](docs/SOURCE_REGISTER.md).

## License

See [`LICENSE`](LICENSE). The Stanford Bunny is not included; its own research-use and attribution terms apply separately.
