# GSP4 Spatial Knowledge Distillation for UGTS-GN

**Version 0.5.0 — runnable sparse geospatial GNN, temporal knowledge transfer, deterministic UGTS event gate, and seed-chain deployment package.**

This repository is the practical GSP4 deliverable requested for an NVIDIA GeForce RTX 5070 Ti Laptop GPU with 12 GB VRAM. It replaces padded geospatial frame tensors with a sparse heterogeneous temporal graph and keeps the UGTS substrate as the event authority.

The runtime path is:

```text
persistent entity / sparse observation / ontology concept
                    │
                    ▼
hierarchical spatial cell broad phase (Morton built in, H3 optional)
                    │
                    ▼
HGT-style typed attention + TGN-style temporal memory student
                    │ semantic proposal / relation score
                    ▼
UGTS support → compatibility → finite guard → verified event
                    │
                    ▼
route / transition → lineage → append-only novelty chain
```

The GNN does **not** replace geometry, identity, or event verification. It transfers semantic and relational knowledge from offline teachers. Exact spatial decisions remain deterministic and inspectable.

## Delivered components

- Sparse `.ugkg` graph container for persistent entities, variable-length observations, events, cells, concepts, and lineage states.
- HGT-style relation-specific attention implemented directly in PyTorch without a PyG dependency.
- TGN-style temporal memory update over irregular event edges.
- Offline embedding distillation through a local OpenAI-compatible endpoint, a local SentenceTransformer, or a deterministic no-download smoke teacher.
- Offline relation labeling through a local or hosted OpenAI-compatible chat teacher with a bounded relation vocabulary and strict JSON output.
- ULTRA-compatible triple export and external score import.
- UGTS query gate: support, compatibility, finite guard, semantic confidence, verified event, route, lineage, novelty commit.
- `.ugnl` hash-linked novelty/event log.
- `.ugdeploy` hash-verified deployment bundle.
- Direct export to the supplied UGTS G64/E32 and packed G32/E16 ABI.
- GeoNames ZIP/TXT adapter, variable observation CSV adapter, and OSM XML/PBF adapter.
- CPU oracle tests, tamper tests, deployment validation, precision checks, and an RTX GPU primitive checker.
- A no-download Flevoland-style pilot graph, student checkpoint, novelty chain, UGTS buffers, teacher workflow examples, and validation outputs.

See [GSP4_DELIVERABLES.md](GSP4_DELIVERABLES.md) for the exact artifact inventory.

## Quick start: included data, no model download

Python 3.10–3.13 is supported. The included checkpoint is a smoke model, not a production-quality geospatial model.

### Windows PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\run_no_download_windows.ps1
```

### Linux / WSL

```bash
bash scripts/setup_linux.sh
bash scripts/run_no_download_linux.sh
```

Verify the extracted package before setup:

```bash
python scripts/verify_package_manifest.py .
```

Manual equivalent:

```bash
python -m venv .venv
# Windows: .venv\Scripts\Activate.ps1
# Linux:   source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .

gsp4 inspect-graph data/flevoland_pilot.ugkg
gsp4 validate-novelty data/flevoland_pilot.ugnl
gsp4 query data/flevoland_pilot.ugkg \
  --model models/gsp4_flevoland_student_smoke.pt \
  --source sensor:1:1:air --relation near --radius 10000 \
  --epsilon 25 --max-events 32 --output results/near_query.json
```

## RTX 5070 Ti path

Install a current NVIDIA driver and the current stable PyTorch CUDA build, then run. As of this release, PyTorch uses CUDA 13.0 as its default Blackwell-capable wheel; the setup script deliberately does not pin the retired `cu128` index:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1 -Cuda
powershell -ExecutionPolicy Bypass -File .\scripts\run_rtx_pilot_windows.ps1
```

The GPU checker exercises the operations used by this implementation: mixed-precision matrix multiplication, indexed aggregation, and `scatter_reduce`.

```powershell
gsp4 check-gpu --device cuda --precision float16
```

The recommended first RTX student is deliberately modest:

```text
hidden dimension     128
attention heads      8
layers               4
precision            FP16
training epochs      30
neighbor/candidate work remains sparse
```

This fits well within 12 GB VRAM for the supplied pilot. Actual peak VRAM depends on graph size, sampled edges, teacher dimensions, batch sizes, and PyTorch runtime allocations. See [docs/RTX5070TI_RUNBOOK.md](docs/RTX5070TI_RUNBOOK.md).

## Knowledge distillation without an edge LLM

The online deployment contains only:

1. Sparse graph state.
2. Compact student checkpoint.
3. Ontology/relation contract.
4. Deterministic UGTS gate.
5. Hash-linked novelty history.

