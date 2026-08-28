[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\windows_cold_lineage_run'),
    [string]$Sizes = '1310720,1441792,1474560,1507328,1540096,1572864,1638400,1703936,1769472,1835008,2097152,4194304',
    [int]$Warmup = 10,
    [int]$WarmupMilliseconds = 750,
    [int]$Iterations = 200,
    [double]$CapacityRatio = 0.0625,
    [switch]$ReverseOrder
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

$arguments = @(
    '--spirv-dir', (Join-Path $gpuRoot 'spirv'),
    '--out-dir', $outputPath,
    '--sizes', $Sizes,
    '--warmup', $Warmup,
    '--warmup-ms', $WarmupMilliseconds,
    '--iterations', $Iterations,
    '--compact-capacity-ratio', $CapacityRatio.ToString([Globalization.CultureInfo]::InvariantCulture),
    '--cold-lineage-only'
)
if ($ReverseOrder) {
    $arguments += '--compact-reverse'
}
& $executable @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Cold-lineage benchmark failed with exit code $LASTEXITCODE"
}
