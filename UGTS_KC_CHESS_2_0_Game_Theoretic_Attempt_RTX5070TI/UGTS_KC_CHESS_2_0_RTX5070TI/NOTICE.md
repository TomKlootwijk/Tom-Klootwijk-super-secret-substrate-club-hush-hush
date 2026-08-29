# Notice and Evidence Boundary

Prepared for Tom Klootwijk. The name is requester-supplied project attribution and is not independently verified.

This package is a technical design artifact and executable reference implementation. It is not legal proof of identity, authorship, ownership, patentability, priority or exclusive rights. The supplied UGTS PDFs are referenced by filename and SHA-256 in `spec/source_register.json`; they are not redistributed in the ZIP.

The package attempts to organize classical chess as a checker-verifiable game-theoretic proof campaign. It does **not** claim that the orthodox initial position is weakly, strongly or ultra-weakly solved. The recorded root value is `UNKNOWN`. Finite horizons, heuristic scores, GPU outputs, 64-bit keys, cache hits and unverified external tablebase probes are never promoted to proof.

The bundled KQK/KRK tables, mate proofs and bounded WDL certificates are exact only under their declared rule/state profiles. The dead-position recognizer intentionally covers a conservative subset; unresolved cases remain open proof obligations.

CUDA source and an SM120 build profile are supplied, but the packaging environment had no `nvcc` and no physical RTX 5070 Ti Laptop GPU. No target-device speed, thermal, power, battery, reliability or playing-strength advantage is claimed. Codex/device evidence must be added under `validation/device/` without overwriting host evidence.

FIDE, NVIDIA, CUDA and Syzygy names identify external standards, products or technical context. They do not imply endorsement.
