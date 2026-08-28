param(
  [Parameter(Mandatory=$true)][string]$GeoNames,
  [Parameter(Mandatory=$true)][string]$OsmPbf
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\setup_windows.ps1 -Full first." }
if (-not (Test-Path $GeoNames)) { throw "Missing GeoNames file: $GeoNames" }
if (-not (Test-Path $OsmPbf)) { throw "Missing OSM PBF: $OsmPbf" }
Set-Location $Root
New-Item -ItemType Directory -Force -Path data\real | Out-Null
& $Python -m ugts_spatial ingest-geonames $GeoNames data\real\flevoland_geonames.ugkg `
  --bbox 52.20 5.10 52.90 6.00 --country-code NL --limit 15000 `
  --observations examples\observations_variable.csv --teacher-dimensions 64
& $Python -m ugts_spatial ingest-osm $OsmPbf data\real\flevoland_osm.ugkg `
  --limit 100000 --spatial-resolution 14 --neighbors 4
& $Python -m ugts_spatial inspect-graph data\real\flevoland_geonames.ugkg | Out-File -Encoding utf8 data\real\flevoland_geonames.summary.json
& $Python -m ugts_spatial inspect-graph data\real\flevoland_osm.ugkg | Out-File -Encoding utf8 data\real\flevoland_osm.summary.json
