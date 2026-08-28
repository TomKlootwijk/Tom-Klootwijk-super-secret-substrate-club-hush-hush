#!/usr/bin/env python3
"""Create a frames.txt file for klb_seedchain fit-sequence from a glob."""

from __future__ import annotations

import argparse
import os
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="directory containing PLY frames")
    parser.add_argument("output", type=Path, help="frames.txt destination")
    parser.add_argument("--pattern", default="*.ply", help="glob pattern (default: *.ply)")
    parser.add_argument(
        "--absolute",
        action="store_true",
        help="write absolute paths instead of paths relative to frames.txt",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    files = sorted(path for path in args.directory.glob(args.pattern) if path.is_file())
    if not files:
        raise FileNotFoundError(f"no files matched {args.directory / args.pattern}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    base = args.output.parent.resolve()
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write("# Stable vertex order and identical vertex counts are required.\n")
        for path in files:
            resolved = path.resolve()
            text = str(resolved) if args.absolute else os.path.relpath(resolved, base)
            stream.write(text.replace("\\", "/") + "\n")
    print(f"Wrote {len(files)} frame paths to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
