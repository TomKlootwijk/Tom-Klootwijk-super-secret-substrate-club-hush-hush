#!/usr/bin/env python3
"""Prevent incomplete 19x19 runs from being mislabeled as solved."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_go19.digests import state_digest
from ugts_go19.rules import Rules
from ugts_go19.state import State


CANONICAL_RULES: dict[str, Any] = {
    "allow_suicide": False,
    "komi2": 15,
    "passes_to_end": 2,
    "profile_id": "UGTS-GO19-AREA-PSK-K7.5-v1",
    "scoring": "area",
    "size": 19,
    "superko": "positional_superko",
}
CANONICAL_ROOT_DIGEST = (
    "62eed2c148b6baefbd0312aa940a447a5c3aaa6ff524d18508a0628079ddc92e"
)
CANONICAL_THRESHOLD2 = 1


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_unknown_preflight(payload: Any) -> None:
    """Reject any bounded preflight outside the pinned canonical proposition."""
    if not isinstance(payload, dict):
        raise ValueError("result envelope must be a JSON object")

    runtime_rules = Rules.canonical_19x19()
    runtime_rules_payload = runtime_rules.as_dict()
    if runtime_rules_payload != CANONICAL_RULES:
        raise ValueError("runtime canonical rules differ from the pinned claim gate")
    runtime_root_digest = state_digest(State.initial(runtime_rules), runtime_rules)
    if runtime_root_digest != CANONICAL_ROOT_DIGEST:
        raise ValueError(
            "runtime canonical root digest differs from the pinned claim gate: "
            f"{runtime_root_digest!r}"
        )

    if payload.get("rules") != CANONICAL_RULES:
        raise ValueError("preflight rules do not match the canonical 19x19 profile")
    if payload.get("root_digest") != CANONICAL_ROOT_DIGEST:
        raise ValueError("preflight root digest does not match the canonical empty root")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise ValueError("preflight result must be a JSON object")
    if result.get("status") != "UNKNOWN":
        raise ValueError(
            f"expected UNKNOWN preflight, received {result.get('status')!r}"
        )
    threshold2 = result.get("threshold2")
    if (
        not isinstance(threshold2, int)
        or isinstance(threshold2, bool)
        or threshold2 != CANONICAL_THRESHOLD2
    ):
        raise ValueError(
            f"expected canonical threshold2={CANONICAL_THRESHOLD2}, "
            f"received {threshold2!r}"
        )
    if not _positive_int(result.get("proof_number")):
        raise ValueError("UNKNOWN preflight requires a positive proof_number")
    if not _positive_int(result.get("disproof_number")):
        raise ValueError("UNKNOWN preflight requires a positive disproof_number")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-unknown", action="store_true")
    parser.add_argument("result")
    args = parser.parse_args()
    payload = json.loads(Path(args.result).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("claim gate: result envelope must be a JSON object")
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        raise SystemExit("claim gate: result must be a JSON object")
    status = result.get("status")
    if args.expect_unknown:
        try:
            validate_unknown_preflight(payload)
        except ValueError as exc:
            raise SystemExit(f"claim gate: {exc}") from exc
        print(
            "claim gate: canonical bounded attempt correctly remains UNKNOWN "
            "with both proof numbers positive"
        )
        return 0

    if status not in {"PROVEN", "DISPROVEN"}:
        raise SystemExit("claim gate: no solved claim; root status is not final")
    certificate = payload.get("full_certificate")
    independent = payload.get("independent_verification")
    if not certificate or not independent:
        raise SystemExit(
            "claim gate: final proof number is insufficient without full certificate "
            "and independent verification"
        )
    raise SystemExit(
        "claim gate: standalone 19x19 certificate verifier is not implemented in 4.3; "
        "do not publish a solved claim"
    )


if __name__ == "__main__":
    raise SystemExit(main())
