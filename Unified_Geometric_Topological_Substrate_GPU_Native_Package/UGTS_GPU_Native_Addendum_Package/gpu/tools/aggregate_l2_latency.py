#!/usr/bin/env python3
"""Validate and aggregate isolated VK_KHR_shader_clock pointer-chase runs."""

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

    run_records = []
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    expected_keys: set[tuple[str, str, int]] | None = None
    total_validated = 0
    total_dependent_loads = 0
    device = None

    for run_dir in args.runs:
        source = run_dir / "l2_latency_results.json"
        document = json.loads(source.read_text(encoding="utf-8"))
        if document.get("schema") != "UGTS-VK-L2-LATENCY-1.0":
            raise RuntimeError(f"unexpected schema in {source}")
        if not document.get("device", {}).get("shader_device_clock"):
            raise RuntimeError(f"shaderDeviceClock was not enabled in {source}")
        if device is None:
            device = document["device"]
        elif document["device"] != device:
            raise RuntimeError(f"device metadata mismatch in {source}")
        rows = document.get("results", [])
        keys = {
            (str(row["mode"]), str(row["pattern"]), int(row["table_bytes"]))
            for row in rows
        }
        if expected_keys is None:
            expected_keys = keys
        elif keys != expected_keys:
            raise RuntimeError(f"row-key mismatch in {source}")
        if not rows or any(not row.get("validation") for row in rows):
            raise RuntimeError(f"failed or missing validation in {source}")
        controls = {
            (str(row["pattern"]), int(row["table_bytes"])): row
            for row in rows
            if int(row["chase_steps"]) == 0
        }
        for row in rows:
            total_validated += int(row["validated_outputs"])
            steps = int(row["chase_steps"])
            if not steps:
                continue
            key = (str(row["pattern"]), int(row["table_bytes"]))
            control = controls.get(key)
            if control is None:
                raise RuntimeError(f"missing paired control for {key} in {source}")
            recomputed = (
                float(row["clock_ticks"]["p50"])
                - float(control["clock_ticks"]["p50"])
            ) / steps
            recorded = float(row["control_subtracted_p50_ticks_per_load"])
            if abs(recomputed - recorded) > 1e-6:
                raise RuntimeError(f"net clock metric mismatch for {key} in {source}")
            grouped[key].append(
                {
                    "dispatch_ms": float(row["device_ms"]["p50"]),
                    "clock_ticks": float(row["clock_ticks"]["p50"]),
                    "control_ticks": float(control["clock_ticks"]["p50"]),
                    "net_ticks_per_load": recorded,
                    "invocations": int(row["invocations"]),
                    "steps": steps,
                    "l2_fraction": float(row["l2_fraction"]),
                }
            )
            total_dependent_loads += int(row["invocations"]) * steps
        run_records.append(
            {
                "directory": str(run_dir.as_posix()),
                "results_sha256": sha256(source),
                "rows": len(rows),
                "reverse": bool(document["run_parameters"]["reverse"]),
            }
        )

    aggregates = []
    for (pattern, table_bytes), samples in sorted(grouped.items()):
        if len(samples) != len(args.runs):
            raise RuntimeError(f"incomplete run coverage for {(pattern, table_bytes)}")
        invocations = {sample["invocations"] for sample in samples}
        steps = {sample["steps"] for sample in samples}
        if len(invocations) != 1 or len(steps) != 1:
            raise RuntimeError(f"parameter mismatch for {(pattern, table_bytes)}")
        dispatch = [sample["dispatch_ms"] for sample in samples]
        clock = [sample["clock_ticks"] for sample in samples]
        control = [sample["control_ticks"] for sample in samples]
        net = [sample["net_ticks_per_load"] for sample in samples]
        aggregates.append(
            {
                "pattern": pattern,
                "table_bytes": table_bytes,
                "table_mib": table_bytes / (1024 * 1024),
                "l2_fraction": samples[0]["l2_fraction"],
                "run_count": len(samples),
                "invocations_per_run": invocations.pop(),
                "chase_steps": steps.pop(),
                "dispatch_p50_ms_median": median(dispatch),
                "dispatch_p50_ms_min": min(dispatch),
                "dispatch_p50_ms_max": max(dispatch),
                "clock_p50_ticks_median": median(clock),
                "clock_p50_ticks_min": min(clock),
                "clock_p50_ticks_max": max(clock),
                "control_p50_ticks_median": median(control),
                "net_p50_ticks_per_load_median": median(net),
                "net_p50_ticks_per_load_min": min(net),
                "net_p50_ticks_per_load_max": max(net),
            }
        )

    by_pattern: dict[str, list[dict]] = defaultdict(list)
    by_size: dict[int, dict[str, dict]] = defaultdict(dict)
    for row in aggregates:
        by_pattern[row["pattern"]].append(row)
        by_size[row["table_bytes"]][row["pattern"]] = row
    for rows in by_pattern.values():
        rows.sort(key=lambda row: row["table_bytes"])
        baseline = next(
            row for row in rows if row["table_bytes"] == 36 * 1024 * 1024
        )["net_p50_ticks_per_load_median"]
        previous = None
        for row in rows:
            current = row["net_p50_ticks_per_load_median"]
            row["relative_to_36_mib"] = current / baseline
            row["ratio_from_previous_size"] = (
                current / previous if previous is not None else 1.0
            )
            previous = current
    for row in aggregates:
        peers = by_size[row["table_bytes"]]
        sequential = peers["sequential_ring"]["net_p50_ticks_per_load_median"]
        random = peers["random_full_period"]["net_p50_ticks_per_load_median"]
        row["random_to_sequential_ratio"] = random / sequential

    aggregates.sort(key=lambda row: (row["table_bytes"], row["pattern"]))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    output_json = {
        "schema": "UGTS-VK-L2-LATENCY-AGGREGATE-1.0",
        "device": device,
        "executable": {
            "path": str(args.executable.as_posix()),
            "sha256": sha256(args.executable),
            "bytes": args.executable.stat().st_size,
        },
        "runs": run_records,
        "validation": {
            "all_rows_valid": True,
            "validated_invocations_including_controls": total_validated,
            "dependent_loads_in_validated_chains": total_dependent_loads,
        },
        "interpretation": (
            "The control-subtracted shader-clock interval is scheduler-exposed "
            "dependent-chain time under a saturated 65,536-invocation workload. "
            "VK_KHR_shader_clock units are implementation-defined; values are "
            "not labelled hardware cycles or nanoseconds."
        ),
        "results": aggregates,
    }
    (args.out_dir / "l2_latency_aggregate.json").write_text(
        json.dumps(output_json, indent=2) + "\n", encoding="utf-8"
    )
    with (args.out_dir / "l2_latency_aggregate.csv").open(
        "w", newline="", encoding="utf-8"
    ) as output:
        writer = csv.DictWriter(output, fieldnames=list(aggregates[0]))
        writer.writeheader()
        writer.writerows(aggregates)
    print(args.out_dir / "l2_latency_aggregate.json")
    print(args.out_dir / "l2_latency_aggregate.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
