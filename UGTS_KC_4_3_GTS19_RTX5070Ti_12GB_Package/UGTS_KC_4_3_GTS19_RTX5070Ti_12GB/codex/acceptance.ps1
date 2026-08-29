$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$env:PYTHONPATH = (Join-Path $Root "src")

python -m unittest discover -s tests -v
python -m ugts_go19 selftest
python -m ugts_go19 solve-tiny --size 1 --komi2 1 --node-budget 20000 `
  --certificate evidence/acceptance_1x1_certificate.json `
  --output evidence/acceptance_1x1_result.json
python -m ugts_go19 verify evidence/acceptance_1x1_certificate.json `
  --node-budget 20000 --output evidence/acceptance_1x1_verify.json
python -m ugts_go19 attempt19 --threshold2 1 --node-budget 2 `
  --output evidence/acceptance_19x19_bounded.json

cmake -S cpp -B build-acceptance -DUGTS_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
cmake --build build-acceptance --config Release
ctest --test-dir build-acceptance --output-on-failure
python scripts/claim_gate.py --expect-unknown evidence/acceptance_19x19_bounded.json
python scripts/verify_release.py --quick
Write-Host "Acceptance gates passed; 19x19 remains UNKNOWN absent a full verified certificate."
