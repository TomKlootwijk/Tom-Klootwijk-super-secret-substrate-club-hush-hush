# Validation performed while preparing KLB SeedChain GPU 0.2.0

## Preparation environment

```text
C++ compiler:      g++ 14.2.0
CMake:             3.31.6
CUDA nvcc:         unavailable
NVIDIA GPU:        unavailable
CUDA syntax parser: Clang 17.0.0
```

## Clean CPU build

Commands:

```bash
cmake -S . -B build_verify \
  -DKLB_BUILD_CUDA=OFF \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build_verify -j2
ctest --test-dir build_verify --output-on-failure
```

Result:

```text
100% tests passed, 0 tests failed out of 1
```

The CPU tests cover:

- 37-bit writes and reads across every 32-bit alignment;
- even parity on generated records;
- XOR swizzle involution;
- discrete Klein x periodicity and reflected y seam;
- ASCII and binary-little-endian PLY input;
- synthetic point generation and KLB37 pack/decode;
- payload hash and save/load round trip;
- ordered base packing for stable sequence correspondence;
- generated SeedChain construction with checkpoints and sparse novelty;
- parent links, node hashes, terminal chain hash, and save/load;
- bounded random-access frame reconstruction;
- fitted sequence prediction with a sparse external edit;
- global sequence reconstruction error reporting.

## Included chain generation

Command:

```bash
build_verify/klb_seedchain create \
  data/procedural_65536.klb \
  data/procedural_65536_240f.klsc \
  --frames 240 \
  --checkpoint 16 \
  --novelty-rate 0.001 \
  --novelty-lifetime 8
```

Observed values:

```text
points                         65,536
frames                         240
maximum linked depth           15
base-word bytes                303,112
node bytes                     23,040
novelty bytes                  583,984
container bytes                910,392
bytes per point-frame          0.057881
ratio versus dense float3      207.321330x
ratio versus dense float4      276.428440x
novelty density                0.232054%
terminal chain hash            0x3431646e6069c6d7
file SHA-256                   eb0680b72a3a5f6b2cc9f05a1f60a6a09a858bb6d831f63de275f7b3aa0f4fe9
```

The generated file was loaded again, its canonical size checked, its embedded KLB payload hash verified, every parent/self hash verified, and the terminal hash matched.

## Fitted-sequence CLI test

A five-frame, 256-point PLY sequence was generated locally with uniform scale, Y rotation, translation, and one sparse external edit. Commands:

```bash
build_verify/klb_seedchain fit-sequence frames.txt fitted.klsc \
  --checkpoint 2 --residual-threshold 0.002
build_verify/klb_seedchain verify-sequence frames.txt fitted.klsc
build_verify/klb_seedchain export fitted.klsc 3 rebuilt_0003.ply
```

Observed verification:

```text
container bytes                 1,944
novelty records                 1
ratio versus dense float3       7.901235x
RMS error                       0.00079108
maximum error                   0.00198069
RMS/base radius                 0.06691498%
maximum/base radius             0.16754097%
```

This confirms the adapter, fitting path, sparse residual chain, independent verifier, and exporter. The ratio versus source PLY bytes reflects the verbosity of the test ASCII PLY files and is not a universal geometry-codec metric.

## CUDA translation-unit syntax validation

Neither `nvcc` nor a GPU was installed. Both `.cu` files were nevertheless parsed in host and device modes with Clang 17 using a local declaration-only CUDA stub. `sm_90` was selected solely because that Clang build does not recognize `sm_120`; no code generation, linkage, or execution was claimed.

Equivalent parser commands:

```bash
clang++ -std=c++20 -x cuda --cuda-host-only \
  --cuda-gpu-arch=sm_90 -nocudainc -nocudalib \
  -D__CUDACC__ -I<cuda-declaration-stub> -Iinclude \
  -fsyntax-only src/bench.cu

clang++ -std=c++20 -x cuda --cuda-device-only \
  --cuda-gpu-arch=sm_90 -nocudainc -nocudalib \
  -D__CUDACC__ -I<cuda-declaration-stub> -Iinclude \
  -fsyntax-only src/bench.cu

# The same two commands were run for src/seedchain_bench.cu.
```

All four host/device parses completed without errors after the stub declared the CUDA runtime and device math interfaces.

This check can catch C++/CUDA annotation and device-callability errors, but it cannot establish:

- CUDA 12.8 `sm_120` compiler compatibility;
- successful CUDA runtime linkage;
- correct behavior on Blackwell hardware;
- performance, occupancy, registers, cache traffic, power, or thermals.


## Adapter and launcher checks

- Every Linux shell script passed `bash -n`.
- `tools/xyz_to_ply.py` and `tools/make_frame_list.py` passed Python bytecode compilation; both tools were also smoke-tested during preparation.
- PowerShell Core was not installed in the preparation environment. The `.ps1` launchers were reviewed as text but were not parsed or executed here; Windows execution remains part of the target-laptop validation.

## Required first validation on the RTX laptop

Build and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
.\build\Release\klb_seedchain_bench.exe `
  .\data\procedural_65536_240f.klsc `
  --frame 239 --mode all --repeats 20 --verify 4096
```

The first accepted run should show:

```text
CPU/GPU RMS difference within the printed tolerance
CPU/GPU maximum difference within the printed tolerance
Lineage mismatches = 0
same verified-event count for compressed and dense query modes
exact sorted point/lineage event-set match, with SDF/guard values within tolerance
```

The benchmark compares counts first and, by default, exactly compares up to 1,048,576 sorted compact events outside the timed section. A difference in point identity, lineage/route, SDF, or guard is a failure even when position RMS is small. This runtime path still requires execution on the target CUDA machine.

## Hardware measurement boundary

Record at least:

```text
laptop model
GPU device name
compute capability
NVIDIA driver version
CUDA toolkit/runtime version
power/TGP mode
AC/battery state
thermal state
frame index and checkpoint depth
point and novelty counts
query parameters
p50/p95/p99 over repeated process runs
Nsight Compute memory, occupancy, stall, and atomic metrics
```

Do not compare rates across runs that change power mode, precision, checkpoint depth, event yield, or query parameters.
