[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_l2_mlp_run'),
    [string]$TableMiB = '4,36,40,64,128',
    [string]$Warps = '1,2,4,8,16,32,46,92,184,368,736,1104',
    [long]$EvictionMiB = 256,
    [int]$Warmup = 3,
    [int]$Samples = 15,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_l2_mlp_bench.exe'
} else {
    $executable = & (Join-Path $PSScriptRoot 'build_windows_cuda_l2_mlp.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed with exit code $LASTEXITCODE"
    }
}
if (-not (Test-Path -LiteralPath $executable)) {
    throw "CUDA benchmark executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
& $executable --out-dir $outputPath --table-mib $TableMiB --warps $Warps `
    --eviction-mib $EvictionMiB --warmup $Warmup --samples $Samples
if ($LASTEXITCODE -ne 0) {
    throw "CUDA L2 MLP benchmark failed with exit code $LASTEXITCODE"
}
