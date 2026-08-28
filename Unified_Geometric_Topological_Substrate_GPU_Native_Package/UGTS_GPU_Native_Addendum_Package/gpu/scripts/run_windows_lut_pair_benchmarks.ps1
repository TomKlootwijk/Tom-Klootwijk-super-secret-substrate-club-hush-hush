[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\windows_lut_pair_run'),
    [string]$Sizes = '262144,524288,786432,1048576,2097152,4194304',
    [int]$Warmup = 10,
    [int]$WarmupMilliseconds = 750,
    [int]$Iterations = 200,
    [switch]$ReverseOrder
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$buildPath = & (Join-Path $PSScriptRoot 'build_windows_vulkan.ps1')
if ($LASTEXITCODE -ne 0) {
    throw "Build failed with exit code $LASTEXITCODE"
}
$executable = Join-Path $buildPath 'ugts_vulkan_bench.exe'
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

$arguments = @(
    '--spirv-dir', (Join-Path $gpuRoot 'spirv'),
    '--out-dir', $outputPath,
    '--sizes', $Sizes,
    '--warmup', $Warmup,
    '--warmup-ms', $WarmupMilliseconds,
    '--iterations', $Iterations,
    '--lut-only'
)
if ($ReverseOrder) {
    $arguments += '--lut-reverse'
}
& $executable @arguments
if ($LASTEXITCODE -ne 0) {
    throw "LUT-pair benchmark failed with exit code $LASTEXITCODE"
}
