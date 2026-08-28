param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release",
    [string]$Data = "data\procedural_65536_240f.klsc",
    [int]$Frame = 239,
    [int]$Repeats = 20,
    [switch]$ExportPreview
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Cpu = Join-Path $Root "$BuildDir\$Configuration\klb_seedchain.exe"
$Gpu = Join-Path $Root "$BuildDir\$Configuration\klb_seedchain_bench.exe"
$DataPath = Join-Path $Root $Data
$Csv = Join-Path $Root "seedchain_results.csv"

if (-not (Test-Path $Cpu)) { throw "Missing $Cpu. Run scripts\build_windows.ps1 first." }
if (-not (Test-Path $Gpu)) { throw "Missing $Gpu. Build with CUDA Toolkit 12.8 or newer." }

& $Cpu inspect $DataPath
if ($ExportPreview) {
    $Preview = Join-Path $Root "seedchain_frame_$Frame.ply"
    & $Cpu export $DataPath $Frame $Preview
    Write-Host "Preview: $Preview"
}
& $Gpu $DataPath --frame $Frame --mode all --repeats $Repeats --csv $Csv
Write-Host "Results appended to $Csv"
