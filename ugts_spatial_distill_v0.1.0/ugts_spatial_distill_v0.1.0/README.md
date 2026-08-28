# UGTS Spatial Distill 0.1.0

A runnable launchpad for **variable-length geospatial knowledge graphs**, offline
teacher knowledge transfer, a compact heterogeneous temporal GNN student, and a
UGTS query-first event gate.

The implementation does not represent geospatial activity as a padded
`[frame, maximum_points, features]` tensor. Persistent entities live in a sparse
graph; irregular observations live in an event stream; external changes are
append-only novelty records.

## What is implemented

```text
stable entity IDs + sparse COO relations + irregular event stream
                            │
                offline embedding/label teacher
                            │
                            ▼
                compact HGT/TGN-style student
                            │
                            ▼
 broad spatial support → typed compatibility → deterministic guard
                            │
                            ▼
         verified relation event → route/lineage → novelty JSONL
                            │
                            └── optional G64/G32/E32/E16 UGTS ABI export
```

The student is pure PyTorch. It intentionally avoids PyTorch Geometric and custom
CUDA extensions on the first deployment path, reducing the risk that a third-
party extension lacks `sm_120` support on an RTX 5070 Ti Laptop GPU.

Included capabilities:

- Variable-length sparse graph and event storage; no frame padding.
- Persistent 64-bit source identities independent of coordinates.
- Ten node types and 22 versioned relations compiled from UGTS semantics plus
  GeoSPARQL/SOSA/SSN/OWL-Time interoperability concepts.
- HGT-style relation-aware sparse attention.
- TGN-style aggregation of irregular events into persistent node memory.
- Offline teacher embeddings through any OpenAI-compatible `/v1/embeddings`
  endpoint.
- Structured JSONL export/import for larger-model relation labels.
- H3 broad phase when installed, with a dependency-free Morton-grid fallback.
- Exact local ENU distance/cone/SDF support after broad-phase candidate lookup.
- Validation-calibrated semantic thresholds stored with each checkpoint.
- Append-only lineage and novelty records.
- GeoNames ZIP/TXT, generic CSV, and optional OpenStreetMap PBF adapters.
- Binary export to the uploaded UGTS G64/E32 and G32/E16 ABI and CPU oracle.
- CPU/CUDA benchmark command with p50/p95/p99 and peak CUDA memory.

## Source and engineering boundary

The uploaded UGTS material supplies the query-first sequence, typed state,
identity/lineage distinction, novelty retention, local support, compatibility,
guards and packed ABI. HGT/TGN, H3, Qwen embeddings, GeoNames ingestion and the
specific training objectives are **engineering translations and additions**.
They are not represented as claims already proved by the substrate.

The DOCX describes a 197-mechanism base catalog. The uploaded package currently
contains an extended 211-record catalog; this project vendors that exact package
catalog and records its hash rather than silently reconciling the two counts.
See `docs/SOURCE_MAPPING.md`.

## No-download first run

The repository includes:

- `data/demo/graph/`: 510 nodes, 1,827 sparse edges, 1,013 irregular events and
  720 relation examples.
- `runs/demo_cpu/checkpoint.pt`: a 477,328-parameter student trained on CPU.
- `runs/demo_cpu/metrics.json`: fixed-threshold and calibration metrics.
- `runs/demo_cpu/benchmark_cpu.json`: preparation-environment timing only.

The graph is synthetic. It uses six named Flevoland municipal anchors, but its
sensors, assets and observations are generated and must not be treated as real
measurements.

Verify everything:

```powershell
python -m ugts_spatial verify .\data\demo\graph `
  --checkpoint .\runs\demo_cpu\checkpoint.pt
```

Run a query from an existing sensor. The command uses the validation-calibrated
threshold for `near` unless it is explicitly overridden:

```powershell
python -m ugts_spatial query `
  .\data\demo\graph `
  .\runs\demo_cpu\checkpoint.pt `
  --source "air_temperature sensor 0 in Almere" `
  --relation near `
  --radius-m 10000 `
  --verified-only `
  --novelty-log .\runs\demo_cpu\novelty.jsonl
```

