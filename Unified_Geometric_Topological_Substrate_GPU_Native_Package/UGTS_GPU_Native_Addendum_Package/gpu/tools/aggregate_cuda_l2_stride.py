#!/usr/bin/env python3
"""Aggregate native CUDA sparse-stride L2 residency runs."""

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()

    documents = []
    run_metadata = []
    by_key = defaultdict(list)
    for run_dir in args.runs:
        path = run_dir / "cuda_l2_stride_results.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        if document["schema"] != "UGTS-CUDA-L2-STRIDE-1.0":
            raise ValueError(f"unexpected schema in {path}")
        documents.append(document)
        local_keys = set()
        for row in document["results"]:
            key = (row["stride_bytes"], row["target_mib"], row["warps"])
            if key in local_keys:
                raise ValueError(f"duplicate key {key} in {path}")
            local_keys.add(key)
            by_key[key].append(row)
        run_metadata.append(
            {
                "directory": run_dir.as_posix(),
                "results_sha256": sha256(path),
                "rows": len(document["results"]),
                "target_order": list(dict.fromkeys(row["target_mib"] for row in document["results"])),
                "stride_order": list(dict.fromkeys(row["stride_bytes"] for row in document["results"])),
                "warp_order": list(dict.fromkeys(row["warps"] for row in document["results"])),
            }
        )

    first = documents[0]
    for document in documents[1:]:
        if document["device"] != first["device"]:
            raise ValueError("device or occupancy mismatch")
        for field in ("measured_pairs", "dependent_loads_per_thread", "eviction_bytes"):
            if document["run_parameters"][field] != first["run_parameters"][field]:
                raise ValueError(f"run parameter mismatch: {field}")
    if any(len(rows) != 4 for rows in by_key.values()):
        bad = {str(key): len(rows) for key, rows in by_key.items() if len(rows) != 4}
        raise ValueError(f"every case must have four runs: {bad}")

    aggregate_rows = []
    for key in sorted(by_key, key=lambda item: (item[0], item[1], item[2])):
        rows = by_key[key]
        stride, target, warps = key
        aggregate_rows.append(
            {
                "stride_bytes": stride,
                "target_mib": target,
                "nodes": rows[0]["nodes"],
                "allocation_bytes": rows[0]["allocation_bytes"],
                "allocation_mib": rows[0]["allocation_mib"],
                "warps": warps,
                "warps_per_sm": rows[0]["warps_per_sm"],
                "run_count": len(rows),
                "hot_gloads_s_median": median(row["hot_gloads_s"] for row in rows),
                "hot_gloads_s_min": min(row["hot_gloads_s"] for row in rows),
                "hot_gloads_s_max": max(row["hot_gloads_s"] for row in rows),
                "cold_gloads_s_median": median(row["cold_gloads_s"] for row in rows),
                "hot_net_cycles_per_step_median": median(row["hot_net_cycles_per_step"] for row in rows),
                "cold_net_cycles_per_step_median": median(row["cold_net_cycles_per_step"] for row in rows),
                "hot_kernel_us_p50_median": median(row["hot_kernel_us"]["p50"] for row in rows),
                "all_runs_valid": all(row["validation"] for row in rows),
            }
        )

    index = {
        (row["stride_bytes"], row["target_mib"], row["warps"]): row
        for row in aggregate_rows
    }
    full_warps = max(row["warps"] for row in aggregate_rows)

    def point(stride, target):
        return index[(stride, target, full_warps)]

    anchor_spec = ((32, 36), (64, 18), (128, 9), (256, 9))
    anchors = []
    for stride, target in anchor_spec:
        row = point(stride, target)
        anchors.append(
            {
                "stride_bytes": stride,
                "target_mib": target,
                "nodes": row["nodes"],
                "allocation_mib": row["allocation_mib"],
                "modeled_128b_line_footprint_mib": row["nodes"] * min(stride, 128) / (1024 * 1024),
                "hot_gloads_s": row["hot_gloads_s_median"],
            }
        )

    common_targets = sorted(
        set(row["target_mib"] for row in aggregate_rows if row["stride_bytes"] == 128)
        & set(row["target_mib"] for row in aggregate_rows if row["stride_bytes"] == 256)
    )
    stride_256_to_128 = []
    for target in common_targets:
        a, b = point(128, target), point(256, target)
        raw_ratios = [
            right["hot_gloads_s"] / left["hot_gloads_s"]
            for left, right in zip(by_key[(128, target, full_warps)], by_key[(256, target, full_warps)])
        ]
        stride_256_to_128.append(
            {
                "target_mib": target,
                "nodes": a["nodes"],
                "stride128_allocation_mib": a["allocation_mib"],
                "stride256_allocation_mib": b["allocation_mib"],
                "stride256_to_stride128_hot_rate_ratio_median": median(raw_ratios),
                "stride256_to_stride128_hot_rate_ratio_min": min(raw_ratios),
                "stride256_to_stride128_hot_rate_ratio_max": max(raw_ratios),
            }
        )

    line_model = {
        "bounded_effective_residency_unit_bytes": 128,
        "classification": "consistent with a 128-byte effective residency unit for isolated dependent-pointer u32 words in this workload; not a universal per-code cost or counter-derived hardware line-size claim",
        "nominal_36_mib_anchors": anchors,
        "active_node_capacity_ratio_stride32_to_64_to_128plus": "4:2:1",
        "stride128_rejects_64_byte_unit": {
            "target_mib": 18,
            "nodes": point(128, 18)["nodes"],
            "modeled_64b_footprint_mib": point(128, 18)["nodes"] * 64 / (1024 * 1024),
            "hot_gloads_s": point(128, 18)["hot_gloads_s_median"],
            "relative_to_stride128_36mib_anchor": point(128, 18)["hot_gloads_s_median"] / point(128, 9)["hot_gloads_s_median"],
        },
        "stride256_saturation_control": stride_256_to_128,
        "interpretation": "The same dependent node sequence at 128- and 256-byte spacing has nearly the same rate despite 2x allocation. Together with the 4:2:1 hot-node capacity at 32/64/128-byte stride, this bounds dependent-pointer residency amplification at 128 bytes on this workload; the independent packed-LUT control shows it is not universal.",
    }

    validation = {
        "all_rows_valid": all(row["validation"] for document in documents for row in document["results"]),
        "input_rows": sum(len(document["results"]) for document in documents),
        "aggregate_cases": len(aggregate_rows),
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
        "cpu_replayed_dependent_links": sum(
            (row["validated_cold"] + row["validated_hot"])
            * document["run_parameters"]["dependent_loads_per_thread"]
            for document in documents
            for row in document["results"]
        ),
        "measured_gpu_dependent_loads": sum(
            row["threads"]
            * row["samples"]
            * 2
            * document["run_parameters"]["dependent_loads_per_thread"]
            for document in documents
            for row in document["results"]
        ),
    }

    source = Path("gpu/src/ugts_cuda_l2_stride_bench.cu")
    executable = Path("gpu/build-windows/ugts_cuda_l2_stride_bench.exe")
    output = {
        "schema": "UGTS-CUDA-L2-STRIDE-AGGREGATE-1.0",
        "device": first["device"],
        "source": {"path": source.as_posix(), "sha256": sha256(source)},
        "executable": {
            "path": executable.as_posix(),
            "bytes": executable.stat().st_size,
            "sha256": sha256(executable),
        },
        "runs": run_metadata,
        "validation": validation,
        "line_model": line_model,
        "results": aggregate_rows,
        "bounds": [
            "The result is a workload-level effective residency inference from controlled capacity cliffs, not a privileged cache-line or sector counter.",
            "Sparse gaps contain deterministic mixed data to avoid zero-line compression; only one u32 pointer per stride is logically consumed.",
            "clock64 includes scheduling and event Gload/s counts logical requests rather than physical transactions.",
        ],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.out_dir / "cuda_l2_stride_aggregate.json"
    json_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    with (args.out_dir / "cuda_l2_stride_aggregate.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(aggregate_rows[0]))
        writer.writeheader()
        writer.writerows(aggregate_rows)
    with (args.out_dir / "cuda_l2_stride_128_256_comparison.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(stride_256_to_128[0]))
        writer.writeheader()
        writer.writerows(stride_256_to_128)
    print(json_path)
    return 0 if validation["all_rows_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
