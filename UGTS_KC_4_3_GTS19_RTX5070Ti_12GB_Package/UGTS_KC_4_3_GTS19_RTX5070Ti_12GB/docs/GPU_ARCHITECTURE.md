# GPU architecture for a 12 GB laptop target

## Design principle

The GPU is a deterministic batch accelerator and hot cache. The CPU owns proof
coordination, collision-safe identity, durable checkpoints, and certificate
assembly. NVMe stores immutable content-addressed segments. This division avoids
pretending that 12 GB can contain the unrestricted proof graph.

## Pipeline

```text
CPU proof coordinator
  -> select most-proving frontier records
  -> gather packed boards + context handles
  -> GPU occupancy/group/liberty/capture candidate batch
  -> CPU or exact GPU superko lookup against persistent history
  -> GPU/CPU terminal and bound kernels
  -> proof/disproof update
  -> hot TT cache
  -> host TT + immutable NVMe segments
  -> checkpoint / certificate Merkle DAG
```

## Board representation

Two complementary representations are provided:

- 2-bit packed board: 722 bits, 91 bytes for storage and transfer;
- two 6-word 64-bit bitplanes: 96 bytes, convenient for occupancy and bitwise
  kernels, with the unused tail bits masked.

Metadata is stored separately so batches remain structure-of-arrays.

## Version 4.3 CUDA boundary

`cpp/cuda/packed_kernels.cu` computes exact empty masks. It deliberately does not
claim full legality. A proof-authoritative CUDA expansion must add:

1. connected-component/group labeling;
2. opponent capture resolution;
3. post-capture own liberties;
4. suicide policy;
5. exact superko lookup;
6. deterministic child encoding;
7. CPU-reference differential tests.

Until all seven pass, the GPU output is a candidate list and the CPU reference
must verify each committed child.

## Free-memory allocation

At startup, call `cudaMemGetInfo`. Let `F` be free bytes, not nominal VRAM.
Reserve 18% by default. Divide the remaining `0.82F` as:

| Pool | Share of usable | Purpose |
|---|---:|---|
| hot transposition cache | 46% | proof values and state handles |
| frontier | 23% | selected/expanded nodes |
| batch workspace | 16% | bitplanes, groups, liberties, outputs |
| proof staging | 8% | deltas before durable commit |
| optional heuristic | 7% | ordering only; reclaimable |

All allocations must degrade gracefully. If allocation fails, reduce the batch
or cache and continue; do not crash after corrupting a checkpoint.

## Laptop constraints

- Keep kernels short enough for display-driver responsiveness unless the laptop
  is configured for compute-only use.
- Poll thermal/power telemetry outside the proof semantics; throttle batches
  rather than changing move selection truth.
- Checkpoint before sleep, driver update, or battery transition.
- Use pinned host buffers sparingly; excessive pinning can hurt system behavior.
- Never assume all nominal VRAM is free.

## Throughput metrics

Record separately:

- states transferred per second;
- candidate points per second;
- exact legal children per second;
- superko lookups per second;
- TT hit/miss/collision-audit counts;
- proof updates per second;
- joules or wall-clock per million updates where telemetry is available;
- checkpoint write and restore throughput.

A high candidate throughput is not a solver result. The meaningful campaign
metric is verified proof-number progress per unit time and storage.
