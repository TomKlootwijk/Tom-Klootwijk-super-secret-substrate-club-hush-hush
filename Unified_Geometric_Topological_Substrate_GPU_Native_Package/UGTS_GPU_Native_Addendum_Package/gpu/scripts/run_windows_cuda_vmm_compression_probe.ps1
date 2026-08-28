[CmdletBinding()]
param(
    [string]$OutputFile = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_vmm_compression_probe\vmm_compression.json'),
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_vmm_compression_probe.exe'
} else {
    $buildOutput = & (Join-Path $PSScriptRoot 'build_windows_cuda_vmm_compression_probe.ps1')
    if ($LASTEXITCODE -ne 0) { throw "Build failed with exit code $LASTEXITCODE" }
    $executable = $buildOutput | Select-Object -Last 1
}
if (-not (Test-Path -LiteralPath $executable)) {
    throw "CUDA VMM compression probe executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputFile)
& $executable --out $outputPath
if ($LASTEXITCODE -ne 0) {
    throw "CUDA VMM compression probe failed with exit code $LASTEXITCODE"
}
