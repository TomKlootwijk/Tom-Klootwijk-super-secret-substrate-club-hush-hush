param(
    [string]$BuildDir = "build",
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BuildPath = Join-Path $Root $BuildDir

function Invoke-NativeChecked {
    param([scriptblock]$Command, [string]$Description)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

Invoke-NativeChecked {
    cmake -S $Root -B $BuildPath `
        -G "Visual Studio 17 2022" -A x64 `
        -DKLB_CUDA_ARCH=120 -DKLB_REQUIRE_CUDA=ON
} "CMake configure"

Invoke-NativeChecked {
    cmake --build $BuildPath --config $Configuration
} "CMake build"

Invoke-NativeChecked {
    ctest --test-dir $BuildPath -C $Configuration --output-on-failure
} "CTest"

$Expected = @(
    "klb_sgp4.exe",
    "klb_network.exe",
    "klb_sgp4_bench.exe",
    "klb_network_bench.exe"
)
foreach ($Binary in $Expected) {
    $Path = Join-Path (Join-Path $BuildPath $Configuration) $Binary
    if (-not (Test-Path $Path)) {
        throw "Expected binary was not created: $Path"
    }
}
Write-Host "Build and tests passed. Network challenge binaries are present."
