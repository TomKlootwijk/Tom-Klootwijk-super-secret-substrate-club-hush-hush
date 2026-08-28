[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_l2_stride_run'),
    [string]$TargetMiB = '4,8,9,10,11,12,16,17,18,19,20,21,22,23,24,28,32,36,37,38,39,40,48,56,64',
    [string]$StrideBytes = '4,8,16,32,64,128,256',
    [string]$Warps = '184,1104',
    [long]$EvictionMiB = 256,
    [int]$Warmup = 3,
    [int]$Samples = 12,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_l2_stride_bench.exe'
} else {
    $executable = & (Join-Path $PSScriptRoot 'build_windows_cuda_l2_stride.ps1')
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $executable)) { throw "CUDA benchmark executable not found: $executable" }
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
& $executable --out-dir $outputPath --target-mib $TargetMiB `
    --stride-bytes $StrideBytes --warps $Warps --eviction-mib $EvictionMiB `
    --warmup $Warmup --samples $Samples
if ($LASTEXITCODE -ne 0) { throw "CUDA L2-stride benchmark failed with exit code $LASTEXITCODE" }
