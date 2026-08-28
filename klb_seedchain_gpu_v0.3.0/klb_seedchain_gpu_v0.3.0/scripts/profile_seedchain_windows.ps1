param(
    [string]$Data = "data\procedural_65536_240f.klsc",
    [string]$Report = "klb_seedchain_direct_query",
    [int]$Frame = 239,
    [string]$BuildDir = "build",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bench = Join-Path $Root "$BuildDir\$Configuration\klb_seedchain_bench.exe"
$DataPath = Join-Path $Root $Data

ncu --set full --target-processes all -o $Report `
    $Bench $DataPath --frame $Frame --mode seed --warmup 0 --repeats 1 --verify 0
