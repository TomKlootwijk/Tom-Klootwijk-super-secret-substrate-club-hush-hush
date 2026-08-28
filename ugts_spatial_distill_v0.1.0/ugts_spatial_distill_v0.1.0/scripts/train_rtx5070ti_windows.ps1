param(
    [string]$Graph = ".\data\demo\graph",
    [string]$Output = ".\runs\rtx5070ti"
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}
python -m ugts_spatial train $Graph $Output --config .\configs\rtx5070ti_train.json
python -m ugts_spatial benchmark $Graph "$Output\checkpoint.pt" --device cuda --warmup 20 --repeats 100 --output "$Output\benchmark.json"
