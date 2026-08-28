# Reproducibility and validation

## Reference environment

Validation was run with the Python and platform recorded in `validation/benchmark_results.json`. The core implementation has no third-party runtime dependency.

## Commands

```bash
python -m unittest discover -s tests -v
python -m json.tool schema/example_world_v3.json > /dev/null
PYTHONPATH=src python examples/query_first_contact_portal.py
PYTHONPATH=src python examples/persistence_demo.py
PYTHONPATH=src python examples/contact_demo.py
PYTHONPATH=src python examples/field_dynamics_demo.py
PYTHONPATH=src python examples/uncertainty_replay_demo.py
PYTHONPATH=src python benchmarks/reference_benchmark.py
```

## Boundaries

- Floating-point results may vary in the last bits across runtimes and architectures.
- Performance measurements are environment-specific.
- The Python benchmark is not a GPU or physical-device benchmark.
- The package tests mathematical contracts and implementation consistency; they do not validate an optofluidic device or universal complexity claims.
- Certified status only applies to the bounded interval/Sturm utilities and declared assumptions.

## Package integrity

Use `provenance/SHA256SUMS.txt` to verify files. `provenance/manifest.json` records size, hash and relative path. Source PDF hashes are recorded separately under `sources/` and the PDFs are not redistributed.
