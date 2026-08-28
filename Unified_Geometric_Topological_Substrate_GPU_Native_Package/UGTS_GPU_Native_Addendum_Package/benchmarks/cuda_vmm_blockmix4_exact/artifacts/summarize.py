#!/usr/bin/env python3
"""Summarize native capacity for four-symbol compressible packed6 mixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


RUN_GROUPS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
ALL_PATTERNS = [f"blockmix6_0_21_42_63_g{groups}" for groups in RUN_GROUPS] + [
    "blockmix6_0_21_42_63_hash"
]
SHORT_PATTERNS = [f"blockmix6_0_21_42_63_g{groups}" for groups in (1, 2, 4, 8, 16)] + [
    "blockmix6_0_21_42_63_hash"
]
LONG_PATTERNS = [f"blockmix6_0_21_42_63_g{groups}" for groups in (32, 64, 128, 256, 512, 1024)]
SCREEN_SIZES = [36, 40, 48, 64, 72, 80, 88, 96, 112, 128, 160, 192, 224, 240, 248]
SHORT_SIZES = list(range(36, 86, 2))
LONG_SIZES = list(range(96, 164, 4))
G64_EXTENSION_SIZES = [160, 164, 168, 172, 176, 180, 184, 188, 192, 200, 208, 224, 240]
FULL_RATE_FRACTION = 0.99
EXPECTED_ENDPOINTS = {
    "blockmix6_0_21_42_63_g1": 40,
    "blockmix6_0_21_42_63_hash": 52,
    "blockmix6_0_21_42_63_g2": 60,
    "blockmix6_0_21_42_63_g4": 70,
    "blockmix6_0_21_42_63_g8": 72,
    "blockmix6_0_21_42_63_g16": 82,
    "blockmix6_0_21_42_63_g32": 120,
    "blockmix6_0_21_42_63_g64": 168,
    "blockmix6_0_21_42_63_g128": 140,
    "blockmix6_0_21_42_63_g256": 148,
    "blockmix6_0_21_42_63_g512": 120,
    "blockmix6_0_21_42_63_g1024": 124,
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_aggregate(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    require(document["schema"] == "UGTS-CUDA-VMM-COMPRESSION-LUT-AGGREGATE-1.0", f"schema: {path}")
    require(document["validation_summary"]["all_valid"], f"invalid aggregate: {path}")
    require(document["observed_orders"] == [0, 1, 0, 1], f"order mismatch: {path}")
    return document


def validate_coverage(document: dict, patterns: list[str], sizes: list[int]) -> None:
    rows = document["aggregate_rows"]
    require({row["pattern"] for row in rows} == set(patterns), "pattern coverage mismatch")
    require({row["size_mib"] for row in rows} == set(sizes), "size coverage mismatch")
    require({row["path"] for row in rows} == {"global_cg"}, "path coverage mismatch")
    require({row["warps"] for row in rows} == {1104}, "warp coverage mismatch")
    require({row["compression"] for row in rows} == {"non_compressible", "generic_compressible"}, "mode coverage mismatch")
    require(len(rows) == len(patterns) * len(sizes) * 2, "row count mismatch")
    require(len(document["compression_comparisons"]) == len(patterns) * len(sizes), "comparison count mismatch")


def group_run(pattern: str) -> int | None:
    if pattern.endswith("_hash"):
        return None
    return int(pattern.rsplit("_g", 1)[1])


def selected_corpus(pattern: str, documents: dict[str, dict]) -> tuple[str, dict, list[int]]:
    if pattern == "blockmix6_0_21_42_63_g64":
        return "g64_extension", documents["g64_extension"], G64_EXTENSION_SIZES
    if pattern in SHORT_PATTERNS:
        return "short_refinement", documents["short_refinement"], SHORT_SIZES
    return "long_refinement", documents["long_refinement"], LONG_SIZES


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen", required=True, type=Path)
    parser.add_argument("--short-refinement", required=True, type=Path)
    parser.add_argument("--long-refinement", required=True, type=Path)
    parser.add_argument("--g64-extension", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    documents = {
        "screen": load_aggregate(args.screen),
        "short_refinement": load_aggregate(args.short_refinement),
        "long_refinement": load_aggregate(args.long_refinement),
        "g64_extension": load_aggregate(args.g64_extension),
    }
    validate_coverage(documents["screen"], ALL_PATTERNS, SCREEN_SIZES)
    validate_coverage(documents["short_refinement"], SHORT_PATTERNS, SHORT_SIZES)
    validate_coverage(documents["long_refinement"], LONG_PATTERNS, LONG_SIZES)
    validate_coverage(documents["g64_extension"], ["blockmix6_0_21_42_63_g64"], G64_EXTENSION_SIZES)
    device = documents["screen"]["device"]
    require(all(document["device"] == device for document in documents.values()), "device mismatch")

    per_pattern = []
    observed_endpoints = {}
    for pattern in ALL_PATTERNS:
        source_name, document, sizes = selected_corpus(pattern, documents)
        rows = {
            row["size_mib"]: row
            for row in document["aggregate_rows"]
            if row["pattern"] == pattern and row["compression"] == "generic_compressible"
        }
        comparisons = {
            row["size_mib"]: row
            for row in document["compression_comparisons"]
            if row["pattern"] == pattern
        }
        require(set(rows) == set(sizes), f"selected curve mismatch: {pattern}")
        best = max(row["hot_glookups_s"] for row in rows.values())
        curve = []
        for size in sizes:
            retained = rows[size]["hot_glookups_s"] / best
            curve.append(
                {
                    "size_mib": size,
                    "hot_glookups_s": rows[size]["hot_glookups_s"],
                    "retained_fraction_of_best": retained,
                    "paired_generic_to_noncompressible_ratio": comparisons[size]["paired_hot_ratio"],
                }
            )
        full = [row for row in curve if row["retained_fraction_of_best"] >= FULL_RATE_FRACTION]
        endpoint = max(full, key=lambda row: row["size_mib"])
        later = [row for row in curve if row["size_mib"] > endpoint["size_mib"]]
        first_below = min(later, key=lambda row: row["size_mib"]) if later else None
        observed_endpoints[pattern] = endpoint["size_mib"]
        groups = group_run(pattern)
        endpoint_bytes = endpoint["size_mib"] * 1024 * 1024
        endpoint_groups = endpoint_bytes // 12
        per_pattern.append(
            {
                "pattern": pattern,
                "selection": (
                    "pseudorandom four-way choice per packed group"
                    if groups is None
                    else f"cyclic 0/21/42/63 runs of {groups} packed groups per symbol"
                ),
                "run_groups_per_symbol": groups,
                "run_codes_per_symbol": None if groups is None else groups * 16,
                "run_bytes_per_symbol": None if groups is None else groups * 12,
                "four_symbol_cycle_bytes": None if groups is None else groups * 48,
                "endpoint_source": source_name,
                "best_hot_glookups_s": best,
                "reported_99pct_endpoint_mib": endpoint["size_mib"],
                "endpoint_allocation_to_nominal_l2": endpoint["size_mib"] / 36,
                "logical_codes_at_endpoint": endpoint_groups * 16,
                "first_below_99pct_mib": None if first_below is None else first_below["size_mib"],
                "first_below_retained_fraction": None if first_below is None else first_below["retained_fraction_of_best"],
                "curve": curve,
            }
        )
    require(observed_endpoints == EXPECTED_ENDPOINTS, "endpoint classification changed")

    validations = {name: document["validation_summary"] for name, document in documents.items()}
    combined = {
        "runs": sum(len(document["inputs"]) for document in documents.values()),
        "raw_rows": sum(value["raw_rows"] for value in validations.values()),
        "validated_payloads": sum(value["validated_payloads"] for value in validations.values()),
        "timed_gpu_lookups": sum(value["timed_gpu_lookups"] for value in validations.values()),
        "invalid_rows": sum(value["invalid_rows"] for value in validations.values()),
    }
    require(combined == {"runs": 16, "raw_rows": 3560, "validated_payloads": 3773030400, "timed_gpu_lookups": 1287861043200, "invalid_rows": 0}, "combined totals changed")

    summary = {
        "schema": "UGTS-CUDA-VMM-BLOCKMIX4-MAP-1.0",
        "source_aggregates": {
            "screen": args.screen.as_posix(),
            "short_refinement": args.short_refinement.as_posix(),
            "long_refinement": args.long_refinement.as_posix(),
            "g64_extension": args.g64_extension.as_posix(),
        },
        "device": device,
        "question": (
            "How much throughput-equivalent L2 capacity remains when every packed group "
            "chooses among all four individually compressible uniform codes 0, 21, 42 and 63?"
        ),
        "full_rate_definition": {
            "retained_fraction_of_best_generic_hot_rate": FULL_RATE_FRACTION,
            "normalization": "Each reported endpoint is normalized only within its dedicated four-process balanced refinement corpus.",
            "screen_sizes_mib": SCREEN_SIZES,
            "short_refinement_sizes_mib": SHORT_SIZES,
            "long_refinement_sizes_mib": LONG_SIZES,
            "g64_extension_sizes_mib": G64_EXTENSION_SIZES,
        },
        "layout": {
            "logical_codes": [0, 21, 42, 63],
            "packed_words": ["0x00000000", "0x55555555", "0xAAAAAAAA", "0xFFFFFFFF"],
            "codes_per_group": 16,
            "bytes_per_group": 12,
            "bytes_per_code": 0.75,
            "symbol_bits_per_group": 2,
            "balance": "Cyclic runs are approximately 25% each; hashed selection is approximately uniform over four symbols.",
        },
        "validation": {**validations, "combined": combined},
        "reported_endpoints_mib": observed_endpoints,
        "per_pattern": per_pattern,
        "conclusion": (
            "A four-symbol alphabet made only from individually compressible uniform word values "
            "still gains capacity, but much less than the two-symbol 0/63 case and not monotonically "
            "with run length. Reported endpoints span 40-82 MiB for hashed/12-192-byte symbol runs "
            "and 120-168 MiB for tested 384-12,288-byte runs. The non-monotonic long-run ordering "
            "is an observed layout/access interaction, not a compressor-block law."
        ),
        "scope_note": (
            "These are deterministic approximately balanced synthetic controls on the validated raw "
            "global path. Two symbolic bits per group is not general data entropy. No texture, physical "
            "compressed-byte, cache-hit, sector, DRAM-traffic or undocumented compressor-format claim is made."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        "blockmix4 map: "
        f"rows={combined['raw_rows']} payloads={combined['validated_payloads']} "
        f"timed_lookups={combined['timed_gpu_lookups']} endpoint_range="
        f"{min(observed_endpoints.values())}-{max(observed_endpoints.values())} MiB"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
