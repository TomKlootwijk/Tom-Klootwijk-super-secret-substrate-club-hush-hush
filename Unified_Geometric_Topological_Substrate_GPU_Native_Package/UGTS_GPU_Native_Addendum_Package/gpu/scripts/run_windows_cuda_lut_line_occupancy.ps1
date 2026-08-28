[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_lut_line_occupancy_run'),
    [string]$TableMiB = '28,32,36,37,38,39,40,48',
    [string]$CodesPerLine = '1,2,4,8,16,32,64,128,170',
    [string]$Warps = '184,1104',
    [long]$EvictionMiB = 256,
    [int]$Warmup = 3,
    [int]$Samples = 12,
    [ValidateRange(0, 1)]
    [int]$Order = 0,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_lut_line_occupancy_bench.exe'
} else {
    $executable = & (Join-Path $PSScriptRoot 'build_windows_cuda_lut_line_occupancy.ps1')
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $executable)) {
    throw "CUDA LUT line-occupancy benchmark executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
& $executable --out-dir $outputPath --table-mib $TableMiB `
    --codes-per-line $CodesPerLine --warps $Warps --eviction-mib $EvictionMiB `
    --warmup $Warmup --samples $Samples --order $Order
if ($LASTEXITCODE -ne 0) {
    throw "CUDA LUT line-occupancy benchmark failed with exit code $LASTEXITCODE"
}
