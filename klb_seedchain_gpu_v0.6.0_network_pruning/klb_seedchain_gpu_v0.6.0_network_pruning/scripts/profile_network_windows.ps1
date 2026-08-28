param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release",
    [string]$Output = "network_grouped_active.ncu-rep"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path (Join-Path (Join-Path $Root $BuildDir) $Configuration) "klb_network_bench.exe"
$Data = Join-Path $Root "data\network\celestrak_mixed_58obj_7d_60s.ksgp"
$Stations = Join-Path $Root "data\network\benchmark_station_network.csv"
if (-not (Get-Command ncu -ErrorAction SilentlyContinue)) { throw "Nsight Compute CLI (ncu) was not found." }
if (-not (Test-Path $Bin)) { throw "Missing $Bin; run scripts\build_windows.ps1 first." }
& ncu --set full --kernel-name "regex:grouped_query_kernel" --launch-count 1 `
    --export (Join-Path $Root $Output) --force-overwrite `
    $Bin $Data $Stations --preset smoke --repeats 1 --min-ms 1 --skip-dense
if ($LASTEXITCODE -ne 0) { throw "Nsight Compute profiling failed." }
