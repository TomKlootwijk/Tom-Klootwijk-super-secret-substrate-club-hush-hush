#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import sys


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a manually downloaded GSP4 asset")
    parser.add_argument("path", type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--bytes", type=int, default=None)
    args = parser.parse_args()
    if not args.path.is_file():
        print(f"missing file: {args.path}", file=sys.stderr)
        return 2
    size = args.path.stat().st_size
    if args.bytes is not None and size != args.bytes:
        print(f"size mismatch: expected {args.bytes}, got {size}", file=sys.stderr)
        return 3
    actual = sha256_file(args.path)
    expected = args.sha256.strip().lower()
    print(f"path:   {args.path}")
    print(f"bytes:  {size}")
    print(f"sha256: {actual}")
    if actual != expected:
        print(f"SHA-256 mismatch; expected {expected}", file=sys.stderr)
        return 4
    print("valid:  true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
