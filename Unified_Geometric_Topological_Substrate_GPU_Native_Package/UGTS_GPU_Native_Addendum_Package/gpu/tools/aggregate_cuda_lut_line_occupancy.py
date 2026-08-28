#!/usr/bin/env python3
"""Aggregate native CUDA packed6 line-occupancy runs."""

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
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def median(values):
    return statistics.median(values)


def address_span_demand(codes_per_region: int) -> dict:
    """Return exact 32-byte address-span demand for uniform packed6 slots."""
    touches = defaultdict(int)
    total_distinct_touches = 0
    straddling_slots = []
    for slot in range(codes_per_region):
        bit_index = slot * 6
        first_word = bit_index // 32
        shift = bit_index & 31
        words = [first_word]
        if shift > 26:
            words.append(first_word + 1)
        spans = sorted({word // 8 for word in words})
        total_distinct_touches += len(spans)
        for span in spans:
            touches[span] += 1
        if len(spans) > 1:
            straddling_slots.append(slot)
    occupied = (codes_per_region * 6 + 255) // 256
    return {
        "occupied_32b_address_spans_per_region": occupied,
        "expected_32b_address_spans_per_lookup": (
            total_distinct_touches / codes_per_region
        ),
        "address_span_touch_probabilities": [
            touches[span] / codes_per_region for span in range(occupied)
        ],
        "address_span_boundary_straddling_slots": straddling_slots,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    documents = []
    run_metadata = []
    by_key = defaultdict(list)
    for run_dir in args.runs:
        path = run_dir / "cuda_lut_line_occupancy_results.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["schema"] != "UGTS-CUDA-LUT-LINE-OCCUPANCY-1.0":
            raise ValueError(f"unexpected schema in {path}")
        documents.append(document)
        local_keys = set()
        for row in document["results"]:
            key = (
                row["path"],
                row["table_mib"],
                row["codes_per_128b_region"],
                row["warps"],
            )
            if key in local_keys:
                raise ValueError(f"duplicate key {key} in {path}")
            local_keys.add(key)
            by_key[key].append(row)
        run_metadata.append(
            {
                "directory": run_dir.as_posix(),
                "results_sha256": sha256(path),
                "rows": len(document["results"]),
                "path_order": document["run_parameters"]["path_order"],
                "table_order": list(
                    dict.fromkeys(row["table_mib"] for row in document["results"])
                ),
                "occupancy_order": list(
                    dict.fromkeys(
                        row["codes_per_128b_region"]
                        for row in document["results"]
                    )
                ),
                "warp_order": list(
                    dict.fromkeys(row["warps"] for row in document["results"])
                ),
            }
        )

    if len(documents) < 4:
        raise ValueError("at least four isolated runs are required")
    first = documents[0]
    for document in documents[1:]:
        if document["device"] != first["device"]:
            raise ValueError("device or occupancy mismatch")
        for field in ("measured_sets", "lookups_per_thread", "eviction_bytes"):
            if document["run_parameters"][field] != first["run_parameters"][field]:
                raise ValueError(f"run parameter mismatch: {field}")
    if any(len(rows) != 4 for rows in by_key.values()):
        bad = {str(key): len(rows) for key, rows in by_key.items() if len(rows) != 4}
        raise ValueError(f"every case must have four runs: {bad}")

    def direction(values):
        if values == sorted(values):
            return "ascending"
        if values == sorted(values, reverse=True):
            return "descending"
        return "mixed"

    balance_groups = defaultdict(list)
    for metadata in run_metadata:
        occupancy_set = tuple(sorted(metadata["occupancy_order"]))
        balance_groups[occupancy_set].append(metadata)
    order_balance = []
    for occupancy_set, group in sorted(balance_groups.items()):
        balance = {
            "codes_per_128b_region": list(occupancy_set),
            "runs": len(group),
            "occupancy_order_balance_applicable": len(occupancy_set) > 1,
            "path_order_0": sum(row["path_order"] == 0 for row in group),
            "path_order_1": sum(row["path_order"] == 1 for row in group),
            "table_ascending": sum(
                direction(row["table_order"]) == "ascending" for row in group
            ),
            "table_descending": sum(
                direction(row["table_order"]) == "descending" for row in group
            ),
            "occupancy_ascending": sum(
                direction(row["occupancy_order"]) == "ascending" for row in group
            ),
            "occupancy_descending": sum(
                direction(row["occupancy_order"]) == "descending" for row in group
            ),
            "warps_ascending": sum(
                direction(row["warp_order"]) == "ascending" for row in group
            ),
            "warps_descending": sum(
                direction(row["warp_order"]) == "descending" for row in group
            ),
        }
        required_fields = [
            "path_order_0",
            "path_order_1",
            "table_ascending",
            "table_descending",
            "warps_ascending",
            "warps_descending",
        ]
        if len(occupancy_set) > 1:
            required_fields.extend(
                ["occupancy_ascending", "occupancy_descending"]
            )
        if any(balance[field] != 2 for field in required_fields):
            raise ValueError(f"run order is not 2/2 counterbalanced: {balance}")
        order_balance.append(balance)

    fields = (
        "hot_glookups_s",
        "cold_glookups_s",
        "hot_requested_word_gloads_s",
        "cold_requested_word_gloads_s",
        "hot_net_cycles_per_lookup",
        "cold_net_cycles_per_lookup",
    )
    aggregate_rows = []
    for key in sorted(by_key, key=lambda item: (item[1], item[2], item[3], item[0])):
        rows = by_key[key]
        path, table_mib, codes_per_line, warps = key
        demand = address_span_demand(codes_per_line)
        aggregate = {
            "path": path,
            "table_mib": table_mib,
            "table_bytes": rows[0]["table_bytes"],
            "l2_fraction": rows[0]["l2_fraction"],
            "regions_128b": rows[0]["regions_128b"],
            "codes_per_128b_region": codes_per_line,
            "active_codes": rows[0]["active_codes"],
            "effective_bytes_per_active_code": rows[0][
                "effective_bytes_per_active_code"
            ],
            "code_bit_utilization": rows[0]["code_bit_utilization"],
            "occupied_words_per_region": (codes_per_line * 6 + 31) // 32,
            **demand,
            "expected_words_per_lookup": rows[0]["expected_words_per_lookup"],
            "warps": warps,
            "warps_per_sm": rows[0]["warps_per_sm"],
            "run_count": len(rows),
            "all_runs_valid": all(row["validation"] for row in rows),
        }
        for field in fields:
            values = [row[field] for row in rows]
            aggregate[f"{field}_median"] = median(values)
            aggregate[f"{field}_min"] = min(values)
            aggregate[f"{field}_max"] = max(values)
        for state in ("cold", "hot"):
            values = [row[f"{state}_kernel_us"]["p50"] for row in rows]
            aggregate[f"{state}_kernel_p50_us_median"] = median(values)
        aggregate_rows.append(aggregate)

    index = {
        (
            row["path"],
            row["table_mib"],
            row["codes_per_128b_region"],
            row["warps"],
        ): row
        for row in aggregate_rows
    }
    full_warps = max(row["warps"] for row in aggregate_rows)
    tables = sorted({row["table_mib"] for row in aggregate_rows})
    occupancies = sorted(
        {row["codes_per_128b_region"] for row in aggregate_rows}
    )

    path_comparison = []
    for table_mib in tables:
        for codes_per_line in occupancies:
            for warps in sorted({row["warps"] for row in aggregate_rows}):
                global_raw = by_key[("global_cg", table_mib, codes_per_line, warps)]
                texture_raw = by_key[
                    ("texture_object", table_mib, codes_per_line, warps)
                ]
                ratios = [
                    texture["hot_glookups_s"] / global_row["hot_glookups_s"]
                    for global_row, texture in zip(global_raw, texture_raw)
                ]
                path_comparison.append(
                    {
                        "table_mib": table_mib,
                        "codes_per_128b_region": codes_per_line,
                        "warps": warps,
                        "global_hot_glookups_s_median": index[
                            ("global_cg", table_mib, codes_per_line, warps)
                        ]["hot_glookups_s_median"],
                        "texture_hot_glookups_s_median": index[
                            ("texture_object", table_mib, codes_per_line, warps)
                        ]["hot_glookups_s_median"],
                        "texture_to_global_hot_rate_ratio_median": median(ratios),
                        "texture_to_global_hot_rate_ratio_min": min(ratios),
                        "texture_to_global_hot_rate_ratio_max": max(ratios),
                    }
                )

    full_occupancy_summary = []
    baseline_table = min(tables)
    for codes_per_line in occupancies:
        demand = address_span_demand(codes_per_line)
        row = {
            "codes_per_128b_region": codes_per_line,
            "effective_bytes_per_active_code": 128.0 / codes_per_line,
            "occupied_words_per_region": (codes_per_line * 6 + 31) // 32,
            **demand,
            "active_codes_at_36_mib": 36 * 1024 * 1024 // 128 * codes_per_line,
            "active_codes_at_28_mib": 28 * 1024 * 1024 // 128 * codes_per_line,
        }
        baseline = index[
            ("texture_object", baseline_table, codes_per_line, full_warps)
        ]["hot_glookups_s_median"]
        first_below_95 = None
        for table_mib in tables:
            for path, short in (("global_cg", "global"), ("texture_object", "texture")):
                aggregate = index[(path, table_mib, codes_per_line, full_warps)]
                row[f"{short}_{table_mib}mib_hot_glookups_s"] = aggregate[
                    "hot_glookups_s_median"
                ]
            texture_rate = row[f"texture_{table_mib}mib_hot_glookups_s"]
            row[f"texture_{table_mib}mib_retention_vs_{baseline_table}mib"] = (
                texture_rate / baseline
            )
            if first_below_95 is None and texture_rate / baseline < 0.95:
                first_below_95 = table_mib
        row["first_measured_table_below_95pct_texture_baseline_mib"] = (
            first_below_95
        )
        full_occupancy_summary.append(row)

    validation = {
        "all_rows_valid": all(
            row["validation"] for document in documents for row in document["results"]
        ),
        "input_rows": sum(len(document["results"]) for document in documents),
        "aggregate_cases": len(aggregate_rows),
        "aggregate_paired_path_cases": len(path_comparison),
        "cpu_validated_payloads": sum(
            row["validated_control"] + row["validated_cold"] + row["validated_hot"]
            for document in documents
            for row in document["results"]
        ),
        "cpu_replayed_timed_endpoints": sum(
            row["validated_cold"] + row["validated_hot"]
            for document in documents
            for row in document["results"]
        ),
        "cpu_replayed_code_checks": sum(
            (row["validated_cold"] + row["validated_hot"])
            * document["run_parameters"]["lookups_per_thread"]
            for document in documents
            for row in document["results"]
        ),
        "measured_gpu_code_lookups": sum(
            row["threads"]
            * row["samples"]
            * 2
            * document["run_parameters"]["lookups_per_thread"]
            for document in documents
            for row in document["results"]
        ),
    }

    source = Path("gpu/src/ugts_cuda_lut_line_occupancy_bench.cu")
    executable = Path("gpu/build-windows/ugts_cuda_lut_line_occupancy_bench.exe")
    output = {
        "schema": "UGTS-CUDA-LUT-LINE-OCCUPANCY-AGGREGATE-1.1",
        "device": first["device"],
        "source": {"path": source.as_posix(), "sha256": sha256(source)},
        "executable": {
            "path": executable.as_posix(),
            "bytes": executable.stat().st_size,
            "sha256": sha256(executable),
        },
        "runs": run_metadata,
        "order_balance": order_balance,
        "validation": validation,
        "full_occupancy_summary": full_occupancy_summary,
        "path_comparison": path_comparison,
        "results": aggregate_rows,
        "interpretation": {
            "classification": "packed6 useful-capacity and throughput vary continuously with occupied subregions; the prior 128-byte pointer-chase residency is not a universal per-code charge",
            "address_span_definition": "occupied_32b_address_spans_per_region is the exact contiguous 6-bit payload span rounded to 32-byte units; it describes address arithmetic, not a counter-measured hardware sector",
            "address_span_probability_note": "address_span_touch_probabilities is the exact probability that a uniformly selected useful slot requests each 32-byte address region; boundary-straddling codes can request two regions",
            "dense_block_capacity_note": "170 codes fit wholly inside each 128-byte block with four padding bits; the continuous packed stream reaches 170.666667 codes per 128 bytes",
        },
        "bounds": [
            "The 128-byte region is an experiment layout chosen from the preceding pointer-chase bound; occupied 32-byte spans are address arithmetic, not privileged cache-sector evidence.",
            "Independent random region/slot generation measures lookup throughput and capacity, not a load-dependent pointer latency.",
            "Glookup/s is logical decoded-code throughput; expected word requests and occupied spans are not physical L2 or DRAM transactions.",
        ],
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "cuda_lut_line_occupancy_aggregate.json"
    json_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    tables_to_write = (
        ("cuda_lut_line_occupancy_aggregate.csv", aggregate_rows),
        ("cuda_lut_line_occupancy_path_comparison.csv", path_comparison),
        ("cuda_lut_line_occupancy_full_occupancy.csv", full_occupancy_summary),
    )
    for name, rows in tables_to_write:
        with (args.out_dir / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json_path)
    return 0 if validation["all_rows_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