Run a local benchmark:

```powershell
python -m ugts_spatial benchmark `
  .\data\demo\graph `
  .\runs\demo_cpu\checkpoint.pt `
  --device auto `
  --warmup 10 `
  --repeats 50 `
  --output .\runs\demo_gpu_benchmark.json
```

## Windows RTX 5070 Ti setup

Use Python 3.10–3.14 and a current NVIDIA driver. PyTorch 2.7 introduced
Blackwell support and CUDA 12.8 wheels; use the current CUDA-enabled install
command offered by PyTorch, with the following stable CUDA 12.8 index as a known
baseline:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cu128
python -m pip install -e .
python -m pip install h3
```


For an existing compatible NumPy/PyTorch environment, install the bundled wheel
without resolving dependencies:

```powershell
python -m pip install --no-deps .\dist\ugts_spatial_distill-0.1.0-py3-none-any.whl
```

The wheel contains the CLI, ontology and uploaded UGTS reference oracle. The
source ZIP additionally contains the demonstration graph, checkpoint, scripts
and validation artifacts.

Confirm the actual device before training:

```powershell
python -c "import torch; print(torch.__version__); print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO CUDA')"
```

Build the synthetic graph and train the larger laptop profile:

```powershell
python -m ugts_spatial demo .\data\my_demo_graph
python -m ugts_spatial train `
  .\data\my_demo_graph `
  .\runs\rtx5070ti `
  --config .\configs\rtx5070ti_train.json
```

The larger configuration starts at four layers, 256 hidden dimensions, eight
heads and 128-dimensional temporal memory. It is a starting profile, not a
promise that it is optimal for a specific laptop power limit.

## Offline knowledge transfer

The default demonstration uses deterministic hash vectors so it runs without a
model download. Replace them with a real teacher as follows.

A compact recommended model is:

```text
Repository: Qwen/Qwen3-Embedding-0.6B-GGUF
File:       Qwen3-Embedding-0.6B-Q8_0.gguf
Size:       approximately 639 MB
```

The official model card describes 0.6B parameters, more than 100 languages, 32K
context and configurable output dimensions from 32 to 1024. The project projects
teacher output to 256 dimensions by default, then trains the student to align
with it.

After manually downloading the GGUF, start llama.cpp:

```powershell
llama-server.exe `
  -m D:\models\Qwen3-Embedding-0.6B-Q8_0.gguf `
  --embedding `
  --pooling last `
  -ub 8192 `
  --host 127.0.0.1 `
  --port 8080
```

Attach embeddings to a new graph directory:

```powershell
python -m ugts_spatial embed `
  .\data\demo\graph `
  .\data\demo\graph_qwen `
  --base-url http://127.0.0.1:8080/v1 `
  --model Qwen3-Embedding-0.6B-Q8_0 `
  --target-dim 256
```

Then train against `graph_qwen`. The large model is absent from runtime after
training; the production query path needs the compact student, graph records and
deterministic gate only.

A hosted or larger local chat model can contribute relation probabilities:

```powershell
python -m ugts_spatial export-teacher-tasks `
  .\data\demo\graph_qwen `
  .\teacher_tasks.jsonl `
  --splits 0

# Fill one JSON object per line with at least:
# {"example_index": 0, "probability": 0.93}

python -m ugts_spatial import-teacher-labels `
  .\data\demo\graph_qwen `
  .\teacher_labels.jsonl `
  .\data\demo\graph_qwen_labeled
```

See `docs/KNOWLEDGE_TRANSFER.md` for the evidence contract and leakage controls.

## Small real-data path

### GeoNames Netherlands

Manually download:

```text
https://download.geonames.org/export/dump/NL.zip
```

The official dump listed `NL.zip` at approximately 709 KiB on 2026-08-16. The
adapter uses Python's standard library and defaults to admin1 code `16`
(Flevoland):

```powershell
python -m ugts_spatial ingest-geonames `
  D:\data\NL.zip `
  .\data\geonames_flevoland `
  --admin1 16
