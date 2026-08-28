#!/usr/bin/env python3
"""Aggregate native CUDA sparse-address packed-LUT runs."""

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


def direction(values):
    if values == sorted(values):
        return "ascending"
    if values == sorted(values, reverse=True):
        return "descending"
    return "mixed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    documents = []
    run_metadata = []
    by_key = defaultdict(list)
    for run_dir in args.runs:
        path = run_dir / "cuda_lut_sparse_address_results.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["schema"] != "UGTS-CUDA-LUT-SPARSE-ADDRESS-1.0":
            raise ValueError(f"unexpected schema in {path}")
        documents.append(document)
        local_keys = set()
        for row in document["results"]:
            key = (
                row["path"],
                row["target_mib"],
                row["stride_bytes"],
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
                "target_order": list(
                    dict.fromkeys(row["target_mib"] for row in document["results"])
                ),
                "stride_order": list(
                    dict.fromkeys(row["stride_bytes"] for row in document["results"])
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
        for field in (
            "address_region_bytes",
            "lookups_per_thread",
            "eviction_bytes",
            "measured_sets",
        ):
            if document["run_parameters"][field] != first["run_parameters"][field]:
                raise ValueError(f"run parameter mismatch: {field}")
    if any(len(rows) != 4 for rows in by_key.values()):
        bad = {str(key): len(rows) for key, rows in by_key.items() if len(rows) != 4}
        raise ValueError(f"every case must have four runs: {bad}")

    balance_groups = defaultdict(list)
    for metadata in run_metadata:
        target_set = tuple(sorted(metadata["target_order"]))
        balance_groups[target_set].append(metadata)
    order_balance = []
    for target_set, group in sorted(balance_groups.items()):
        balance = {
            "target_mib": list(target_set),
            "runs": len(group),
            "path_order_0": sum(row["path_order"] == 0 for row in group),
            "path_order_1": sum(row["path_order"] == 1 for row in group),
            "target_ascending": sum(
                direction(row["target_order"]) == "ascending" for row in group
            ),
            "target_descending": sum(
                direction(row["target_order"]) == "descending" for row in group
            ),
            "stride_ascending": sum(
                direction(row["stride_order"]) == "ascending" for row in group
            ),
            "stride_descending": sum(
                direction(row["stride_order"]) == "descending" for row in group
            ),
            "warps_ascending": sum(
                direction(row["warp_order"]) == "ascending" for row in group
            ),
            "warps_descending": sum(
                direction(row["warp_order"]) == "descending" for row in group
            ),
        }
        if any(
            balance[field] != 2
            for field in balance
            if field not in {"target_mib", "runs"}
        ):
            raise ValueError(f"run order is not 2/2 counterbalanced: {balance}")
        order_balance.append(balance)

    fields = (
        "hot_glookups_s",
        "cold_glookups_s",
        "hot_net_cycles_per_lookup",
        "cold_net_cycles_per_lookup",
    )
    aggregate_rows = []
    for key in sorted(by_key, key=lambda item: (item[1], item[2], item[3], item[0])):
        rows = by_key[key]
        path, target_mib, stride_bytes, warps = key
        row = {
            "path": path,
            "target_mib": target_mib,
            "stride_bytes": stride_bytes,
            "regions": rows[0]["regions"],
            "unique_code_bytes": rows[0]["unique_code_bytes"],
            "unique_word_bytes": rows[0]["unique_word_bytes"],
            "address_span_32b_bytes": rows[0]["address_span_32b_bytes"],
            "hypothetical_128b_residency_bytes": rows[0][
                "hypothetical_128b_residency_bytes"
            ],
            "hypothetical_128b_residency_mib": rows[0][
                "hypothetical_128b_residency_bytes"
            ]
            / (1024 * 1024),
            "allocation_bytes": rows[0]["allocation_bytes"],
            "allocation_mib": rows[0]["allocation_mib"],
            "warps": warps,
            "warps_per_sm": rows[0]["warps_per_sm"],
            "run_count": len(rows),
            "all_runs_valid": all(raw["validation"] for raw in rows),
        }
        for field in fields:
            values = [raw[field] for raw in rows]
            row[f"{field}_median"] = median(values)
            row[f"{field}_min"] = min(values)
            row[f"{field}_max"] = max(values)
        for state in ("cold", "hot"):
            values = [raw[f"{state}_kernel_us"]["p50"] for raw in rows]
            row[f"{state}_kernel_p50_us_median"] = median(values)
        aggregate_rows.append(row)

    index = {
        (row["path"], row["target_mib"], row["stride_bytes"], row["warps"]): row
        for row in aggregate_rows
    }
    full_warps = max(row["warps"] for row in aggregate_rows)
    targets = sorted({row["target_mib"] for row in aggregate_rows})
    strides = sorted({row["stride_bytes"] for row in aggregate_rows})

    path_comparison = []
    for target_mib in targets:
        for stride_bytes in strides:
            for warps in sorted({row["warps"] for row in aggregate_rows}):
                global_raw = by_key[("global_cg", target_mib, stride_bytes, warps)]
                texture_raw = by_key[
                    ("texture_object", target_mib, stride_bytes, warps)
                ]
                ratios = [
                    texture["hot_glookups_s"] / global_row["hot_glookups_s"]
                    for global_row, texture in zip(global_raw, texture_raw)
                ]
                path_comparison.append(
                    {
                        "target_mib": target_mib,
                        "stride_bytes": stride_bytes,
                        "warps": warps,
                        "global_hot_glookups_s_median": index[
                            ("global_cg", target_mib, stride_bytes, warps)
                        ]["hot_glookups_s_median"],
                        "texture_hot_glookups_s_median": index[
                            ("texture_object", target_mib, stride_bytes, warps)
                        ]["hot_glookups_s_median"],
                        "texture_to_global_hot_rate_ratio_median": median(ratios),
                        "texture_to_global_hot_rate_ratio_min": min(ratios),
                        "texture_to_global_hot_rate_ratio_max": max(ratios),
                    }
                )

    full_occupancy = []
    baseline_target = min(targets)
    for stride_bytes in strides:
        baseline = index[
            ("texture_object", baseline_target, stride_bytes, full_warps)
        ]["hot_glookups_s_median"]
        first_below_95 = None
        for target_mib in targets:
            global_row = index[("global_cg", target_mib, stride_bytes, full_warps)]
            texture_row = index[
                ("texture_object", target_mib, stride_bytes, full_warps)
            ]
            retention = texture_row["hot_glookups_s_median"] / baseline
            if first_below_95 is None and retention < 0.95:
                first_below_95 = target_mib
            full_occupancy.append(
                {
                    "target_mib": target_mib,
                    "stride_bytes": stride_bytes,
                    "regions": texture_row["regions"],
                    "allocation_mib": texture_row["allocation_mib"],
                    "hypothetical_128b_residency_mib": texture_row[
                        "hypothetical_128b_residency_mib"
                    ],
                    "global_hot_glookups_s": global_row["hot_glookups_s_median"],
                    "texture_hot_glookups_s": texture_row[
                        "hot_glookups_s_median"
                    ],
                    "texture_retention_vs_4_target_mib": retention,
                }
            )
        for row in full_occupancy:
            if row["stride_bytes"] == stride_bytes:
                row["first_target_below_95pct_texture_baseline_mib"] = (
                    first_below_95
                )

    same_target = []
    for target_mib in targets:
        for path in ("global_cg", "texture_object"):
            rates = {
                stride: index[(path, target_mib, stride, full_warps)][
                    "hot_glookups_s_median"
                ]
                for stride in strides
            }
            comparison = {
                "path": path,
                "target_mib": target_mib,
                **{f"stride_{stride}_glookups_s": rates[stride] for stride in strides},
                "max_to_min_rate_ratio": max(rates.values()) / min(rates.values()),
            }
            if 128 in rates:
                comparison.update(
                    {
                        f"stride_{stride}_to_128_rate_ratio": rates[stride]
                        / rates[128]
                        for stride in strides
                    }
                )
            same_target.append(comparison)

    model_groups = defaultdict(list)
    for row in aggregate_rows:
        if row["warps"] == full_warps:
            model_groups[
                (row["path"], row["hypothetical_128b_residency_mib"])
            ].append(row)
    model_alignment = []
    for (path, model_mib), rows in sorted(model_groups.items()):
        if len(rows) < 2:
            continue
        rates = [row["hot_glookups_s_median"] for row in rows]
        model_alignment.append(
            {
                "path": path,
                "hypothetical_128b_residency_mib": model_mib,
                "member_count": len(rows),
                "members": ";".join(
                    f"target={row['target_mib']},stride={row['stride_bytes']}"
                    for row in sorted(rows, key=lambda value: value["stride_bytes"])
                ),
                "hot_glookups_s_median_of_members": median(rates),
                "hot_rate_min": min(rates),
                "hot_rate_max": max(rates),
                "max_to_min_rate_ratio": max(rates) / min(rates),
            }
        )

    anchors = []
    for model_mib in (36.0, 38.0, 40.0, 48.0):
        for path in ("global_cg", "texture_object"):
            match = next(
                (
                    row
                    for row in model_alignment
                    if row["path"] == path
                    and row["hypothetical_128b_residency_mib"] == model_mib
                ),
                None,
            )
            if match is not None:
                anchors.append(match)

    def hot(path, target_mib, stride_bytes):
        return index[(path, target_mib, stride_bytes, full_warps)][
            "hot_glookups_s_median"
        ]

    diagnostic_summary = {}
    if {128, 256}.issubset(strides):
        texture_256_128_ratios = [
            hot("texture_object", target, 256)
            / hot("texture_object", target, 128)
            for target in targets
        ]
        diagnostic_summary["stride_256_to_128_texture_rate_ratio"] = {
            "median_all_targets": median(texture_256_128_ratios),
            "minimum_all_targets": min(texture_256_128_ratios),
            "maximum_all_targets": max(texture_256_128_ratios),
            **{
                f"target_{target}_mib": hot("texture_object", target, 256)
                / hot("texture_object", target, 128)
                for target in targets
            },
        }
    if {32, 64, 128}.issubset(strides) and {
        10,
        12,
        20,
        36,
        37,
        38,
        39,
        40,
    }.issubset(targets):
        diagnostic_summary.update(
            {
                "same_40mib_allocation_same_128b_line_count_texture": [
                    {
                        "stride_bytes": stride,
                        "target_mib": 40 * 32 // stride,
                        "requested_32b_span_mib": 40 * 32 // stride,
                        "allocation_mib": 40,
                        "unique_128b_line_count": 40 * 1024 * 1024 // 128,
                        "hot_glookups_s": hot(
                            "texture_object", 40 * 32 // stride, stride
                        ),
                    }
                    for stride in (32, 64, 128)
                ],
                "same_12mib_requested_32b_span_texture": [
                    {
                        "stride_bytes": stride,
                        "target_mib": 12,
                        "unique_128b_line_count": (
                            12 * 1024 * 1024 // 32
                            * min(stride, 128)
                            // 128
                        ),
                        "allocation_mib": 12 * stride // 32,
                        "hot_glookups_s": hot("texture_object", 12, stride),
                    }
                    for stride in strides
                ],
                "dense_32b_stride_texture_boundary": [
                    {
                        "target_mib": target,
                        "hot_glookups_s": hot("texture_object", target, 32),
                    }
                    for target in (36, 37, 38, 39, 40)
                ],
                "one_sector_per_line_128b_stride_texture_boundary": [
                    {
                        "target_mib": target,
                        "allocation_mib": target * 4,
                        "unique_128b_line_count": target * 1024 * 1024 // 32,
                        "hot_glookups_s": hot("texture_object", target, 128),
                    }
                    for target in (9, 10, 11, 12)
                ],
            }
        )
    if min(strides) >= 128:
        baseline_stride = 128 if 128 in strides else min(strides)
        diagnostic_summary["page_span_matrix"] = [
            {
                "path": path,
                "target_mib": target,
                "stride_bytes": stride,
                "requested_32b_span_mib": target,
                "containing_128b_lines": target * 1024 * 1024 // 32,
                "allocation_mib": target * stride // 32,
                "nominal_4k_pages_in_span": target
                * stride
                * 1024
                * 1024
                // 32
                // 4096,
                "average_useful_regions_per_nominal_4k_span": 4096 / stride,
                "hot_glookups_s": hot(path, target, stride),
                f"rate_ratio_to_stride_{baseline_stride}": hot(
                    path, target, stride
                )
                / hot(path, target, baseline_stride),
            }
            for path in ("global_cg", "texture_object")
            for target in targets
            for stride in strides
        ]

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

    source = Path("gpu/src/ugts_cuda_lut_sparse_address_bench.cu")
    executable = Path("gpu/build-windows/ugts_cuda_lut_sparse_address_bench.exe")
    output = {
        "schema": "UGTS-CUDA-LUT-SPARSE-ADDRESS-AGGREGATE-1.0",
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
        "model_anchor_summary": anchors,
        "diagnostic_summary": diagnostic_summary,
        "model_alignment": model_alignment,
        "same_target_comparison": same_target,
        "full_occupancy_summary": full_occupancy,
        "path_comparison": path_comparison,
        "results": aggregate_rows,
        "interpretation": {
            "target_definition": "target_mib equals region_count times 32 address bytes; it is address arithmetic, not measured sector traffic",
            "line_model_definition": "hypothetical_128b_residency_bytes counts one 128-byte line for each aligned line containing a requested word; it is a tested model, not a hardware fact",
            "stride_128_256_control": "128- and 256-byte spacing request the same number of hypothetical 128-byte lines while 256 uses twice the allocation and address span; their paired rate bounds extra address/TLB cost",
            "page_span_control": "For stride sets at or above 128 bytes, requested data and containing 128-byte line count stay fixed at a target while allocation span and nominal 4-KiB page count scale with stride; page counts are address arithmetic, not a declaration of the GPU page size or TLB occupancy",
        },
        "bounds": [
            "Every independent lookup requests one u32 containing one packed6 code; Glookup/s is logical code throughput, not physical cache or DRAM traffic.",
            "All unused words contain mixed data and remain physically allocated, but are not logically requested by the timed kernel.",
            "Exact L2 hit, sector, tag, TLB and DRAM counters remain unavailable; curve collapse can support or reject workload models without identifying undocumented hardware structures.",
        ],
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "cuda_lut_sparse_address_aggregate.json"
    json_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    tables = (
        ("cuda_lut_sparse_address_aggregate.csv", aggregate_rows),
        ("cuda_lut_sparse_address_full_occupancy.csv", full_occupancy),
        ("cuda_lut_sparse_address_path_comparison.csv", path_comparison),
        ("cuda_lut_sparse_address_same_target.csv", same_target),
        ("cuda_lut_sparse_address_model_alignment.csv", model_alignment),
    )
    for name, rows in tables:
        with (args.out_dir / name).open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(json_path)
    return 0 if validation["all_rows_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
