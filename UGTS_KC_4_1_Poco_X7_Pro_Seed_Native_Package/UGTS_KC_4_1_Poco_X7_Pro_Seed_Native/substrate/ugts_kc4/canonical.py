"""Canonical serialization helpers for UGTS-KC 4.0 spatial evidence records.

The routines intentionally normalize numerically equivalent integral spellings and
reject NaN/Infinity so state hashes remain stable across JSON round trips.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any


def normalize_json_value(value: Any) -> Any:
    """Return a JSON-safe value with deterministic numeric normalization."""
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        return {str(key): normalize_json_value(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_json_value(item) for item in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("canonical JSON does not permit NaN or Infinity")
        if value == 0.0:
            return 0
        if value.is_integer() and abs(value) <= 2**53:
            return int(value)
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")


def canonical_json(value: Any) -> bytes:
    """Serialize a value as canonical UTF-8 JSON bytes."""
    normalized = normalize_json_value(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_text(value: Any, *, indent: int = 2) -> str:
    """Pretty deterministic JSON for human-facing files."""
    normalized = normalize_json_value(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        indent=indent,
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def content_address(namespace: str, value: Any, *, length: int = 24) -> str:
    if not namespace or ":" in namespace:
        raise ValueError("namespace must be a non-empty token without ':'")
    if length < 8 or length > 64:
        raise ValueError("length must be between 8 and 64")
    return f"{namespace}:{content_hash(value)[:length]}"


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(canonical_text(value), encoding="utf-8")
    return target
