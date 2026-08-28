param(
    [string]$Benchmark = ".\\b128\\Release\\klb_network_bench.exe",
    [string]$Container = "data\\network\\celestrak_mixed_58obj_7d_60s.ksgp",
    [string]$Stations = "data\\network\\benchmark_station_network.csv",
    [string]$ConsoleLog = "verification_v060_gpu_laptop_console.txt",
    [string]$Csv = "verification_v060_gpu_laptop_results.csv",
    [string]$Telemetry = "verification_v060_gpu_laptop_telemetry.csv"
)

$ErrorActionPreference = "Stop"
$nvidiaSmi = Join-Path $env:SystemRoot "System32\\nvidia-smi.exe"
$telemetryJob = Start-Job -ArgumentList $nvidiaSmi -ScriptBlock {
    param($Tool)
    while ($true) {
        & $Tool --query-gpu=timestamp,utilization.gpu,utilization.memory,memory.used,power.draw,temperature.gpu,clocks.sm,clocks.mem --format=csv,noheader,nounits
        Start-Sleep -Milliseconds 250
    }
}

$exitCode = 1
try {
    & $Benchmark $Container $Stations --preset laptop --repeats 7 --min-ms 150 --validation-intervals 10080 --csv $Csv 2>&1 | Tee-Object -FilePath $ConsoleLog
    $exitCode = $LASTEXITCODE
}
finally {
    Stop-Job -Job $telemetryJob
    $rows = Receive-Job -Job $telemetryJob
    Remove-Job -Job $telemetryJob
    @("timestamp, utilization_gpu_pct, utilization_memory_pct, memory_used_mib, power_draw_w, temperature_gpu_c, clocks_sm_mhz, clocks_mem_mhz") + $rows | Set-Content -LiteralPath $Telemetry -Encoding utf8
}

exit $exitCode
