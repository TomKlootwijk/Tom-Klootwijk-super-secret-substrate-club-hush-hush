#!/usr/bin/env python3
"""Check release structure, JSON evidence, and internal manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    parser.add_argument(
        "--attempt",
        type=Path,
        help="bounded-attempt JSON to validate; relative paths resolve from the repository root",
    )
    args = parser.parse_args()

    required = [
        "README.md",
        "docs/FORMAL_SPEC.md",
        "docs/EXACTNESS_CONTRACT.md",
        "configs/go19_canonical.toml",
        "src/ugts_go19/engine.py",
        "cpp/src/go_state.cpp",
        "codex/AGENTS.md",
    ]
    missing = [item for item in required if not (ROOT / item).is_file()]
    if missing:
        raise SystemExit(f"missing release files: {missing}")

    attempt_path = args.attempt
    if attempt_path is not None and not attempt_path.is_absolute():
        attempt_path = ROOT / attempt_path
    if attempt_path is None:
        acceptance_attempt = ROOT / "evidence" / "acceptance_19x19_bounded.json"
        legacy_attempt = ROOT / "evidence" / "attempt19_bounded.json"
        if acceptance_attempt.exists():
            attempt_path = acceptance_attempt
        elif legacy_attempt.exists():
            attempt_path = legacy_attempt

    attempt_status = None
    if args.attempt is not None and (attempt_path is None or not attempt_path.is_file()):
        raise SystemExit(f"attempt file missing: {args.attempt}")
    if attempt_path is not None and attempt_path.exists():
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        if not isinstance(attempt, dict) or not isinstance(attempt.get("result"), dict):
            raise SystemExit(f"invalid attempt envelope: {attempt_path}")
        attempt_status = attempt["result"].get("status")
        if attempt_status not in {"PROVEN", "DISPROVEN", "UNKNOWN"}:
            raise SystemExit(f"invalid attempt status: {attempt_status}")

    manifest_path = ROOT / "SHA256SUMS.txt"
    if manifest_path.exists() and not args.quick:
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            expected, relative = line.split("  ", 1)
            path = ROOT / relative
            if not path.is_file():
                raise SystemExit(f"manifest file missing: {relative}")
            if sha256(path) != expected:
                raise SystemExit(f"manifest mismatch: {relative}")
    print(
        json.dumps(
            {
                "ok": True,
                "quick": args.quick,
                "root": str(ROOT),
                "attempt": str(attempt_path) if attempt_path is not None else None,
                "attempt_status": attempt_status,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
