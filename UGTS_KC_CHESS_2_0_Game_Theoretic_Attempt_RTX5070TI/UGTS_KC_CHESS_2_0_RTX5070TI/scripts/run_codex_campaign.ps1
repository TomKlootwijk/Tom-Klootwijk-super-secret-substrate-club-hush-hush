param(
    [switch]$ResetCampaign
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
$env:PYTHONPATH = "src"
$Exe = "cpp/build/rtx5070ti-release/ugts-chess-gpu.exe"
if (-not (Test-Path $Exe)) { throw "Build the RTX preset first with scripts/build_rtx5070ti.ps1" }
New-Item -ItemType Directory -Force -Path "validation/device/batch" | Out-Null
New-Item -ItemType Directory -Force -Path "validation/device/gpu-qualification-1024-batches" | Out-Null

function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

python -m ugts_chess gpu-config --out "validation/device/rtx5070ti-profile.json"
Assert-NativeSuccess "GPU profile export"

$CampaignDir = "validation/device/campaign"
$CampaignDb = Join-Path $CampaignDir "classical_root.sqlite3"
$CampaignInitArgs = @(
    "-m", "ugts_chess", "campaign-init",
    "--out-dir", $CampaignDir,
    "--out", "validation/device/campaign-init.json"
)
if ($ResetCampaign) {
    $CampaignInitArgs += "--force"
}
elseif (Test-Path -LiteralPath $CampaignDb -PathType Leaf) {
    throw "Refusing to erase the existing authoritative campaign at $CampaignDb. " +
        "Archive it first, or rerun with -ResetCampaign to explicitly replace it."
}
python @CampaignInitArgs
Assert-NativeSuccess "Device campaign initialization"
python -m ugts_chess campaign-status $CampaignDb --out "validation/device/campaign-status.json"
Assert-NativeSuccess "Device campaign status"
python -m ugts_chess campaign-verify $CampaignDb --out "validation/device/campaign-verify.json"
Assert-NativeSuccess "Device campaign verification"
python -m ugts_chess campaign-export $CampaignDb `
  --output "validation/device/campaign-snapshot.json" `
  --out "validation/device/campaign-export.json"
Assert-NativeSuccess "Portable campaign checkpoint export"

python -m ugts_chess gpu-batch --executable $Exe --work-dir "validation/device/batch" `
  --fen "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1" `
  --fen "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1" `
  --fen "8/8/8/1Q6/8/8/k7/2K5 w - - 100 2" `
  --out "validation/device/gpu-differential.json"
Assert-NativeSuccess "CUDA/Python differential batch"

# The three-position smoke check above is useful for diagnosis.  This
# deterministic fixture-plus-random corpus is the actual move-generation gate:
# every batch must report the CUDA backend, exact native counters, no fallback,
# and the same complete legal-move sets as the independent Python oracle.
python -m ugts_chess gpu-qualify --executable $Exe `
  --random-count 1024 --max-plies 100 --chunk-size 256 `
  --work-dir "validation/device/gpu-qualification-1024-batches" `
  --out "validation/device/gpu-movegen-qualification-1024.json"
Assert-NativeSuccess "Deterministic CUDA move-generation qualification"

& "cpp/build/rtx5070ti-release/ugts-chess2.exe" retro-demo | Tee-Object -FilePath "validation/device/cuda-retro-demo.json"
Assert-NativeSuccess "CUDA retrograde demonstration"
& "cpp/build/rtx5070ti-release/ugts-chess2.exe" root-shards | Tee-Object -FilePath "validation/device/native-root-shards.json"
Assert-NativeSuccess "Native root-shard export"

Write-Host "Campaign initialized. Root remains UNKNOWN until independently verified child certificates close the WDL obligations."
