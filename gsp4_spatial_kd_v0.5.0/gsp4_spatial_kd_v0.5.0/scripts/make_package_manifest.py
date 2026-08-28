#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Iterable

EXCLUDED_NAMES = {"PACKAGE_MANIFEST.json", "PACKAGE_MANIFEST.json.sha256"}
EXCLUDED_PARTS = {".git", ".pytest_cache", "__pycache__", "build", ".venv"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def included_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if path.name in EXCLUDED_NAMES:
            continue
        if any(part in EXCLUDED_PARTS for part in rel.parts):
            continue
        if path.suffix in EXCLUDED_SUFFIXES:
            continue
        yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the GSP4 package SHA-256 manifest")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    parser.add_argument("--output", default="PACKAGE_MANIFEST.json", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    rows = []
    total_bytes = 0
    for path in included_files(root):
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        total_bytes += size
        rows.append({"path": rel, "bytes": size, "sha256": sha256_file(path)})
    manifest = {
        "format": "GSP4-PACKAGE-MANIFEST-1",
        "version": "0.5.0",
        "file_count": len(rows),
        "total_member_bytes": total_bytes,
        "coverage": "all distributed regular files except this manifest and its detached SHA-256 file",
        "files": rows,
    }
    output = args.output if args.output.is_absolute() else root / args.output
    payload = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    output.write_bytes(payload)
    signature = output.with_name(output.name + ".sha256")
    signature.write_text(f"{hashlib.sha256(payload).hexdigest()}  {output.name}\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "files": len(rows), "bytes": total_bytes}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
