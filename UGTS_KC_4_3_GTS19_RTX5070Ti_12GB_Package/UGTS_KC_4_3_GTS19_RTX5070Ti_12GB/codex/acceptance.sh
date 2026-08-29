#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python -m pytest -q
python -m ugts_go19 selftest
python -m ugts_go19 solve-tiny --size 1 --komi2 1 --node-budget 20000 \
  --certificate evidence/acceptance_1x1_certificate.json \
  --output evidence/acceptance_1x1_result.json
python -m ugts_go19 verify evidence/acceptance_1x1_certificate.json \
  --node-budget 20000 --output evidence/acceptance_1x1_verify.json
python -m ugts_go19 solve-tiny --size 2 --komi2 1 --node-budget 20000 \
  --certificate evidence/acceptance_2x2_certificate.json \
  --output evidence/acceptance_2x2_result.json
python -m ugts_go19 verify evidence/acceptance_2x2_certificate.json \
  --node-budget 20000 --output evidence/acceptance_2x2_verify.json
python -m ugts_go19 pndag-tiny --size 2 --komi2 1 --threshold2 1 \
  --additional-expansions 7 \
  --checkpoint evidence/acceptance_pndag_2x2_t1_checkpoint.json \
  --overwrite --expect-status UNKNOWN \
  --output evidence/acceptance_pndag_2x2_t1_partial.json
python -m ugts_go19 pndag-tiny --size 2 --komi2 1 --threshold2 1 \
  --additional-expansions 10000 \
  --checkpoint evidence/acceptance_pndag_2x2_t1_checkpoint.json \
  --resume --expect-status PROVEN \
  --output evidence/acceptance_pndag_2x2_t1_complete.json
python -m ugts_go19 pndag-tiny --size 2 --komi2 1 --threshold2 1 \
  --additional-expansions 0 \
  --checkpoint evidence/acceptance_pndag_2x2_t1_checkpoint.json \
  --resume --expect-status PROVEN \
  --output evidence/acceptance_pndag_2x2_t1_reload.json
python -m ugts_go19 pndag-tiny --size 2 --komi2 1 --threshold2 3 \
  --additional-expansions 7 \
  --checkpoint evidence/acceptance_pndag_2x2_t3_checkpoint.json \
  --overwrite --expect-status UNKNOWN \
  --output evidence/acceptance_pndag_2x2_t3_partial.json
python -m ugts_go19 pndag-tiny --size 2 --komi2 1 --threshold2 3 \
  --additional-expansions 10000 \
  --checkpoint evidence/acceptance_pndag_2x2_t3_checkpoint.json \
  --resume --expect-status DISPROVEN \
  --output evidence/acceptance_pndag_2x2_t3_complete.json
python -m ugts_go19 pndag-tiny --size 2 --komi2 1 --threshold2 3 \
  --additional-expansions 0 \
  --checkpoint evidence/acceptance_pndag_2x2_t3_checkpoint.json \
  --resume --expect-status DISPROVEN \
  --output evidence/acceptance_pndag_2x2_t3_reload.json
python -m ugts_go19 attempt19 --threshold2 1 --node-budget 2 \
  --output evidence/acceptance_19x19_bounded.json

cmake -S cpp -B build-acceptance -DUGTS_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-acceptance --config Release
ctest --test-dir build-acceptance --build-config Release --output-on-failure

python scripts/parity_gate.py evidence/local_m1_cpp_python_parity_v2_1m.json
python scripts/storage_gate.py --validate evidence/local_m2_storage_gate.json
python scripts/claim_gate.py --expect-unknown evidence/acceptance_19x19_bounded.json
python scripts/verify_release.py --quick \
  --attempt evidence/acceptance_19x19_bounded.json

echo "UGTS GTS-19 acceptance gates passed. Root 19x19 status remains UNKNOWN unless a full certificate is separately verified."
