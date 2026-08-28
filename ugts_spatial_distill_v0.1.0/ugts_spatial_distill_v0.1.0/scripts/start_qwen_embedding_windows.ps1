param(
    [Parameter(Mandatory=$true)][string]$ModelPath,
    [int]$Port = 8080,
    [string]$LlamaServer = "llama-server.exe"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $ModelPath)) {
    throw "Model file not found: $ModelPath"
}
& $LlamaServer -m $ModelPath --embedding --pooling last -ub 8192 --host 127.0.0.1 --port $Port
