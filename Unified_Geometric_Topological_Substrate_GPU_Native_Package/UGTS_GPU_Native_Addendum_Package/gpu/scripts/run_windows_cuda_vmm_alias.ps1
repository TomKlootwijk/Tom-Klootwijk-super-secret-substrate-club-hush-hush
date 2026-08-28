[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_vmm_alias_smoke'),
    [string]$Cases = '32x2,64x2,120x2,126x2,127x2,128x2,129x2,130x2,136x2,160x2,64x4,64x6,64x8',
    [string]$Warps = '184,1104',
    [int]$EvictionMiB = 256,
    [int]$Warmup = 2,
    [int]$Samples = 10,
    [ValidateSet(0, 1)]
    [int]$Order = 0,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_vmm_alias_bench.exe'
} else {
    $buildOutput = & (Join-Path $PSScriptRoot 'build_windows_cuda_vmm_alias.ps1')
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
    $executable = $buildOutput | Select-Object -Last 1
}
if (-not (Test-Path -LiteralPath $executable)) {
    throw "CUDA VMM-alias benchmark executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
& $executable --out-dir $outputPath --cases $Cases --warps $Warps `
    --eviction-mib $EvictionMiB --warmup $Warmup --samples $Samples --order $Order
if ($LASTEXITCODE -ne 0) {
    throw "CUDA VMM-alias benchmark failed with exit code $LASTEXITCODE"
}
