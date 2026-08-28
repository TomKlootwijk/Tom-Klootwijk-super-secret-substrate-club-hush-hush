$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location -LiteralPath $Root

$Log = Join-Path $Root "profile_orbit_elevated_console.txt"
$ExitFile = Join-Path $Root "profile_orbit_elevated_exit_code.txt"

$Identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$Principal = [Security.Principal.WindowsPrincipal]::new($Identity)
$IsAdmin = $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

"Identity: $($Identity.Name)" | Tee-Object -FilePath $Log
"Administrator: $IsAdmin" | Tee-Object -FilePath $Log -Append
"Elevated NVIDIA preflight:" | Tee-Object -FilePath $Log -Append
& nvidia-smi --query-gpu=name,driver_version,compute_cap,memory.total `
    --format=csv,noheader 2>&1 | Tee-Object -FilePath $Log -Append
$PreflightCode = $LASTEXITCODE
"NVIDIA_PREFLIGHT_EXIT_CODE=$PreflightCode" | Tee-Object -FilePath $Log -Append

if ($PreflightCode -eq 0) {
    & .\scripts\profile_orbit_windows.ps1 `
        -BuildDir build-cuda128-vs -Configuration Release 2>&1 |
        Tee-Object -FilePath $Log -Append
    $Code = $LASTEXITCODE
} else {
    $Code = $PreflightCode
}

Set-Content -LiteralPath $ExitFile -Value $Code -Encoding ASCII
Write-Host "ELEVATED_PROFILE_EXIT_CODE=$Code"
exit $Code
