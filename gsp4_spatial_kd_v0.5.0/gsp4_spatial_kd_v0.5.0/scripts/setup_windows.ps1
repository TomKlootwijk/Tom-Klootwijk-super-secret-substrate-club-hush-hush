param(
  [switch]$Cuda,
  [switch]$Full,
  [string]$Python = "python",
  [string]$TorchIndexUrl = ""
)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
& $Python -m venv .venv
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel
if ($Cuda) {
  # Current stable PyTorch publishes its Blackwell-capable CUDA build through
  # the normal package index. Supply -TorchIndexUrl only for a future/nightly
  # wheel channel or a controlled mirror.
  if ($TorchIndexUrl) {
    & $VenvPython -m pip install torch torchvision torchaudio --index-url $TorchIndexUrl
  } else {
    & $VenvPython -m pip install torch torchvision torchaudio
  }
} else {
  & $VenvPython -m pip install torch --index-url https://download.pytorch.org/whl/cpu
}
if ($Full) {
  & $VenvPython -m pip install -e ".[all]"
} else {
  & $VenvPython -m pip install -e ".[dev]"
}
& $VenvPython -m ugts_spatial --version
try {
  & $VenvPython -m ugts_spatial check-gpu --device auto --precision float16
} catch {
  Write-Warning "GPU smoke check did not pass during setup: $($_.Exception.Message)"
}
