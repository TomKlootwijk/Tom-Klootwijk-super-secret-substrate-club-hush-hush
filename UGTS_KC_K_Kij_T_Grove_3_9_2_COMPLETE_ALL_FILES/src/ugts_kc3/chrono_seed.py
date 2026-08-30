"""Minimal root-seed payload for the fixed UGTOMS chrono traversal profile.

``UGSEED64`` is deliberately an external-profile payload rather than a
self-describing container: its entire representation is one little-endian
``uint64``.  It regenerates deterministic addressing only.  It is not a
standalone video, an observation payload, or a collision-resistant content
identifier.
"""
from __future__ import annotations

import struct


ROOT_SEED_BYTES = 8
_ROOT_SEED = struct.Struct("<Q")


class ChronoSeedError(ValueError):
    """The seed or source digest is outside the fixed UGSEED64 contract."""


def derive_root_seed(source_sha256: str) -> int:
    """Derive the existing traversal root from the first eight digest bytes."""

    if (
        not isinstance(source_sha256, str)
        or len(source_sha256) != 64
        or any(character not in "0123456789abcdef" for character in source_sha256)
    ):
        raise ChronoSeedError("source SHA-256 must be 64 lowercase hexadecimal characters")
    return int.from_bytes(bytes.fromhex(source_sha256[:16]), "little")


def pack_root_seed(root_seed: int) -> bytes:
    """Pack one traversal root into the minimum fixed-profile payload."""

    if not isinstance(root_seed, int) or isinstance(root_seed, bool):
        raise ChronoSeedError("root seed must be an integer")
    if not 0 <= root_seed <= 0xFFFFFFFFFFFFFFFF:
        raise ChronoSeedError("root seed must fit uint64")
    return _ROOT_SEED.pack(root_seed)


def unpack_root_seed(payload: bytes | bytearray | memoryview) -> int:
    """Decode a canonical eight-byte fixed-profile root seed."""

    raw = bytes(payload)
    if len(raw) != ROOT_SEED_BYTES:
        raise ChronoSeedError("UGSEED64 payload must be exactly 8 bytes")
    return _ROOT_SEED.unpack(raw)[0]


__all__ = [
    "ChronoSeedError",
    "ROOT_SEED_BYTES",
    "derive_root_seed",
    "pack_root_seed",
    "unpack_root_seed",
]
