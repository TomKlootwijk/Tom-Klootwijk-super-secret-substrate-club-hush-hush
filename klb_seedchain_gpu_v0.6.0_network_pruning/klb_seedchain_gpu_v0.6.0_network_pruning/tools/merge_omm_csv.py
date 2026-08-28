#!/usr/bin/env python3
"""Merge OMM-keyword CSV snapshots while rejecting duplicate NORAD IDs."""
from __future__ import annotations
import argparse
import csv
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args()
    header: list[str] | None = None
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for path in args.inputs:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise SystemExit(f"missing CSV header: {path}")
            if header is None:
                header = reader.fieldnames
            elif reader.fieldnames != header:
                raise SystemExit(f"OMM header mismatch: {path}")
            for row in reader:
                catalog = row.get("NORAD_CAT_ID", "").strip()
                if not catalog:
                    raise SystemExit(f"missing NORAD_CAT_ID in {path}")
                if catalog in seen:
                    raise SystemExit(f"duplicate NORAD_CAT_ID {catalog}")
                seen.add(catalog)
                rows.append(row)
    assert header is not None
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"merged {len(rows)} unique OMM records -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
