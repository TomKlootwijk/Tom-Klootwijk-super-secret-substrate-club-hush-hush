#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
python -m unittest discover -s tests -v
PYTHONPATH=src python examples/query_first_contact_portal.py
PYTHONPATH=src python examples/persistence_demo.py
PYTHONPATH=src python examples/contact_demo.py
PYTHONPATH=src python examples/field_dynamics_demo.py
PYTHONPATH=src python examples/uncertainty_replay_demo.py
PYTHONPATH=src python benchmarks/reference_benchmark.py
