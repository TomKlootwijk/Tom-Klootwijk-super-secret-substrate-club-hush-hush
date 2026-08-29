#!/usr/bin/env python3
"""Independent KSEED 4.1 CRC/zlib/SHA-chain inspector and optional PLY exporter."""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"KSEED41\0"
HEADER_BYTES = 128
CHUNK_HEADER_BYTES = 64
SUMMARY_BYTES = 60
FLAG_COMPRESSED = 1
CHUNK_VOXELS = 4
CHUNK_SUMMARY = 255
INITIAL_CHAIN = hashlib.sha256(b"KSEED41-CHAIN").digest()


class KSeedError(ValueError):
    pass


@dataclass(frozen=True)
class Chunk:
    type: int
    flags: int
    sequence: int
    record_count: int
    decoded_length: int
    stored_length: int
    decoded_crc32: int
    stored_crc32: int
    schema_id: int
    chain_sha256: str
    decoded: bytes


def crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def parse(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < HEADER_BYTES:
        raise KSeedError("truncated KSEED header")
    header = data[:HEADER_BYTES]
    if header[:8] != MAGIC:
        raise KSeedError("KSEED magic mismatch")
    major, minor, header_size, mode = struct.unpack_from("<HHHH", header, 8)
    if (major, minor, header_size, mode) != (4, 1, 128, 1):
        raise KSeedError("unsupported KSEED version/mode")
    flags = struct.unpack_from("<I", header, 16)[0]
    seed = header[20:36].hex()
    start_ns = struct.unpack_from("<Q", header, 36)[0]
    width, height, requested_fps, feature_budget = struct.unpack_from("<IIII", header, 44)
    capture_profile_sha256 = header[60:92].hex()
    calibration_sha256 = header[92:124].hex()
    declared_header_crc = struct.unpack_from("<I", header, 124)[0]
    actual_header_crc = crc32(header[:124])
    if declared_header_crc != actual_header_crc:
        raise KSeedError("KSEED header CRC mismatch")

    chunks: list[Chunk] = []
    offset = HEADER_BYTES
    expected_sequence = 0
    previous = INITIAL_CHAIN
    summary: bytes | None = None
    while offset < len(data):
        if len(data) - offset < CHUNK_HEADER_BYTES:
            raise KSeedError("truncated KSEED chunk header")
        first32 = data[offset : offset + 32]
        declared_chain = data[offset + 32 : offset + 64]
        (
            chunk_type,
            chunk_flags,
            sequence,
            record_count,
            decoded_length,
            stored_length,
            decoded_crc,
            stored_crc,
            schema_id,
        ) = struct.unpack("<HHIIIIIII", first32)
        if sequence != expected_sequence:
            raise KSeedError(f"chunk sequence {sequence}, expected {expected_sequence}")
        expected_sequence += 1
        payload_start = offset + CHUNK_HEADER_BYTES
        payload_end = payload_start + stored_length
        if stored_length < 0 or payload_end > len(data):
            raise KSeedError("invalid KSEED stored length")
        stored = data[payload_start:payload_end]
        if crc32(stored) != stored_crc:
            raise KSeedError(f"stored CRC mismatch at chunk {sequence}")
        actual_chain = hashlib.sha256(previous + first32 + stored).digest()
        if actual_chain != declared_chain:
            raise KSeedError(f"SHA-256 chain mismatch at chunk {sequence}")
        if chunk_flags & FLAG_COMPRESSED:
            try:
                decoded = zlib.decompress(stored)
            except zlib.error as exc:
                raise KSeedError(f"zlib failure at chunk {sequence}: {exc}") from exc
        else:
            decoded = stored
        if len(decoded) != decoded_length:
            raise KSeedError(f"decoded length mismatch at chunk {sequence}")
        if crc32(decoded) != decoded_crc:
            raise KSeedError(f"decoded CRC mismatch at chunk {sequence}")
        chunk = Chunk(
            chunk_type,
            chunk_flags,
            sequence,
            record_count,
            decoded_length,
            stored_length,
            decoded_crc,
            stored_crc,
            schema_id,
            actual_chain.hex(),
            decoded,
        )
        chunks.append(chunk)
        if chunk_type == CHUNK_SUMMARY:
            if summary is not None or len(decoded) != SUMMARY_BYTES:
                raise KSeedError("invalid or duplicate summary")
            summary = decoded
        previous = actual_chain
        offset = payload_end
    if offset != len(data) or summary is None:
        raise KSeedError("summary missing or trailing data")
    if chunks[-1].type != CHUNK_SUMMARY:
        raise KSeedError("summary is not final chunk")
    (
        frames,
        keyframes,
        events,
        voxels,
        raw_input_bytes,
        stored_bytes,
        rejected_proposals,
        state_flags,
        chunk_count,
    ) = struct.unpack("<QQQQQQIII", summary)
    if stored_bytes != len(data):
        raise KSeedError("summary stored_bytes differs from actual file length")
    if chunk_count != len(chunks):
        raise KSeedError("summary chunk_count mismatch")
    return {
        "schema": "ugts.kseed-inspection/4.1.1",
        "file": str(path),
        "file_sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "header": {
            "version": f"{major}.{minor}",
            "storage_mode": mode,
            "flags": flags,
            "seed": seed,
            "start_time_ns": start_ns,
            "analysis_width": width,
            "analysis_height": height,
            "requested_capture_fps": requested_fps,
            "feature_budget": feature_budget,
            "capture_profile_sha256": capture_profile_sha256,
            "calibration_sha256": calibration_sha256,
            "header_crc32": f"{declared_header_crc:08x}",
        },
        "summary": {
            "frames": frames,
            "keyframes": keyframes,
            "events": events,
            "voxels": voxels,
            "raw_input_bytes": raw_input_bytes,
            "stored_bytes": stored_bytes,
            "rejected_proposals": rejected_proposals,
            "state_flags": state_flags,
            "chunk_count": chunk_count,
        },
        "compression": {
            "raw_to_stored_ratio": (
                raw_input_bytes / stored_bytes if stored_bytes else None
            ),
            "note": "ratio compares captured luma bytes with retained evidence, not equal-information reconstruction",
        },
        "chunks": [
            {
                "type": chunk.type,
                "flags": chunk.flags,
                "sequence": chunk.sequence,
                "record_count": chunk.record_count,
                "decoded_length": chunk.decoded_length,
                "stored_length": chunk.stored_length,
                "schema_id": f"0x{chunk.schema_id:08x}",
                "chain_sha256": chunk.chain_sha256,
            }
            for chunk in chunks
        ],
        "final_chain_sha256": previous.hex(),
        "integrity": "PASS",
        "_parsed_chunks": chunks,
    }


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while shift < 64:
        if offset >= len(data):
            raise KSeedError("truncated varint")
        item = data[offset]
        offset += 1
        value |= (item & 0x7F) << shift
        if not item & 0x80:
            return value, offset
        shift += 7
    raise KSeedError("varint overflow")


