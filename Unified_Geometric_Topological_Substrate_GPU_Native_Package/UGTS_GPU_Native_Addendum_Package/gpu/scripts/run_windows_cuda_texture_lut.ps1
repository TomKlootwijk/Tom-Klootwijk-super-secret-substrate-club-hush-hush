[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\cuda_texture_lut_run'),
    [string]$TableMiB = '4,32,36,38,40,48,64,128',
    [string]$Warps = '1,46,184,1104',
    [long]$EvictionMiB = 256,
    [int]$Warmup = 3,
    [int]$Samples = 12,
    [switch]$TextureFirst,
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if ($SkipBuild) {
    $executable = Join-Path $gpuRoot 'build-windows\ugts_cuda_texture_lut_bench.exe'
} else {
    $executable = & (Join-Path $PSScriptRoot 'build_windows_cuda_texture_lut.ps1')
    if ($LASTEXITCODE -ne 0) {
        throw "Build failed with exit code $LASTEXITCODE"
    }
}
if (-not (Test-Path -LiteralPath $executable)) {
    throw "CUDA benchmark executable not found: $executable"
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$arguments = @('--out-dir', $outputPath, '--table-mib', $TableMiB,
    '--warps', $Warps, '--eviction-mib', $EvictionMiB,
    '--warmup', $Warmup, '--samples', $Samples)
if ($TextureFirst) {
    $arguments += '--texture-first'
}
& $executable @arguments
if ($LASTEXITCODE -ne 0) {
    throw "CUDA texture-LUT benchmark failed with exit code $LASTEXITCODE"
}
