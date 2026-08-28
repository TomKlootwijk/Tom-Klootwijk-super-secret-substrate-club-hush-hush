[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_lut_sparse_address_run'),
    [string]$TargetMiB = '4,8,9,10,11,12,13,14,15,16,18,20,24,28,32,36,40,48',
    [string]$StrideBytes = '32,64,128,256',
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
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_lut_sparse_address_bench.exe'
} else {
    $executable = & (Join-Path $PSScriptRoot 'build_windows_cuda_lut_sparse_address.ps1')
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
}
if (-not (Test-Path -LiteralPath $executable)) {
    throw "CUDA sparse-address LUT benchmark executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
& $executable --out-dir $outputPath --target-mib $TargetMiB `
    --stride-bytes $StrideBytes --warps $Warps --eviction-mib $EvictionMiB `
    --warmup $Warmup --samples $Samples --order $Order
if ($LASTEXITCODE -ne 0) {
    throw "CUDA sparse-address LUT benchmark failed with exit code $LASTEXITCODE"
}
