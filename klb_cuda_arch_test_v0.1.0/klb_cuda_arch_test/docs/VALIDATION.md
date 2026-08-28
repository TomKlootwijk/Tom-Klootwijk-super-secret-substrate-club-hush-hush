# Validation performed while preparing this package

Environment available during preparation:

```text
C++ compiler: g++ 14.2.0
CMake:        3.31.6
CUDA nvcc:    unavailable
NVIDIA GPU:   unavailable
```

Commands run:

```bash
cmake -S . -B build-cpu -DKLB_BUILD_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-cpu -j2
ctest --test-dir build-cpu --output-on-failure
```

Result:

```text
100% tests passed, 0 tests failed out of 1
```

The tests cover:

- 37-bit writes and reads at every possible word-crossing alignment.
- Even parity on generated records.
- XOR swizzle/unswizzle involution.
- Klein x-periodicity and reflected y seam.
- ASCII and binary-little-endian PLY input.
- Synthetic generation, pack, payload hash, save/load, decode, and quantization threshold.

The included `data/procedural_65536.klb` was generated and successfully inspected with the compiled CPU tool. CUDA source was reviewed but could not be compiled or executed in that environment. The first laptop run should retain `--verify 4096` and all three modes.

