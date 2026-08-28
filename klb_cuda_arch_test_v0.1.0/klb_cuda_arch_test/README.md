# KLB37: low-level CUDA test of the proposed packed topology architecture

KLB37 is a standalone C++20/CUDA benchmark that turns the attached architecture description into a falsifiable implementation. It uses raw CUDA allocations and kernels only—no PyTorch, CuPy, OptiX, Vulkan, DirectX, or third-party parsing library.

This is "bare-metal style" rather than literal bare metal: NVIDIA does not expose a documented way to run arbitrary code on a GeForce GPU without the NVIDIA driver and CUDA execution stack.

## What is implemented

- **Continuous packed storage:** every point is a 37-bit record inside a `uint32_t` stream. Records cross byte and word boundaries; there is no per-record padding.
- **Log-polar analogue:** positions are encoded in log-spherical coordinates (`rho`, `theta`, `phi`) and reconstructed in the kernel.
- **Swizzle/unswizzle:** points are Morton-sorted, then records use a reversible 16×16 XOR tile swizzle.
- **Parity-driven bifurcation:** an implicit binary traversal chooses left/right behavior from stored parity, a query key, and a compact L-system symbol.
- **Klein-bottle addressing:** the logical record grid wraps one axis normally and wraps the other with an x-reflection.
- **Swept cone field:** each traversal evaluates an analytic infinite-cone signed field whose angle advances by time, delta, and delta-delta.
- **Measured baselines:** the same traversal runs against 16-byte decoded records, 8-byte `uint64_t` records, and the 37-bit packed stream.
- **Correctness checks:** CPU reference, exact `uint64_t` versus packed GPU comparisons, per-record parity, payload hash, and topology unit tests.

See [`docs/ARCHITECTURE_MAPPING.md`](docs/ARCHITECTURE_MAPPING.md) for the exact mapping and limitations.

## What is deliberately *not* assumed

The source document proposes 50:1–500:1 compression, near-zero VRAM traffic, L2-only execution, and constant-time adaptive raymarching. Those are hypotheses, not properties established by the description. KLB37 reports actual storage, error, timing, and profiler counters instead.

A fixed 37-bit point record has a theoretical payload of **4.625 bytes/point**, or about **2.59× smaller than `float3`** before container/padding overhead. Larger ratios require a different codec, stronger assumptions about the data, or procedural regeneration rather than arbitrary point preservation.

## Target machine

The project is configured for **consumer Blackwell `sm_120`**, matching GeForce RTX 50-series laptop GPUs such as the RTX 5070 Ti Laptop GPU. Use:

- NVIDIA driver that recognizes the laptop GPU.
- CUDA Toolkit **12.8 or newer**; CUDA 12.8 added compiler support for `SM_120`.
- CMake 3.24 or newer.
- Windows: Visual Studio 2022 x64, or a host compiler supported by your installed CUDA Toolkit.
- Linux: a CUDA-supported GCC/toolchain combination.

The CMake target emits both a native `sm_120` image and `compute_120` PTX.

## Build on Windows

From **x64 Native Tools Command Prompt for VS 2022** or PowerShell with Visual Studio and CUDA on `PATH`:

```powershell
cmake -S . -B build -G "Visual Studio 17 2022" -A x64 -DKLB_CUDA_ARCH=120
cmake --build build --config Release
ctest --test-dir build -C Release --output-on-failure
```

Executables are normally placed in `build\Release\`.

The included helper performs the same steps:

```powershell
.\scripts\build_windows.ps1
```

## Build on Linux

```bash
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DKLB_CUDA_ARCH=120
cmake --build build -j
ctest --test-dir build --output-on-failure
```

Or:

```bash
./scripts/build_linux.sh
```

When CUDA is missing, CMake still builds `klb_pack` and the CPU tests. Set `-DKLB_REQUIRE_CUDA=ON` to make missing CUDA a configuration error.

## Run immediately with the included dataset

`data/procedural_65536.klb` is a generated 65,536-point parity-bifurcated L-system sample. It is about 303 KB and requires no external download.

Windows:

```powershell
.\build\Release\klb_bench.exe .\data\procedural_65536.klb `
  --queries 1048576 --depth 12 --repeats 20 `
  --csv procedural_results.csv
