#!/usr/bin/env python3
"""Validate and aggregate isolated CUDA L2 concurrency/MLP runs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def median(values: list[float]) -> float:
    return float(statistics.median(values))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--executable", type=Path, required=True)
    args = parser.parse_args()

    grouped: dict[tuple[int, int], list[dict]] = defaultdict(list)
    run_records = []
    device = None
    expected_cases = None
    reference_parameters = None
    validated_payloads = 0
    dependent_loads = 0
    for run_dir in args.runs:
        source = run_dir / "cuda_l2_mlp_results.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        if document.get("schema") != "UGTS-CUDA-L2-MLP-1.0":
            raise RuntimeError(f"unexpected schema in {source}")
        if device is None:
            device = document["device"]
        elif device != document["device"]:
            raise RuntimeError(f"device mismatch in {source}")
        parameters = document["run_parameters"]
        if reference_parameters is None:
            reference_parameters = parameters
        elif parameters != reference_parameters:
            raise RuntimeError(f"run-parameter mismatch in {source}")
        rows = document.get("results", [])
        cases = {(int(row["table_bytes"]), int(row["warps"])) for row in rows}
        if len(cases) != len(rows):
            raise RuntimeError(f"duplicate table/warp case in {source}")
        if expected_cases is None:
            expected_cases = cases
        elif cases != expected_cases:
            raise RuntimeError(f"table/warp matrix mismatch in {source}")
        if not rows or any(not row.get("validation") for row in rows):
            raise RuntimeError(f"failed or missing validation in {source}")
        samples = int(parameters["measured_pairs"])
        steps = int(parameters["dependent_loads_per_thread"])
        for row in rows:
            expected = samples * int(row["threads"])
            for field in ("validated_control", "validated_cold", "validated_hot"):
                if int(row[field]) != expected:
                    raise RuntimeError(f"{field} mismatch in {source}")
            validated_payloads += expected * 3
            dependent_loads += expected * steps * 2
            grouped[(int(row["table_bytes"]), int(row["warps"]))].append(row)
        run_records.append(
            {
                "directory": str(run_dir.as_posix()),
                "results_sha256": sha256(source),
                "rows": len(rows),
                "table_order": list(dict.fromkeys(int(row["table_mib"]) for row in rows)),
                "warp_order": list(dict.fromkeys(int(row["warps"]) for row in rows)),
            }
        )

    if device is None or reference_parameters is None:
        raise RuntimeError("no input runs")
    aggregates = []
    for (table_bytes, warps), rows in sorted(grouped.items()):
        if len(rows) != len(args.runs):
            raise RuntimeError(f"incomplete coverage for {table_bytes}/{warps}")
        fields = {
            "control_p50_cycles": [float(row["control_cycles"]["p50"]) for row in rows],
            "cold_net_cycles_per_step": [float(row["cold_net_cycles_per_step"]) for row in rows],
            "hot_net_cycles_per_step": [float(row["hot_net_cycles_per_step"]) for row in rows],
            "cold_to_hot_ratio": [float(row["cold_to_hot_ratio"]) for row in rows],
            "cold_kernel_p50_us": [float(row["cold_kernel_us"]["p50"]) for row in rows],
            "hot_kernel_p50_us": [float(row["hot_kernel_us"]["p50"]) for row in rows],
            "cold_requested_gloads_s": [float(row["cold_requested_gloads_s"]) for row in rows],
            "hot_requested_gloads_s": [float(row["hot_requested_gloads_s"]) for row in rows],
            "cold_logical_gib_s": [float(row["cold_logical_gib_s"]) for row in rows],
            "hot_logical_gib_s": [float(row["hot_logical_gib_s"]) for row in rows],
            "cold_ns_per_warp_step": [float(row["cold_ns_per_warp_step"]) for row in rows],
            "hot_ns_per_warp_step": [float(row["hot_ns_per_warp_step"]) for row in rows],
        }
        aggregate = {
            "table_bytes": table_bytes,
            "table_mib": table_bytes / (1024 * 1024),
            "l2_fraction": table_bytes / int(device["l2_bytes"]),
            "warps": warps,
            "warps_per_sm": warps / int(device["multiprocessors"]),
            "threads": int(rows[0]["threads"]),
            "run_count": len(rows),
            "samples_per_run": int(rows[0]["samples"]),
        }
        for name, values in fields.items():
            aggregate[f"{name}_median"] = median(values)
            aggregate[f"{name}_min"] = min(values)
            aggregate[f"{name}_max"] = max(values)
        aggregates.append(aggregate)

    by_table: dict[int, list[dict]] = defaultdict(list)
    by_warps: dict[int, list[dict]] = defaultdict(list)
    for row in aggregates:
        by_table[int(row["table_bytes"])].append(row)
        by_warps[int(row["warps"])].append(row)
    for rows in by_table.values():
        one = next(row for row in rows if int(row["warps"]) == 1)
        for row in rows:
            warps = int(row["warps"])
            for state in ("cold", "hot"):
                throughput = float(row[f"{state}_requested_gloads_s_median"])
                baseline = float(one[f"{state}_requested_gloads_s_median"])
                speedup = throughput / baseline
                row[f"{state}_throughput_speedup_vs_one_warp"] = speedup
                row[f"{state}_parallel_efficiency"] = speedup / warps
    for rows in by_warps.values():
        fit = next(row for row in rows if int(row["table_mib"]) == 4)
        for row in rows:
            for state in ("cold", "hot"):
                row[f"{state}_throughput_fraction_of_4mib"] = (
                    float(row[f"{state}_requested_gloads_s_median"])
                    / float(fit[f"{state}_requested_gloads_s_median"])
                )

    table_summaries = []
    for table_bytes, rows in sorted(by_table.items()):
        rows.sort(key=lambda row: int(row["warps"]))
        hot_peak = max(rows, key=lambda row: float(row["hot_requested_gloads_s_median"]))
        cold_peak = max(rows, key=lambda row: float(row["cold_requested_gloads_s_median"]))
        table_summaries.append(
            {
                "table_bytes": table_bytes,
                "table_mib": table_bytes / (1024 * 1024),
                "l2_fraction": table_bytes / int(device["l2_bytes"]),
                "peak_hot_warps": int(hot_peak["warps"]),
                "peak_hot_requested_gloads_s": hot_peak["hot_requested_gloads_s_median"],
                "peak_hot_logical_gib_s": hot_peak["hot_logical_gib_s_median"],
                "peak_cold_warps": int(cold_peak["warps"]),
                "peak_cold_requested_gloads_s": cold_peak["cold_requested_gloads_s_median"],
                "peak_cold_logical_gib_s": cold_peak["cold_logical_gib_s_median"],
            }
        )

    maximum_warps = max(by_warps)
    saturated_rows = sorted(by_warps[maximum_warps], key=lambda row: row["table_bytes"])
    saturated_comparison = [
        {
            "table_mib": row["table_mib"],
            "l2_fraction": row["l2_fraction"],
            "hot_requested_gloads_s": row["hot_requested_gloads_s_median"],
            "hot_logical_gib_s": row["hot_logical_gib_s_median"],
            "hot_fraction_of_4mib": row["hot_throughput_fraction_of_4mib"],
            "hot_slowdown_vs_4mib": 1.0 / row["hot_throughput_fraction_of_4mib"],
            "cold_requested_gloads_s": row["cold_requested_gloads_s_median"],
            "cold_logical_gib_s": row["cold_logical_gib_s_median"],
            "cold_fraction_of_4mib": row["cold_throughput_fraction_of_4mib"],
            "cold_slowdown_vs_4mib": 1.0 / row["cold_throughput_fraction_of_4mib"],
        }
        for row in saturated_rows
    ]
    fit36 = next(row for row in saturated_rows if int(row["table_mib"]) == 36)
    over40 = next(row for row in saturated_rows if int(row["table_mib"]) == 40)
    output = {
        "schema": "UGTS-CUDA-L2-MLP-AGGREGATE-1.0",
        "device": device,
        "executable": {
            "path": str(args.executable.as_posix()),
            "bytes": args.executable.stat().st_size,
            "sha256": sha256(args.executable),
        },
        "runs": run_records,
        "validation": {
            "all_rows_valid": True,
            "input_rows": sum(record["rows"] for record in run_records),
            "aggregate_cases": len(aggregates),
            "validated_payloads": validated_payloads,
            "dependent_loads_in_validated_chains": dependent_loads,
        },
        "high_concurrency_summary": {
            "warps": maximum_warps,
            "warps_per_sm": maximum_warps / int(device["multiprocessors"]),
            "nominal_l2_boundary_hot_throughput_drop_36_to_40": 1.0
            - float(over40["hot_requested_gloads_s_median"])
            / float(fit36["hot_requested_gloads_s_median"]),
            "nominal_l2_boundary_hot_slowdown_36_to_40": float(
                fit36["hot_requested_gloads_s_median"]
            )
            / float(over40["hot_requested_gloads_s_median"]),
            "results": saturated_comparison,
        },
        "table_summaries": table_summaries,
        "interpretation": (
            "Each block is exactly one warp. Every lane performs 512 strictly dependent "
            "ld.global.cg.u32 steps, so adding blocks adds independent warp-level memory "
            "parallelism without adding instruction-level parallelism inside a chain. "
            "clock64 measures per-thread exposed cycles including scheduling; CUDA events "
            "measure complete-kernel throughput. Requested Gload/s counts logical u32 "
            "requests, not physical L2/DRAM transactions or bytes on the memory bus."
        ),
        "results": aggregates,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "cuda_l2_mlp_aggregate.json"
    csv_path = args.out_dir / "cuda_l2_mlp_aggregate.csv"
    json_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(aggregates[0]))
        writer.writeheader()
        writer.writerows(aggregates)
    print(json_path)
    print(csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
