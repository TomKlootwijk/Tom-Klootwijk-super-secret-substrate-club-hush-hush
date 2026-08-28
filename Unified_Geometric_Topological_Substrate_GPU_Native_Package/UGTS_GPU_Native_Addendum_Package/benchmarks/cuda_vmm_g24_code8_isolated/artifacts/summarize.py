#!/usr/bin/env python3
"""Summarize the native CUDA VMM result for the current UGTS G24 code stream."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import struct
from pathlib import Path


PATTERN = "ugts_g24_floor70_code8"
PATHS = ("global_cg", "texture_object")
MODES = ("non_compressible", "generic_compressible")
FULL_RATE_FRACTION = 0.99


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def packed_words(code: int) -> list[int]:
    words = [0, 0, 0]
    for offset in range(16):
        bit = offset * 6
        word = bit >> 5
        shift = bit & 31
        words[word] = (words[word] | ((code << shift) & 0xFFFFFFFF)) & 0xFFFFFFFF
        if shift > 26:
            words[word + 1] |= code >> (32 - shift)
    return words


def ratio_summary(values: list[float]) -> dict[str, float]:
    return {
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
        "maximum_absolute_distance_from_unity": max(abs(value - 1.0) for value in values),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("aggregate", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    aggregate = json.loads(args.aggregate.read_text(encoding="utf-8"))
    require(
        aggregate["schema"] == "UGTS-CUDA-VMM-COMPRESSION-LUT-AGGREGATE-1.0",
        "unexpected aggregate schema",
    )
    validation = aggregate["validation_summary"]
    require(validation["all_valid"], "aggregate contains invalid rows")
    require(validation["invalid_rows"] == 0, "aggregate reports invalid rows")
    require(aggregate["observed_orders"] == [0, 1, 0, 1], "unexpected run order")

    rows = [row for row in aggregate["aggregate_rows"] if row["pattern"] == PATTERN]
    comparisons = [
        row for row in aggregate["compression_comparisons"] if row["pattern"] == PATTERN
    ]
    require(len(rows) == validation["aggregate_rows"], "unexpected additional patterns")
    require(
        len(comparisons) == validation["paired_comparisons"],
        "unexpected additional comparison patterns",
    )
    require({row["path"] for row in rows} == set(PATHS), "path coverage mismatch")
    require({row["compression"] for row in rows} == set(MODES), "mode coverage mismatch")
    require({row["warps"] for row in rows} == {1104}, "occupancy coverage mismatch")

    row_index = {
        (row["path"], row["compression"], row["size_mib"]): row for row in rows
    }
    sizes = sorted({row["size_mib"] for row in rows})
    full_rate: dict[str, dict[str, dict[str, float | int]]] = {}
    transitions: dict[str, dict[str, dict[str, float]]] = {}
    for path in PATHS:
        full_rate[path] = {}
        transitions[path] = {}
        for mode in MODES:
            curve = [row_index[(path, mode, size)] for size in sizes]
            best = max(row["hot_glookups_s"] for row in curve)
            qualifying = [
                row for row in curve if row["hot_glookups_s"] >= FULL_RATE_FRACTION * best
            ]
            best_row = max(curve, key=lambda row: row["hot_glookups_s"])
            last_row = max(qualifying, key=lambda row: row["size_mib"])
            full_rate[path][mode] = {
                "best_size_mib": best_row["size_mib"],
                "best_hot_glookups_s": best,
                "last_size_mib": last_row["size_mib"],
                "last_entries": last_row["entries"],
                "last_table_bytes": last_row["table_bytes"],
            }
            at_36 = row_index[(path, mode, 36)]["hot_glookups_s"]
            at_40 = row_index[(path, mode, 40)]["hot_glookups_s"]
            transitions[path][mode] = {
                "hot_glookups_s_36_mib": at_36,
                "hot_glookups_s_40_mib": at_40,
                "loss_fraction_36_to_40_mib": 1.0 - at_40 / at_36,
            }

    all_ratios = [row["paired_hot_ratio"] for row in comparisons]
    by_path = {
        path: ratio_summary(
            [row["paired_hot_ratio"] for row in comparisons if row["path"] == path]
        )
        for path in PATHS
    }
    absolute_relative_ranges = [row["hot_glookups_s_relative_range"] for row in rows]
    unstable_rows = [
        {
            "path": row["path"],
            "compression": row["compression"],
            "size_mib": row["size_mib"],
            "hot_glookups_s_relative_range": row["hot_glookups_s_relative_range"],
        }
        for row in rows
        if row["hot_glookups_s_relative_range"] >= 0.10
    ]

    floor_f16 = struct.unpack("<e", struct.pack("<e", 0.70))[0]
    distance = -math.log2(floor_f16) / 32.0
    code = round(distance / 0.125 * 63.0)
    require(code == 8, f"G24 producer quantization changed: observed code {code}")
    words = packed_words(code)

    same_capacity_endpoint = all(
        full_rate[path]["non_compressible"]["last_size_mib"]
        == full_rate[path]["generic_compressible"]["last_size_mib"]
        for path in PATHS
    )
    all_within_two_percent = all(abs(value - 1.0) <= 0.02 for value in all_ratios)

    summary = {
        "schema": "UGTS-CUDA-VMM-G24-CODE8-SUMMARY-1.0",
        "source_aggregate": args.aggregate.as_posix(),
        "question": (
            "Does the exact uniform packed6 threshold-code stream emitted by the current "
            "G24 benchmark producer gain throughput-equivalent cache capacity from a "
            "driver-confirmed generic-compressible CUDA VMM allocation?"
        ),
        "producer_mapping": {
            "confidence_floor_source_value": 0.70,
            "confidence_floor_binary16": floor_f16,
            "confidence_distance": distance,
            "quantized_code": code,
            "codes_per_group": 16,
            "bytes_per_group": 12,
            "bytes_per_code": 0.75,
            "packed_words_hex": [f"0x{word:08X}" for word in words],
            "set_bits_per_96_bit_group": sum(word.bit_count() for word in words),
        },
        "validation": validation,
        "sizes_mib": sizes,
        "full_rate_definition": {
            "retained_fraction_of_best_hot_rate": FULL_RATE_FRACTION,
            "result": full_rate,
        },
        "l2_transition": transitions,
        "paired_generic_to_non_compressible_hot_ratio": {
            "all_size_path_pairs": ratio_summary(all_ratios),
            "by_path": by_path,
            "all_pairs_within_two_percent_of_unity": all_within_two_percent,
        },
        "absolute_rate_stability": {
            "maximum_repetition_relative_range": max(absolute_relative_ranges),
            "rows_at_or_above_10_percent_relative_range": unstable_rows,
            "interpretation": (
                "Laptop clock/performance-state changes make some cross-size absolute medians "
                "unstable. Compression modes alternate inside each measured sample, so paired "
                "compression ratios are the primary causal evidence."
            ),
        },
        "conclusion": {
            "compression_capacity_extension_observed": not same_capacity_endpoint,
            "both_modes_last_full_rate_at_36_mib_on_both_paths": all(
                full_rate[path][mode]["last_size_mib"] == 36
                for path in PATHS
                for mode in MODES
            ),
            "interpretation": (
                "The exact current G24 uniform code-8 stream does not extend the 99%-of-best "
                "throughput endpoint beyond nominal 36 MiB L2 on either native access path. "
                "A uniform semantic value is therefore insufficient; the packed physical word "
                "pattern matters."
            ),
        },
        "scope_note": (
            "This is an externalized packed threshold-code stream from the package's synthetic "
            "G24 producer, not the complete interleaved G24 state record and not a measured "
            "production knowledge distribution. It does not expose physical compressed bytes, "
            "cache-hit rate, sector traffic, or a portable hardware compression ratio."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        "G24 code8: "
        f"rows={validation['raw_rows']} "
        f"timed_lookups={validation['timed_gpu_lookups']} "
        f"paired_ratio_median={statistics.median(all_ratios):.6f} "
        f"full_rate_36_mib={summary['conclusion']['both_modes_last_full_rate_at_36_mib_on_both_paths']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
