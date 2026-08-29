#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p evidence

python -m pytest -q 2>&1 | tee evidence/python_pytest.txt
python scripts/generate_fixtures.py
python -m ugts_go19 selftest > evidence/python_selftest.json
python -m ugts_go19 frontier --depth 1 --limit 64 --output evidence/opening_frontier.json
python -m ugts_go19 plan-memory --free-vram-gib 10 --output evidence/memory_plan_10gib_free.json
python -m ugts_go19 attempt19 --threshold2 1 --node-budget 64 --output evidence/attempt19_bounded.json
python scripts/claim_gate.py --expect-unknown evidence/attempt19_bounded.json
python scripts/state_space_bounds.py > evidence/state_space_bounds.json

rm -rf evidence/build-cpu
cmake -S cpp -B evidence/build-cpu -DUGTS_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release \
  > evidence/cmake_configure.txt 2>&1
cmake --build evidence/build-cpu --config Release > evidence/cmake_build.txt 2>&1
evidence/build-cpu/ugts_go19_smoke > evidence/cpp_smoke.json
ctest --test-dir evidence/build-cpu --output-on-failure > evidence/ctest.txt
python scripts/parity_gate.py evidence/local_m1_cpp_python_parity_v2_1m.json
python scripts/storage_gate.py --validate evidence/local_m2_storage_gate.json
python scripts/persistent_pndag_gate.py --validate evidence/local_m2_persistent_pndag_gate.json

python scripts/make_manifest.py
python scripts/verify_release.py
