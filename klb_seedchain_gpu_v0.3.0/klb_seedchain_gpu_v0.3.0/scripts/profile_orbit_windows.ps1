param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path (Join-Path $Root $BuildDir) $Configuration
$Data = Join-Path $Root "data\orbit\gps_ops_2026-08-16_7d_1s.kloc"
$Out = Join-Path $Root "orbit_seed_profile"

ncu --target-processes all --set full --force-overwrite `
    --export $Out `
    (Join-Path $Bin "klb_orbit_bench.exe") $Data `
    --preset laptop --query crossing --mode seed `
    --samples 1 --min-sample-ms 1 --warmup 0 --verify-epochs 0

Write-Host "Nsight Compute report: $Out.ncu-rep"
