"""Deterministic identity and lineage helpers.

Coordinates are deliberately not used as identity. External source namespace plus
source-local identifier produces a durable 64-bit entity key. Ordered novelty
updates derive a separate 32-bit hot-path lineage checksum; the full event log
remains authoritative.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_u64(namespace: str, external_id: str | int) -> int:
    payload = f"{namespace}\x1f{external_id}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8, person=b"UGTS-ID1").digest(), "little")


def stable_u32(namespace: str, external_id: str | int) -> int:
    value = stable_u64(namespace, external_id)
    return mix32((value & 0xFFFFFFFF) ^ (value >> 32))


def mix32(x: int) -> int:
    x &= 0xFFFFFFFF
    x ^= x >> 16
    x = (x * 0x7FEB352D) & 0xFFFFFFFF
    x ^= x >> 15
    x = (x * 0x846CA68B) & 0xFFFFFFFF
    x ^= x >> 16
    return x & 0xFFFFFFFF


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def payload_hash32(value: Any) -> int:
    digest = hashlib.blake2s(canonical_json_bytes(value), digest_size=4, person=b"UGTSPAY").digest()
    return int.from_bytes(digest, "little")


def lineage_update(parent_hash: int, entity_id: int, sequence: int, event_kind: int, payload: Any) -> int:
    x = parent_hash & 0xFFFFFFFF
    x ^= entity_id & 0xFFFFFFFF
    x ^= (entity_id >> 32) & 0xFFFFFFFF
    x ^= mix32(sequence)
    x ^= mix32(event_kind)
    x ^= payload_hash32(payload)
    return mix32(x)


def u64_hex(value: int) -> str:
    return f"0x{value & 0xFFFFFFFFFFFFFFFF:016x}"


def u32_hex(value: int) -> str:
    return f"0x{value & 0xFFFFFFFF:08x}"
