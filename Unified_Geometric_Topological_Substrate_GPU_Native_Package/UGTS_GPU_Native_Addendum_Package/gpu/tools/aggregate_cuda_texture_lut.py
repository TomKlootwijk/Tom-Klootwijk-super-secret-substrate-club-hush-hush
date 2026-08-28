#!/usr/bin/env python3
"""Validate and aggregate matched CUDA texture-object/global-L2 runs."""

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

    grouped: dict[tuple[int, int, str], list[dict]] = defaultdict(list)
    paired: dict[tuple[int, int], list[dict[str, dict]]] = defaultdict(list)
    run_records = []
    device = None
    expected_cases = None
    common_parameters = None
    validated_payloads = 0
    dependent_loads = 0
    for run_dir in args.runs:
        source = run_dir / "cuda_texture_lut_results.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        if document.get("schema") != "UGTS-CUDA-TEXTURE-LUT-1.0":
            raise RuntimeError(f"unexpected schema in {source}")
        if device is None:
            device = document["device"]
        elif device != document["device"]:
            raise RuntimeError(f"device mismatch in {source}")
        parameters = dict(document["run_parameters"])
        path_order = parameters.pop("path_order")
        if common_parameters is None:
            common_parameters = parameters
        elif parameters != common_parameters:
            raise RuntimeError(f"run-parameter mismatch in {source}")
        rows = document.get("results", [])
        cases = {
            (int(row["table_bytes"]), int(row["warps"]), str(row["path"]))
            for row in rows
        }
        if len(cases) != len(rows):
            raise RuntimeError(f"duplicate path/table/warp case in {source}")
        if expected_cases is None:
            expected_cases = cases
        elif cases != expected_cases:
            raise RuntimeError(f"path/table/warp matrix mismatch in {source}")
        if not rows or any(not row.get("validation") for row in rows):
            raise RuntimeError(f"failed or missing validation in {source}")
        samples = int(parameters["measured_pairs"])
        steps = int(parameters["dependent_loads_per_thread"])
        run_pairs: dict[tuple[int, int], dict[str, dict]] = defaultdict(dict)
        for row in rows:
            expected = samples * int(row["threads"])
            for field in ("validated_control", "validated_cold", "validated_hot"):
                if int(row[field]) != expected:
                    raise RuntimeError(f"{field} mismatch in {source}")
            validated_payloads += expected * 3
            dependent_loads += expected * steps * 2
            key = (int(row["table_bytes"]), int(row["warps"]), str(row["path"]))
            grouped[key].append(row)
            run_pairs[(key[0], key[1])][key[2]] = row
        for key, paths in run_pairs.items():
            if set(paths) != {"global_cg", "texture_object"}:
                raise RuntimeError(f"unpaired paths for {key} in {source}")
            paired[key].append(paths)
        run_records.append(
            {
                "directory": str(run_dir.as_posix()),
                "results_sha256": sha256(source),
                "rows": len(rows),
                "path_order": path_order,
                "table_order": list(dict.fromkeys(int(row["table_mib"]) for row in rows)),
                "warp_order": list(dict.fromkeys(int(row["warps"]) for row in rows)),
            }
        )

    if device is None or common_parameters is None:
        raise RuntimeError("no input runs")
    aggregates: dict[tuple[int, int, str], dict] = {}
    for key, rows in sorted(grouped.items()):
        if len(rows) != len(args.runs):
            raise RuntimeError(f"incomplete coverage for {key}")
        table_bytes, warps, path = key
        aggregate = {
            "path": path,
            "table_bytes": table_bytes,
            "table_mib": table_bytes / (1024 * 1024),
            "l2_fraction": table_bytes / int(device["l2_bytes"]),
            "warps": warps,
            "warps_per_sm": warps / int(device["multiprocessors"]),
            "threads": int(rows[0]["threads"]),
            "run_count": len(rows),
            "samples_per_run": int(rows[0]["samples"]),
        }
        scalar_fields = (
            "cold_net_cycles_per_step",
            "hot_net_cycles_per_step",
            "cold_requested_gloads_s",
            "hot_requested_gloads_s",
            "cold_logical_gib_s",
            "hot_logical_gib_s",
        )
        for field in scalar_fields:
            values = [float(row[field]) for row in rows]
            aggregate[f"{field}_median"] = median(values)
            aggregate[f"{field}_min"] = min(values)
            aggregate[f"{field}_max"] = max(values)
        for state in ("cold", "hot"):
            values = [float(row[f"{state}_kernel_us"]["p50"]) for row in rows]
            aggregate[f"{state}_kernel_p50_us_median"] = median(values)
            aggregate[f"{state}_kernel_p50_us_min"] = min(values)
            aggregate[f"{state}_kernel_p50_us_max"] = max(values)
        aggregates[key] = aggregate

    comparisons = []
    for (table_bytes, warps), groups in sorted(paired.items()):
        global_aggregate = aggregates[(table_bytes, warps, "global_cg")]
        texture_aggregate = aggregates[(table_bytes, warps, "texture_object")]
        hot_rate_ratios = [
            float(paths["texture_object"]["hot_requested_gloads_s"])
            / float(paths["global_cg"]["hot_requested_gloads_s"])
            for paths in groups
        ]
        cold_rate_ratios = [
            float(paths["texture_object"]["cold_requested_gloads_s"])
            / float(paths["global_cg"]["cold_requested_gloads_s"])
            for paths in groups
        ]
        hot_cycle_ratios = [
            float(paths["texture_object"]["hot_net_cycles_per_step"])
            / float(paths["global_cg"]["hot_net_cycles_per_step"])
            for paths in groups
        ]
        comparisons.append(
            {
                "table_bytes": table_bytes,
                "table_mib": table_bytes / (1024 * 1024),
                "l2_fraction": table_bytes / int(device["l2_bytes"]),
                "warps": warps,
                "warps_per_sm": warps / int(device["multiprocessors"]),
                "run_count": len(groups),
                "samples_per_run": int(common_parameters["measured_pairs"]),
                "global_hot_gloads_s_median": global_aggregate[
                    "hot_requested_gloads_s_median"
                ],
                "texture_hot_gloads_s_median": texture_aggregate[
                    "hot_requested_gloads_s_median"
                ],
                "texture_to_global_hot_rate_ratio_median": median(hot_rate_ratios),
                "texture_to_global_hot_rate_ratio_min": min(hot_rate_ratios),
                "texture_to_global_hot_rate_ratio_max": max(hot_rate_ratios),
                "global_cold_gloads_s_median": global_aggregate[
                    "cold_requested_gloads_s_median"
                ],
                "texture_cold_gloads_s_median": texture_aggregate[
                    "cold_requested_gloads_s_median"
                ],
                "texture_to_global_cold_rate_ratio_median": median(cold_rate_ratios),
                "texture_to_global_cold_rate_ratio_min": min(cold_rate_ratios),
                "texture_to_global_cold_rate_ratio_max": max(cold_rate_ratios),
                "global_hot_cycles_per_step_median": global_aggregate[
                    "hot_net_cycles_per_step_median"
                ],
                "texture_hot_cycles_per_step_median": texture_aggregate[
                    "hot_net_cycles_per_step_median"
                ],
                "texture_to_global_hot_cycle_ratio_median": median(hot_cycle_ratios),
            }
        )

    by_warps: dict[int, list[dict]] = defaultdict(list)
    for row in comparisons:
        by_warps[int(row["warps"])].append(row)
    concurrency_summary = []
    for warps, rows in sorted(by_warps.items()):
        ratios = [float(row["texture_to_global_hot_rate_ratio_median"]) for row in rows]
        concurrency_summary.append(
            {
                "warps": warps,
                "warps_per_sm": warps / int(device["multiprocessors"]),
                "texture_to_global_hot_ratio_median_of_sizes": median(ratios),
                "texture_to_global_hot_ratio_min_across_sizes": min(ratios),
                "texture_to_global_hot_ratio_max_across_sizes": max(ratios),
            }
        )

    maximum_warps = max(by_warps)
    full_occupancy = sorted(by_warps[maximum_warps], key=lambda row: row["table_bytes"])
    full_occupancy_summary = [
        {
            "table_mib": row["table_mib"],
            "l2_fraction": row["l2_fraction"],
            "global_hot_gloads_s": row["global_hot_gloads_s_median"],
            "texture_hot_gloads_s": row["texture_hot_gloads_s_median"],
            "texture_to_global_hot_ratio": row[
                "texture_to_global_hot_rate_ratio_median"
            ],
        }
        for row in full_occupancy
    ]
    output = {
        "schema": "UGTS-CUDA-TEXTURE-LUT-AGGREGATE-1.0",
        "device": device,
        "executable": {
            "path": str(args.executable.as_posix()),
            "bytes": args.executable.stat().st_size,
            "sha256": sha256(args.executable),
        },
        "runs": run_records,
        "path_order_balance": {
            "global_first": sum(record["path_order"] == "global_first" for record in run_records),
            "texture_first": sum(record["path_order"] == "texture_first" for record in run_records),
        },
        "validation": {
            "all_rows_valid": True,
            "input_rows": sum(record["rows"] for record in run_records),
            "aggregate_path_cases": len(aggregates),
            "aggregate_paired_cases": len(comparisons),
            "validated_payloads": validated_payloads,
            "dependent_loads_in_validated_chains": dependent_loads,
        },
        "concurrency_summary": concurrency_summary,
        "full_occupancy_summary": {
            "warps": maximum_warps,
            "warps_per_sm": maximum_warps / int(device["multiprocessors"]),
            "results": full_occupancy_summary,
        },
        "interpretation": (
            "The same cudaMalloc pointer table is read through native texture-object "
            "TLD instructions and native ld.global.cg LDG instructions. Each mode has "
            "independent eviction and paired seeds. Requested Gload/s counts logical u32 "
            "requests, not physical cache-sector or DRAM traffic. A texture/global ratio "
            "near one above L2 does not mean identical front-end caches; it means no "
            "end-to-end capacity or throughput advantage was exposed by this workload."
        ),
        "results": comparisons,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "cuda_texture_lut_aggregate.json"
    csv_path = args.out_dir / "cuda_texture_lut_aggregate.csv"
    json_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)
    print(json_path)
    print(csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
