# CUDA VMM generic-compression allocation probe

The selected RTX 5070 Ti Laptop GPU advertises `CU_DEVICE_ATTRIBUTE_GENERIC_COMPRESSION_SUPPORTED`. This native Driver API probe goes beyond the capability bit: it explicitly requests both non-compressible and generic-compressible pinned device-local allocations, queries the effective property returned by each handle, maps each allocation, fills the complete 2 MiB object, and verifies its first and last words by device-to-host readback.

Results:

| Requested mode | Requested enum | Effective enum | Minimum granularity | Created | Mapped | Full-range endpoint readback |
|---|---:|---:|---:|---|---|---|
| Non-compressible | 0 | 0 | 2,097,152 B | yes | yes | verified |
| Generic compressible | 1 | 1 | 2,097,152 B | yes | yes | verified |

The generic request is therefore accepted rather than silently downgraded. The effective property establishes allocation mode, not achieved compression ratio. CUDA exposes no compression ratio, compressed-L2-byte count, DRAM traffic or compression counter through this query.

Reproducibility:

- source: `gpu/src/ugts_cuda_vmm_compression_probe.cpp`;
- source SHA-256: `9CC989452D3D9DED36A63016AD2E4377E9A5467DFFA6B3788AD84EFA2BC31D64`;
- native executable SHA-256: `DB5631071649BA4B1FC6C906FC485273618E857AF6975E2E9CE19DCC1D517B5C`;
- machine-readable result: `vmm_compression.json`.

```powershell
& gpu/scripts/run_windows_cuda_vmm_compression_probe.ps1
```
