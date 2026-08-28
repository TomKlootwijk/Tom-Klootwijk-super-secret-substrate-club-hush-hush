#!/usr/bin/env python3
"""Aggregate order-balanced native CUDA VMM-alias benchmark runs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


RESULT_FILE = "cuda_vmm_alias_results.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    return parser.parse_args()


def median(rows: list[dict[str, Any]], field: str) -> float:
    return float(statistics.median(float(row[field]) for row in rows))


def relative_range(values: list[float]) -> float:
    center = statistics.median(values)
    return (max(values) - min(values)) / center if center else 0.0


def main() -> int:
    args = parse_args()
    documents = []
    for input_path in args.inputs:
        path = input_path if input_path.is_file() else input_path / RESULT_FILE
        with path.open("r", encoding="utf-8") as stream:
            document = json.load(stream)
        if document.get("schema") != "UGTS-CUDA-VMM-ALIAS-1.0":
            raise ValueError(f"unexpected schema in {path}")
        documents.append((path, document))
    if not documents:
        raise ValueError("no inputs")

    first_device = documents[0][1]["device"]
    first_parameters = documents[0][1]["run_parameters"]
    invariant_parameters = {
        key: value
        for key, value in first_parameters.items()
        if key != "path_and_case_order"
    }
    rows_by_key: dict[tuple[int, int, str, int], list[dict[str, Any]]] = (
        defaultdict(list)
    )
    raw_rows = 0
    cpu_payloads = 0
    gpu_payloads = 0
    invalid_rows = 0
    timed_lookups = 0
    observed_orders = []
    paired_mapping_verified = True
    for path, document in documents:
        if document["device"] != first_device:
            raise ValueError(f"device mismatch in {path}")
        parameters = document["run_parameters"]
        if {
            key: value
            for key, value in parameters.items()
            if key != "path_and_case_order"
        } != invariant_parameters:
            raise ValueError(f"run-parameter mismatch in {path}")
        observed_orders.append(int(parameters["path_and_case_order"]))
        document_case_bases: dict[tuple[int, int], set[int]] = defaultdict(set)
        for row in document["results"]:
            raw_rows += 1
            key = (
                int(row["aliases"]),
                int(row["pitch_mib"]),
                str(row["path"]),
                int(row["warps"]),
            )
            rows_by_key[key].append(row)
            document_case_bases[(int(row["aliases"]), int(row["pitch_mib"]))].add(
                int(row["virtual_base_address"])
            )
            if not row["validation"]:
                invalid_rows += 1
            cpu_payloads += sum(int(value) for value in row["validated_cpu_payloads"].values())
            gpu_payloads += sum(
                int(value) for value in row["zero_mismatch_gpu_payloads"].values()
            )
            timed_lookups += (
                2
                * int(row["samples"])
                * int(row["threads"])
                * int(invariant_parameters["lookups_per_thread"])
            )
        if any(len(bases) != 1 for bases in document_case_bases.values()):
            paired_mapping_verified = False

    expected_repetitions = len(documents)
    bad_repetition_keys = {
        key: len(rows)
        for key, rows in rows_by_key.items()
        if len(rows) != expected_repetitions
    }
    if bad_repetition_keys:
        raise ValueError(f"unbalanced keys: {bad_repetition_keys}")

    aggregate_rows: list[dict[str, Any]] = []
    for key in sorted(rows_by_key):
        aliases, pitch_mib, path, warps = key
        rows = rows_by_key[key]
        invariant_fields = [
            "pitch_bytes",
            "virtual_span_bytes",
            "virtual_span_mib",
            "mapped_slots",
            "physical_backing_bytes",
            "accessed_physical_bytes",
            "virtual_to_physical_ratio",
            "threads",
            "samples",
        ]
        for field in invariant_fields:
            if len({row[field] for row in rows}) != 1:
                raise ValueError(f"{field} mismatch for {key}")
        hot_values = [float(row["hot_glookups_s"]) for row in rows]
        cold_values = [float(row["cold_glookups_s"]) for row in rows]
        aggregate_rows.append(
            {
                "aliases": aliases,
                "pitch_mib": pitch_mib,
                "path": path,
                "warps": warps,
                **{field: rows[0][field] for field in invariant_fields},
                "virtual_base_addresses": sorted(
                    {int(row["virtual_base_address"]) for row in rows}
                ),
                "repetitions": len(rows),
                "hot_glookups_s": statistics.median(hot_values),
                "hot_glookups_s_min": min(hot_values),
                "hot_glookups_s_max": max(hot_values),
                "hot_glookups_s_relative_range": relative_range(hot_values),
                "cold_glookups_s": statistics.median(cold_values),
                "cold_glookups_s_min": min(cold_values),
                "cold_glookups_s_max": max(cold_values),
                "cold_glookups_s_relative_range": relative_range(cold_values),
                "hot_net_cycles_per_lookup": median(rows, "hot_net_cycles_per_lookup"),
                "cold_net_cycles_per_lookup": median(rows, "cold_net_cycles_per_lookup"),
                "validation": all(bool(row["validation"]) for row in rows),
            }
        )

    by_comparison = {
        (int(row["aliases"]), int(row["pitch_mib"]), int(row["warps"])): row
        for row in aggregate_rows
        if row["path"] == "global_cg"
    }
    path_comparisons = []
    for texture in aggregate_rows:
        if texture["path"] != "texture_object":
            continue
        key = (texture["aliases"], texture["pitch_mib"], texture["warps"])
        global_row = by_comparison[key]
        path_comparisons.append(
            {
                "aliases": texture["aliases"],
                "pitch_mib": texture["pitch_mib"],
                "virtual_span_mib": texture["virtual_span_mib"],
                "warps": texture["warps"],
                "global_hot_glookups_s": global_row["hot_glookups_s"],
                "texture_hot_glookups_s": texture["hot_glookups_s"],
                "texture_over_global": texture["hot_glookups_s"]
                / global_row["hot_glookups_s"],
            }
        )
    path_comparisons.sort(
        key=lambda row: (row["aliases"], row["pitch_mib"], row["warps"])
    )

    max_warps = max(int(row["warps"]) for row in aggregate_rows)
    span_sweep = [
        row
        for row in path_comparisons
        if row["pitch_mib"] == 2 and row["warps"] == max_warps
    ]
    span_sweep.sort(key=lambda row: row["virtual_span_mib"])
    fixed_alias_sweeps = {
        str(aliases): sorted(
            [
                row
                for row in path_comparisons
                if row["aliases"] == aliases and row["warps"] == max_warps
            ],
            key=lambda row: row["virtual_span_mib"],
        )
        for aliases in (32, 64, 128)
    }
    near_boundary_keys = {(32, 8), (64, 4), (124, 2), (126, 2), (127, 2),
                          (128, 2), (129, 2), (130, 2), (132, 2)}
    near_boundary = [
        row
        for row in path_comparisons
        if (row["aliases"], row["pitch_mib"]) in near_boundary_keys
        and row["warps"] == max_warps
    ]
    near_boundary.sort(key=lambda row: (row["virtual_span_mib"], row["aliases"]))

    all_valid = (
        invalid_rows == 0
        and paired_mapping_verified
        and all(row["validation"] for row in aggregate_rows)
    )
    aggregate = {
        "schema": "UGTS-CUDA-VMM-ALIAS-AGGREGATE-1.0",
        "device": first_device,
        "run_parameters": invariant_parameters,
        "inputs": [str(path) for path, _ in documents],
        "observed_orders": observed_orders,
        "validation_summary": {
            "all_valid": all_valid,
            "raw_rows": raw_rows,
            "aggregate_rows": len(aggregate_rows),
            "repetitions_per_case": expected_repetitions,
            "invalid_rows": invalid_rows,
            "paired_mapping_per_process_verified": paired_mapping_verified,
            "cpu_validated_payloads": cpu_payloads,
            "zero_mismatch_gpu_payloads": gpu_payloads,
            "timed_gpu_lookups": timed_lookups,
        },
        "aggregate_rows": aggregate_rows,
        "path_comparisons": path_comparisons,
        "high_occupancy_pitch_2_mib_span_sweep": span_sweep,
        "high_occupancy_fixed_alias_sweeps": fixed_alias_sweeps,
        "high_occupancy_near_256_mib": near_boundary,
        "scope_note": (
            "All virtual slots alias one physical VMM allocation. Results isolate "
            "virtual-address reach and alias-count/index effects from physical backing, "
            "but do not identify an undocumented page size, TLB, cache set or bank."
        ),
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "cuda_vmm_alias_aggregate.json").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        json.dump(aggregate, stream, indent=2)
        stream.write("\n")

    fieldnames = list(aggregate_rows[0].keys())
    with (args.out_dir / "cuda_vmm_alias_aggregate.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(aggregate_rows)

    comparison_fields = list(path_comparisons[0].keys())
    with (args.out_dir / "cuda_vmm_alias_path_comparison.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=comparison_fields)
        writer.writeheader()
        writer.writerows(path_comparisons)

    if not all_valid:
        return 2
    print(
        f"runs={len(documents)} raw_rows={raw_rows} "
        f"aggregate_rows={len(aggregate_rows)} timed_lookups={timed_lookups} "
        f"all_valid={all_valid}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
