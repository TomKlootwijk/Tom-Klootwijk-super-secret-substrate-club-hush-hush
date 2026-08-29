$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if (-not (Test-Path ".venv")) { python -m venv .venv }
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .

New-Item -ItemType Directory -Force evidence | Out-Null
python scripts/hardware_probe.py evidence/target_hardware.json
.\codex\acceptance.ps1

cmake -S cpp -B build-cuda `
  -DUGTS_ENABLE_CUDA=ON `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_CUDA_ARCHITECTURES=native
cmake --build build-cuda --config Release

$Probe = Join-Path $Root "build-cuda\Release\ugts_go19_gpu_probe.exe"
if (-not (Test-Path $Probe)) { $Probe = Join-Path $Root "build-cuda\ugts_go19_gpu_probe.exe" }
if (Test-Path $Probe) { & $Probe | Tee-Object -FilePath evidence/target_cuda_probe.json }

Write-Host "Bootstrap complete. Read codex/TASKS.md and start M1; do not launch a long 19x19 campaign yet."
