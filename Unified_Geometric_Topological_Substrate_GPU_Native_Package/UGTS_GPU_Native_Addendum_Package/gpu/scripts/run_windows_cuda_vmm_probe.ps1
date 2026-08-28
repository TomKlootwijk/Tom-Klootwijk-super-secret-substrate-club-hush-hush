[CmdletBinding()]
param(
    [string]$OutputFile = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_vmm_granularity_probe\vmm_granularity.json'),
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_vmm_granularity_probe.exe'
} else {
    $buildOutput = & (Join-Path $PSScriptRoot 'build_windows_cuda_vmm_probe.ps1')
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
    $executable = $buildOutput | Select-Object -Last 1
}
if (-not (Test-Path -LiteralPath $executable)) {
    throw "CUDA VMM granularity probe executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputFile)
& $executable --out $outputPath
if ($LASTEXITCODE -ne 0) {
    throw "CUDA VMM granularity probe failed with exit code $LASTEXITCODE"
}
