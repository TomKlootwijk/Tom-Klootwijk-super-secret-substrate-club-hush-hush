param([string]$Destination = "external_data")

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$OutDir = Join-Path $Root $Destination
$Archive = Join-Path $OutDir "bunny.tar.gz"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Invoke-WebRequest -Uri "https://graphics.stanford.edu/pub/3Dscanrep/bunny.tar.gz" -OutFile $Archive
tar -xzf $Archive -C $OutDir
Write-Host "PLY: $(Join-Path $OutDir 'bunny\reconstruction\bun_zipper.ply')"
Write-Host "Review Stanford's attribution and use terms before use beyond testing."
