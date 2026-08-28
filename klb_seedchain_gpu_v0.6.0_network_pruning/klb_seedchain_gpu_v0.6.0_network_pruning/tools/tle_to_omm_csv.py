#!/usr/bin/env python3
"""Convert 3-line TLE text to the OMM-keyword CSV accepted by klb_sgp4.

This adapter deliberately preserves the TLE's SGP4 mean elements. It does not
create a new orbit determination or claim better physical accuracy than the
source element set.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

HEADER = [
    "OBJECT_NAME", "OBJECT_ID", "EPOCH", "MEAN_MOTION", "ECCENTRICITY",
    "INCLINATION", "RA_OF_ASC_NODE", "ARG_OF_PERICENTER", "MEAN_ANOMALY",
    "EPHEMERIS_TYPE", "CLASSIFICATION_TYPE", "NORAD_CAT_ID", "ELEMENT_SET_NO",
    "REV_AT_EPOCH", "BSTAR", "MEAN_MOTION_DOT", "MEAN_MOTION_DDOT",
]


def tle_implied(field: str) -> float:
    """Parse an implied-decimal TLE mantissa/exponent field."""
    text = field.strip().replace(" ", "")
    if not text:
        return 0.0
    match = re.fullmatch(r"([+-]?)(\d+)([+-]\d+)", text)
    if not match:
        raise ValueError(f"invalid implied-decimal TLE field: {field!r}")
    sign = -1.0 if match.group(1) == "-" else 1.0
    mantissa = float(f"0.{match.group(2)}")
    return sign * mantissa * (10.0 ** int(match.group(3)))


def full_year(two_digit: int) -> int:
    return 1900 + two_digit if two_digit >= 57 else 2000 + two_digit


def epoch_iso(two_digit_year: int, day_of_year: float) -> str:
    year = full_year(two_digit_year)
    whole = int(day_of_year)
    fraction = day_of_year - whole
    instant = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(
        days=whole - 1, seconds=fraction * 86400.0
    )
    return instant.strftime("%Y-%m-%dT%H:%M:%S.%f")


def object_id(field: str) -> str:
    token = field.strip()
    if not token:
        return ""
    yy = int(token[:2])
    launch = token[2:5]
    piece = token[5:].strip()
    return f"{full_year(yy):04d}-{launch}{piece}"


def parse_three_line(path: Path) -> list[dict[str, object]]:
    lines = [line.rstrip("\r\n") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) % 3 != 0:
        raise ValueError(f"expected 3-line element groups, got {len(lines)} non-empty lines")
    rows: list[dict[str, object]] = []
    for offset in range(0, len(lines), 3):
        name, line1, line2 = lines[offset:offset + 3]
        if not line1.startswith("1 ") or not line2.startswith("2 "):
            raise ValueError(f"invalid TLE group at source line {offset + 1}")
        if line1[2:7].strip() != line2[2:7].strip():
            raise ValueError(f"catalog mismatch at source line {offset + 1}")
        epoch_year = int(line1[18:20])
        epoch_day = float(line1[20:32])
        rows.append({
            "OBJECT_NAME": name.strip(),
            "OBJECT_ID": object_id(line1[9:17]),
            "EPOCH": epoch_iso(epoch_year, epoch_day),
            "MEAN_MOTION": float(line2[52:63]),
            "ECCENTRICITY": float(f"0.{line2[26:33].strip()}"),
            "INCLINATION": float(line2[8:16]),
            "RA_OF_ASC_NODE": float(line2[17:25]),
            "ARG_OF_PERICENTER": float(line2[34:42]),
            "MEAN_ANOMALY": float(line2[43:51]),
            "EPHEMERIS_TYPE": int(line1[62:63] or 0),
            "CLASSIFICATION_TYPE": line1[7:8] or "U",
            "NORAD_CAT_ID": int(line1[2:7]),
            "ELEMENT_SET_NO": int(line1[64:68]),
            "REV_AT_EPOCH": int(line2[63:68]),
            "BSTAR": tle_implied(line1[53:61]),
            "MEAN_MOTION_DOT": float(line1[33:43]),
            "MEAN_MOTION_DDOT": tle_implied(line1[44:52]),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = parse_three_line(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"converted {len(rows)} TLE records -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
