param(
    [string]$InputGraph = ".\data\demo\graph",
    [string]$OutputGraph = ".\data\demo\graph_qwen",
    [string]$BaseUrl = "http://127.0.0.1:8080/v1",
    [int]$TargetDim = 256
)

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
if (Test-Path ".venv\Scripts\Activate.ps1") {
    & .\.venv\Scripts\Activate.ps1
}
python -m ugts_spatial embed $InputGraph $OutputGraph --base-url $BaseUrl --model Qwen3-Embedding-0.6B-Q8_0 --target-dim $TargetDim
