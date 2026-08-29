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

    attempt_path = ROOT / "evidence" / "attempt19_bounded.json"
    if attempt_path.exists():
        attempt = json.loads(attempt_path.read_text(encoding="utf-8"))
        status = attempt["result"]["status"]
        if status not in {"PROVEN", "DISPROVEN", "UNKNOWN"}:
            raise SystemExit(f"invalid attempt status: {status}")

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
    print(json.dumps({"ok": True, "quick": args.quick, "root": str(ROOT)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
