[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\windows_l2_latency_run'),
    [string]$Entries = '1048576,4194304,6291456,7340032,8388608,8912896,9437184,9961472,10485760,12582912,16777216,33554432',
    [long]$Invocations = 65536,
    [long]$L2Bytes = 37748736,
    [int]$Warmup = 10,
    [int]$WarmupMilliseconds = 750,
    [int]$Iterations = 100,
    [switch]$ReverseOrder,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $buildPath = Join-Path $gpuRoot 'build-windows'
} else {
    $buildPath = & (Join-Path $PSScriptRoot 'build_windows_vulkan.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed with exit code $LASTEXITCODE"
    }
}
$executable = Join-Path $buildPath 'ugts_vulkan_lut_bench.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw "Benchmark executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null

$arguments = @(
    '--spirv-dir', (Join-Path $gpuRoot 'spirv'),
    '--out-dir', $outputPath,
    '--latency-only',
    '--entries', $Entries,
    '--latency-invocations', $Invocations,
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
    throw "L2 latency benchmark failed with exit code $LASTEXITCODE"
}
