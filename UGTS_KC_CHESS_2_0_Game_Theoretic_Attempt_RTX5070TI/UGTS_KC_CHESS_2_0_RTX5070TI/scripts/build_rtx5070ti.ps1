$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root
New-Item -ItemType Directory -Force -Path "validation/device" | Out-Null

function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

function Import-VsDevEnvironment {
    if (Get-Command cl.exe -ErrorAction SilentlyContinue) { return }

    $VsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $VsWhere)) {
        throw "Visual Studio C++ build tools are required, but vswhere.exe was not found."
    }
    $InstallPath = & $VsWhere -latest -products * `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 `
        -property installationPath
    Assert-NativeSuccess "Visual Studio discovery"
    if (-not $InstallPath) {
        throw "No Visual Studio installation with the x64 C++ toolchain was found."
    }

    $DevCmd = Join-Path $InstallPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path -LiteralPath $DevCmd)) {
        throw "Visual Studio developer command file was not found: $DevCmd"
    }
    & $env:ComSpec /s /c "`"$DevCmd`" -no_logo -arch=x64 -host_arch=x64 && set" |
        ForEach-Object {
            if ($_ -match '^([^=]+)=(.*)$') {
                Set-Item -Path "Env:$($Matches[1])" -Value $Matches[2]
            }
        }
    Assert-NativeSuccess "Visual Studio developer-environment setup"
    if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
        throw "Visual Studio developer environment loaded without exposing cl.exe."
    }
}

function New-ShortWorkspaceMount([string]$WorkspaceRoot) {
    foreach ($Letter in @("U", "V", "W", "X", "Y", "Z")) {
        $Drive = "${Letter}:"
        if (-not (Test-Path -LiteralPath "${Drive}\")) {
            subst.exe $Drive $WorkspaceRoot
            Assert-NativeSuccess "Short workspace mount"
            return $Drive
        }
    }
    throw "No free drive letter is available for the short CUDA build path."
}

Import-VsDevEnvironment

Write-Host "[1/7] Capturing NVIDIA and build environment"
try {
    nvidia-smi | Tee-Object -FilePath "validation/device/nvidia-smi.txt"
    Assert-NativeSuccess "nvidia-smi"
} catch { throw "nvidia-smi failed: $_" }
try {
    nvcc --version | Tee-Object -FilePath "validation/device/nvcc-version.txt"
    Assert-NativeSuccess "nvcc"
} catch { throw "CUDA nvcc 12.8 or newer is required for the SM120 preset: $_" }
cmake --version | Tee-Object -FilePath "validation/device/cmake-version.txt"
Assert-NativeSuccess "CMake version check"
Get-CimInstance Win32_OperatingSystem |
    Select-Object Caption, Version, BuildNumber, OSArchitecture |
    ConvertTo-Json | Set-Content -Encoding utf8 "validation/device/os-info.json"
powercfg.exe /getactivescheme | Tee-Object -FilePath "validation/device/active-power-scheme.txt"
Assert-NativeSuccess "Active power-scheme inspection"

Write-Host "[2/7] Configuring the SM120 CUDA build"
$BuildRoot = Join-Path $Root "cpp\build"
$BuildTarget = Join-Path $BuildRoot "rtx5070ti-release"
if (Test-Path -LiteralPath $BuildTarget) {
    $ResolvedBuildRoot = [System.IO.Path]::GetFullPath($BuildRoot).TrimEnd('\')
    $ResolvedTarget = [System.IO.Path]::GetFullPath($BuildTarget)
    if (-not $ResolvedTarget.StartsWith("$ResolvedBuildRoot\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove build target outside the expected build root: $ResolvedTarget"
    }
    Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
}

# nvcc on Windows cannot emit dependency files beneath this package's very
# long absolute path.  A temporary SUBST drive preserves the physical output
# location while keeping CMake/Ninja paths below the toolchain limit.
$ShortDrive = New-ShortWorkspaceMount $Root
Push-Location (Join-Path "${ShortDrive}\" "cpp")
try {
    & $env:ComSpec /d /s /c "cmake --preset rtx5070ti-release 2>&1" |
        Tee-Object -FilePath "$Root/validation/device/cmake-configure-rtx5070ti.txt"
    Assert-NativeSuccess "CMake SM120 configure"
    Write-Host "[3/7] Building"
    & $env:ComSpec /d /s /c "cmake --build --preset rtx5070ti-release --parallel 2>&1" |
        Tee-Object -FilePath "$Root/validation/device/cmake-build-rtx5070ti.txt"
    Assert-NativeSuccess "SM120 build"
    Write-Host "[4/7] Running native tests"
    ctest --preset rtx5070ti-release --output-on-failure 2>&1 | Tee-Object -FilePath "$Root/validation/device/ctest-rtx5070ti.txt"
    Assert-NativeSuccess "SM120 native tests"
}
finally {
    Pop-Location
    subst.exe $ShortDrive /D
    Assert-NativeSuccess "Short workspace unmount"
}

Write-Host "[5/7] Inspecting the physical device"
& "cpp/build/rtx5070ti-release/ugts-chess-gpu.exe" device-info | Tee-Object -FilePath "validation/device/device-info.json"
Assert-NativeSuccess "GPU device inspection"
& "cpp/build/rtx5070ti-release/ugts-chess2.exe" info | Tee-Object -FilePath "validation/device/native-info.json"
Assert-NativeSuccess "Native solver inspection"
cuobjdump --list-elf "cpp/build/rtx5070ti-release/ugts-chess-gpu.exe" |
    Tee-Object -FilePath "validation/device/gpu-cubins.txt"
Assert-NativeSuccess "GPU binary architecture inspection"
cuobjdump --list-elf "cpp/build/rtx5070ti-release/ugts-chess2.exe" |
    Tee-Object -FilePath "validation/device/retro-cubins.txt"
Assert-NativeSuccess "Retrograde binary architecture inspection"
$BinaryHashes = Get-FileHash -Algorithm SHA256 `
    "cpp/build/rtx5070ti-release/ugts-chess-gpu.exe", `
    "cpp/build/rtx5070ti-release/ugts-chess2.exe" |
    ForEach-Object {
        [ordered]@{
            path = (Resolve-Path -Relative $_.Path)
            sha256 = $_.Hash.ToLowerInvariant()
        }
    }
$BinaryHashes | ConvertTo-Json | Set-Content -Encoding utf8 "validation/device/binary-hashes.json"

Write-Host "[6/7] Running the Python differential suite"
$env:PYTHONPATH = "src"
$env:UGTS_GPU_HOST_EXE = "cpp/build/rtx5070ti-release/ugts-chess-gpu.exe"
# unittest's verbose progress is intentionally written to stderr.  Merge it
# inside cmd.exe so Windows PowerShell does not turn successful progress lines
# into NativeCommandError records; cmd.exe still returns Python's exit code.
& $env:ComSpec /d /s /c "python -m unittest discover -s tests -v 2>&1" |
    Tee-Object -FilePath "validation/device/python-tests.txt"
Assert-NativeSuccess "Python differential suite"

Write-Host "[7/7] Device build complete"
Write-Host "The build is not a chess solution or a performance claim. Run scripts/run_codex_campaign.ps1 and retain long-run telemetry."
