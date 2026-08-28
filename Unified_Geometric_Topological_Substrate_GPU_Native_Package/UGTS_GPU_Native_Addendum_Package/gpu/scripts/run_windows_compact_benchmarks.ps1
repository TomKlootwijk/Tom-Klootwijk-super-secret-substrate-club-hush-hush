[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\..\benchmarks\windows_compact_run'),
    [string]$Sizes = '262144,393216,524288,786432,1048576,2097152,4194304',
    [int]$Warmup = 10,
    [int]$WarmupMilliseconds = 750,
    [int]$Iterations = 200,
    [double]$CapacityRatio = 1.0,
    [switch]$AllowOverflow,
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
    '--compact-only',
    '--compact-capacity-ratio', $CapacityRatio.ToString([Globalization.CultureInfo]::InvariantCulture)
)
if ($AllowOverflow) {
    $arguments += '--allow-compact-overflow'
}
if ($ReverseOrder) {
    $arguments += '--compact-reverse'
}
& $executable @arguments
if ($LASTEXITCODE -ne 0) {
    throw "Compact benchmark failed with exit code $LASTEXITCODE"
}