```

Linux:

```bash
./build/klb_bench data/procedural_65536.klb \
  --queries 1048576 --depth 12 --repeats 20 \
  --csv procedural_results.csv
```

Generate a larger synthetic test without consuming download bandwidth:

```bash
./build/klb_pack generate procedural_262k.klb \
  --points 262144 --decoded procedural_preview.ply
./build/klb_bench procedural_262k.klb --queries 4194304 --depth 14 --repeats 20
```

The decoded PLY is optional and much larger than the packed file.

## Small real dataset: Stanford Bunny

Recommended manual download:

- Repository page: <https://graphics.stanford.edu/data/3Dscanrep/>
- Direct archive: <https://graphics.stanford.edu/pub/3Dscanrep/bunny.tar.gz>
- Download size: about 4.9 MB; reconstructed model: 35,947 vertices.
- After extraction, use `bunny/reconstruction/bun_zipper.ply`.

The built-in PLY adapter handles ASCII, binary-little-endian, and binary-big-endian PLY without extra libraries:

```bash
./build/klb_pack pack \
  bunny/reconstruction/bun_zipper.ply bunny.klb \
  --decoded bunny_roundtrip_points.ply

./build/klb_bench bunny.klb \
  --queries 1048576 --depth 12 --repeats 30 \
  --csv bunny_results.csv
```

On a Visual Studio multi-configuration build, replace `./build/klb_pack` and `./build/klb_bench` with the corresponding `build\Release\*.exe` paths.

The converter intentionally packs **vertices only** and ignores faces. This makes it a point-layout benchmark, not a complete triangle-mesh codec. Stanford permits research use and free redistribution with attribution but restricts commercial product use; read the repository terms before using the data beyond testing.

For an even smaller external smoke test, Stanford's drill-bit archive is about 0.6 MB:

<https://graphics.stanford.edu/pub/3Dscanrep/drill.tar.gz>

## Understand the output

Each mode reports:

- `ms`: average kernel time per launch.
- `Mquery/s`: completed traversals per second.
- `nominal GB/s`: algorithmic record bytes divided by time. It is **not** a hardware DRAM counter.
- `load-ceil GB/s`: an upper accounting bound from explicit load width; the packed decoder can issue up to three 32-bit word loads per visit.
- `hash`: deterministic aggregate over traversal outputs.

Modes:

- `float`: 16-byte decoded position + metadata; no log decode.
- `u64`: one 8-byte code per logical record; log decode remains.
- `packed`: 37-bit continuous stream + XOR unswizzle + log decode.

The `u64` and `packed` GPU results should match bit-for-bit for the verified queries. CPU/GPU floating-point comparison uses a tolerance, while branch hashes must match exactly.

Run only the packed mode for profiling:

```bash
./build/klb_bench data/procedural_65536.klb \
  --mode packed --queries 1048576 --depth 12 \
  --warmup 0 --repeats 1 --verify 0
```

## Profile real memory and occupancy

Nsight Compute is included with the CUDA Toolkit. A broad report:

```bash
ncu --set full --target-processes all -o klb_packed_report \
  ./build/klb_bench data/procedural_65536.klb \
  --mode packed --queries 1048576 --depth 12 --warmup 0 --repeats 1 --verify 0
```

Use the report's Memory Workload Analysis, Occupancy, Source Counters, and Roofline sections. These counters—not the benchmark's nominal GB/s number—answer whether the kernel is DRAM-, cache-, instruction-, or latency-limited.

The helper scripts are:

```text
scripts/profile_linux.sh
scripts/profile_windows.ps1
```

## VRAM and disk footprint

With the default 1,048,576 queries, the output buffer is 8 MiB. The included dataset and both baselines add only a few MiB. Normal runs remain far below 100 MiB of VRAM and do not need a large local dataset. Increase `--queries` to raise parallel work without increasing disk usage.

## Validation status

In the creation environment, the C++ packer and CPU tests were compiled with GCC 14.2 and CMake 3.31. The tests passed, and the included 65,536-point file was generated and reloaded successfully. That environment had no CUDA compiler or NVIDIA GPU, so the `.cu` target could not be compiled or timed there. Run the build and verification commands above on the RTX laptop; any CUDA compilation or runtime issue should be treated as a project bug rather than as a benchmark result.

