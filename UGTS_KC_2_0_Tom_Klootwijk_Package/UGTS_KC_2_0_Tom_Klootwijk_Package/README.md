# UGTS-KC 2.0 - Pattern, Kinematic Calculus and Dynamics Expansion

This package extends the supplied **Unified Geometric-Topological Substrate** reports while preserving their core rule:

`local support -> compatibility -> guard crossing -> verified event -> route/transition -> lineage + novelty log`

The baseline catalog contains 197 normalized mechanisms. This engineering extension adds 60 explicitly marked mechanisms (M198-M257) covering parametric patterns, implicit fields/surfaces, topology descriptors, rigid-body and curve kinematics, and bounded dynamics/event resolution. The resulting extended catalog contains 257 entries.

## Attribution and privacy

Prepared for **Tom Klootwijk**. The identifier `NL200678942` and date of birth `1990-07-10` were supplied by the requester and are **not independently verified**. This package is a technical design artifact and is not legal proof of authorship, identity, ownership, patentability or priority.

## Quick start

```bash
python -m unittest discover -s tests -v
PYTHONPATH=src python examples/kinematic_event_demo.py
```

The reference runtime uses only the Python standard library. Diagram regeneration requires NumPy and Matplotlib.

## Layout

- `report/` - upgraded PDF and DOCX source.
- `spec/` - extended mechanism catalog, JSON schema and technical notes.
- `src/ugts_kc/` - dependency-free reference implementation.
- `tests/` - executable unit tests.
- `examples/` - JSON substrate definition and runnable demos.
- `diagrams/` - original figures generated for the report.
- `validation/` - captured test results, counts, hashes and manifest.
- `docs/` - changelog, evidence boundary and attribution notice.

## Evidence boundary

The 60 additions are engineering expansions, not claims that they were all present in the supplied source PDFs. Physical, performance and universal-complexity claims remain subject to measurement and the original kill criteria.
