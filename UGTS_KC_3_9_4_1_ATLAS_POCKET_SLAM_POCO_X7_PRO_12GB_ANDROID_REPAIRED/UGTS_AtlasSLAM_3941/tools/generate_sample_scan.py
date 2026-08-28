#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import math
import struct
import zipfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "samples" / "synthetic_codec_sample.ugtsscan"
VOXEL = 0.02


def varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def zigzag(value: int) -> int:
    return (value << 1) ^ (value >> 31)


def map_blob() -> tuple[bytes, int]:
    records = []
    for i in range(240):
        angle = 2 * math.pi * i / 80
        ring = i // 80
        x = round((0.45 + ring * 0.08) * math.cos(angle) / VOXEL)
        y = round((ring * 0.06 - 0.06) / VOXEL)
        z = round((1.2 + (0.45 + ring * 0.08) * math.sin(angle)) / VOXEL)
        records.append((x, y, z, 80 + (i * 7) % 150, 180 + i % 70, 1 + i % 5))
    records.sort()
    payload = bytearray(varint(len(records)))
    previous = (0, 0, 0)
    for x, y, z, intensity, confidence, observations in records:
        payload += varint(zigzag(x - previous[0]))
        payload += varint(zigzag(y - previous[1]))
        payload += varint(zigzag(z - previous[2]))
        payload += bytes((intensity, confidence))
        payload += varint(observations)
        previous = (x, y, z)
    return b"UG3D" + bytes((1,)) + struct.pack(">d", VOXEL) + zlib.compress(payload, 3), len(records)


def main() -> None:
    geometry, count = map_blob()
    entries = {
        "map.ugtsbin": geometry,
        "trajectory.csv": (
            "keyframe,timestamp_ns,x,y,z,qw,qx,qy,qz\n"
            "0,1000000000,0,0,0,1,0,0,0\n"
            "1,1500000000,0.08,0,0,1,0,0,0\n"
        ).encode(),
        "ledger.ndjson": (
            '{"sequence":0,"type":"session_started","commit":"accepted"}\n'
            '{"sequence":1,"type":"keyframe_committed","commit":"accepted"}\n'
        ).encode(),
        "capture_policy.json": json.dumps(
            {
                "schema": "ugts.capture-policy/3.9.4.1",
                "scale_state": "relative_units",
                "keyframe_images_persisted": False,
            },
            indent=2,
            sort_keys=True,
        ).encode() + b"\n",
        "README.txt": b"Synthetic non-device fixture for codec and manifest validation.\n",
    }
    manifest = {
        "schema": "ugts.scan-manifest/3.9.4.1",
        "session_id": "synthetic_codec_sample",
        "frames": 2,
        "keyframes": 2,
        "voxels": count,
        "voxel_size": VOXEL,
        "scale_state": "relative_units",
        "entries": {
            name: {"sha256": hashlib.sha256(data).hexdigest()}
            for name, data in entries.items()
        },
    }
    entries["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=3)
    print(OUTPUT)


if __name__ == "__main__":
    main()
