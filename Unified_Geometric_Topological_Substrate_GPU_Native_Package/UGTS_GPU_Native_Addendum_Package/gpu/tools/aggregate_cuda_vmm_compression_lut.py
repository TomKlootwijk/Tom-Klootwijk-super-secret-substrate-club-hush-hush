#!/usr/bin/env python3
"""Aggregate paired native CUDA VMM compression-LUT runs."""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


RESULT_FILE = "cuda_vmm_compression_lut_results.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    return parser.parse_args()


def relative_range(values: list[float]) -> float:
    center = statistics.median(values)
    return (max(values) - min(values)) / center if center else 0.0


def main() -> int:
    args = parse_args()
    documents: list[tuple[Path, dict[str, Any]]] = []
    for input_path in args.inputs:
        path = input_path if input_path.is_file() else input_path / RESULT_FILE
        with path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        if document.get("schema") != "UGTS-CUDA-VMM-COMPRESSION-LUT-1.0":
            raise ValueError(f"unexpected schema in {path}")
        documents.append((path, document))
    if not documents:
        raise ValueError("no inputs")

    first_device = documents[0][1]["device"]
    first_parameters = documents[0][1]["run_parameters"]
    invariant_parameters = {
        key: value for key, value in first_parameters.items() if key != "order"
    }
    rows_by_key: dict[
        tuple[int, str, str, str, int], list[dict[str, Any]]
    ] = defaultdict(list)
    paired_by_run: list[
        dict[tuple[int, str, str, int, str], dict[str, Any]]
    ] = []
    raw_rows = invalid_rows = validated_payloads = timed_lookups = 0
    observed_orders: list[int] = []
    paired_mapping_verified = True
    for path, document in documents:
        if document["device"] != first_device:
            raise ValueError(f"device mismatch in {path}")
        parameters = document["run_parameters"]
        if {key: value for key, value in parameters.items() if key != "order"} != invariant_parameters:
            raise ValueError(f"run-parameter mismatch in {path}")
        observed_orders.append(int(parameters["order"]))
        run_lookup: dict[
            tuple[int, str, str, int, str], dict[str, Any]
        ] = {}
        mapping_bases: dict[tuple[int, str, str], set[int]] = defaultdict(set)
        for row in document["results"]:
            raw_rows += 1
            key = (
                int(row["size_mib"]),
                str(row["pattern"]),
                str(row["compression"]),
                str(row["path"]),
                int(row["warps"]),
            )
            rows_by_key[key].append(row)
            pair_key = (
                int(row["size_mib"]),
                str(row["pattern"]),
                str(row["path"]),
                int(row["warps"]),
            )
            run_lookup[(pair_key[0], pair_key[1], pair_key[2], pair_key[3], str(row["compression"]))] = row
            mapping_bases[(int(row["size_mib"]), str(row["pattern"]), str(row["compression"]))].add(
                int(row["base_address"])
            )
            if not bool(row["validation"]):
                invalid_rows += 1
            validated_payloads += sum(
                int(value) for value in row["validated_payloads"].values()
            )
            timed_lookups += (
                2
                * int(row["samples"])
                * int(row["threads"])
                * int(invariant_parameters["lookups_per_thread"])
            )
        if any(len(bases) != 1 for bases in mapping_bases.values()):
            paired_mapping_verified = False
        paired_by_run.append(run_lookup)

    expected_repetitions = len(documents)
    bad_keys = {
        key: len(rows)
        for key, rows in rows_by_key.items()
        if len(rows) != expected_repetitions
    }
    if bad_keys:
        raise ValueError(f"unbalanced keys: {bad_keys}")

    aggregate_rows: list[dict[str, Any]] = []
    invariant_fields = [
        "requested_compression",
        "effective_compression",
        "allocation_bytes",
        "table_bytes",
        "groups",
        "entries",
        "bytes_per_code",
        "threads",
        "samples",
    ]
    for key in sorted(rows_by_key):
        size_mib, pattern, compression, path, warps = key
        rows = rows_by_key[key]
        for field in invariant_fields:
            if len({row[field] for row in rows}) != 1:
                raise ValueError(f"{field} mismatch for {key}")
        hot_values = [float(row["hot_glookups_s"]) for row in rows]
        cold_values = [float(row["cold_glookups_s"]) for row in rows]
        aggregate_rows.append(
            {
                "size_mib": size_mib,
                "pattern": pattern,
                "compression": compression,
                "path": path,
                "warps": warps,
                **{field: rows[0][field] for field in invariant_fields},
                "base_addresses": sorted({int(row["base_address"]) for row in rows}),
                "repetitions": len(rows),
                "hot_glookups_s": statistics.median(hot_values),
                "hot_glookups_s_min": min(hot_values),
                "hot_glookups_s_max": max(hot_values),
                "hot_glookups_s_relative_range": relative_range(hot_values),
                "cold_glookups_s": statistics.median(cold_values),
                "cold_glookups_s_min": min(cold_values),
                "cold_glookups_s_max": max(cold_values),
                "cold_glookups_s_relative_range": relative_range(cold_values),
                "hot_net_cycles_per_lookup": statistics.median(
                    float(row["hot_net_cycles_per_lookup"]) for row in rows
                ),
                "cold_net_cycles_per_lookup": statistics.median(
                    float(row["cold_net_cycles_per_lookup"]) for row in rows
                ),
                "validation": all(bool(row["validation"]) for row in rows),
            }
        )

    pair_keys = sorted(
        {
            (key[0], key[1], key[3], key[4])
            for key in rows_by_key
        }
    )
    compression_comparisons: list[dict[str, Any]] = []
    for size_mib, pattern, path, warps in pair_keys:
        hot_ratios: list[float] = []
        cold_ratios: list[float] = []
        none_hot: list[float] = []
        generic_hot: list[float] = []
        for run in paired_by_run:
            none = run[(size_mib, pattern, path, warps, "non_compressible")]
            generic = run[(size_mib, pattern, path, warps, "generic_compressible")]
            none_value = float(none["hot_glookups_s"])
            generic_value = float(generic["hot_glookups_s"])
            none_hot.append(none_value)
            generic_hot.append(generic_value)
            hot_ratios.append(generic_value / none_value)
            cold_ratios.append(
                float(generic["cold_glookups_s"]) / float(none["cold_glookups_s"])
            )
        compression_comparisons.append(
            {
                "size_mib": size_mib,
                "pattern": pattern,
                "path": path,
                "warps": warps,
                "non_compressible_hot_glookups_s": statistics.median(none_hot),
                "generic_compressible_hot_glookups_s": statistics.median(generic_hot),
                "paired_hot_ratio": statistics.median(hot_ratios),
                "paired_hot_ratio_min": min(hot_ratios),
                "paired_hot_ratio_max": max(hot_ratios),
                "paired_hot_ratio_relative_range": relative_range(hot_ratios),
                "paired_cold_ratio": statistics.median(cold_ratios),
            }
        )

    max_warps = max(row["warps"] for row in aggregate_rows)
    high_occupancy = [
        row for row in compression_comparisons if row["warps"] == max_warps
    ]
    curves: dict[str, list[dict[str, Any]]] = {}
    patterns = sorted({row["pattern"] for row in high_occupancy})
    paths = sorted({row["path"] for row in high_occupancy})
    for pattern in patterns:
        for path in paths:
            curves[f"{pattern}_{path}"] = sorted(
                [
                    row
                    for row in high_occupancy
                    if row["pattern"] == pattern and row["path"] == path
                ],
                key=lambda row: row["size_mib"],
            )

    all_valid = (
        invalid_rows == 0
        and paired_mapping_verified
        and all(row["validation"] for row in aggregate_rows)
    )
    output = {
        "schema": "UGTS-CUDA-VMM-COMPRESSION-LUT-AGGREGATE-1.0",
        "device": first_device,
        "run_parameters": invariant_parameters,
        "inputs": [str(path) for path, _ in documents],
        "observed_orders": observed_orders,
        "validation_summary": {
            "all_valid": all_valid,
            "raw_rows": raw_rows,
            "aggregate_rows": len(aggregate_rows),
            "paired_comparisons": len(compression_comparisons),
            "repetitions_per_case": expected_repetitions,
            "invalid_rows": invalid_rows,
            "paired_mapping_per_process_verified": paired_mapping_verified,
            "validated_payloads": validated_payloads,
            "timed_gpu_lookups": timed_lookups,
        },
        "aggregate_rows": aggregate_rows,
        "compression_comparisons": compression_comparisons,
        "high_occupancy_curves": curves,
        "scope_note": (
            "Effective property 1 confirms the driver granted generic-compressible "
            "allocations. Paired throughput ratios measure workload behavior, not an "
            "achieved physical compression ratio or counter-derived byte traffic."
        ),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "cuda_vmm_compression_lut_aggregate.json").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        json.dump(output, stream, indent=2)
        stream.write("\n")

    with (args.out_dir / "cuda_vmm_compression_lut_aggregate.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(aggregate_rows[0].keys()))
        writer.writeheader()
        writer.writerows(aggregate_rows)
    with (args.out_dir / "cuda_vmm_compression_lut_comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=list(compression_comparisons[0].keys())
        )
        writer.writeheader()
        writer.writerows(compression_comparisons)

    print(
        f"runs={len(documents)} raw_rows={raw_rows} "
        f"comparisons={len(compression_comparisons)} "
        f"timed_lookups={timed_lookups} all_valid={all_valid}"
    )
    return 0 if all_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
