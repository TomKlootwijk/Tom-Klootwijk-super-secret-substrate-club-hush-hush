$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$env:PYTHONPATH = "src"
$Exe = "cpp/build/rtx5070ti-release/ugts-chess-gpu.exe"
if (-not (Test-Path $Exe)) { throw "Build the RTX preset first with scripts/build_rtx5070ti.ps1" }
New-Item -ItemType Directory -Force -Path "validation/device/batch" | Out-Null

function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

python -m ugts_chess gpu-config --out "validation/device/rtx5070ti-profile.json"
Assert-NativeSuccess "GPU profile export"

$CampaignDir = "validation/device/campaign"
$CampaignDb = Join-Path $CampaignDir "classical_root.sqlite3"
python -m ugts_chess campaign-init --out-dir $CampaignDir --force --out "validation/device/campaign-init.json"
Assert-NativeSuccess "Device campaign initialization"
python -m ugts_chess campaign-status $CampaignDb --out "validation/device/campaign-status.json"
Assert-NativeSuccess "Device campaign status"
python -m ugts_chess campaign-verify $CampaignDb --out "validation/device/campaign-verify.json"
Assert-NativeSuccess "Device campaign verification"

python -m ugts_chess gpu-batch --executable $Exe --work-dir "validation/device/batch" `
  --fen "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" `
  --fen "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1" `
  --fen "8/8/8/1Q6/8/8/k7/2K5 w - - 100 2" `
  --out "validation/device/gpu-differential.json"
Assert-NativeSuccess "CUDA/Python differential batch"

& "cpp/build/rtx5070ti-release/ugts-chess2.exe" retro-demo | Tee-Object -FilePath "validation/device/cuda-retro-demo.json"
Assert-NativeSuccess "CUDA retrograde demonstration"
& "cpp/build/rtx5070ti-release/ugts-chess2.exe" root-shards | Tee-Object -FilePath "validation/device/native-root-shards.json"
Assert-NativeSuccess "Native root-shard export"

Write-Host "Campaign initialized. Root remains UNKNOWN until independently verified child certificates close the WDL obligations."
