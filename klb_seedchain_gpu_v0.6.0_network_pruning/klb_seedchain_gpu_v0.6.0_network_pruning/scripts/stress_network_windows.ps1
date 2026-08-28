param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path (Join-Path (Join-Path $Root $BuildDir) $Configuration) "klb_network_bench.exe"
$Data = Join-Path $Root "data\network\celestrak_mixed_58obj_7d_60s.ksgp"
$Stations = Join-Path $Root "data\network\benchmark_station_network.csv"
if (-not (Test-Path $Bin)) { throw "Missing $Bin; run scripts\build_windows.ps1 first." }
& $Bin $Data $Stations --preset laptop --repeats 7 --min-ms 150 `
    --validation-intervals 10080 `
    --csv (Join-Path $Root "network_gpu_laptop_results.csv")
if ($LASTEXITCODE -ne 0) { throw "Laptop network stress test failed." }
