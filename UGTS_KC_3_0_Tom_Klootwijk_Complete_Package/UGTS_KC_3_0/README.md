# UGTS-KC 3.0

UGTS-KC 3.0 is a bounded engineering expansion of the Unified Geometric-Topological Substrate. It preserves the query-first authority chain:

`local support -> compatibility -> guard/certification -> verified event -> atomic transition -> lineage and novelty log`

Projection, rendering, GPU execution and physical devices remain optional consumers. They are not the authoritative state.

## Package highlights

- 360 atomic mechanisms in one traceable catalog.
  - M001-M197: UGTS-GN 1.1 source-derived or normalized baseline.
  - M198-M257: UGTS-KC 2.0 engineering expansion.
  - M258-M360: UGTS-KC 3.0 engineering expansion.
- 103 new 3.0 mechanisms for jet/Lie kinematics, constraints and contact, certified hybrid events, persistent topology, multiscale patterns, geometric and field dynamics, uncertainty, deterministic replay and runtime ABI contracts.
- Dependency-free Python reference implementation.
- JSON Schema Draft 2020-12 exchange contract and a validated example world.
- 182 executable unit tests.
- Reference-only CPU microbenchmarks with an explicit non-hardware performance boundary.
- Technical report in PDF, DOCX and Markdown.

## Evidence boundary

The two supplied PDF reports establish the existing architecture and 197-mechanism baseline. M198-M360 are explicitly marked as engineering extensions. They are not represented as quotations or discoveries from the supplied source corpus.

The package does not redistribute the supplied PDFs. It records their SHA-256 hashes and a privacy-safe source register.

## Quick start

```bash
python -m unittest discover -s tests -v
PYTHONPATH=src python examples/query_first_contact_portal.py
PYTHONPATH=src python examples/persistence_demo.py
PYTHONPATH=src python benchmarks/reference_benchmark.py
```

Optional editable install:

```bash
python -m pip install -e .
```

## Layout

- `report/` - technical report sources and final documents.
- `catalog/` - complete 360-mechanism catalog and summaries.
- `schema/` - UGTS-KC 3.0 world exchange schema and example.
- `src/ugts_kc3/` - dependency-free reference implementation.
- `tests/` - unit and integrity tests.
- `examples/` - executable demonstrations.
- `diagrams/` - report figures and diagram sources.
- `benchmarks/` - bounded reference CPU benchmark.
- `validation/` - captured test, schema, example and benchmark results.
- `sources/` - source register and hashes; no raw source PDFs.
- `provenance/` - package manifests and checksums.

## Correctness boundary

Passing tests establish internal consistency of the bounded reference implementation. They do not prove universal complexity, physical-device throughput, physical-GPU performance, exact roots for arbitrary fields, or a general replacement for conventional simulation, indexing, rendering or control systems.

## Requester attribution

See `REQUESTER_ATTRIBUTION.txt`. The identity data in that file was supplied by the requester and was not independently verified.
