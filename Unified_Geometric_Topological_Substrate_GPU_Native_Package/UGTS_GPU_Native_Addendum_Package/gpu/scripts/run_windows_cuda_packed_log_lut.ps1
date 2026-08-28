[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_packed_log_lut_run'),
    [string]$Entries = '2097152,14680064,16777216,18874368,20971520,25165824,33554432,39146832,50331648,55924048,67108864',
    [string]$Warps = '1,46,184,1104',
    [long]$EvictionMiB = 256,
    [int]$Warmup = 3,
    [int]$Samples = 12,
    [ValidateRange(0, 3)]
    [int]$Order = 0,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_packed_log_lut_bench.exe'
} else {
    $executable = & (Join-Path $PSScriptRoot 'build_windows_cuda_packed_log_lut.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed with exit code $LASTEXITCODE"
    }
}
if (-not (Test-Path -LiteralPath $executable)) {
    throw "CUDA benchmark executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$arguments = @('--out-dir', $outputPath, '--entries', $Entries,
    '--warps', $Warps, '--eviction-mib', $EvictionMiB,
    '--warmup', $Warmup, '--samples', $Samples, '--order', $Order)
& $executable @arguments
if ($LASTEXITCODE -ne 0) {
    throw "CUDA packed log-LUT benchmark failed with exit code $LASTEXITCODE"
}
