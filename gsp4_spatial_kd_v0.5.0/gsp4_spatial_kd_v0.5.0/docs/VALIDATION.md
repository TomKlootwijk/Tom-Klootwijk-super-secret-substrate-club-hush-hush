# Validation Report — GSP4 v0.5.0

## Preparation environment

```text
OS       Linux 6.18 x86_64
Python   3.13.5
PyTorch  2.10.0+cpu
CUDA     unavailable in this environment
```

No RTX timing claim is made from this environment.

## Test suite

Command:

```bash
PYTHONPATH=src python -m pytest -q
```

Result:

```text
21 passed
```

Covered behavior:

- variable-length sparse graph round trips;
- graph schema hashing and type compatibility;
- Morton broad phase and local geometry;
- GeoNames ZIP/TXT ingestion;
- OSM XML ingestion and parent/child tag parsing;
- novelty append, replay, terminal hash, and tamper detection;
- teacher candidate generation and strict label compilation;
- ULTRA triple export and scored-triple import;
- HGT/TGN training and checkpoint reload;
- support/compatibility/guard query execution;
- verified-event novelty commit;
- G64 and packed G32 export;
- packed precision contract;
- deployment build and member-hash validation;
- hardware profile/reference tests.

## Included pilot

```text
nodes                         228
edges                         1,305
node classes                  7
relation classes              16
observation windows           8
observations/window           15,9,12,11,14,14,11,11
fixed frame padding           none
novelty records               118
graph SHA-256                 649ba082f664506c89e4bac0a0e3bdc6000feb9e1496d89835464cc2f379472b
schema hash                   37cc2bf6620a97f61721584935f12e538ac8e29464888961253f274b8fdac9c4
```

## Student smoke training

```text
parameters                    341,459
checkpoint                    1.343 MiB
layers / heads / hidden       2 / 4 / 64
training epochs               6
best epoch                    6
CPU elapsed                   24.98 s
validation link accuracy      0.5582
test link accuracy            0.5500
```

These metrics prove the train/evaluate/checkpoint path, not production model quality. The bundled teacher vectors are deterministic lexical smoke vectors rather than Qwen embeddings.

## Query smoke result

A `near` query around `sensor:1:1:air`, radius 10 km, epsilon 25 m, returned 32 verified events after a 110-candidate bounded lookup. The event list and lineage checksum were persisted for replay validation.

## UGTS bridge

```text
candidate records             126
G64 bytes                     8,064
G32 bytes                     4,032
G32 max position error        4.3646 m
declared guard epsilon        25.0 m
precision contract            passed for this sample
```

This verdict is workload- and guard-specific. It must be recalculated for every coordinate range and event margin.

## CPU measurement plumbing

The included one-repeat CPU benchmark measured model encoding, batched relation scoring, and cached query timing. It is included so the JSON schema and formulas can be reproduced, not as a performance baseline for the RTX laptop.

## Remaining physical-device validation

Run on the target laptop:

```text
PyTorch CUDA/SM_120 availability
FP16/BF16 numerical comparison against float32
p50/p95/p99 latencies
peak VRAM
support/compatibility rejection gains
event yield and verified events/s
G32 error and event-order comparison
power/thermal context
lineage and event-set equality
```

Promotion must stop when pruning fails, event/branch density exceeds avoided materialization, quantization crosses the guard margin, atomic/compaction costs dominate, event errors exceed budget, or a conventional sparse baseline is better at equal error.
