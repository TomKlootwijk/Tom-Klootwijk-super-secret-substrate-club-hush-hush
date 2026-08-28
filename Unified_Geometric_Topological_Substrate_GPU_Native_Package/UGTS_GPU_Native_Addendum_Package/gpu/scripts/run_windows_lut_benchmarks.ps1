[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\windows_lut_cache_run'),
    [string]$Entries = '2048,16384,131072,1048576,8388608,16777216,33554432,67108864',
    [long]$MinimumCandidates = 4194304,
    [long]$L2Bytes = 37748736,
    [int]$Warmup = 10,
    [int]$WarmupMilliseconds = 500,
    [int]$Iterations = 30,
    [switch]$ReverseOrder
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$buildPath = & (Join-Path $PSScriptRoot 'build_windows_vulkan.ps1')
if ($LASTEXITCODE -ne 0) {
    throw "Build failed with exit code $LASTEXITCODE"
}
$executable = Join-Path $buildPath 'ugts_vulkan_lut_bench.exe'
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

$arguments = @(
    '--spirv-dir', (Join-Path $gpuRoot 'spirv'),
    '--out-dir', $outputPath,
    '--entries', $Entries,
    '--min-candidates', $MinimumCandidates,
    '--l2-bytes', $L2Bytes,
    '--warmup', $Warmup,
    '--warmup-ms', $WarmupMilliseconds,
    '--iterations', $Iterations
)
if ($ReverseOrder) {
    $arguments += '--reverse'
}

& $executable @arguments
if ($LASTEXITCODE -ne 0) {
    throw "LUT benchmark failed with exit code $LASTEXITCODE"
}
