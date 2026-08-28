# GSP4 Deliverable Inventory — v0.5.0

## Runtime and model

- `src/ugts_spatial/model.py` — typed heterogeneous attention and temporal memory student.
- `src/ugts_spatial/training.py` — link, type, temporal, embedding, and soft-edge distillation losses.
- `src/ugts_spatial/query.py` — support, compatibility, guard, semantic score, verified event, lineage, and optional novelty commit.
- `src/ugts_spatial/environment.py` — RTX/CUDA primitive acceptance check.

## Sparse data and identity

- `src/ugts_spatial/graph.py` — `.ugkg` sparse heterogeneous graph.
- `src/ugts_spatial/novelty.py` — `.ugnl` hash-linked event/novelty chain.
- `src/ugts_spatial/deployment.py` — `.ugdeploy` deployment bundle and integrity validation.
- `src/ugts_spatial/ugts_bridge.py` — G64/E32 and G32/E16 substrate bridge.

## Knowledge transfer

- `src/ugts_spatial/embeddings.py` — hash, local HTTP/llama.cpp, and SentenceTransformer embedding adapters.
- `src/ugts_spatial/teacher.py` — bounded OpenAI-compatible relation teacher.
- `src/ugts_spatial/edge_teacher.py` — soft teacher edge format and ULTRA interchange.
- `prompts/` — ontology-bounded teacher prompt and JSON schema.

## Ingestion

- `src/ugts_spatial/builders.py` — GeoNames plus irregular sensor CSV compiler.
- `src/ugts_spatial/ingest_osm.py` — OSM XML/PBF compiler.
- `src/ugts_spatial/synthetic.py` — deterministic variable-event Flevoland pilot.
- `examples/observations_variable.csv` — irregular event-stream example.
- `examples/tiny_geonames.txt` and `examples/tiny_flevoland.osm` — tiny adapter fixtures.

## Included runnable assets

- `data/flevoland_pilot.ugkg` — 228 nodes, 1,305 sparse edges, 8 unequal observation windows.
- `data/flevoland_pilot.ugnl` — 118 hash-linked novelty/event records.
- `models/gsp4_flevoland_student_smoke.pt` — 341,459-parameter smoke student.
- `examples/teacher_edges_smoke.ugte` — compiled soft teacher-edge fixture.
- `examples/ultra_export/` — ULTRA train/validation/test triple export.
- `examples/ugts_bridge/` — G64, G32, exchange JSON, and precision manifest.
- `data/gsp4_flevoland_smoke.ugdeploy` — complete deployment bundle.

## Validation

- `tests/` — 21 passing tests.
- `results/validation/` — graph, training, query, teacher, bridge, benchmark, and deployment evidence.
- `PACKAGE_MANIFEST.json` — SHA-256 and byte count for every distributed file.
- `scripts/validate_all_windows.ps1` and `scripts/validate_all_linux.sh` — reproduction sequence.

## External assets intentionally not bundled

- Qwen model weights.
- llama.cpp binaries.
- PyTorch CUDA wheels.
- GeoNames and OpenStreetMap source files.
- ULTRA source/checkpoints.

The exact manual download recommendations and checksums are in `assets/manual_downloads.json`.
