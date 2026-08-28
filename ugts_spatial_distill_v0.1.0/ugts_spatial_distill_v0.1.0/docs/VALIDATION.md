# Validation Report

## Completed in the preparation environment

- Python 3.13.5 import and bytecode checks.
- Pure-PyTorch CPU execution with PyTorch 2.10.0+cpu.
- 10 dependency-free `unittest` cases passed after final packaging changes.
- Wheel built without network isolation and installed into an isolated target.
- Wheel-bundled ontology, 211-record catalog and reference oracle loaded successfully.
- Stable identity and ordered lineage update tests.
- Local ENU, metric distance, cone/sphere/SDF and Morton broad-phase tests.
- Sparse graph save/load and SHA-256 verification.
- Variable-length temporal aggregation and HGT forward pass.
- Distillation loss and metric execution.
- Two-epoch train/load/query integration test.
- Teacher task export/import round trip.
- Synthetic GeoNames ZIP ingestion.
- UGTS G64/G32/E32/E16 record-size and oracle export checks.
- A 203-candidate ABI smoke export produced the exact 64/32/32/16-byte record profiles.
- A calibrated `near` query returned four verified events from the bundled checkpoint.
- Full 510-node demo training and checkpoint generation.
- CPU benchmark JSON generation.

Run:

```bash
python -m unittest discover -s tests -v
```

## Demo metrics

At fixed probability threshold 0.5:

```text
validation average precision  0.8642
validation ROC-AUC            0.8444
validation F1                 0.7627
holdout average precision     0.8207
holdout ROC-AUC               0.8030
holdout F1                    0.6975
```

The relation-specific report must be read. `governed_by` is easy and perfectly
separated in this synthetic corpus; `observes` is weak. The overall number is not
a deployment claim.

## Not completed here

- CUDA execution on the user's RTX 5070 Ti Laptop GPU.
- Power, thermal, p95/p99 GPU and peak-VRAM measurements.
- Qwen model download or embedding quality evaluation.
- Real GeoNames/OSM ingestion in the preparation environment.
- Baselines against R-GCN, GraphSAGE, rule-only and PyG HGT.
- Large-graph neighbor sampling and streaming checkpoint persistence.

## Target-laptop acceptance

A first accepted run should include:

```text
torch.cuda.is_available() = true
correct GPU name
finite logits
no graph/checkpoint hash errors
query support/guard invariants pass
no lineage serialization errors
p50/p95/p99 benchmark JSON
peak allocated and reserved VRAM
```

Promote only after spatial, temporal and ontology holdouts outperform a simpler
baseline at an acceptable cost.
