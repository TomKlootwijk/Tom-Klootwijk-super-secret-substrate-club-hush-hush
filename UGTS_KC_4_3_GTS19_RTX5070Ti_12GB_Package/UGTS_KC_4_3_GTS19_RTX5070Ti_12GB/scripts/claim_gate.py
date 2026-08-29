#!/usr/bin/env python3
"""Prevent incomplete 19x19 runs from being mislabeled as solved."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-unknown", action="store_true")
    parser.add_argument("result")
    args = parser.parse_args()
    payload = json.loads(Path(args.result).read_text(encoding="utf-8"))
    result = payload.get("result", payload)
    status = result.get("status")
    if args.expect_unknown:
        if status != "UNKNOWN":
            raise SystemExit(f"expected UNKNOWN preflight, received {status!r}")
        print("claim gate: bounded attempt correctly remains UNKNOWN")
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
