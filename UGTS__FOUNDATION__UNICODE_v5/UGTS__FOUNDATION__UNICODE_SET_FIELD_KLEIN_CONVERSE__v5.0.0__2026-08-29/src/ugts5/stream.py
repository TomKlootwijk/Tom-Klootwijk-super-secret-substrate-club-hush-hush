"""Binary stream framing for Packed Set-Field Node 32 arrays."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any, Iterable

from .canonical import canonical_bytes
from .packing import PackedNode32

MAGIC = b"UG5N"
VERSION = 1
PREFIX = struct.Struct("<4sBBHI")  # magic, version, flags, header_len, node_count
U32 = struct.Struct("<I")


class StreamError(ValueError):
    pass


def write_stream(path: str | Path, header: dict[str, Any], words: Iterable[int], *, flags: int = 0) -> None:
    word_list = [w & 0xFFFF_FFFF for w in words]
    for index, word in enumerate(word_list):
        if not PackedNode32.verify_parity(word):
            raise StreamError(f"node {index} has invalid parity")
    header_bytes = canonical_bytes(header)
    if len(header_bytes) > 0xFFFF:
        raise StreamError("header exceeds uint16 length")
    prefix = PREFIX.pack(MAGIC, VERSION, flags & 0xFF, len(header_bytes), len(word_list))
    body = prefix + header_bytes + b"".join(U32.pack(w) for w in word_list)
    crc = zlib.crc32(body) & 0xFFFF_FFFF
    Path(path).write_bytes(body + U32.pack(crc))


def read_stream(path: str | Path, *, verify_nodes: bool = True) -> tuple[dict[str, Any], list[int]]:
    data = Path(path).read_bytes()
    if len(data) < PREFIX.size + U32.size:
        raise StreamError("stream too short")
    body, crc_bytes = data[:-4], data[-4:]
    expected_crc = U32.unpack(crc_bytes)[0]
    actual_crc = zlib.crc32(body) & 0xFFFF_FFFF
    if expected_crc != actual_crc:
        raise StreamError(f"CRC mismatch: expected 0x{expected_crc:08x}, got 0x{actual_crc:08x}")
    magic, version, _flags, header_len, node_count = PREFIX.unpack_from(body, 0)
    if magic != MAGIC:
        raise StreamError("bad magic")
    if version != VERSION:
        raise StreamError(f"unsupported stream version {version}")
    offset = PREFIX.size
    header_end = offset + header_len
    node_end = header_end + node_count * 4
    if node_end != len(body):
        raise StreamError("declared lengths do not match stream size")
    header = json.loads(body[offset:header_end].decode("utf-8"))
    words = [U32.unpack_from(body, header_end + i * 4)[0] for i in range(node_count)]
    if verify_nodes:
        for index, word in enumerate(words):
            if not PackedNode32.verify_parity(word):
                raise StreamError(f"node {index} has invalid parity")
    return header, words
