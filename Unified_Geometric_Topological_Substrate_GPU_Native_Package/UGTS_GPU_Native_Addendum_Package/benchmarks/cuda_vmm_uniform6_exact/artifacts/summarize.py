#!/usr/bin/env python3
"""Classify all uniform packed6 values under native CUDA VMM compression."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


SCREEN_SIZES = [36, 40, 64, 128, 240, 248]
REFINEMENT_SIZES = [36, 40, 64, 66, 68, 70, 72, 74, 76, 78, 80, 82, 84, 88, 96, 112, 128]
REFINEMENT_CODES = [0, 21, 42, 63]
FULL_RATE_FRACTION = 0.99


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def code_from_pattern(pattern: str) -> int:
    require(pattern.startswith("uniform6_"), f"unexpected pattern: {pattern}")
    code = int(pattern.removeprefix("uniform6_"))
    require(0 <= code <= 63, f"uniform code out of range: {code}")
    return code


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


def minimal_source_bit_period(code: int) -> int:
    bits = [(code >> bit) & 1 for bit in range(6)]
    for period in (1, 2, 3, 6):
        if all(bits[index] == bits[index % period] for index in range(6)):
            return period
    raise AssertionError("period search failed")


def load_aggregate(path: Path) -> dict:
    document = json.loads(path.read_text(encoding="utf-8"))
    require(
        document["schema"] == "UGTS-CUDA-VMM-COMPRESSION-LUT-AGGREGATE-1.0",
        f"unexpected aggregate schema: {path}",
    )
    require(document["validation_summary"]["all_valid"], f"invalid aggregate: {path}")
    require(document["observed_orders"] == [0, 1, 0, 1], f"order mismatch: {path}")
    return document


def validate_coverage(document: dict, codes: list[int], sizes: list[int]) -> None:
    rows = document["aggregate_rows"]
    require({code_from_pattern(row["pattern"]) for row in rows} == set(codes), "code coverage mismatch")
    require({row["size_mib"] for row in rows} == set(sizes), "size coverage mismatch")
    require({row["path"] for row in rows} == {"global_cg"}, "path coverage mismatch")
    require({row["warps"] for row in rows} == {1104}, "warp coverage mismatch")
    require(
        {row["compression"] for row in rows}
        == {"non_compressible", "generic_compressible"},
        "compression coverage mismatch",
    )
    expected_rows = len(codes) * len(sizes) * 2
    require(len(rows) == expected_rows, "aggregate row count mismatch")
    require(
        len(document["compression_comparisons"]) == len(codes) * len(sizes),
        "comparison count mismatch",
    )


def row_index(document: dict) -> dict[tuple[int, str, int], dict]:
    return {
        (code_from_pattern(row["pattern"]), row["compression"], row["size_mib"]): row
        for row in document["aggregate_rows"]
    }


def full_rate_endpoint(index: dict, code: int, mode: str, sizes: list[int]) -> dict:
    curve = [index[(code, mode, size)] for size in sizes]
    best = max(row["hot_glookups_s"] for row in curve)
    last = max(
        (row for row in curve if row["hot_glookups_s"] >= FULL_RATE_FRACTION * best),
        key=lambda row: row["size_mib"],
    )
    return {
        "best_hot_glookups_s": best,
        "last_size_mib": last["size_mib"],
        "last_entries": last["entries"],
        "last_table_bytes": last["table_bytes"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--screen", required=True, type=Path)
    parser.add_argument("--refinement", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    screen = load_aggregate(args.screen)
    refinement = load_aggregate(args.refinement)
    validate_coverage(screen, list(range(64)), SCREEN_SIZES)
    validate_coverage(refinement, REFINEMENT_CODES, REFINEMENT_SIZES)
    require(screen["device"] == refinement["device"], "device mismatch")
    screen_index = row_index(screen)
    refinement_index = row_index(refinement)

    code_rows = []
    endpoint_groups: defaultdict[int, list[int]] = defaultdict(list)
    identical_word_codes = []
    for code in range(64):
        words = packed_words(code)
        if len(set(words)) == 1:
            identical_word_codes.append(code)
        generic_screen = full_rate_endpoint(
            screen_index, code, "generic_compressible", SCREEN_SIZES
        )
        non_screen = full_rate_endpoint(
            screen_index, code, "non_compressible", SCREEN_SIZES
        )
        selected_endpoint = generic_screen["last_size_mib"]
        refined = None
        if code in (21, 42):
            refined = full_rate_endpoint(
                refinement_index, code, "generic_compressible", REFINEMENT_SIZES
            )
            selected_endpoint = refined["last_size_mib"]
        endpoint_groups[selected_endpoint].append(code)
        code_rows.append(
            {
                "code": code,
                "binary_lsb_first": "".join(str((code >> bit) & 1) for bit in range(6)),
                "source_bit_period": minimal_source_bit_period(code),
                "packed_words_hex": [f"0x{word:08X}" for word in words],
                "distinct_packed_words": len(set(words)),
                "set_bits_per_96_bit_group": sum(word.bit_count() for word in words),
                "screen_99pct_endpoint_mib": generic_screen["last_size_mib"],
                "refined_99pct_endpoint_mib": None if refined is None else refined["last_size_mib"],
                "reported_99pct_endpoint_mib": selected_endpoint,
                "non_compressible_screen_endpoint_mib": non_screen["last_size_mib"],
                "generic_retained_fraction": {
                    str(size): screen_index[(code, "generic_compressible", size)]["hot_glookups_s"]
                    / generic_screen["best_hot_glookups_s"]
                    for size in SCREEN_SIZES
                },
            }
        )

    require(identical_word_codes == [0, 21, 42, 63], "identical-word classification changed")
    require(endpoint_groups[240] == [0, 63], "240 MiB class mismatch")
    require(endpoint_groups[70] == [21, 42], "refined mid-pattern class mismatch")
    require(endpoint_groups[36] == [code for code in range(64) if code not in (0, 21, 42, 63)], "ordinary class mismatch")
    extended_at_40 = [row["code"] for row in code_rows if row["screen_99pct_endpoint_mib"] >= 40]
    require(extended_at_40 == identical_word_codes, "extension/identical-word equivalence changed")

    refinement_transition = {}
    for code in (21, 42):
        best = max(
            refinement_index[(code, "generic_compressible", size)]["hot_glookups_s"]
            for size in REFINEMENT_SIZES
        )
        refinement_transition[str(code)] = [
            {
                "size_mib": size,
                "hot_glookups_s": refinement_index[(code, "generic_compressible", size)]["hot_glookups_s"],
                "retained_fraction_of_best": refinement_index[(code, "generic_compressible", size)]["hot_glookups_s"] / best,
                "repetition_relative_range": refinement_index[(code, "generic_compressible", size)]["hot_glookups_s_relative_range"],
            }
            for size in (64, 66, 68, 70, 72, 74, 76)
        ]

    period_counts = Counter(row["source_bit_period"] for row in code_rows)
    screen_validation = screen["validation_summary"]
    refinement_validation = refinement["validation_summary"]
    combined = {
        "runs": len(screen["inputs"]) + len(refinement["inputs"]),
        "raw_rows": screen_validation["raw_rows"] + refinement_validation["raw_rows"],
        "validated_payloads": screen_validation["validated_payloads"]
        + refinement_validation["validated_payloads"],
        "timed_gpu_lookups": screen_validation["timed_gpu_lookups"]
        + refinement_validation["timed_gpu_lookups"],
        "invalid_rows": screen_validation["invalid_rows"] + refinement_validation["invalid_rows"],
    }
    require(combined["invalid_rows"] == 0, "combined invalid rows")

    summary = {
        "schema": "UGTS-CUDA-VMM-UNIFORM6-MAP-1.0",
        "source_aggregates": {
            "all_code_screen": args.screen.as_posix(),
            "midpattern_refinement": args.refinement.as_posix(),
        },
        "device": screen["device"],
        "question": (
            "Which of all 64 uniform logical 6-bit values gain throughput-equivalent cache "
            "capacity after sixteen values are densely packed into three u32 words?"
        ),
        "full_rate_definition": {
            "retained_fraction_of_best_generic_hot_rate": FULL_RATE_FRACTION,
            "screen_sizes_mib": SCREEN_SIZES,
            "refinement_sizes_mib": REFINEMENT_SIZES,
        },
        "validation": {
            "all_code_screen": screen_validation,
            "midpattern_refinement": refinement_validation,
            "combined": combined,
        },
        "mathematical_layout": {
            "codes_per_group": 16,
            "bits_per_code": 6,
            "words_per_group": 3,
            "bytes_per_code": 0.75,
            "word_boundary_phase_advance_bits": 32 % 6,
            "source_period_counts": {str(period): count for period, count in sorted(period_counts.items())},
            "identical_packed_word_codes": identical_word_codes,
            "explanation": (
                "A 32-bit boundary advances two positions through the repeated 6-bit motif. "
                "All three words are identical only when the motif is invariant under that "
                "two-bit rotation, giving exactly periods 1 or 2 and codes 0, 21, 42 and 63."
            ),
        },
        "observed_capacity_classes": {
            "240_mib_address_limited": endpoint_groups[240],
            "70_mib_refined_endpoint": endpoint_groups[70],
            "36_mib_no_extension": endpoint_groups[36],
            "codes_full_at_248_mib": [],
            "identical_words_exactly_match_codes_extending_beyond_36_mib": True,
        },
        "midpattern_transition": {
            "balanced_median_last_99pct_size_mib": 70,
            "first_below_99pct_size_mib": 72,
            "direction_sensitive_transition_note": (
                "Forward runs remain near full at 72 MiB while reverse runs slow, so 70 MiB "
                "is the balanced 99%-of-best endpoint, not a counter-derived physical capacity."
            ),
            "codes": refinement_transition,
        },
        "per_code": code_rows,
        "conclusion": (
            "Logical constancy alone does not predict compression. Only the four codes that "
            "pack into identical u32 words extend beyond nominal L2. Uniform zero/all-one words "
            "remain full through 240 MiB before the independent address-reach loss; alternating "
            "0x55555555/0xAAAAAAAA words reach a balanced 70 MiB endpoint; all other three-word "
            "patterns remain at 36 MiB. This is an exact correlation for this layout and GPU, "
            "not proof of an undocumented compressor format."
        ),
        "scope_note": (
            "The map covers uniform logical values through the validated raw global L2 path. "
            "Parameterized uniform texture rows are excluded because nonzero sentinels fail and "
            "the compiler emits the known result-discarding TLD path. No physical compressed-byte, "
            "cache-hit, sector, DRAM-traffic or portable compression-ratio claim is made."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        "uniform6 map: "
        f"rows={combined['raw_rows']} payloads={combined['validated_payloads']} "
        f"timed_lookups={combined['timed_gpu_lookups']} classes="
        f"36:{len(endpoint_groups[36])},70:{len(endpoint_groups[70])},240:{len(endpoint_groups[240])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
