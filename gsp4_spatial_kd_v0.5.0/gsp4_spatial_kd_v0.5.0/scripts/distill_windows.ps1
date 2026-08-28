param(
  [string]$Graph = "data\flevoland_pilot.ugkg",
  [string]$Output = "results\distillation",
  [int]$LabelLimit = 2000
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\setup_windows.ps1 first." }
Set-Location $Root
New-Item -ItemType Directory -Force -Path $Output | Out-Null
& $Python -m ugts_spatial embed $Graph "$Output\semantic.ugkg" `
  --backend http --base-url http://127.0.0.1:8080/v1 `
  --model Qwen3-Embedding --dimensions 256 --batch-size 32
& $Python -m ugts_spatial teacher-candidates "$Output\semantic.ugkg" "$Output\candidates.jsonl" `
  --max-distance 12000 --concepts-per-source 4 --spatial-per-source 6 --max-candidates $LabelLimit
& $Python -m ugts_spatial teacher-label "$Output\candidates.jsonl" "$Output\labels.jsonl" `
  --base-url http://127.0.0.1:8081/v1 --model Qwen3-4B --limit $LabelLimit --progress
& $Python -m ugts_spatial labels-to-edges "$Output\semantic.ugkg" "$Output\labels.jsonl" `
  "$Output\relation_teacher.ugte" --teacher-name qwen3-4b-local
& $Python -m ugts_spatial train "$Output\semantic.ugkg" "$Output\student.pt" `
  --teacher-edges "$Output\relation_teacher.ugte" --metrics "$Output\training.json" `
  --hidden-dim 128 --heads 8 --layers 4 --epochs 30 --device auto --precision float16
