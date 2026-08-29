#!/usr/bin/env python3
"""Black-box contract tests for the bounded native PNDAG CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


EXPECTED_KEYS = {
    "algorithm",
    "claim_boundary",
    "committed_expansions",
    "disproof_number",
    "edge_count",
    "expanded_this_call",
    "format",
    "graph_sha256",
    "node_count",
    "proof_arithmetic",
    "proof_number",
    "requested_expansions",
    "root_state",
    "root_state_object_id",
    "rules",
    "status",
    "threshold2",
}
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


def invoke(cli: Path, arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(cli), *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def successful_payload(cli: Path, budget: int) -> tuple[str, dict[str, object]]:
    process = invoke(cli, ["19", "15", "1", str(budget)])
    if process.returncode != 0:
        raise AssertionError(
            f"CLI failed with {process.returncode}: {process.stderr!r}"
        )
    if process.stderr:
        raise AssertionError(f"successful CLI wrote stderr: {process.stderr!r}")
    try:
        payload = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        raise AssertionError(f"CLI did not emit JSON: {process.stdout!r}") from error
    if not isinstance(payload, dict) or set(payload) != EXPECTED_KEYS:
        raise AssertionError("CLI result has a noncanonical top-level shape")
    canonical = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    )
    if process.stdout != canonical:
        raise AssertionError("CLI result is not one canonical JSON line")
    return process.stdout, payload


def validate_common(payload: dict[str, object], budget: int) -> None:
    rules = {
        "allow_suicide": False,
        "komi2": 15,
        "passes_to_end": 2,
        "scoring": "area",
        "size": 19,
        "superko": "positional_superko",
    }
    empty_board = "00" * 361
    root_state = {
        "board_hex": empty_board,
        "format": "UGTS-GO-STATE-v1",
        "passes": 0,
        "previous_board_hex": None,
        "rules": rules,
        "seen_hex": [empty_board],
        "to_play": 1,
    }
    if payload["algorithm"] != "exact-pndag-bounded-v1":
        raise AssertionError("unexpected algorithm identifier")
    if payload["claim_boundary"] != {
        "certificate": False,
        "expansion_budget_stop_status": "UNKNOWN",
        "scope": "host-memory-exact-bounded-attempt",
    }:
        raise AssertionError("native result lost its bounded non-certificate boundary")
    if payload["format"] != "UGTS-CPP-PNDAG-RESULT-v1":
        raise AssertionError("unexpected result format")
    if payload["rules"] != rules or payload["root_state"] != root_state:
        raise AssertionError("rules or exact root identity changed")
    root_bytes = json.dumps(
        root_state, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    if payload["root_state_object_id"] != hashlib.sha256(root_bytes).hexdigest():
        raise AssertionError("root object ID does not hash the exact root bytes")
    if payload["proof_arithmetic"] != {
        "bits": 64,
        "endianness": "little",
        "infinity": str((1 << 64) - 1),
        "kind": "saturating_uint64",
    }:
        raise AssertionError("proof arithmetic declaration changed")
    if payload["threshold2"] != 1 or payload["requested_expansions"] != budget:
        raise AssertionError("CLI request envelope changed")
    if (
        not isinstance(payload["graph_sha256"], str)
        or SHA256_RE.fullmatch(payload["graph_sha256"]) is None
    ):
        raise AssertionError("graph SHA-256 is malformed")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, type=Path)
    args = parser.parse_args()

    zero_text, zero = successful_payload(args.cli, 0)
    validate_common(zero, 0)
    if (
        zero["status"],
        zero["proof_number"],
        zero["disproof_number"],
        zero["expanded_this_call"],
        zero["committed_expansions"],
        zero["node_count"],
        zero["edge_count"],
    ) != ("UNKNOWN", 1, 1, 0, 0, 1, 0):
        raise AssertionError("zero-budget 19x19 result is not the exact open root")

    one_text, one = successful_payload(args.cli, 1)
    validate_common(one, 1)
    if (
        one["status"],
        one["proof_number"],
        one["disproof_number"],
        one["expanded_this_call"],
        one["committed_expansions"],
        one["node_count"],
        one["edge_count"],
    ) != ("UNKNOWN", 1, 362, 1, 1, 363, 362):
        raise AssertionError("one-expansion 19x19 result is not exactly UNKNOWN")
    repeated_text, repeated = successful_payload(args.cli, 1)
    if repeated_text != one_text or repeated != one:
        raise AssertionError("identical CLI runs are nondeterministic")
    if zero_text == one_text or zero["graph_sha256"] == one["graph_sha256"]:
        raise AssertionError("committed expansion did not change graph evidence")

    invalid_cases = [
        [],
        ["0", "15", "1", "0"],
        ["20", "15", "1", "0"],
        ["19", "2147483648", "1", "0"],
        ["19", "15", "9223372036854775808", "0"],
        ["19", "15", "1", "-1"],
        ["19", "15", "1", "18446744073709551616"],
        ["19x", "15", "1", "0"],
        ["019", "15", "1", "0"],
        ["19", "15", "-0", "0"],
        ["19", "15", "1", "00"],
    ]
    for arguments in invalid_cases:
        process = invoke(args.cli, arguments)
        if process.returncode == 0 or process.stdout:
            raise AssertionError(f"invalid arguments were accepted: {arguments!r}")
        if not process.stderr:
            raise AssertionError(
                f"invalid arguments lacked a diagnostic: {arguments!r}"
            )

    help_result = invoke(args.cli, ["--help"])
    if help_result.returncode != 0 or "Usage:" not in help_result.stdout:
        raise AssertionError("CLI help contract failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
