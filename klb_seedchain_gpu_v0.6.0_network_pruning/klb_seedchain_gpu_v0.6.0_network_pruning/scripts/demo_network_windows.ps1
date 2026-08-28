param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release",
    [ValidateSet("smoke", "file")][string]$Preset = "file"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path (Join-Path (Join-Path $Root $BuildDir) $Configuration) "klb_network_bench.exe"
$Cpu = Join-Path (Join-Path (Join-Path $Root $BuildDir) $Configuration) "klb_network.exe"
$Data = Join-Path $Root "data\network\celestrak_mixed_58obj_7d_60s.ksgp"
$Stations = Join-Path $Root "data\network\benchmark_station_network.csv"
if (-not (Test-Path $Bin)) { throw "Missing $Bin; run scripts\build_windows.ps1 first." }

& $Cpu verify $Data $Stations --hours 168 --step-seconds 60 `
    --events (Join-Path $Root "network_cpu_events.csv") `
    --metrics (Join-Path $Root "network_cpu_metrics.csv")
if ($LASTEXITCODE -ne 0) { throw "CPU pruning oracle failed." }

& $Bin $Data $Stations --preset $Preset --repeats 7 --min-ms 150 `
    --csv (Join-Path $Root "network_gpu_${Preset}_results.csv")
if ($LASTEXITCODE -ne 0) { throw "GPU network challenge failed." }
