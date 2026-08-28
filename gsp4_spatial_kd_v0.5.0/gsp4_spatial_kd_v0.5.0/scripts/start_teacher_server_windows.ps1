param(
  [Parameter(Mandatory=$true)][string]$ModelPath,
  [int]$Port = 8081,
  [int]$GpuLayers = 99,
  [int]$Context = 8192,
  [string]$Llama = ""
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $ModelPath)) { throw "Missing model: $ModelPath" }
if (-not $Llama) {
  $cmd = Get-Command llama -ErrorAction SilentlyContinue
  if ($cmd) { $Llama = $cmd.Source } else {
    $cmd = Get-Command llama-server -ErrorAction SilentlyContinue
    if ($cmd) { $Llama = $cmd.Source } else { throw "llama or llama-server is not on PATH" }
  }
}
$leaf = [IO.Path]::GetFileNameWithoutExtension($Llama)
if ($leaf -eq "llama") {
  & $Llama serve -m $ModelPath --host 127.0.0.1 --port $Port -ngl $GpuLayers -c $Context
} else {
  & $Llama -m $ModelPath --host 127.0.0.1 --port $Port -ngl $GpuLayers -c $Context
}
