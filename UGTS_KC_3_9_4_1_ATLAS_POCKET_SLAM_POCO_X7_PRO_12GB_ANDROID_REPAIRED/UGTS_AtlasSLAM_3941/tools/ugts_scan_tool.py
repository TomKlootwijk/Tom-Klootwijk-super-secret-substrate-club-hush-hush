#!/usr/bin/env python3
"""Verify, inspect, and convert UGTS Atlas 3.9.4/3.9.4.1 compact scans."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

MAX_RECORDS = 10_000_000
EXPECTED_ENTRIES = {
    "map.ugtsbin",
    "trajectory.csv",
    "ledger.ndjson",
    "capture_policy.json",
    "README.txt",
    "manifest.json",
}


def read_varint(data: bytes, position: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while shift < 64:
        if position >= len(data):
            raise ValueError("truncated varint")
        byte = data[position]
        position += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, position
        shift += 7
    raise ValueError("varint overflow")


def unzigzag(value: int) -> int:
    return (value >> 1) ^ -(value & 1)


def decode_map(blob: bytes) -> tuple[float, list[tuple[float, float, float, int, float, int]]]:
    if len(blob) < 13 or blob[:4] != b"UG3D" or blob[4] != 1:
        raise ValueError("unsupported or truncated map")
    voxel_size = struct.unpack(">d", blob[5:13])[0]
    if not 0 < voxel_size < 1_000_000:
        raise ValueError("invalid voxel size")
    raw = zlib.decompress(blob[13:])
    count, position = read_varint(raw, 0)
    if count > MAX_RECORDS:
        raise ValueError("unreasonable voxel count")
    x = y = z = 0
    records: list[tuple[float, float, float, int, float, int]] = []
    for _ in range(count):
        dx, position = read_varint(raw, position)
        dy, position = read_varint(raw, position)
        dz, position = read_varint(raw, position)
        x += unzigzag(dx)
        y += unzigzag(dy)
        z += unzigzag(dz)
        if position + 2 > len(raw):
            raise ValueError("truncated intensity/confidence")
        intensity = raw[position]
        confidence = raw[position + 1] / 255.0
        position += 2
        observations, position = read_varint(raw, position)
        records.append(
            (x * voxel_size, y * voxel_size, z * voxel_size,
             intensity, confidence, observations)
        )
    if position != len(raw):
        raise ValueError(f"unexpected trailing map bytes: {len(raw) - position}")
    return voxel_size, records


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and "\\" not in name


def load_scan(path: Path) -> tuple[dict[str, Any], float, list[tuple], list[str]]:
    errors: list[str] = []
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            errors.append(f"ZIP CRC failure: {bad}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            errors.append("duplicate ZIP member names")
        for name in names:
            if not safe_member(name):
                errors.append(f"unsafe ZIP member: {name}")
        missing = sorted(EXPECTED_ENTRIES - set(names))
        if missing:
            errors.append("missing entries: " + ", ".join(missing))
        manifest = json.loads(archive.read("manifest.json"))
        for name, metadata in manifest.get("entries", {}).items():
            if name not in names:
                errors.append(f"manifest entry missing: {name}")
                continue
            expected = metadata.get("sha256")
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            if actual != expected:
                errors.append(f"hash mismatch: {name}")
        voxel_size, records = decode_map(archive.read("map.ugtsbin"))
        declared_voxels = manifest.get("voxels")
        if isinstance(declared_voxels, int) and declared_voxels != len(records):
            errors.append(
                f"voxel count mismatch: manifest={declared_voxels}, decoded={len(records)}"
            )
    return manifest, voxel_size, records, errors


def write_ply(path: Path, records: list[tuple]) -> None:
    with path.open("w", encoding="ascii", newline="\n") as output:
        output.write("ply\nformat ascii 1.0\n")
        output.write(f"element vertex {len(records)}\n")
        output.write("property float x\nproperty float y\nproperty float z\n")
        output.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        output.write("property float confidence\n")
        output.write("property uint observations\nend_header\n")
        for x, y, z, intensity, confidence, observations in records:
            output.write(
                f"{x:.8g} {y:.8g} {z:.8g} "
                f"{intensity} {intensity} {intensity} "
                f"{confidence:.6g} {observations}\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scan", type=Path)
    parser.add_argument("--to-ply", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    try:
        manifest, voxel_size, records, errors = load_scan(args.scan)
        output: dict[str, Any] = {
            "file": str(args.scan),
            "file_sha256": hashlib.sha256(args.scan.read_bytes()).hexdigest(),
            "decoded_voxels": len(records),
            "voxel_size": voxel_size,
            "verification_errors": errors,
        }
        if not args.summary_only:
            output["manifest"] = manifest
        print(json.dumps(output, indent=2, sort_keys=True))
        if args.to_ply:
            write_ply(args.to_ply, records)
        return 1 if errors else 0
    except Exception as error:
        print(json.dumps({"file": str(args.scan), "fatal_error": str(error)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
