param(
    [string]$BuildDir = "$env:USERPROFILE\Documents\sara363_cuda_build",
    [string]$Configuration = "Release",
    [int]$Bip39Batch = 8192,
    [int]$Bip32Batch = 512,
    [int]$Runs = 5
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$CudaRoot = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8"
$Nvcc = Join-Path $CudaRoot "bin\nvcc.exe"
$Metrics = Join-Path $Root "output\benchmark_metrics.json"

if (-not (Test-Path -LiteralPath $Nvcc)) {
    throw "Required CUDA 12.8 compiler not found at $Nvcc"
}

cmake -S $Root -B $BuildDir `
    -G "Visual Studio 17 2022" -A x64 -T "cuda=$CudaRoot" `
    -DCMAKE_CUDA_COMPILER="$Nvcc" -DSARA_CUDA_ARCH=120 -DBUILD_TESTING=ON
cmake --build $BuildDir --config $Configuration --parallel
ctest --test-dir $BuildDir -C $Configuration --output-on-failure

$Executable = Join-Path $BuildDir "$Configuration\sara363_cuda_conformance.exe"
& $Executable --bip39-batch $Bip39Batch --bip32-batch $Bip32Batch --runs $Runs --json $Metrics

$SaraPython = Join-Path (Split-Path -Parent $Root) ".venv-security\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $SaraPython)) {
    throw "Literal SARA verification environment not found at $SaraPython"
}
& $SaraPython (Join-Path $Root "scripts\verify_against_sara.py")
