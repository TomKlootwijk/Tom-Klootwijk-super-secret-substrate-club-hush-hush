param(
    [Parameter(Mandatory=$true)][string]$Sp3File,
    [string]$BuildDir = "build",
    [string]$Configuration = "Release",
    [string]$Ksgp = "data\network\celestrak_mixed_58obj_7d_60s.ksgp",
    [string]$Output = "sp3_comparison.csv",
    [string]$Summary = "sp3_comparison.summary.txt",
    [int]$MaxEpochs = 96,
    [int]$Stride = 1,
    [double]$Dut1Seconds = 0.0
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Get-Command python -ErrorAction Stop
$Tool = Join-Path $Root "tools\compare_sp3.py"
$Binary = Join-Path (Join-Path (Join-Path $Root $BuildDir) $Configuration) "klb_sgp4.exe"
$KsgpPath = if ([System.IO.Path]::IsPathRooted($Ksgp)) { $Ksgp } else { Join-Path $Root $Ksgp }
$OutputPath = if ([System.IO.Path]::IsPathRooted($Output)) { $Output } else { Join-Path $Root $Output }
$SummaryPath = if ([System.IO.Path]::IsPathRooted($Summary)) { $Summary } else { Join-Path $Root $Summary }
if (-not (Test-Path $Sp3File)) { throw "SP3 file not found: $Sp3File" }
if (-not (Test-Path $Binary)) { throw "Missing $Binary; run scripts\build_windows.ps1 first." }
& $Python.Source $Tool --sp3 $Sp3File --ksgp $KsgpPath --klb-sgp4 $Binary `
    --output $OutputPath --summary $SummaryPath --max-epochs $MaxEpochs `
    --stride $Stride --dut1-seconds $Dut1Seconds
if ($LASTEXITCODE -ne 0) { throw "SP3 comparison failed with exit code $LASTEXITCODE" }
Write-Host "Comparison CSV: $OutputPath"
Write-Host "Summary: $SummaryPath"
