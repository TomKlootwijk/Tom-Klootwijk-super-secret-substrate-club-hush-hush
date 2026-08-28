param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

cmake -S $Root -B (Join-Path $Root $BuildDir) `
    -G "Visual Studio 17 2022" -A x64 `
    -DKLB_CUDA_ARCH=120 -DKLB_REQUIRE_CUDA=ON
cmake --build (Join-Path $Root $BuildDir) --config $Configuration
ctest --test-dir (Join-Path $Root $BuildDir) -C $Configuration --output-on-failure
