$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\setup_windows.ps1 first." }
Set-Location $Root
$env:OMP_NUM_THREADS = "4"
$env:MKL_NUM_THREADS = "4"
New-Item -ItemType Directory -Force -Path "results\no_download" | Out-Null
& $Python -m ugts_spatial inspect-graph data\flevoland_pilot.ugkg | Out-File -Encoding utf8 results\no_download\graph.json
& $Python -m ugts_spatial validate-novelty data\flevoland_pilot.ugnl | Out-File -Encoding utf8 results\no_download\novelty.json
& $Python -m ugts_spatial inspect-teacher examples\teacher_edges_smoke.ugte | Out-File -Encoding utf8 results\no_download\teacher.json
& $Python -m ugts_spatial query data\flevoland_pilot.ugkg `
  --model models\gsp4_flevoland_student_smoke.pt `
  --source sensor:1:1:air --relation near --radius 10000 --epsilon 25 `
  --max-events 32 --device cpu --precision float32 `
  --output results\no_download\query.json | Out-File -Encoding utf8 results\no_download\query_console.json
& $Python -m ugts_spatial validate-package data\gsp4_flevoland_smoke.ugdeploy | Out-File -Encoding utf8 results\no_download\deployment.json
& $Python -m pytest -q | Tee-Object -FilePath results\no_download\tests.txt
Write-Host "GSP4 no-download validation complete: $Root\results\no_download"
