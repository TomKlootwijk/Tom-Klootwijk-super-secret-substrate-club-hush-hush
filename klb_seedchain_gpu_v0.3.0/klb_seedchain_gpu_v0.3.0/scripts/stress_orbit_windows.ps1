param(
    [ValidateSet("smoke", "file", "laptop", "vram")]
    [string]$Preset = "laptop",
    [string]$BuildDir = "build",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path (Join-Path $Root $BuildDir) $Configuration
$Data = Join-Path $Root "data\orbit\gps_ops_2026-08-16_7d_1s.kloc"
$Results = Join-Path $Root ("orbit_{0}_results.csv" -f $Preset)

& (Join-Path $Bin "klb_orbit_bench.exe") $Data `
    --preset $Preset --query crossing --mode all --write-events `
    --samples 11 --min-sample-ms 250 --verify-epochs 4096 `
    --csv $Results

Write-Host "Results: $Results"
