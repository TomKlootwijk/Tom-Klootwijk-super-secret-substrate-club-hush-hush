$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

function Assert-NativeCommandSucceeded {
  param([Parameter(Mandatory = $true)][string]$Step)
  if ($LASTEXITCODE -ne 0) {
    throw "$Step failed with native exit code $LASTEXITCODE."
  }
}

if (-not (Test-Path ".venv")) {
  python -m venv .venv
  Assert-NativeCommandSucceeded "Virtual environment creation"
}
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
Assert-NativeCommandSucceeded "pip upgrade"
python -m pip install -e .
Assert-NativeCommandSucceeded "Editable package installation"

New-Item -ItemType Directory -Force evidence | Out-Null
python scripts/hardware_probe.py evidence/target_hardware.json
Assert-NativeCommandSucceeded "Target hardware probe"
.\codex\acceptance.ps1

cmake -S cpp -B build-cuda `
  -DUGTS_ENABLE_CUDA=ON `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_CUDA_ARCHITECTURES=native
Assert-NativeCommandSucceeded "CUDA configure"
cmake --build build-cuda --config Release
Assert-NativeCommandSucceeded "CUDA build"

$Probe = Join-Path $Root "build-cuda\Release\ugts_go19_gpu_probe.exe"
if (-not (Test-Path $Probe)) { $Probe = Join-Path $Root "build-cuda\ugts_go19_gpu_probe.exe" }
if (Test-Path $Probe) {
  & $Probe | Tee-Object -FilePath evidence/target_cuda_probe.json
  Assert-NativeCommandSucceeded "CUDA runtime probe"
}

Write-Host "Bootstrap complete. Read codex/TASKS.md and start M1; do not launch a long 19x19 campaign yet."
