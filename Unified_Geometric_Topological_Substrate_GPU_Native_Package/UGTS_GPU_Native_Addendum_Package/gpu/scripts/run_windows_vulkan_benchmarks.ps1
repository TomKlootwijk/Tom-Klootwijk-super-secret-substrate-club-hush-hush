[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\windows_native_run'),
    [string]$Sizes = '1024,16384,262144,1048576',
    [int]$Warmup = 10,
    [int]$WarmupMilliseconds = 500,
    [int]$Iterations = 50
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

& $executable `
    --spirv-dir (Join-Path $gpuRoot 'spirv') `
    --out-dir $outputPath `
    --sizes $Sizes `
    --warmup $Warmup `
    --warmup-ms $WarmupMilliseconds `
    --iterations $Iterations
if ($LASTEXITCODE -ne 0) {
    throw "Benchmark failed with exit code $LASTEXITCODE"
}
