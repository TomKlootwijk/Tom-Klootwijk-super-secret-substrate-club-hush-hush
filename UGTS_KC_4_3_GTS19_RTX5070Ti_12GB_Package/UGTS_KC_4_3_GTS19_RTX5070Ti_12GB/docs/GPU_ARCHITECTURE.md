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

`cpp/cuda/packed_kernels.cu` preserves the original exact empty-mask API and now
also exposes a sibling asynchronous, fixed-slot pre-superko transition kernel.
For canonical no-suicide rules it deterministically performs:

1. connected-component/group labeling;
2. opponent capture resolution;
3. post-capture own liberties;
4. suicide policy;
5. deterministic child bitplane encoding.

The lower-level output remains untrusted until its stream completes and the
error word, every status/count, and every child word have passed CPU replay.
`cuda_verified_expander.cu` recomputes every board point, including GPU rejects,
so a GPU false negative cannot hide a legal move. It fails closed on any CUDA,
protocol, memory-shape, sentinel, or parity error. The CPU alone handles pass,
exact raw-board positional-superko membership, previous-board/pass/ply/history
metadata, and all proof updates.

The target-laptop v1 gate is bounded: 25,281 unique point slots and 50,562
default/nondefault Python/C++/CUDA point comparisons, plus a 524,533-candidate
dual-stream grid-stride guard, all with zero mismatches. It has not reached the
10,000,000-slot M4 exit gate, is not wired into proof search, and establishes no
throughput or solved-result claim. The dense 19×19 device representation uses
36,606 bytes per input state plus one batch error word; the adapter queries
`cudaMemGetInfo`, retains an 18% free-memory reserve, admits at most 16% of the
post-reserve amount for this workspace, and rejects rather than silently
shrinking or partially evaluating a batch.

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
