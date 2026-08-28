[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\build-windows'),
    [string]$CudaRoot = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8'
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$nvcc = Join-Path $CudaRoot 'bin\nvcc.exe'
if (-not (Test-Path -LiteralPath $nvcc)) { throw "CUDA compiler not found: $nvcc" }
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Visual Studio Build Tools were not found.' }
$vsRoot = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsRoot) { throw 'A Visual Studio installation with the x64 C++ tools was not found.' }
$vcvars = Join-Path $vsRoot 'VC\Auxiliary\Build\vcvars64.bat'
$environmentLines = & $env:ComSpec /d /c "call `"$vcvars`" >nul && set"
if ($LASTEXITCODE -ne 0) { throw "Visual Studio environment setup failed: $LASTEXITCODE" }
foreach ($line in $environmentLines) {
    if ($line -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$source = Join-Path $gpuRoot 'src\ugts_cuda_l2_stride_bench.cu'
$executable = Join-Path $outputPath 'ugts_cuda_l2_stride_bench.exe'
& $nvcc -std=c++17 -O3 -lineinfo -arch=sm_120 -Xptxas=-v $source -o $executable
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $executable)) {
    throw "CUDA L2-stride benchmark build failed with exit code $LASTEXITCODE"
}
Write-Output $executable
