param(
    [Parameter(Mandatory = $true)][string]$Frames,
    [Parameter(Mandatory = $true)][string]$Output,
    [string]$BuildDir = "build",
    [string]$Configuration = "Release",
    [int]$Checkpoint = 16,
    [double]$ResidualThreshold = 0.002
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Tool = Join-Path $Root "$BuildDir\$Configuration\klb_seedchain.exe"
& $Tool fit-sequence $Frames $Output --checkpoint $Checkpoint --residual-threshold $ResidualThreshold
