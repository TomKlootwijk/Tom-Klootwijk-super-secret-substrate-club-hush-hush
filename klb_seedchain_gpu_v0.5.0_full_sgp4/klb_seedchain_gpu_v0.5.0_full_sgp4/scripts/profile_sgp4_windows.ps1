param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release",
    [ValidateSet("smoke", "file", "laptop")]
    [string]$Preset = "file"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Exe = Join-Path $Root "$BuildDir\$Configuration\klb_sgp4_bench.exe"
$Data = Join-Path $Root "data\sgp4\gps_ops_2026-08-16_7d_1s.ksgp"
$Report = Join-Path $Root "sgp4_${Preset}_ncu"

ncu --set full --target-processes all --export $Report --force-overwrite `
    $Exe $Data --preset $Preset --repeats 1 --min-ms 25 --skip-events
