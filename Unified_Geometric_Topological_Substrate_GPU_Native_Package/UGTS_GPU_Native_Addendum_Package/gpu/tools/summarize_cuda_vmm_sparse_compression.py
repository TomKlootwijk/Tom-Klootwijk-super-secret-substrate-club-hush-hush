#!/usr/bin/env python3
"""Summarize full-rate limits for sparse packed6 generic-compression runs."""

from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
from pathlib import Path
from typing import Any


PATTERN = re.compile(r"^sparse1_(\d+)$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--retained-fraction", type=float, default=0.99)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 0.0 < args.retained_fraction <= 1.0:
        raise ValueError("retained fraction must be in (0, 1]")
    rows_by_pattern: dict[str, dict[int, list[dict[str, Any]]]] = {}
    entry_lookup: dict[tuple[str, int], int] = {}
    device: dict[str, Any] | None = None
    inputs: list[str] = []
    for value in args.inputs:
        path = value if value.is_file() else value / "cuda_vmm_compression_lut_aggregate.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schema") != "UGTS-CUDA-VMM-COMPRESSION-LUT-AGGREGATE-1.0":
            raise ValueError(f"unexpected schema in {path}")
        if not document["validation_summary"]["all_valid"]:
            raise ValueError(f"invalid input corpus: {path}")
        if device is None:
            device = document["device"]
        elif document["device"] != device:
            raise ValueError(f"device mismatch in {path}")
        inputs.append(str(path))
        for row in document["aggregate_rows"]:
            if (
                row["compression"] == "generic_compressible"
                and row["path"] == "global_cg"
                and PATTERN.match(row["pattern"])
            ):
                entry_lookup[(str(row["pattern"]), int(row["size_mib"]))] = int(row["entries"])
        for row in document["compression_comparisons"]:
            if row["path"] != "global_cg" or not PATTERN.match(row["pattern"]):
                continue
            pattern = str(row["pattern"])
            size_mib = int(row["size_mib"])
            rows_by_pattern.setdefault(pattern, {}).setdefault(size_mib, []).append(row)

    summary_rows: list[dict[str, Any]] = []
    for pattern, rows_by_size in sorted(
        rows_by_pattern.items(), key=lambda item: int(PATTERN.match(item[0]).group(1))
    ):
        interval = int(PATTERN.match(pattern).group(1))
        rows: list[dict[str, Any]] = []
        for size_mib, repeated_rows in sorted(rows_by_size.items()):
            rows.append(
                {
                    "size_mib": size_mib,
                    "generic_compressible_hot_glookups_s": statistics.median(
                        float(row["generic_compressible_hot_glookups_s"])
                        for row in repeated_rows
                    ),
                    "non_compressible_hot_glookups_s": statistics.median(
                        float(row["non_compressible_hot_glookups_s"])
                        for row in repeated_rows
                    ),
                    "repeat_corpora": len(repeated_rows),
                }
            )
        best_rate = max(float(row["generic_compressible_hot_glookups_s"]) for row in rows)
        qualified = [
            row
            for row in rows
            if float(row["generic_compressible_hot_glookups_s"]) / best_rate
            >= args.retained_fraction
        ]
        if not qualified:
            raise ValueError(f"no full-rate row for {pattern}")
        limit = max(qualified, key=lambda row: int(row["size_mib"]))
        limit_size = int(limit["size_mib"])
        later = [row for row in rows if int(row["size_mib"]) > limit_size]
        next_row = min(later, key=lambda row: int(row["size_mib"])) if later else None
        entries = entry_lookup[(pattern, limit_size)]
        spacing_bytes = interval * 6 / 8
        exceptions = (entries + interval - 1) // interval
        summary_rows.append(
            {
                "pattern": pattern,
                "code_interval": interval,
                "packed_spacing_bytes": spacing_bytes,
                "nonzero_code_percent": 100.0 / interval,
                "set_bit_percent_of_packed_payload": 100.0 / (interval * 6),
                "best_generic_glookups_s": best_rate,
                "full_rate_definition": args.retained_fraction,
                "max_full_rate_size_mib": limit_size,
                "max_full_rate_l2_multiple": limit_size / 36.0,
                "generic_glookups_s_at_limit": float(
                    limit["generic_compressible_hot_glookups_s"]
                ),
                "retained_rate_at_limit": float(
                    limit["generic_compressible_hot_glookups_s"]
                )
                / best_rate,
                "logical_codes_at_limit": entries,
                "nonzero_exceptions_at_limit": exceptions,
                "next_tested_size_mib": int(next_row["size_mib"]) if next_row else None,
                "retained_rate_at_next_size": (
                    float(next_row["generic_compressible_hot_glookups_s"]) / best_rate
                    if next_row
                    else None
                ),
                "maximum_repeat_corpora_per_size": max(
                    len(repeated_rows) for repeated_rows in rows_by_size.values()
                ),
            }
        )

    compression_limited_format_rows = [
        row
        for row in summary_rows
        if 544 <= int(row["code_interval"]) <= 736
        and int(row["max_full_rate_size_mib"]) < 240
        and row["next_tested_size_mib"] is not None
        and float(row["retained_rate_at_next_size"]) < args.retained_fraction
    ]
    exception_counts = [
        int(row["nonzero_exceptions_at_limit"])
        for row in compression_limited_format_rows
    ]
    fitted_boundaries = {
        "format_series_observed_compression_cliffs": {
            "included_patterns": [row["pattern"] for row in compression_limited_format_rows],
            "selection": (
                "Sparse intervals 544..736 whose last full-rate point is below the "
                "240 MiB reliable-address ceiling and whose next tested point falls "
                "below the retained-rate threshold."
            ),
            "median_nonzero_exceptions_at_limit": statistics.median(exception_counts),
            "minimum_nonzero_exceptions_at_limit": min(exception_counts),
            "maximum_nonzero_exceptions_at_limit": max(exception_counts),
            "scope_note": (
                "This empirical exception-count band is descriptive for the tested "
                "packed6 layout. It is not a physical compressor capacity."
            ),
        }
    }

    output = {
        "schema": "UGTS-CUDA-VMM-SPARSE-COMPRESSION-SUMMARY-1.0",
        "device": device,
        "inputs": inputs,
        "full_rate_definition": (
            "Highest tested allocation retaining at least the configured fraction "
            "of that pattern's best median generic-compressible global rate."
        ),
        "retained_fraction": args.retained_fraction,
        "layout": (
            "Dense packed6; code 1 at index multiples of code_interval and code 0 "
            "elsewhere. Intervals are multiples of 16, so every exception is the "
            "first code of a 12-byte packed group."
        ),
        "scope_note": (
            "Thresholds are workload-level throughput-equivalent allocation limits, "
            "not achieved physical compression ratios or compressor-block sizes."
        ),
        "duplicate_measurement_rule": (
            "When corpora repeat a pattern and size, the summary uses the median of "
            "their independently aggregated median rates."
        ),
        "fitted_boundaries": fitted_boundaries,
        "thresholds": summary_rows,
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "sparse_compression_thresholds.json").write_text(
        json.dumps(output, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    with (args.out_dir / "sparse_compression_thresholds.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=list(summary_rows[0].keys()))
        writer.writeheader()
        writer.writerows(summary_rows)
    print(
        f"patterns={len(summary_rows)} retained_fraction={args.retained_fraction:.3f} "
        f"out={args.out_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
