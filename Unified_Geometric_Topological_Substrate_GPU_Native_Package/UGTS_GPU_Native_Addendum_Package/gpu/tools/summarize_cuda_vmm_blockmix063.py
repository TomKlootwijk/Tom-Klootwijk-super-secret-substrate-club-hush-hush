#!/usr/bin/env python3
"""Summarize native CUDA VMM capacity for balanced packed6 code-0/63 mixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SCREEN_SIZES = [36, 40, 48, 64, 80, 96, 112, 128, 160, 192, 224, 240, 248]
REFINEMENT_SIZES = list(range(64, 98, 2))
RUN_GROUPS = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
SCREEN_PATTERNS = [f"blockmix6_0_63_g{groups}" for groups in RUN_GROUPS] + [
    "blockmix6_0_63_hash"
]
REFINEMENT_PATTERNS = [
    "blockmix6_0_63_g1",
    "blockmix6_0_63_g2",
    "blockmix6_0_63_g4",
    "blockmix6_0_63_g8",
    "blockmix6_0_63_g16",
    "blockmix6_0_63_hash",
]
FULL_RATE_FRACTION = 0.99


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_aggregate(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    require(
        document["schema"] == "UGTS-CUDA-VMM-COMPRESSION-LUT-AGGREGATE-1.0",
        f"unexpected aggregate schema: {path}",
    )
    require(document["validation_summary"]["all_valid"], f"invalid aggregate: {path}")
    require(document["observed_orders"] == [0, 1, 0, 1], f"order mismatch: {path}")
    return document


def validate_coverage(document: dict, patterns: list[str], sizes: list[int]) -> None:
    rows = document["aggregate_rows"]
    require({row["pattern"] for row in rows} == set(patterns), "pattern coverage mismatch")
    require({row["size_mib"] for row in rows} == set(sizes), "size coverage mismatch")
    require({row["path"] for row in rows} == {"global_cg"}, "path coverage mismatch")
    require({row["warps"] for row in rows} == {1104}, "warp coverage mismatch")
    require(
        {row["compression"] for row in rows}
        == {"non_compressible", "generic_compressible"},
        "compression coverage mismatch",
    )
    require(len(rows) == len(patterns) * len(sizes) * 2, "aggregate row count mismatch")
    require(
        len(document["compression_comparisons"]) == len(patterns) * len(sizes),
        "comparison count mismatch",
    )


def row_index(document: dict) -> dict[tuple[str, str, int], dict]:
    return {
        (row["pattern"], row["compression"], row["size_mib"]): row
        for row in document["aggregate_rows"]
    }


def comparison_index(document: dict) -> dict[tuple[str, int], dict]:
    return {
        (row["pattern"], row["size_mib"]): row
        for row in document["compression_comparisons"]
    }


def group_run(pattern: str) -> int | None:
    if pattern == "blockmix6_0_63_hash":
        return None
    prefix = "blockmix6_0_63_g"
    require(pattern.startswith(prefix), f"unexpected pattern: {pattern}")
    groups = int(pattern.removeprefix(prefix))
    require(groups in RUN_GROUPS, f"unexpected group run: {groups}")
    return groups


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen", required=True, type=Path)
    parser.add_argument("--refinement", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    screen = load_aggregate(args.screen)
    refinement = load_aggregate(args.refinement)
    validate_coverage(screen, SCREEN_PATTERNS, SCREEN_SIZES)
    validate_coverage(refinement, REFINEMENT_PATTERNS, REFINEMENT_SIZES)
    require(screen["device"] == refinement["device"], "device mismatch")
    screen_rows = row_index(screen)
    refinement_rows = row_index(refinement)
    screen_comparisons = comparison_index(screen)
    refinement_comparisons = comparison_index(refinement)

    pattern_rows = []
    for pattern in SCREEN_PATTERNS:
        sizes = sorted(
            set(SCREEN_SIZES)
            | (set(REFINEMENT_SIZES) if pattern in REFINEMENT_PATTERNS else set())
        )
        curve = []
        for size in sizes:
            use_refinement = pattern in REFINEMENT_PATTERNS and size in REFINEMENT_SIZES
            rows = refinement_rows if use_refinement else screen_rows
            comparisons = refinement_comparisons if use_refinement else screen_comparisons
            row = rows[(pattern, "generic_compressible", size)]
            comparison = comparisons[(pattern, size)]
            curve.append(
                {
                    "size_mib": size,
                    "hot_glookups_s": row["hot_glookups_s"],
                    "paired_generic_to_noncompressible_ratio": comparison["paired_hot_ratio"],
                    "source": "refinement" if use_refinement else "screen",
                }
            )
        # Normalize endpoint decisions within one balanced process matrix.  The
        # refinement intentionally supersedes the coarse screen for its six
        # patterns so cross-process clock states cannot move a borderline 99%
        # classification.
        endpoint_curve = (
            [row for row in curve if row["source"] == "refinement"]
            if pattern in REFINEMENT_PATTERNS
            else curve
        )
        best = max(row["hot_glookups_s"] for row in endpoint_curve)
        for row in curve:
            row["retained_fraction_of_best"] = row["hot_glookups_s"] / best
        full = [
            row
            for row in endpoint_curve
            if row["retained_fraction_of_best"] >= FULL_RATE_FRACTION
        ]
        endpoint = max(full, key=lambda row: row["size_mib"])
        next_rows = [
            row for row in endpoint_curve if row["size_mib"] > endpoint["size_mib"]
        ]
        first_below = min(next_rows, key=lambda row: row["size_mib"]) if next_rows else None
        groups = group_run(pattern)
        pattern_rows.append(
            {
                "pattern": pattern,
                "selection": (
                    "pseudorandom code 0/63 choice independently per 16-code group"
                    if groups is None
                    else f"alternating code 0/63 runs of {groups} packed groups"
                ),
                "run_groups": groups,
                "run_codes": None if groups is None else groups * 16,
                "run_bytes": None if groups is None else groups * 12,
                "best_hot_glookups_s": best,
                "reported_99pct_endpoint_mib": endpoint["size_mib"],
                "endpoint_allocation_to_nominal_l2": endpoint["size_mib"] / 36,
                "first_below_99pct_mib": None if first_below is None else first_below["size_mib"],
                "first_below_retained_fraction": (
                    None if first_below is None else first_below["retained_fraction_of_best"]
                ),
                "curve": curve,
            }
        )

    endpoint_by_pattern = {
        row["pattern"]: row["reported_99pct_endpoint_mib"] for row in pattern_rows
    }
    require(
        endpoint_by_pattern["blockmix6_0_63_hash"] == 72,
        "hashed-group endpoint changed",
    )
    for groups in (1, 2, 4, 8):
        require(endpoint_by_pattern[f"blockmix6_0_63_g{groups}"] == 72, "short-run endpoint changed")
    require(endpoint_by_pattern["blockmix6_0_63_g16"] == 88, "16-group endpoint changed")
    for groups in (32, 64, 128, 256, 512, 1024):
        require(endpoint_by_pattern[f"blockmix6_0_63_g{groups}"] == 240, "long-run endpoint changed")

    screen_validation = screen["validation_summary"]
    refinement_validation = refinement["validation_summary"]
    combined = {
        "runs": len(screen["inputs"]) + len(refinement["inputs"]),
        "raw_rows": screen_validation["raw_rows"] + refinement_validation["raw_rows"],
        "validated_payloads": screen_validation["validated_payloads"]
        + refinement_validation["validated_payloads"],
        "timed_gpu_lookups": screen_validation["timed_gpu_lookups"]
        + refinement_validation["timed_gpu_lookups"],
        "invalid_rows": screen_validation["invalid_rows"]
        + refinement_validation["invalid_rows"],
    }
    require(combined["invalid_rows"] == 0, "combined invalid rows")

    summary = {
        "schema": "UGTS-CUDA-VMM-BLOCKMIX063-MAP-1.0",
        "source_aggregates": {
            "capacity_screen": args.screen.as_posix(),
            "transition_refinement": args.refinement.as_posix(),
        },
        "device": screen["device"],
        "question": (
            "How much throughput-equivalent L2 capacity remains when the individually "
            "compressible packed6 codes 0 and 63 are mixed at controlled spatial scales?"
        ),
        "full_rate_definition": {
            "retained_fraction_of_best_generic_hot_rate": FULL_RATE_FRACTION,
            "screen_sizes_mib": SCREEN_SIZES,
            "refinement_sizes_mib": REFINEMENT_SIZES,
            "normalization": (
                "Refined patterns use best rate and endpoints from the four-process "
                "refinement matrix; the other patterns use the four-process screen."
            ),
        },
        "layout": {
            "codes_per_group": 16,
            "bytes_per_group": 12,
            "bytes_per_code": 0.75,
            "code_0_words": ["0x00000000"] * 3,
            "code_63_words": ["0xFFFFFFFF"] * 3,
            "balance": "Each synthetic corpus is approximately 50% code 0 and 50% code 63.",
        },
        "validation": {
            "capacity_screen": screen_validation,
            "transition_refinement": refinement_validation,
            "combined": combined,
        },
        "observed_capacity_classes": {
            "72_mib_endpoint": [
                "blockmix6_0_63_hash",
                "blockmix6_0_63_g1",
                "blockmix6_0_63_g2",
                "blockmix6_0_63_g4",
                "blockmix6_0_63_g8",
            ],
            "88_mib_endpoint": ["blockmix6_0_63_g16"],
            "240_mib_address_limited": [
                f"blockmix6_0_63_g{groups}" for groups in (32, 64, 128, 256, 512, 1024)
            ],
            "first_tested_run_span_full_through_240_mib": {
                "groups": 32,
                "codes": 512,
                "bytes": 384,
            },
        },
        "per_pattern": pattern_rows,
        "conclusion": (
            "The hardware benefit survives nonzero, balanced code-0/63 mixtures, but depends "
            "strongly on spatial organization. Hashed or 12-96-byte alternating runs reach a "
            "72 MiB balanced endpoint; 192-byte runs reach 88 MiB; every tested run from 384 "
            "through 12,288 bytes remains full through the independently address-bounded 240 "
            "MiB endpoint. This bounds workload behavior and does not identify an undocumented "
            "compressor block size or a physical byte ratio."
        ),
        "scope_note": (
            "The sequences are deterministic balanced synthetic controls on the validated raw "
            "global L2 path. They do not prove that arbitrary binary data with the same nominal "
            "run length compresses identically, and no texture, cache-hit, sector, DRAM-traffic "
            "or physical compressed-byte claim is made."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        "blockmix063 map: "
        f"rows={combined['raw_rows']} payloads={combined['validated_payloads']} "
        f"timed_lookups={combined['timed_gpu_lookups']} endpoints=72/88/240"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
