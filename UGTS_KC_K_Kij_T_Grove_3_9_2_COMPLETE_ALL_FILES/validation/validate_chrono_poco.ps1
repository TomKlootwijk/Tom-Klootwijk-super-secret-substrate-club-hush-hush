$repoRoot = Split-Path -Parent $PSScriptRoot
$previousPythonPath = $env:PYTHONPATH
$env:PYTHONPATH = Join-Path $repoRoot "src"
if ($previousPythonPath) {
    $env:PYTHONPATH = "$($env:PYTHONPATH);$previousPythonPath"
}

try {
    & python (Join-Path $PSScriptRoot "validate_chrono_poco.py") @args
    $validationExitCode = $LASTEXITCODE
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

exit $validationExitCode
