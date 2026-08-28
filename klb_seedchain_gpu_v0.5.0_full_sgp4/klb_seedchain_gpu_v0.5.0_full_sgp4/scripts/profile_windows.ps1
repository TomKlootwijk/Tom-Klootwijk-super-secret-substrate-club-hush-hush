param(
    [string]$Data = "data\procedural_65536.klb",
    [string]$Report = "klb_packed_report",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Bench = Join-Path $Root "build\$Configuration\klb_bench.exe"
$DataPath = Join-Path $Root $Data

ncu --set full --target-processes all -o $Report `
    $Bench $DataPath `
    --mode packed --queries 1048576 --depth 12 `
    --warmup 0 --repeats 1 --verify 0
