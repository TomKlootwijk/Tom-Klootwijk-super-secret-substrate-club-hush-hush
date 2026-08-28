#!/usr/bin/env python3
"""Compare KLB TEME samples with the independent python-sgp4 package."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

from sgp4.api import Satrec, WGS72
from sgp4 import __version__ as sgp4_version
from sgp4.omm import initialize


def load_satellites(path: Path) -> dict[int, Satrec]:
    satellites: dict[int, Satrec] = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for fields in csv.DictReader(stream):
            satellite = Satrec()
            initialize(satellite, fields, WGS72)
            satellites[int(fields["NORAD_CAT_ID"])] = satellite
    return satellites


def norm_delta(actual: tuple[float, float, float], expected: tuple[float, float, float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(actual, expected)))


def compare_dataset(
    label: str,
    source_csv: Path,
    sample_glob: str,
    root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    satellites = load_satellites(source_csv)
    details: list[dict[str, object]] = []
    error_mismatches = 0
    sum_position_sq = 0.0
    sum_velocity_sq = 0.0
    max_position = 0.0
    max_velocity = 0.0

    sample_paths = sorted(root.glob(sample_glob))
    if not sample_paths:
        raise RuntimeError(f"no sample files matched {sample_glob}")

    for sample_path in sample_paths:
        with sample_path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                norad_id = int(row["norad_id"])
                satellite = satellites.get(norad_id)
                if satellite is None:
                    raise RuntimeError(f"NORAD {norad_id} missing from {source_csv}")
                minutes = float(row["minutes_from_element_epoch"])
                error, position, velocity = satellite.sgp4_tsince(minutes)
                klb_error = int(row["sgp4_error"])
                if error != klb_error:
                    error_mismatches += 1
                klb_position = tuple(float(row[name]) for name in ("x_teme_km", "y_teme_km", "z_teme_km"))
                klb_velocity = tuple(float(row[name]) for name in ("vx_teme_km_s", "vy_teme_km_s", "vz_teme_km_s"))
                position_delta = norm_delta(position, klb_position)
                velocity_delta = norm_delta(velocity, klb_velocity)
                sum_position_sq += position_delta * position_delta
                sum_velocity_sq += velocity_delta * velocity_delta
                max_position = max(max_position, position_delta)
                max_velocity = max(max_velocity, velocity_delta)
                details.append(
                    {
                        "dataset": label,
                        "sample_file": sample_path.name,
                        "norad_id": norad_id,
                        "seconds_from_reference": float(row["seconds_from_reference"]),
                        "minutes_from_element_epoch": minutes,
                        "klb_error": klb_error,
                        "python_sgp4_error": error,
                        "position_delta_km": position_delta,
                        "velocity_delta_km_s": velocity_delta,
                    }
                )

    count = len(details)
    summary = {
        "dataset": label,
        "states": count,
        "sample_files": len(sample_paths),
        "error_mismatches": error_mismatches,
        "rms_position_delta_km": math.sqrt(sum_position_sq / count),
        "max_position_delta_km": max_position,
        "rms_velocity_delta_km_s": math.sqrt(sum_velocity_sq / count),
        "max_velocity_delta_km_s": max_velocity,
    }
    return details, summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--details", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    all_details: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    datasets = (
        (
            "gps_operational",
            root / "data" / "orbit" / "source" / "gps_ops_2026-08-16_omm.csv",
            "verification_independent_samples/gps_*.csv",
        ),
        (
            "vallado_all_branches",
            root / "data" / "sgp4" / "source" / "vallado_branch_vectors_omm.csv",
            "verification_independent_samples/branches_*.csv",
        ),
    )
    for label, source_csv, sample_glob in datasets:
        details, summary = compare_dataset(label, source_csv, sample_glob, root)
        all_details.extend(details)
        summaries.append(summary)

    args.details.parent.mkdir(parents=True, exist_ok=True)
    with args.details.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_details[0]))
        writer.writeheader()
        writer.writerows(all_details)

    overall_count = len(all_details)
    overall = {
        "python_sgp4_version": sgp4_version,
        "gravity_model": "WGS72",
        "datasets": summaries,
        "overall": {
            "states": overall_count,
            "error_mismatches": sum(int(item["error_mismatches"]) for item in summaries),
            "rms_position_delta_km": math.sqrt(
                sum(float(row["position_delta_km"]) ** 2 for row in all_details) / overall_count
            ),
            "max_position_delta_km": max(float(row["position_delta_km"]) for row in all_details),
            "rms_velocity_delta_km_s": math.sqrt(
                sum(float(row["velocity_delta_km_s"]) ** 2 for row in all_details) / overall_count
            ),
            "max_velocity_delta_km_s": max(float(row["velocity_delta_km_s"]) for row in all_details),
        },
    }
    args.summary.write_text(json.dumps(overall, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(overall, indent=2))

    # This cross-implementation check includes records propagated years away from
    # their element epochs. Require sub-millimetre position agreement and a
    # velocity delta five times tighter than the package's 0.01 mm/s GPU gate.
    if overall["overall"]["error_mismatches"] != 0:
        return 1
    if overall["overall"]["max_position_delta_km"] > 1.0e-6:
        return 1
    if overall["overall"]["max_velocity_delta_km_s"] > 2.0e-9:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
