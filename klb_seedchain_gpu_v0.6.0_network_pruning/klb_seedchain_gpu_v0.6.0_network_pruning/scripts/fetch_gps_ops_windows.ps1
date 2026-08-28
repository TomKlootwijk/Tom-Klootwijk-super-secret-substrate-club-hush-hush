param(
    [string]$OutputPath = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $Root "data\orbit\source\gps_ops_latest_omm.csv"
}
if ((Test-Path $OutputPath) -and -not $Force) {
    throw "Refusing to overwrite existing snapshot: $OutputPath. Use -Force only for an intentional refresh."
}
$Directory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Force -Path $Directory | Out-Null
$Temporary = "$OutputPath.tmp"
$Url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=GPS-OPS&FORMAT=CSV"
Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Temporary
$Header = Get-Content -Path $Temporary -TotalCount 1
if (-not $Header.StartsWith("OBJECT_NAME,OBJECT_ID,EPOCH,MEAN_MOTION")) {
    Remove-Item -Force $Temporary
    throw "Downloaded response is not the expected OMM CSV"
}
Move-Item -Force $Temporary $OutputPath
Get-FileHash -Algorithm SHA256 $OutputPath
Write-Host "Downloaded once to $OutputPath. Respect CelesTrak's update/usage policy; do not poll this script."
