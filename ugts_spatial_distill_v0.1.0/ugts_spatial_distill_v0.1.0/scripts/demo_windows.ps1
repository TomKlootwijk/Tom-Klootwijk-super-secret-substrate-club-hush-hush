param(
    [string]$Device = "auto"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}

python -m ugts_spatial verify .\data\demo\graph --checkpoint .\runs\demo_cpu\checkpoint.pt
python -m ugts_spatial query .\data\demo\graph .\runs\demo_cpu\checkpoint.pt `
    --source "air_temperature sensor 0 in Almere" `
    --relation near `
    --radius-m 10000 `
    --verified-only `
    --novelty-log .\runs\demo_query_novelty.jsonl
python -m ugts_spatial benchmark .\data\demo\graph .\runs\demo_cpu\checkpoint.pt `
    --device $Device `
    --warmup 10 `
    --repeats 50 `
    --output .\runs\demo_benchmark.json
