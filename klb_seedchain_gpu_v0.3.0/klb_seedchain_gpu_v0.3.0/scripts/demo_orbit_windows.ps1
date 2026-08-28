param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path (Join-Path $Root $BuildDir) $Configuration
$Data = Join-Path $Root "data\orbit\gps_ops_2026-08-16_7d_1s.kloc"
$Results = Join-Path $Root "orbit_file_results.csv"
$Passes = Join-Path $Root "orbit_pass_events_rebuilt.csv"

& (Join-Path $Bin "klb_orbit.exe") inspect $Data
& (Join-Path $Bin "klb_orbit.exe") verify $Data
& (Join-Path $Bin "klb_orbit.exe") passes $Data `
    --lat 52 --lon 5 --alt-km 0.05 `
    --elevation-deg 10 --crossing-band-deg 0.25 `
    --hours 168 --step-seconds 1 --output $Passes
& (Join-Path $Bin "klb_orbit_bench.exe") $Data `
    --preset file --query crossing --mode all --write-events `
    --samples 9 --min-sample-ms 150 --verify-epochs 4096 `
    --csv $Results

Write-Host "Results: $Results"
Write-Host "Coarse pass schedule: $Passes"
