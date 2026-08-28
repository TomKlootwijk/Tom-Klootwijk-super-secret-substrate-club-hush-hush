# CUDA driver VMM granularity probe

The native CUDA driver reports virtual-memory-management support and a minimum/recommended **2,097,152-byte (2 MiB)** allocation granularity for pinned device-local generic allocations on the selected RTX 5070 Ti Laptop GPU. It also reports generic compression capability and the same 37,748,736-byte L2 size used by the benchmarks.

- Source: `gpu/src/ugts_cuda_vmm_granularity_probe.cpp`
- Source SHA-256: `6F1476536DAEC0DB510AB23D14C6ED0C5A1E80781D357F48B952F1E55895DF0D`
- Executable: `gpu/build-windows/ugts_cuda_vmm_granularity_probe.exe`
- Executable bytes: 368,128
- Executable SHA-256: `6B75D64B17B0FBE61A3747981F10F9863B5BC532FE7C1208F5D004204D80BD64`
- Machine-readable result: `vmm_granularity.json`

This is a driver allocation-property query, not a GPU performance counter. It does not establish the translation page size used by `cudaMalloc`, the number of TLB entries, whether benchmark allocations were compressed, or physical page-walk traffic. Benchmark gaps contain mixed data and no compressible VMM allocation was requested.
