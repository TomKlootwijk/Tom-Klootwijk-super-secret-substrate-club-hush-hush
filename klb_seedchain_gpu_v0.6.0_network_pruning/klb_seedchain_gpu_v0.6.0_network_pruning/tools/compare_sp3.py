#!/usr/bin/env python3
"""Compare KSGP/SGP4 PEF samples with an external SP3 precise-orbit product.

The reported difference includes orbit-model error, element age, the package's
GMST+DUT1 TEME-to-PEF approximation, SP3 terrestrial-frame realization, and
any omitted Earth-orientation effects. It is intentionally a real-world error
challenge rather than an implementation-consistency test.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
import math
from pathlib import Path
import struct
import subprocess
import tempfile


def open_text(path: Path):
    if path.suffix.lower() == ".gz":
        return gzip.open(path, "rt", encoding="ascii", errors="replace")
    return path.open("r", encoding="ascii", errors="replace")


def parse_sp3(path: Path) -> dict[datetime, dict[str, tuple[float, float, float]]]:
    epochs: dict[datetime, dict[str, tuple[float, float, float]]] = {}
    current: datetime | None = None
    with open_text(path) as handle:
        for line in handle:
            if line.startswith("*"):
                fields = line[1:].split()
                if len(fields) < 6:
                    continue
                year, month, day, hour, minute = map(int, fields[:5])
                seconds = float(fields[5])
                whole = int(seconds)
                micro = int(round((seconds - whole) * 1_000_000.0))
                current = datetime(year, month, day, hour, minute, whole,
                                   microsecond=micro, tzinfo=timezone.utc)
                epochs.setdefault(current, {})
            elif current is not None and line.startswith("P") and len(line) >= 46:
                satellite = line[1:4].strip().upper()
                if not satellite.startswith("G"):
                    continue
                try:
                    x = float(line[4:18])
                    y = float(line[18:32])
                    z = float(line[32:46])
                except ValueError:
                    continue
                if any(abs(value) >= 999999.0 for value in (x, y, z)):
                    continue
                epochs[current][satellite] = (x, y, z)
    return {epoch: values for epoch, values in epochs.items() if values}


def ksgp_reference_unix(path: Path) -> float:
    with path.open("rb") as handle:
        header = handle.read(256)
    if len(header) != 256 or header[:7] != b"KSGP1\0\0":
        raise ValueError("not a KSGP1 container")
    microseconds = struct.unpack_from("<q", header, 112)[0]
    return microseconds / 1_000_000.0


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    index = max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sp3", type=Path, required=True)
    parser.add_argument("--ksgp", type=Path, required=True)
    parser.add_argument("--klb-sgp4", type=Path, required=True,
                        help="path to klb_sgp4 or klb_sgp4.exe")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--max-epochs", type=int, default=96)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--dut1-seconds", type=float, default=0.0)
    args = parser.parse_args()
    if args.max_epochs <= 0 or args.stride <= 0:
        raise SystemExit("max-epochs and stride must be positive")
    epochs = sorted(parse_sp3(args.sp3).items())[::args.stride][:args.max_epochs]
    if not epochs:
        raise SystemExit("SP3 file contained no GPS position epochs")
    reference_unix = ksgp_reference_unix(args.ksgp)
    rows: list[dict[str, object]] = []
    errors: list[float] = []
    with tempfile.TemporaryDirectory(prefix="klb_sp3_") as temp:
        sample_path = Path(temp) / "sample.csv"
        for epoch, precise in epochs:
            seconds = epoch.timestamp() - reference_unix
            command = [
                str(args.klb_sgp4), "sample", str(args.ksgp),
                "--seconds", f"{seconds:.9f}",
                "--dut1-seconds", f"{args.dut1_seconds:.9f}",
                "--output", str(sample_path),
            ]
            completed = subprocess.run(command, text=True, capture_output=True)
            if completed.returncode != 0:
                raise SystemExit(
                    f"klb_sgp4 sample failed at {epoch.isoformat()}:\n"
                    f"{completed.stdout}\n{completed.stderr}")
            with sample_path.open(newline="", encoding="utf-8") as handle:
                for sample in csv.DictReader(handle):
                    prn = int(sample["prn"])
                    if prn <= 0:
                        continue
                    key = f"G{prn:02d}"
                    if key not in precise or int(sample["sgp4_error"]) != 0:
                        continue
                    predicted = tuple(float(sample[field]) for field in
                                      ("x_pef_km", "y_pef_km", "z_pef_km"))
                    target = precise[key]
                    delta = tuple(predicted[i] - target[i] for i in range(3))
                    error = math.sqrt(sum(value * value for value in delta))
                    errors.append(error)
                    rows.append({
                        "epoch_utc": epoch.isoformat().replace("+00:00", "Z"),
                        "gps_id": key,
                        "norad_id": sample["norad_id"],
                        "name": sample["name"],
                        "dx_km": delta[0], "dy_km": delta[1], "dz_km": delta[2],
                        "position_error_km": error,
                    })
    if not rows:
        raise SystemExit("no GPS PRNs overlapped between KSGP and SP3")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
    rms = math.sqrt(sum(value * value for value in errors) / len(errors))
    lines = [
        "KSGP full-SGP4 versus external SP3 comparison",
        f"samples: {len(errors)}",
        f"epochs: {len(epochs)}",
        f"RMS position difference: {rms:.9f} km",
        f"median position difference: {percentile(errors, 0.5):.9f} km",
        f"p95 position difference: {percentile(errors, 0.95):.9f} km",
        f"maximum position difference: {max(errors):.9f} km",
        "Interpretation: combined model/element-age/frame/EOP difference; not pure SGP4 arithmetic error.",
    ]
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
