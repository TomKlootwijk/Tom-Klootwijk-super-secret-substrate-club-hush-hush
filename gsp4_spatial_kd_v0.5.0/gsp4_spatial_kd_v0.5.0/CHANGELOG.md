# Changelog

## 0.5.0 — 2026-08-16

- Delivered sparse variable-length geospatial graph pipeline.
- Added dependency-light HGT-style typed attention and TGN-style temporal memory.
- Added embedding and bounded chat-teacher knowledge transfer.
- Added soft teacher-edge and ULTRA interchange.
- Added deterministic UGTS support/compatibility/guard/event query gate.
- Added hash-linked novelty and deployment formats.
- Added G64/G32 substrate export with precision contract.
- Added GeoNames, irregular observation CSV, OSM XML/PBF adapters.
- Added no-download Flevoland pilot, smoke checkpoint, teacher fixtures, UGTS bridge, and deployment bundle.
- Added RTX 5070 Ti setup, training, benchmark, and validation scripts.
- Added 21 passing tests and preparation-environment validation evidence.
- Fixed OSM XML parent/child clearing and query-local FP16 bridge time/elevation handling.
- Fixed duplicate ontology archive member when packaging an explicit ontology.

- Updated RTX setup to the current PyTorch CUDA 13.0 default and removed the retired hard-coded `cu128` wheel index; explicit index overrides remain available.
