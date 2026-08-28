#!/usr/bin/env python3
"""Validate and aggregate isolated CUDA clock64 L2-control runs."""

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

    grouped: dict[int, list[dict]] = defaultdict(list)
    run_records = []
    device = None
    expected_sizes = None
    validated_payloads = 0
    loads_in_validated_chains = 0
    for run_dir in args.runs:
        source = run_dir / "cuda_l2_clock_results.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        if document.get("schema") != "UGTS-CUDA-L2-CLOCK64-1.0":
            raise RuntimeError(f"unexpected schema in {source}")
        if device is None:
            device = document["device"]
        elif device != document["device"]:
            raise RuntimeError(f"device mismatch in {source}")
        rows = document.get("results", [])
        sizes = {int(row["table_bytes"]) for row in rows}
        if expected_sizes is None:
            expected_sizes = sizes
        elif sizes != expected_sizes:
            raise RuntimeError(f"table-size mismatch in {source}")
        if not rows or any(not row.get("validation") for row in rows):
            raise RuntimeError(f"failed or missing validation in {source}")
        params = document["run_parameters"]
        samples = int(params["measured_pairs"])
        threads = int(params["threads"])
        steps = int(params["dependent_loads_per_thread"])
        for row in rows:
            expected = samples * threads
            for field in ("validated_control", "validated_cold", "validated_hot"):
                if int(row[field]) != expected:
                    raise RuntimeError(f"{field} mismatch in {source}")
            validated_payloads += expected * 3
            loads_in_validated_chains += expected * steps * 2
            grouped[int(row["table_bytes"])].append(row)
        run_records.append(
            {
                "directory": str(run_dir.as_posix()),
                "results_sha256": sha256(source),
                "rows": len(rows),
                "table_order": [int(row["table_mib"]) for row in rows],
            }
        )

    aggregates = []
    for table_bytes, rows in sorted(grouped.items()):
        if len(rows) != len(args.runs):
            raise RuntimeError(f"incomplete coverage for {table_bytes} bytes")
        cold = [float(row["cold_net_cycles_per_load"]) for row in rows]
        hot = [float(row["hot_net_cycles_per_load"]) for row in rows]
        ratios = [float(row["cold_to_hot_ratio"]) for row in rows]
        control = [float(row["control_cycles"]["p50"]) for row in rows]
        cold_p95 = [float(row["cold_cycles"]["p95"]) for row in rows]
        hot_p95 = [float(row["hot_cycles"]["p95"]) for row in rows]
        cold_kernel = [float(row["cold_kernel_us"]["p50"]) for row in rows]
        hot_kernel = [float(row["hot_kernel_us"]["p50"]) for row in rows]
        aggregates.append(
            {
                "table_bytes": table_bytes,
                "table_mib": table_bytes / (1024 * 1024),
                "l2_fraction": table_bytes / int(device["l2_bytes"]),
                "run_count": len(rows),
                "samples_per_run": int(rows[0]["samples"]),
                "control_p50_cycles_median": median(control),
                "cold_net_cycles_per_load_median": median(cold),
                "cold_net_cycles_per_load_min": min(cold),
                "cold_net_cycles_per_load_max": max(cold),
                "hot_net_cycles_per_load_median": median(hot),
                "hot_net_cycles_per_load_min": min(hot),
                "hot_net_cycles_per_load_max": max(hot),
                "cold_to_hot_ratio_median": median(ratios),
                "cold_to_hot_ratio_min": min(ratios),
                "cold_to_hot_ratio_max": max(ratios),
                "cold_p95_chain_cycles_median": median(cold_p95),
                "hot_p95_chain_cycles_median": median(hot_p95),
                "cold_kernel_p50_us_median": median(cold_kernel),
                "hot_kernel_p50_us_median": median(hot_kernel),
                "cold_kernel_ns_per_step": median(cold_kernel) * 1000 / 512,
                "hot_kernel_ns_per_step": median(hot_kernel) * 1000 / 512,
            }
        )

    cold_all = [row["cold_net_cycles_per_load_median"] for row in aggregates]
    hot_all = [row["hot_net_cycles_per_load_median"] for row in aggregates]
    ratio_all = [row["cold_to_hot_ratio_median"] for row in aggregates]
    cold_ns_all = [row["cold_kernel_ns_per_step"] for row in aggregates]
    hot_ns_all = [row["hot_kernel_ns_per_step"] for row in aggregates]
    output = {
        "schema": "UGTS-CUDA-L2-CLOCK64-AGGREGATE-1.0",
        "device": device,
        "executable": {
            "path": str(args.executable.as_posix()),
            "bytes": args.executable.stat().st_size,
            "sha256": sha256(args.executable),
        },
        "runs": run_records,
        "validation": {
            "all_rows_valid": True,
            "validated_payloads": validated_payloads,
            "dependent_loads_in_validated_chains": loads_in_validated_chains,
        },
        "cross_size_summary": {
            "cold_cycles_per_load_median_of_sizes": median(cold_all),
            "cold_cycles_per_load_min_across_sizes": min(cold_all),
            "cold_cycles_per_load_max_across_sizes": max(cold_all),
            "hot_cycles_per_load_median_of_sizes": median(hot_all),
            "hot_cycles_per_load_min_across_sizes": min(hot_all),
            "hot_cycles_per_load_max_across_sizes": max(hot_all),
            "cold_to_hot_ratio_median_of_sizes": median(ratio_all),
            "cold_to_hot_ratio_min_across_sizes": min(ratio_all),
            "cold_to_hot_ratio_max_across_sizes": max(ratio_all),
            "cold_kernel_ns_per_step_median_of_sizes": median(cold_ns_all),
            "hot_kernel_ns_per_step_median_of_sizes": median(hot_ns_all),
        },
        "interpretation": (
            "One warp issues 512 dependent ld.global.cg steps. The cache operator "
            "bypasses L1 and uses the L2/global path. Cold follows a 256 MiB "
            "eviction pass; hot immediately repeats the same path. clock64 counts "
            "per-SM cycles but includes any thread time slicing. Each warp step may "
            "service up to 32 random sectors, so this is warp-exposed dependent-step "
            "latency, not one scalar memory-transaction latency."
        ),
        "results": aggregates,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "cuda_l2_clock_aggregate.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8"
    )
    with (args.out_dir / "cuda_l2_clock_aggregate.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(aggregates[0]))
        writer.writeheader()
        writer.writerows(aggregates)
    print(args.out_dir / "cuda_l2_clock_aggregate.json")
    print(args.out_dir / "cuda_l2_clock_aggregate.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
