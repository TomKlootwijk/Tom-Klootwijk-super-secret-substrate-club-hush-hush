# RTX 5070 Ti Laptop Runbook

## Target profile

The target is the GeForce RTX 5070 Ti Laptop GPU:

```text
architecture             NVIDIA Blackwell
CUDA cores               5,888
AI TOPS                   992 (vendor specification)
VRAM                      12 GB GDDR7
memory interface          192-bit
listed bandwidth          672 GB/s
GPU subsystem power       laptop-dependent, listed 60–115 W
CUDA architecture target  SM_120
```

The implementation does not assume a fixed laptop power limit. Record the actual model, driver, power mode, charger state, thermal state, and any OEM performance profile.

## Software

Recommended:

```text
Windows 11 or Linux/WSL2
Python 3.11 or 3.12
current NVIDIA Studio or Game Ready driver
current stable PyTorch CUDA 13.0-or-newer Blackwell-capable binary
```

CUDA 12.8 first introduced compiler support for SM_120. The current PyTorch release matrix uses CUDA 13.0 as the stable default for Blackwell and no longer publishes `cu128` in the standard matrix. The supplied setup script therefore uses the current PyPI wheel by default; use its explicit index override only for a future/nightly channel or controlled mirror.

## Setup

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Cuda
.\.venv\Scripts\Activate.ps1
gsp4 check-gpu --device cuda --precision float16 --output results\gpu_environment.json
```

Acceptance:

- `cuda.available` is true.
- The reported compute capability is `12.0` for the target.
- Matrix multiplication, `index_add`, and `scatter_reduce` complete without NaN/Inf.
- Peak smoke memory is finite and reported.

## Pilot training

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_rtx_pilot_windows.ps1
```

The script trains a 4-layer, 8-head, hidden-128 student in FP16 and writes:

```text
results/rtx_pilot/gpu_environment.json
results/rtx_pilot/training_metrics.json
results/rtx_pilot/query.json
results/rtx_pilot/benchmark.json
results/rtx_pilot/flevoland_rtx_student.pt
results/rtx_pilot/flevoland_rtx.ugdeploy
```

## First scaling sequence

Scale one dimension at a time:

1. Increase pilot graph rows while holding model size fixed.
2. Increase candidate/encoder edges while measuring peak VRAM.
3. Increase hidden dimension from 128 to 192 or 256.
4. Increase teacher dimension from 256 only when retrieval quality justifies it.
5. Increase temporal history/sample depth.
6. Measure full-batch versus sampled-subgraph performance.

Do not load a large chat teacher, embedding teacher, student training graph, and benchmark graph concurrently unless measured headroom is adequate. Teacher inference and student training can be separate phases.

## Metrics to retain

```text
selected device and compute capability
driver and PyTorch/CUDA versions
power mode and temperature range
model parameters and checkpoint bytes
nodes/edges and candidate limits
precision and guard epsilon
p50/p95/p99 encoding latency
candidate score throughput
verified event throughput
support and compatibility rejection gains
event yield
peak CUDA memory
lineage/event mismatches
G32 error versus event margin
```

The package benchmark reports logical workload rates, not raw VRAM bandwidth.

## Precision policy

Run the reference path in float32 first. Then repeat with FP16 or BF16 and compare:

- candidate membership;
- event count and ordered event IDs;
- route and lineage hashes;
- SDF and guard values;
- teacher/student score tolerance.

A smaller record or faster kernel is rejected when coordinate/axis/radius/guard error exceeds the declared event margin or changes event ordering.

## Thermal policy

Laptop performance varies with OEM power limits and cooling. Use:

- AC power;
- a fixed OEM performance profile;
- warmup before measurement;
- separate p50/p95/p99 reporting;
- a cool-down between configuration sweeps when throttling is observed.

Do not compare rates across laptops without preserving model, batch, precision, driver, power, and thermal context.
