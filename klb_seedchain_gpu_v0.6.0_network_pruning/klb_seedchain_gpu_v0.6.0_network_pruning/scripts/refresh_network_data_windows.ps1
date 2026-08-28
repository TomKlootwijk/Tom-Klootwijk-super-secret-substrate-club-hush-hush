param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release",
    [switch]$Force
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SourceDir = Join-Path $Root "data\network\refresh"
New-Item -ItemType Directory -Force -Path $SourceDir | Out-Null
$Gps = Join-Path $SourceDir "gps_ops_current.csv"
$Mixed = Join-Path $SourceDir "tdrss_current.csv"
$Merged = Join-Path $SourceDir "celestrak_mixed_current.csv"
$Container = Join-Path $SourceDir "celestrak_mixed_current_7d_60s.ksgp"
if ((Test-Path $Merged) -and -not $Force) {
    throw "$Merged already exists. Use -Force for an intentional refresh; do not poll unchanged public data."
}
$Headers = @{"User-Agent" = "KLB-SeedChain-Research/0.6 (manual refresh)"}
Invoke-WebRequest -Headers $Headers -Uri "https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=CSV" -OutFile $Gps
Invoke-WebRequest -Headers $Headers -Uri "https://celestrak.org/NORAD/elements/gp.php?GROUP=TDRSS&FORMAT=CSV" -OutFile $Mixed
python (Join-Path $Root "tools\merge_omm_csv.py") $Merged $Gps $Mixed
if ($LASTEXITCODE -ne 0) { throw "OMM merge failed." }
$Packer = Join-Path (Join-Path (Join-Path $Root $BuildDir) $Configuration) "klb_sgp4.exe"
& $Packer pack-omm-csv $Merged $Container --horizon-hours 168 --step-seconds 60 --tile-hours 24
if ($LASTEXITCODE -ne 0) { throw "KSGP1 repack failed." }
Write-Host "Refreshed container: $Container"
