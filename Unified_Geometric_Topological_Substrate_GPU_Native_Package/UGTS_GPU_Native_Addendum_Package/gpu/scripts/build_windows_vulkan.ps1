[CmdletBinding()]
param(
    [string]$BuildDirectory = (Join-Path $PSScriptRoot '..\build-windows')
)

$ErrorActionPreference = 'Stop'
$gpuRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$buildPath = [System.IO.Path]::GetFullPath($BuildDirectory)
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) {
    throw 'Visual Studio Build Tools were not found (vswhere.exe is missing).'
}

$vsRoot = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsRoot) {
    throw 'A Visual Studio installation with the x64 C++ tools was not found.'
}
$vcvars = Join-Path $vsRoot 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path -LiteralPath $vcvars)) {
    throw "vcvars64.bat was not found under $vsRoot"
}

New-Item -ItemType Directory -Force -Path $buildPath | Out-Null
$defPath = Join-Path $gpuRoot 'windows\vulkan-1.def'
$sourcePath = Join-Path $gpuRoot 'src\ugts_vulkan_bench.cpp'
$lutSourcePath = Join-Path $gpuRoot 'src\ugts_vulkan_lut_bench.cpp'
$includePath = Join-Path $gpuRoot 'include'
$importLibrary = Join-Path $buildPath 'vulkan-1.lib'
$executable = Join-Path $buildPath 'ugts_vulkan_bench.exe'
$lutExecutable = Join-Path $buildPath 'ugts_vulkan_lut_bench.exe'
$objectPath = Join-Path $buildPath 'ugts_vulkan_bench.obj'
$lutObjectPath = Join-Path $buildPath 'ugts_vulkan_lut_bench.obj'

$environmentLines = & $env:ComSpec /d /c "call `"$vcvars`" >nul && set"
if ($LASTEXITCODE -ne 0) {
    throw "Visual Studio environment setup failed with exit code $LASTEXITCODE"
}
foreach ($line in $environmentLines) {
    if ($line -match '^([^=]+)=(.*)$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
    }
}

& lib.exe /nologo "/def:$defPath" /machine:x64 "/out:$importLibrary" | Out-Host
if ($LASTEXITCODE -ne 0) {
    throw "Vulkan import-library generation failed with exit code $LASTEXITCODE"
}
& cl.exe /nologo /std:c++17 /EHsc /W4 /O2 "/I$includePath" "/Fo:$objectPath" $sourcePath "/Fe:$executable" /link /incremental:no $importLibrary | Out-Host
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $executable)) {
    throw "Native Vulkan benchmark build failed with exit code $LASTEXITCODE"
}
& cl.exe /nologo /std:c++17 /EHsc /W4 /O2 "/I$includePath" "/Fo:$lutObjectPath" $lutSourcePath "/Fe:$lutExecutable" /link /incremental:no $importLibrary | Out-Host
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $lutExecutable)) {
    throw "Native Vulkan LUT benchmark build failed with exit code $LASTEXITCODE"
}

Write-Output $buildPath
