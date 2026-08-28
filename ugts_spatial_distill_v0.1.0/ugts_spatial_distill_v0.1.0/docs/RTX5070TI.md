# RTX 5070 Ti Laptop Deployment Notes

## Compatibility-first stack

Use a current NVIDIA driver and an official PyTorch CUDA wheel that supports
Blackwell. PyTorch 2.7 was the first release with official Blackwell support and
CUDA 12.8 wheels. The current PyTorch selector should remain the source of truth;
`cu128` is a known baseline.

The project uses only operators shipped in core PyTorch:

- dense linear layers;
- sparse COO index aggregation via `index_add_`/`scatter_reduce_`;
- embeddings, GRUCell and layer normalization;
- ordinary elementwise attention.

No custom `sm_120` extension is required.

## Initial training profile

```text
hidden dimension       256
heads                    8
HGT layers               4
temporal memory        128
precision          FP16 AMP
optimizer            AdamW
```

Run the smaller 64-dimensional profile first. The larger profile should be
promoted only after recording p50/p95/p99, peak memory, power mode and thermal
state.

## Benchmark

```powershell
python -m ugts_spatial benchmark data\demo\graph runs\rtx5070ti\checkpoint.pt --device cuda --warmup 20 --repeats 100 --output runs\rtx5070ti\benchmark.json
```

Record alongside the JSON:

```text
laptop model
GPU power mode/TGP
NVIDIA driver
PyTorch version and CUDA runtime
wall-power or battery mode
fan/thermal state
```

## Expected memory scale

The bundled graph tensors occupy well below 1 MiB and the small checkpoint is
under 2 MiB in FP32. The real limit will be graph/event scale and sampled
neighborhood design, not the demonstration. Full-graph execution is included for
clarity; large graphs require temporal windows and neighbor sampling.

## When to add PyTorch Geometric

Only add PyG after the pure-PyTorch baseline works on the laptop. PyG can provide
mature neighbor samplers, but each native extension must match the installed
PyTorch and CUDA architecture. It is an optimization path, not a prerequisite.