The larger teacher is used only to generate versioned supervision:

```text
entity text → embedding teacher → teacher_x cache
bounded candidate pair → relation teacher → soft relation edge
ULTRA/external scorer → structural soft edge
all teacher artifacts → HGT/TGN student training
```

A teacher may be local, partly GPU-offloaded, CPU-only, or hosted. Once its labels and embeddings have been materialized, it is not needed for online spatial queries.

The smallest recommended manual model is the official Qwen3 Embedding 0.6B Q8 GGUF at about 639 MB. A balanced fully local pair is Qwen3 Embedding 4B Q4_K_M plus Qwen3 4B Q4_K_M, about 5 GB total. Exact filenames, checksums, roles, and manual URLs are in [assets/manual_downloads.json](assets/manual_downloads.json) and [docs/MODEL_AND_DATA_DOWNLOADS.md](docs/MODEL_AND_DATA_DOWNLOADS.md).

## Real data conversion

### GeoNames plus irregular observations

```bash
gsp4 ingest-geonames external/NL.zip data/nl_flevoland.ugkg \
  --bbox 52.20 5.10 52.90 6.00 \
  --country-code NL \
  --limit 15000 \
  --observations examples/observations_variable.csv \
  --teacher-dimensions 64
```

The observation CSV is sparse: each sensor may emit any number of records at arbitrary timestamps. No maximum-points or maximum-events frame is allocated.

### OpenStreetMap Flevoland extract

```bash
python -m pip install -e '.[osm]'
gsp4 ingest-osm external/flevoland-latest.osm.pbf data/flevoland_osm.ugkg \
  --limit 100000 --spatial-resolution 14 --neighbors 4
```

For a low-disk pilot, the Flevoland regional extract is strongly preferred over the full Netherlands extract.

## Local teacher workflow

Start the embedding server in one terminal:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_embedding_server_windows.ps1 `
  -ModelPath D:\models\Qwen3-Embedding-0.6B-Q8_0.gguf
```

Start the relation teacher in another terminal:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_teacher_server_windows.ps1 `
  -ModelPath D:\models\Qwen3-4B-Q4_K_M.gguf
```

Then run the bounded distillation chain:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\distill_windows.ps1 `
  -Graph data\flevoland_pilot.ugkg
```

The equivalent individual commands are documented in [docs/DISTILLATION_WORKFLOW.md](docs/DISTILLATION_WORKFLOW.md).

## Principal commands

```text
gsp4 build-pilot          create a deterministic no-download variable-event graph
gsp4 ingest-geonames      convert GeoNames and optional irregular observations
gsp4 ingest-osm           convert OSM XML/PBF
gsp4 embed                attach semantic teacher vectors
gsp4 teacher-candidates   generate geometry/type-bounded relation candidates
gsp4 teacher-label        label bounded candidates with an offline teacher
gsp4 labels-to-edges      compile labels into soft supervision
gsp4 export-ultra         export train/validation/test triples
gsp4 import-scores        import ULTRA or another structural scorer
gsp4 train                train the HGT/TGN student
gsp4 query                run support→compatibility→guard→score→event
gsp4 export-ugts          export G64 and packed G32 substrate buffers
gsp4 package              create a hash-verified deployment archive
gsp4 validate-package     verify every deployment member
gsp4 benchmark            measure named model/query paths
gsp4 check-gpu            verify required CUDA primitives
```

## Included validation result

The preparation environment had PyTorch 2.10 CPU-only and no NVIDIA GPU. The following work was completed there:

- 21 tests passed.
- `.ugkg`, `.ugnl`, `.ugte`, `.ugdeploy`, G64 and G32 paths exercised.
- Graph and novelty hash/tamper validation passed.
- Six-epoch CPU smoke training completed.
- Direct UGTS bridge produced 126 candidate records; packed G32 maximum position error was 4.365 m against a declared 25 m guard, so this sample satisfied its declared precision contract.
- A CPU benchmark was produced only to validate measurement plumbing; it is not an RTX performance claim.

The source substrate itself requires physical-device reruns and names SPIR-V, shader source, ABI, oracle vectors, and metric definitions—not vendor-specific caches—as the portable contract. The same boundary is retained here.

## Authorship and provenance

The substrate authorship details in this package are recorded exactly as supplied by the user and are not independently adjudicated. See [AUTHORS_AND_PROVENANCE.md](AUTHORS_AND_PROVENANCE.md) and [provenance/source_hashes.json](provenance/source_hashes.json).

## License boundary

The GSP4 engineering code in this repository is MIT-licensed. Third-party data, model weights, runtimes, and ontologies retain their own licenses and are not redistributed here. Model and data manifests are download guidance, not license substitutions.
