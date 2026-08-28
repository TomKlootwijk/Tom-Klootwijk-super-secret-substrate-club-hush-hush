#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re
import statistics


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return math.nan
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def numeric_summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "rms": math.sqrt(sum(value * value for value in values) / len(values)),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "p95": percentile(values, 0.95),
        "p99": percentile(values, 0.99),
        "maximum": max(values),
    }


def pearson(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return math.nan
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    denominator = math.sqrt(
        sum((a - mean_left) ** 2 for a in left) *
        sum((b - mean_right) ** 2 for b in right)
    )
    return numerator / denominator if denominator else math.nan


def compare_rows(left: list[dict[str, str]], right: list[dict[str, str]]) -> dict[str, object]:
    field_differences: list[dict[str, object]] = []
    if len(left) == len(right):
        for index, (a, b) in enumerate(zip(left, right)):
            for field in a:
                if a[field] != b.get(field):
                    field_differences.append({
                        "row": index,
                        "field": field,
                        "left": a[field],
                        "right": b.get(field),
                    })
    return {
        "left_rows": len(left),
        "right_rows": len(right),
        "same_row_count": len(left) == len(right),
        "field_difference_count": len(field_differences) if len(left) == len(right) else None,
        "field_differences": field_differences[:20],
    }


def summarize_network(
    pairs: list[dict[str, str]],
    events: list[dict[str, str]],
    packaged_pairs: list[dict[str, str]],
    packaged_events: list[dict[str, str]],
) -> dict[str, object]:
    pair_keys = [(row["norad_id"], row["station_id"]) for row in pairs]
    object_rows: dict[str, dict[str, str]] = {}
    station_rows: dict[str, dict[str, str]] = {}
    for row in pairs:
        object_rows.setdefault(row["norad_id"], row)
        station_rows.setdefault(row["station_id"], row)

    active_pairs = {
        (row["norad_id"], row["station_id"])
        for row in pairs if row["active"] == "1"
    }
    event_pairs = {(row["norad_id"], row["station_id"]) for row in events}
    event_objects = {row["norad_id"] for row in events}
    event_stations = {row["station_id"] for row in events}
    event_identity = [
        (row["station_id"], row["norad_id"], row["interval_index"],
         row["event_type"], row["lineage"])
        for row in events
    ]

    by_orbit: dict[str, dict[str, int]] = {}
    for orbit in ("LEO", "MEO", "GEO", "HEO"):
        selected = [row for row in pairs if row["orbit_class"] == orbit]
        orbit_objects = {row["norad_id"] for row in selected}
        orbit_events = [row for row in events if row["norad_id"] in orbit_objects]
        active = {
            (row["norad_id"], row["station_id"])
            for row in selected if row["active"] == "1"
        }
        by_orbit[orbit] = {
            "objects": len(orbit_objects),
            "total_pairs": len(selected),
            "support_pairs": sum(row["support_possible"] == "1" for row in selected),
            "compatible_pairs": sum(row["compatible"] == "1" for row in selected),
            "active_pairs": len(active),
            "active_pairs_with_events": len(active & event_pairs),
            "events": len(orbit_events),
            "objects_with_events": len({row["norad_id"] for row in orbit_events}),
        }

    by_service: dict[str, dict[str, int]] = {}
    service_classes = sorted({row["service_class"] for row in object_rows.values()})
    for service in service_classes:
        selected = [row for row in pairs if row["service_class"] == service]
        service_objects = {row["norad_id"] for row in selected}
        service_events = [row for row in events if row["norad_id"] in service_objects]
        by_service[service] = {
            "objects": len(service_objects),
            "support_pairs": sum(row["support_possible"] == "1" for row in selected),
            "active_pairs": sum(row["active"] == "1" for row in selected),
            "events": len(service_events),
        }

    per_station = []
    for station_id, station in sorted(station_rows.items(), key=lambda item: int(item[0])):
        selected = [row for row in pairs if row["station_id"] == station_id]
        station_events = [row for row in events if row["station_id"] == station_id]
        per_station.append({
            "station_id": int(station_id),
            "station_name": station["station_name"],
            "support_pairs": sum(row["support_possible"] == "1" for row in selected),
            "active_pairs": sum(row["active"] == "1" for row in selected),
            "events": len(station_events),
        })

    per_object = []
    for norad_id, obj in sorted(object_rows.items(), key=lambda item: int(item[0])):
        selected = [row for row in pairs if row["norad_id"] == norad_id]
        object_events = [row for row in events if row["norad_id"] == norad_id]
        per_object.append({
            "norad_id": int(norad_id),
            "object_name": obj["object_name"],
            "orbit_class": obj["orbit_class"],
            "service_class": obj["service_class"],
            "support_pairs": sum(row["support_possible"] == "1" for row in selected),
            "active_pairs": sum(row["active"] == "1" for row in selected),
            "events": len(object_events),
        })

    invariant_errors = []
    for index, row in enumerate(pairs):
        support = row["support_possible"] == "1"
        compatible = row["compatible"] == "1"
        active = row["active"] == "1"
        if active != (support and compatible):
            invariant_errors.append(index)

    pair_comparison = compare_rows(packaged_pairs, pairs)
    event_comparison = compare_rows(packaged_events, events)
    packaged_by_identity = {
        (row["station_id"], row["norad_id"], row["interval_index"],
         row["event_type"], row["lineage"]): row
        for row in packaged_events
    }
    fresh_by_identity = {
        (row["station_id"], row["norad_id"], row["interval_index"],
         row["event_type"], row["lineage"]): row
        for row in events
    }
    shared_identities = packaged_by_identity.keys() & fresh_by_identity.keys()
    event_time_deltas = [
        abs(float(packaged_by_identity[key]["seconds_from_reference"]) -
            float(fresh_by_identity[key]["seconds_from_reference"]))
        for key in shared_identities
    ]
    event_guard_deltas = [
        abs(float(packaged_by_identity[key]["minimum_abs_guard"]) -
            float(fresh_by_identity[key]["minimum_abs_guard"]))
        for key in shared_identities
    ]

    return {
        "row_coverage": {
            "pair_rows": len(pairs),
            "unique_pair_rows": len(set(pair_keys)),
            "objects": len(object_rows),
            "stations": len(station_rows),
            "complete_cartesian_product": len(pairs) == len(object_rows) * len(station_rows)
                and len(set(pair_keys)) == len(pairs),
            "event_rows": len(events),
            "unique_event_identities": len(set(event_identity)),
        },
        "pair_counts": {
            "all": len(pairs),
            "support": sum(row["support_possible"] == "1" for row in pairs),
            "compatible_before_support": sum(row["compatible"] == "1" for row in pairs),
            "active": len(active_pairs),
            "active_invariant_errors": len(invariant_errors),
        },
        "object_counts_by_orbit": dict(Counter(row["orbit_class"] for row in object_rows.values())),
        "object_counts_by_service": dict(Counter(row["service_class"] for row in object_rows.values())),
        "coverage_by_orbit": by_orbit,
        "coverage_by_service": by_service,
        "event_coverage": {
            "events": len(events),
            "event_types": dict(Counter(row["event_type"] for row in events)),
            "route_sectors": dict(sorted(Counter(row["orbit_route"] for row in events).items())),
            "objects_with_events": len(event_objects),
            "objects_without_events": [row for row in per_object if row["events"] == 0],
            "stations_with_events": len(event_stations),
            "stations_without_events": [row for row in per_station if row["events"] == 0],
            "active_pairs_with_events": len(active_pairs & event_pairs),
            "active_pairs_without_events": len(active_pairs - event_pairs),
            "events_map_only_to_active_pairs": event_pairs <= active_pairs,
            "minimum_interval_index": min(int(row["interval_index"]) for row in events),
            "maximum_interval_index": max(int(row["interval_index"]) for row in events),
        },
        "per_station": per_station,
        "per_object": per_object,
        "packaged_reproduction": {
            "pair_table": pair_comparison,
            "event_table": event_comparison,
            "event_identity_intersection": len(shared_identities),
            "event_identity_only_packaged": len(packaged_by_identity.keys() - fresh_by_identity.keys()),
            "event_identity_only_fresh": len(fresh_by_identity.keys() - packaged_by_identity.keys()),
            "event_time_delta_seconds": numeric_summary(event_time_deltas),
            "event_guard_delta": numeric_summary(event_guard_deltas),
        },
    }


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def summarize_sp3(sp3_rows: list[dict[str, str]], omm_rows: list[dict[str, str]]) -> dict[str, object]:
    prn_epochs: dict[str, datetime] = {}
    prn_pattern = re.compile(r"PRN\s+(\d{1,2})")
    for row in omm_rows:
        match = prn_pattern.search(row["OBJECT_NAME"])
        if match:
            prn_epochs[f"G{int(match.group(1)):02d}"] = parse_timestamp(row["EPOCH"] + "Z")

    samples = []
    for row in sp3_rows:
        epoch = parse_timestamp(row["epoch_utc"])
        gps_id = row["gps_id"]
        element_epoch = prn_epochs[gps_id]
        samples.append({
            "epoch": epoch,
            "gps_id": gps_id,
            "error_km": float(row["position_error_km"]),
            "signed_age_hours": (epoch - element_epoch).total_seconds() / 3600.0,
        })

    epochs = sorted({sample["epoch"] for sample in samples})
    observed_boundary = epochs[0] + timedelta(hours=24)
    reference_epoch = datetime(2026, 8, 16, 5, 33, 12, 693024, tzinfo=timezone.utc)

    def subset_summary(selected: list[dict[str, object]]) -> dict[str, object]:
        errors = [float(sample["error_km"]) for sample in selected]
        ages = [abs(float(sample["signed_age_hours"])) for sample in selected]
        return {
            **numeric_summary(errors),
            "absolute_element_age_hours": numeric_summary(ages),
            "age_error_pearson": pearson(ages, errors),
        }

    per_prn = []
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for sample in samples:
        grouped[str(sample["gps_id"])].append(sample)
    for gps_id, selected in sorted(grouped.items()):
        per_prn.append({
            "gps_id": gps_id,
            "element_epoch": prn_epochs[gps_id].isoformat().replace("+00:00", "Z"),
            **subset_summary(selected),
        })

    buckets = {
        "under_24h": [s for s in samples if abs(float(s["signed_age_hours"])) < 24.0],
        "24_to_72h": [s for s in samples if 24.0 <= abs(float(s["signed_age_hours"])) < 72.0],
        "72h_or_more": [s for s in samples if abs(float(s["signed_age_hours"])) >= 72.0],
    }
    return {
        "epochs": len(epochs),
        "samples": len(samples),
        "first_epoch": epochs[0].isoformat().replace("+00:00", "Z"),
        "last_epoch": epochs[-1].isoformat().replace("+00:00", "Z"),
        "observed_predicted_boundary_inferred": observed_boundary.isoformat().replace("+00:00", "Z"),
        "all": subset_summary(samples),
        "observed_half": subset_summary([s for s in samples if s["epoch"] < observed_boundary]),
        "predicted_half": subset_summary([s for s in samples if s["epoch"] >= observed_boundary]),
        "at_or_after_container_reference": subset_summary([s for s in samples if s["epoch"] >= reference_epoch]),
        "age_buckets": {name: subset_summary(selected) for name, selected in buckets.items()},
        "per_prn": per_prn,
        "worst_prn_by_maximum": max(per_prn, key=lambda row: float(row["maximum"])),
    }


def parse_sp3_positions(path: Path) -> dict[datetime, dict[str, tuple[float, float, float]]]:
    epochs: dict[datetime, dict[str, tuple[float, float, float]]] = {}
    current: datetime | None = None
    with path.open("r", encoding="ascii", errors="replace") as handle:
        for line in handle:
            if line.startswith("*"):
                fields = line[1:].split()
                year, month, day, hour, minute = map(int, fields[:5])
                seconds = float(fields[5])
                whole = int(seconds)
                microseconds = int(round((seconds - whole) * 1_000_000.0))
                current = datetime(year, month, day, hour, minute, whole,
                                   microsecond=microseconds, tzinfo=timezone.utc)
                epochs.setdefault(current, {})
            elif current is not None and line.startswith("P") and len(line) >= 46:
                satellite = line[1:4].strip().upper()
                if not satellite.startswith("G"):
                    continue
                try:
                    position = tuple(float(line[start:end]) for start, end in ((4, 18), (18, 32), (32, 46)))
                except ValueError:
                    continue
                if not any(abs(value) >= 999999.0 for value in position):
                    epochs[current][satellite] = position
    return epochs


def station_geometry(row: dict[str, str]) -> dict[str, object]:
    latitude = math.radians(float(row["latitude_deg"]))
    longitude = math.radians(float(row["longitude_deg"]))
    altitude = float(row["altitude_km"])
    equatorial_radius = 6378.137
    flattening = 1.0 / 298.257223563
    eccentricity_squared = flattening * (2.0 - flattening)
    sin_lat, cos_lat = math.sin(latitude), math.cos(latitude)
    sin_lon, cos_lon = math.sin(longitude), math.cos(longitude)
    prime_vertical = equatorial_radius / math.sqrt(1.0 - eccentricity_squared * sin_lat * sin_lat)
    ecef = (
        (prime_vertical + altitude) * cos_lat * cos_lon,
        (prime_vertical + altitude) * cos_lat * sin_lon,
        (prime_vertical * (1.0 - eccentricity_squared) + altitude) * sin_lat,
    )
    elevation_mask_sin = math.sin(math.radians(float(row["elevation_mask_deg"])))
    band_limit = min(89.999999, float(row["elevation_mask_deg"]) + float(row["crossing_band_deg"]))
    crossing_band_sin = max(abs(math.sin(math.radians(band_limit)) - elevation_mask_sin), 1.0e-12)
    return {
        "ecef": ecef,
        "up": (cos_lat * cos_lon, cos_lat * sin_lon, sin_lat),
        "mask_sin": elevation_mask_sin,
        "crossing_band_sin": crossing_band_sin,
        "max_range_km": float(row["max_range_km"]),
    }


def visibility(position: tuple[float, float, float], station: dict[str, object]) -> dict[str, object]:
    delta = tuple(position[index] - station["ecef"][index] for index in range(3))
    distance = math.sqrt(sum(value * value for value in delta))
    elevation_sin = sum(delta[index] * station["up"][index] for index in range(3)) / distance
    guard = float(station["mask_sin"]) - elevation_sin
    supported = distance <= float(station["max_range_km"])
    return {"guard": guard, "supported": supported, "visible": supported and guard <= 0.0}


def crossing(previous: dict[str, object], current: dict[str, object],
             start: datetime, end: datetime, band: float) -> tuple[str, datetime] | None:
    if not previous["supported"] and not current["supported"]:
        return None
    changed = (previous["guard"] > 0.0 and current["guard"] <= 0.0) or (
        previous["guard"] <= 0.0 and current["guard"] > 0.0)
    if not changed or min(abs(float(previous["guard"])), abs(float(current["guard"]))) > band:
        return None
    denominator = float(previous["guard"]) - float(current["guard"])
    alpha = float(previous["guard"]) / denominator if denominator else 0.5
    alpha = max(0.0, min(1.0, alpha))
    event_type = "acquire" if previous["guard"] > 0.0 else "loss"
    return event_type, start + (end - start) * alpha


def summarize_sp3_visibility(
    pairs: list[dict[str, str]],
    stations_csv: list[dict[str, str]],
    sp3_results: list[dict[str, str]],
    sp3_file: Path,
) -> dict[str, object]:
    precise = parse_sp3_positions(sp3_file)
    result_rows = {
        (parse_timestamp(row["epoch_utc"]), row["gps_id"]): row
        for row in sp3_results
    }
    prn_to_norad = {row["gps_id"]: row["norad_id"] for row in sp3_results}
    active_by_norad: dict[str, list[str]] = defaultdict(list)
    for row in pairs:
        if row["active"] == "1" and row["service_class"] == "NAV":
            active_by_norad[row["norad_id"]].append(row["station_id"])
    stations = {row["station_id"]: station_geometry(row) for row in stations_csv}
    epochs = sorted(precise)
    state: dict[tuple[str, str, str], list[dict[str, object]]] = defaultdict(list)
    endpoint_total = 0
    endpoint_visible_disagreements = 0
    endpoint_support_disagreements = 0
    sgp4_visible = 0
    sp3_visible = 0

    for epoch in epochs:
        for gps_id, target in precise[epoch].items():
            row = result_rows.get((epoch, gps_id))
            if row is None:
                continue
            norad_id = prn_to_norad[gps_id]
            delta = tuple(float(row[field]) for field in ("dx_km", "dy_km", "dz_km"))
            predicted = tuple(target[index] + delta[index] for index in range(3))
            for station_id in active_by_norad[norad_id]:
                predicted_visibility = visibility(predicted, stations[station_id])
                precise_visibility = visibility(target, stations[station_id])
                state[(gps_id, norad_id, station_id)].append({
                    "epoch": epoch,
                    "sgp4": predicted_visibility,
                    "sp3": precise_visibility,
                })
                endpoint_total += 1
                sgp4_visible += int(bool(predicted_visibility["visible"]))
                sp3_visible += int(bool(precise_visibility["visible"]))
                endpoint_visible_disagreements += int(
                    predicted_visibility["visible"] != precise_visibility["visible"])
                endpoint_support_disagreements += int(
                    predicted_visibility["supported"] != precise_visibility["supported"])

    sgp4_events: dict[tuple[str, str, int, str], datetime] = {}
    sp3_events: dict[tuple[str, str, int, str], datetime] = {}
    for (_, norad_id, station_id), samples in state.items():
        band = float(stations[station_id]["crossing_band_sin"])
        for index in range(len(samples) - 1):
            previous, current = samples[index], samples[index + 1]
            sgp4_crossing = crossing(previous["sgp4"], current["sgp4"], previous["epoch"], current["epoch"], band)
            sp3_crossing = crossing(previous["sp3"], current["sp3"], previous["epoch"], current["epoch"], band)
            if sgp4_crossing:
                event_type, event_time = sgp4_crossing
                sgp4_events[(norad_id, station_id, index, event_type)] = event_time
            if sp3_crossing:
                event_type, event_time = sp3_crossing
                sp3_events[(norad_id, station_id, index, event_type)] = event_time

    common = sgp4_events.keys() & sp3_events.keys()
    timing_deltas = [abs((sgp4_events[key] - sp3_events[key]).total_seconds()) for key in common]
    return {
        "scope": {
            "epochs": len(epochs),
            "gps_satellites": len(prn_to_norad),
            "active_gps_station_pairs": sum(len(value) for value in active_by_norad.values()),
            "endpoint_evaluations": endpoint_total,
            "sample_step_seconds": (epochs[1] - epochs[0]).total_seconds(),
        },
        "endpoint_visibility": {
            "sgp4_visible": sgp4_visible,
            "sp3_visible": sp3_visible,
            "disagreements": endpoint_visible_disagreements,
            "agreement_fraction": 1.0 - endpoint_visible_disagreements / endpoint_total,
            "support_disagreements": endpoint_support_disagreements,
        },
        "coarse_crossings": {
            "sgp4_events": len(sgp4_events),
            "sp3_events": len(sp3_events),
            "common_identities": len(common),
            "only_sgp4": len(sgp4_events.keys() - sp3_events.keys()),
            "only_sp3": len(sp3_events.keys() - sgp4_events.keys()),
            "common_crossing_time_delta_seconds": numeric_summary(timing_deltas),
        },
        "boundary": "15-minute SP3 endpoint and linear crossing comparison; not the package's 60-second seven-day oracle",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pairs", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--packaged-pairs", type=Path, required=True)
    parser.add_argument("--packaged-events", type=Path, required=True)
    parser.add_argument("--omm", type=Path, required=True)
    parser.add_argument("--sp3-results", type=Path, required=True)
    parser.add_argument("--sp3-file", type=Path, required=True)
    parser.add_argument("--stations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    pairs = read_csv(args.pairs)
    events = read_csv(args.events)
    sp3_results = read_csv(args.sp3_results)
    result = {
        "network": summarize_network(
            pairs, events,
            read_csv(args.packaged_pairs), read_csv(args.packaged_events),
        ),
        "sp3": summarize_sp3(sp3_results, read_csv(args.omm)),
        "sp3_visibility": summarize_sp3_visibility(
            pairs, read_csv(args.stations), sp3_results, args.sp3_file),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