```

To import all Dutch records, use `--admin1 all`.

### OpenStreetMap Flevoland

The stable latest-download address is:

```text
https://download.geofabrik.de/europe/netherlands/flevoland-latest.osm.pbf
```

The August 2026 PBF was about 34.5 MB. The optional adapter requires `osmium`:

```powershell
python -m pip install osmium
python -m ugts_spatial ingest-osm `
  D:\data\flevoland-latest.osm.pbf `
  .\data\osm_flevoland `
  --max-features 100000
```

OpenStreetMap attribution and licence obligations remain with any derived use.
The package does not bundle OSM data.

## Generic user data

A generic CSV adapter accepts:

```csv
id,lat,lon,alt,text,type
station-001,52.52,5.47,1.2,Lelystad water-level station,sensor
bridge-007,52.50,5.50,0.0,Bridge asset,spatial_entity
```

```powershell
python -m ugts_spatial ingest-csv points.csv .\data\my_graph
```

The CSV adapter creates persistent source IDs and spatial-cell edges. Add task
examples and irregular event records programmatically with `GraphBuilder` before
training.

## UGTS ABI bridge

Export a candidate set into the exact uploaded reference layouts:

```powershell
python -m ugts_spatial export-ugts `
  .\data\demo\graph `
  .\runs\abi_export `
  --source "air_temperature sensor 0 in Almere" `
  --relation near `
  --max-candidates 256 `
  --radius-m 10000 `
  --epsilon-m 50
```

Output:

```text
states_g64.bin       64 bytes/candidate
states_g32.bin       32 bytes/candidate
events_e32.bin       32 bytes/candidate
events_e16.bin       16 bytes/candidate
candidate_indices.u64le
manifest.json
```

The vendor oracle uses a boundary guard (`abs(SDF)-epsilon`). This bridge is for
ABI validation and native UGTS evaluation; it is distinct from the student's
ordinary `inside` distance relation query.

## Demonstration validation result

Preparation environment:

```text
Python       3.13.5
PyTorch      2.10.0+cpu
CUDA         unavailable in preparation environment
CPU tests    10/10 passed
```

Demo checkpoint at fixed threshold 0.5:

```text
Validation AP          0.8642
Validation ROC-AUC     0.8444
Validation F1          0.7627
Test AP                0.8207
Test ROC-AUC           0.8030
Test F1                0.6975
```

The `governed_by` ontology task is deliberately easy in the synthetic graph. The
`observes` relation remains weak and close to chance on the held-out areas. That
is recorded rather than hidden; a real embedding teacher and real labelled
sensor/property examples are required before treating it as useful. See
`runs/demo_cpu/metrics.json` for per-relation results.

## Acceptance and kill criteria

Do not promote the model merely because it is smaller than an LLM. Reject or
redesign it when:

- spatial candidate pruning does not materially reduce relations;
- event or branch density erases the avoided materialization;
- compression error crosses the declared geometric guard margin;
- full-graph attention or compaction becomes the bottleneck;
- spatial, temporal or ontology holdouts fail;
- a rule-only or conventional sparse baseline is cheaper and equally accurate.

The GNN is a candidate scorer. It does not overrule a failed support,
compatibility or guard test.

## Project map

```text
ugts_spatial/               implementation
ontology/                   compact typed ontology
vendor/ugts_gn_1_1/         exact files vendored from uploaded package
configs/                    demo and RTX training profiles
data/demo/graph/            no-download sparse graph
runs/demo_cpu/              checkpoint, metrics and CPU benchmark
scripts/                    setup and execution helpers
dist/                       prebuilt pure-Python wheel (model/data remain in source bundle)
docs/                       design, formats, transfer and validation
```

## Licence and provenance

Project code is MIT licensed. Vendored files retain their supplied MIT licence.
No Qwen, GeoNames or OpenStreetMap data/model weights are redistributed.

`AUTHORSHIP_NOTICE.md` records the user-supplied substrate provenance separately
from independent legal or inventorship verification.
