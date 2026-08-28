# Source register and evidence boundary

The user-provided source files are not redistributed in this package. Their hashes are recorded so a local copy can be matched to the engineering work.

| Source | SHA-256 | Role |
|---|---|---|
| `Pasted markdown(2).md` | `52b3308c47c21ad5f06ca93ea429e6d308c210e3b2738c349d9f23c29e7d9d72` | Original architecture request: log-polar LUTs, continuous bit packing, parity grammar, implicit tree traversal, Klein routing, cone field, and RTX laptop test |
| `Unified_Geometric_Topological_Substrate_GPU_Native_Addendum(1).docx` | `cb95f7e9036e1b89e009c88ae1849ee71cddb3bdb6629c98593e32f3d65254f8` | Canonical query-first substrate, typed state/event ABI, seed+grammar+novelty persistence, precision contract, validation and kill criteria |
| `klb_cuda_arch_test_v0.1.0.zip` | `fdc90da89d1ffe5015d046ed8a16d804881237f89574c431d3525e4bda8d5276` | Prior KLB37 base implementation used as the code substrate for version 0.2.0 |

## Engineering interpretation retained

The package retains these source-grounded rules:

```text
local support
-> compatibility
-> finite guard crossing
-> verified event
-> route/transition
-> lineage + novelty log
```

```text
closed deterministic state = rebuild from seed + grammar + node parameters
external unpredictable change = store in ordered novelty records
```

```text
packed representation is accepted only when reconstruction error stays below the declared event margin
```

## Corrections and boundaries

The implementation deliberately does not claim:

- that VRAM is physically a Klein bottle;
- that one bit contains complete state;
- that a packed format has zero latency, heat, memory, or bandwidth;
- that every dataset is reconstructible from a small seed;
- that 50×, 200×, or 500× compression applies to arbitrary geometry;
- that a software syntax check proves RTX 5070 Ti performance;
- that FNV hashes prove identity or authorship;
- that topology creates or recycles energy.

## External engineering references

The package build and data recommendations use these public sources:

- NVIDIA CUDA 12.8 features: `https://docs.nvidia.com/cuda/archive/12.8.0/cuda-features-archive/index.html`
- NVIDIA Blackwell compatibility guide: `https://docs.nvidia.com/cuda/blackwell-compatibility-guide/index.html`
- NVIDIA Blackwell tuning guide: `https://docs.nvidia.com/cuda/blackwell-tuning-guide/index.html`
- NVIDIA RTX 50-series laptop specifications: `https://www.nvidia.com/en-eu/geforce/laptops/50-series/`
- Stanford 3D Scanning Repository: `https://graphics.stanford.edu/data/3Dscanrep/`

These links are not bundled data or third-party code dependencies.
