[CmdletBinding()]
param(
    [string]$OutputDirectory = (Join-Path $PSScriptRoot '..\build-windows'),
    [string]$CudaRoot = 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8'
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$compiler = Join-Path $CudaRoot 'bin\nvcc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw "CUDA compiler not found: $compiler" }
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
$source = Join-Path $gpuRoot 'src\ugts_cuda_vmm_compression_probe.cpp'
$executable = Join-Path $outputPath 'ugts_cuda_vmm_compression_probe.exe'
& $compiler -std=c++17 -O2 -x cu -I (Join-Path $CudaRoot 'include') $source `
    -L (Join-Path $CudaRoot 'lib\x64') -lcuda -o $executable
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $executable)) {
    throw "CUDA VMM compression probe build failed with exit code $LASTEXITCODE"
}
Write-Output $executable
