#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the GSP4 package manifest")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument("--manifest", default="PACKAGE_MANIFEST.json")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = root / args.manifest
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    checked_bytes = 0
    for row in manifest.get("files", []):
        rel = str(row["path"])
        path = root / rel
        if not path.is_file():
            failures.append(f"missing: {rel}")
            continue
        actual_bytes = path.stat().st_size
        checked_bytes += actual_bytes
        if actual_bytes != int(row["bytes"]):
            failures.append(f"size mismatch: {rel}: expected {row['bytes']}, got {actual_bytes}")
            continue
        actual_hash = sha256_file(path)
        if actual_hash != row["sha256"]:
            failures.append(f"SHA-256 mismatch: {rel}")
    result = {
        "format": manifest.get("format"),
        "valid": not failures,
        "checked_files": len(manifest.get("files", [])),
        "checked_bytes": checked_bytes,
        "failures": failures,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
