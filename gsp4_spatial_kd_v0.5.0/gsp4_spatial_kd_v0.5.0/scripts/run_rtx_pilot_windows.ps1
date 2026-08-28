param([int]$Epochs = 30)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\setup_windows.ps1 -Cuda first." }
Set-Location $Root
$env:OMP_NUM_THREADS = "4"
$env:MKL_NUM_THREADS = "4"
$Out = "results\rtx_pilot"
New-Item -ItemType Directory -Force -Path $Out | Out-Null
& $Python -m ugts_spatial check-gpu --device cuda --precision float16 --output "$Out\gpu_environment.json"
& $Python -m ugts_spatial train data\flevoland_pilot.ugkg "$Out\flevoland_rtx_student.pt" `
  --teacher-edges examples\teacher_edges_smoke.ugte `
  --metrics "$Out\training_metrics.json" `
  --hidden-dim 128 --heads 8 --layers 4 --epochs $Epochs `
  --max-edges 8000 --max-encoder-edges 16000 --temporal-edges 2048 `
  --device cuda --precision float16
& $Python -m ugts_spatial query data\flevoland_pilot.ugkg `
  --model "$Out\flevoland_rtx_student.pt" `
  --source sensor:1:1:air --relation near --radius 10000 --epsilon 25 `
  --confidence-min 0.5 --max-events 32 --device cuda --precision float16 `
  --output "$Out\query.json"
& $Python -m ugts_spatial benchmark data\flevoland_pilot.ugkg "$Out\flevoland_rtx_student.pt" `
  --source sensor:1:1:air --relation near --radius 10000 --epsilon 25 `
  --warmup 10 --repeats 50 --device cuda --precision float16 `
  --output "$Out\benchmark.json"
& $Python -m ugts_spatial package data\flevoland_pilot.ugkg "$Out\flevoland_rtx.ugdeploy" `
  --model "$Out\flevoland_rtx_student.pt" --novelty data\flevoland_pilot.ugnl `
  --ontology ontology\gsp4_ontology.json
& $Python -m ugts_spatial validate-package "$Out\flevoland_rtx.ugdeploy" | Out-File -Encoding utf8 "$Out\deployment_validation.json"
Write-Host "RTX pilot complete: $Root\$Out"
