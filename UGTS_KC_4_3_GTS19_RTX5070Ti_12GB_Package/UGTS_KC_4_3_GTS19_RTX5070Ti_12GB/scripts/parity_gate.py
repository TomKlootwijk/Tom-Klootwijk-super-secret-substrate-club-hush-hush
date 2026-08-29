#!/usr/bin/env python3
"""Validate archived M1 Python/C++ exact-parity evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


EVIDENCE_FORMAT = "UGTS-M1-PARITY-EVIDENCE-v2"
PROTOCOL = "UGTS_TRACE_V2"
MODE = "campaign"
ROOT_STATUS = "UNKNOWN"
GENERATOR = "splitmix64-v1-shallow-reachable-psk"
HASH_ROLE = (
    "SHA-256 object IDs and corpus hash are evidence/content addresses only; "
    "exact raw fields establish equality"
)
STATE_OBJECT_ID = "sha256(utf8(UGTS-GO-STATE-v1 canonical JSON))"
EXPECTED_SEEDS = (0x5EED19, 0xC0FFEE)
MINIMUM_TARGET_TRANSITIONS = 1_000_000
REQUIRED_BOARD_SIZES = frozenset({"1", "3", "5", "9", "19"})
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

EXPECTED_KEYS = frozenset(
    {
        "cases_by_size",
        "chunk_size",
        "chunks",
        "comparisons",
        "corpus_sha256",
        "elapsed_seconds",
        "evidence_format",
        "field_comparisons",
        "generator",
        "hash_role",
        "max_seen_boards",
        "mismatches",
        "mode",
        "protocol",
        "root_status",
        "seeds",
        "state_object_id",
        "states",
        "target_met",
        "target_transitions",
        "transitions",
        "transitions_per_second",
    }
)

POSITIVE_INTEGER_FIELDS = (
    "chunk_size",
    "chunks",
    "comparisons",
    "field_comparisons",
    "max_seen_boards",
    "states",
    "target_transitions",
    "transitions",
)


def _require_exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    raise ValueError(f"{label} keys are noncanonical: missing={missing}, extra={extra}")


def _require_positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _require_positive_number(value: Any, label: str) -> int | float:
    if type(value) is int:
        valid = value > 0
    elif type(value) is float:
        valid = math.isfinite(value) and value > 0
    else:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be a finite positive number")
    return value


def validate_parity_evidence(payload: Any) -> None:
    """Fail closed unless *payload* is the pinned, successful M1 campaign shape."""
    if type(payload) is not dict:
        raise ValueError("evidence must be a JSON object")
    _require_exact_keys(payload, EXPECTED_KEYS, "evidence")

    pinned_fields = {
        "evidence_format": EVIDENCE_FORMAT,
        "generator": GENERATOR,
        "hash_role": HASH_ROLE,
        "mode": MODE,
        "protocol": PROTOCOL,
        "root_status": ROOT_STATUS,
        "state_object_id": STATE_OBJECT_ID,
    }
    for field, expected in pinned_fields.items():
        if payload[field] != expected:
            raise ValueError(f"{field} is not the pinned M1 value")

    seeds = payload["seeds"]
    if type(seeds) is not list or any(type(seed) is not int for seed in seeds):
        raise ValueError("seeds must be the pinned integer list")
    if seeds != list(EXPECTED_SEEDS):
        raise ValueError("seeds do not match the pinned deterministic corpus")

    cases_by_size = payload["cases_by_size"]
    if type(cases_by_size) is not dict:
        raise ValueError("cases_by_size must be a JSON object")
    _require_exact_keys(cases_by_size, REQUIRED_BOARD_SIZES, "cases_by_size")
    for size in sorted(REQUIRED_BOARD_SIZES, key=int):
        _require_positive_int(cases_by_size[size], f"cases_by_size[{size!r}]")

    counts = {
        field: _require_positive_int(payload[field], field)
        for field in POSITIVE_INTEGER_FIELDS
    }
    _require_positive_number(payload["elapsed_seconds"], "elapsed_seconds")
    _require_positive_number(
        payload["transitions_per_second"], "transitions_per_second"
    )

    mismatches = payload["mismatches"]
    if type(mismatches) is not int or mismatches != 0:
        raise ValueError("mismatches must be the integer zero")
    if payload["target_met"] is not True:
        raise ValueError("target_met must be the boolean true")

    target = counts["target_transitions"]
    transitions = counts["transitions"]
    states = counts["states"]
    if target < MINIMUM_TARGET_TRANSITIONS:
        raise ValueError(
            f"target_transitions must be at least {MINIMUM_TARGET_TRANSITIONS}"
        )
    if transitions < target:
        raise ValueError("transitions do not meet target_transitions")
    if counts["comparisons"] != states + transitions:
        raise ValueError("comparisons must equal states + transitions")
    if counts["field_comparisons"] != states * 6 + transitions * 13:
        raise ValueError(
            "field_comparisons must account for every v2 canonical/raw field"
        )
    if sum(cases_by_size.values()) != states:
        raise ValueError("cases_by_size counts must sum to states")

    corpus_sha256 = payload["corpus_sha256"]
    if type(corpus_sha256) is not str or SHA256_RE.fullmatch(corpus_sha256) is None:
        raise ValueError("corpus_sha256 must be a canonical lowercase SHA-256")


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def load_parity_evidence(path: str | Path) -> Any:
    return json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_object_without_duplicate_keys,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate archived M1 Python/C++ parity evidence."
    )
    parser.add_argument("evidence", type=Path)
    args = parser.parse_args()

    try:
        payload = load_parity_evidence(args.evidence)
        validate_parity_evidence(payload)
    except (OSError, UnicodeError, ValueError) as exc:
        raise SystemExit(f"parity gate: {exc}") from exc

    print(
        "parity gate: accepted archived M1 v2 canonical-byte/object-ID parity evidence; "
        "root status remains UNKNOWN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