def morton_decode(key: int, lane: int) -> int:
    value = 0
    for bit in range(21):
        value |= ((key >> (bit * 3 + lane)) & 1) << bit
    return value - (1 << 20)


def decode_voxels(chunks: list[Chunk]) -> list[tuple[int, int, int, int, int, int]]:
    voxel_chunks = [chunk for chunk in chunks if chunk.type == CHUNK_VOXELS]
    if len(voxel_chunks) != 1:
        raise KSeedError("expected exactly one voxel chunk")
    data = voxel_chunks[0].decoded
    count, offset = read_varint(data, 0)
    output = []
    key = 0
    for _ in range(count):
        delta, offset = read_varint(data, offset)
        key = (key + delta) & ((1 << 64) - 1)
        if offset + 2 > len(data):
            raise KSeedError("truncated voxel payload")
        intensity = data[offset]
        confidence = data[offset + 1]
        offset += 2
        observations, offset = read_varint(data, offset)
        output.append(
            (
                morton_decode(key, 0),
                morton_decode(key, 1),
                morton_decode(key, 2),
                intensity,
                confidence,
                observations,
            )
        )
    if offset != len(data):
        raise KSeedError("voxel payload has trailing bytes")
    return output


def write_ply(path: Path, voxels: list[tuple[int, int, int, int, int, int]], voxel_size: float) -> None:
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write("ply\nformat ascii 1.0\n")
        stream.write(f"element vertex {len(voxels)}\n")
        stream.write("property float x\nproperty float y\nproperty float z\n")
        stream.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        stream.write("property uchar confidence\nproperty uint observations\nend_header\n")
        for x, y, z, intensity, confidence, observations in voxels:
            stream.write(
                f"{(x + 0.5) * voxel_size:.9g} {(y + 0.5) * voxel_size:.9g} "
                f"{(z + 0.5) * voxel_size:.9g} {intensity} {intensity} {intensity} "
                f"{confidence} {observations}\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kseed", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--to-ply", type=Path)
    parser.add_argument("--voxel-size", type=float, default=0.012)
    args = parser.parse_args()
    try:
        report = parse(args.kseed)
        chunks = report.pop("_parsed_chunks")
        if args.to_ply:
            write_ply(args.to_ply, decode_voxels(chunks), args.voxel_size)
            report["ply"] = str(args.to_ply)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            summary = report["summary"]
            print(f"KSEED integrity: PASS")
            print(f"File: {args.kseed}")
            print(f"Bytes: {report['bytes']}")
            print(f"Seed: {report['header']['seed']}")
            print(
                "Frames/keyframes/events/voxels: "
                f"{summary['frames']}/{summary['keyframes']}/{summary['events']}/{summary['voxels']}"
            )
            print(f"Final chain: {report['final_chain_sha256']}")
        return 0
    except (OSError, KSeedError) as error:
        print(f"KSEED integrity: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
