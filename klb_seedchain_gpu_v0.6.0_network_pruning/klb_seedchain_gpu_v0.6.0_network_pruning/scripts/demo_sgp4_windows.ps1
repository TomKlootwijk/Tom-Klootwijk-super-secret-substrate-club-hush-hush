param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release",
    [ValidateSet("smoke", "file", "laptop")]
    [string]$Preset = "smoke"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bin = Join-Path $Root "$BuildDir\$Configuration"
$Data = Join-Path $Root "data\sgp4\gps_ops_2026-08-16_7d_1s.ksgp"
$Results = Join-Path $Root "sgp4_${Preset}_results.csv"
$Expected = Join-Path $Root "data\sgp4\gps_ops_2026-08-16_52N_5E_full_sgp4_pass_events.csv"

& (Join-Path $Bin "klb_sgp4.exe") inspect $Data
& (Join-Path $Bin "klb_sgp4.exe") verify $Data

$Args = @(
    $Data,
    "--preset", $Preset,
    "--repeats", "7",
    "--min-ms", "150",
    "--csv", $Results
)
if ($Preset -eq "smoke") {
    $Args += "--validation-only"
} elseif ($Preset -eq "file") {
    $Args += @("--expected-events", $Expected)
}
& (Join-Path $Bin "klb_sgp4_bench.exe") @Args
Write-Host "Results: $Results"
