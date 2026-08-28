#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${1:-${ROOT}/build}"
"${BUILD}/klb_network" verify \
  "${ROOT}/data/network/celestrak_mixed_58obj_7d_60s.ksgp" \
  "${ROOT}/data/network/benchmark_station_network.csv" \
  --hours 168 --step-seconds 60 \
  --events "${ROOT}/network_cpu_events.csv" \
  --metrics "${ROOT}/network_cpu_metrics.csv"
"${BUILD}/klb_network_bench" \
  "${ROOT}/data/network/celestrak_mixed_58obj_7d_60s.ksgp" \
  "${ROOT}/data/network/benchmark_station_network.csv" \
  --preset file --repeats 7 --min-ms 150 \
  --csv "${ROOT}/network_gpu_file_results.csv"
