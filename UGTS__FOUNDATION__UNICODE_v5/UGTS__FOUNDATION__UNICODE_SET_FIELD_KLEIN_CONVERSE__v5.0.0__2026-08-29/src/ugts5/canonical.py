"""Canonical JSON and content-address helpers.

The release intentionally hashes exact Unicode spellings. Strings are NFC-normalized,
not compatibility-normalized, so presentation-distinct mathematical characters are not
silently collapsed.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, tuple):
        return [_normalize(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    return value


def canonical_bytes(value: Any) -> bytes:
    """Return deterministic UTF-8 JSON bytes."""
    normalized = _normalize(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def content_hash(record: dict[str, Any], *, excluded: Iterable[str] = ("content_hash",)) -> str:
    copy = deepcopy(record)
    for key in excluded:
        copy.pop(key, None)
    return sha256_hex(copy)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any, *, pretty: bool = True) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if pretty:
        text = json.dumps(_normalize(value), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    else:
        text = canonical_bytes(value).decode("utf-8") + "\n"
    p.write_text(text, encoding="utf-8")
