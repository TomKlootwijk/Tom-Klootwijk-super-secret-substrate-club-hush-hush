$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root
$env:PYTHONPATH = (Join-Path $Root "src")

function Assert-NativeCommandSucceeded {
  param([Parameter(Mandatory = $true)][string]$Step)
  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with native exit code $LASTEXITCODE."
  }
}

python -m unittest discover -s tests -v
Assert-NativeCommandSucceeded "Python unit tests"
python -m ugts_go19 selftest
Assert-NativeCommandSucceeded "Python selftest"
python -m ugts_go19 solve-tiny --size 1 --komi2 1 --node-budget 20000 `
  --certificate evidence/acceptance_1x1_certificate.json `
  --output evidence/acceptance_1x1_result.json
Assert-NativeCommandSucceeded "1x1 exact solve and certificate generation"
python -m ugts_go19 verify evidence/acceptance_1x1_certificate.json `
  --node-budget 20000 --output evidence/acceptance_1x1_verify.json
Assert-NativeCommandSucceeded "1x1 fresh-process certificate verification"
python -m ugts_go19 solve-tiny --size 2 --komi2 1 --node-budget 20000 `
  --certificate evidence/acceptance_2x2_certificate.json `
  --output evidence/acceptance_2x2_result.json
Assert-NativeCommandSucceeded "2x2 exact solve and certificate generation"
python -m ugts_go19 verify evidence/acceptance_2x2_certificate.json `
  --node-budget 20000 --output evidence/acceptance_2x2_verify.json
Assert-NativeCommandSucceeded "2x2 fresh-process certificate verification"
python -m ugts_go19 attempt19 --threshold2 1 --node-budget 2 `
  --output evidence/acceptance_19x19_bounded.json
Assert-NativeCommandSucceeded "Bounded 19x19 preflight"

cmake -S cpp -B build-acceptance -DUGTS_ENABLE_CUDA=OFF -DCMAKE_BUILD_TYPE=Release
Assert-NativeCommandSucceeded "C++ CPU configure"
cmake --build build-acceptance --config Release
Assert-NativeCommandSucceeded "C++ CPU build"
ctest --test-dir build-acceptance --build-config Release --output-on-failure
Assert-NativeCommandSucceeded "C++ CPU tests"
python scripts/claim_gate.py --expect-unknown evidence/acceptance_19x19_bounded.json
Assert-NativeCommandSucceeded "19x19 UNKNOWN claim gate"
python scripts/verify_release.py --quick `
  --attempt evidence/acceptance_19x19_bounded.json
Assert-NativeCommandSucceeded "Release structure verification"
Write-Host "Acceptance gates passed; 19x19 remains UNKNOWN absent a full verified certificate."
