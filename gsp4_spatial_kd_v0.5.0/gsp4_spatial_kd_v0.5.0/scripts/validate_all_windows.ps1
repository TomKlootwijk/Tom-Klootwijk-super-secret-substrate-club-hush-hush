$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) { throw "Run scripts\setup_windows.ps1 first." }
Set-Location $Root
New-Item -ItemType Directory -Force -Path results\validation_replay | Out-Null
& $Python -m pytest -q | Tee-Object -FilePath results\validation_replay\tests.txt
& $Python -m ugts_spatial inspect-graph data\flevoland_pilot.ugkg | Out-File -Encoding utf8 results\validation_replay\graph.json
& $Python -m ugts_spatial validate-novelty data\flevoland_pilot.ugnl | Out-File -Encoding utf8 results\validation_replay\novelty.json
& $Python -m ugts_spatial validate-package data\gsp4_flevoland_smoke.ugdeploy | Out-File -Encoding utf8 results\validation_replay\deployment.json
& $Python -m compileall -q src scripts\verify_manual_asset.py
& $Python -m build
Get-ChildItem dist\* | Get-FileHash -Algorithm SHA256 | Format-Table -AutoSize | Out-String | Out-File -Encoding utf8 results\validation_replay\dist.sha256.txt
