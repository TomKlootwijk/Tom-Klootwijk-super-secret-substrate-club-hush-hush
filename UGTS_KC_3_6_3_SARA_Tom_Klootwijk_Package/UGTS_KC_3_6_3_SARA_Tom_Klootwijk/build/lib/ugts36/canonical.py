"""Canonical serialization and content-addressing for UGTS-KC 3.6.

The content hash intentionally excludes the ``content_hash`` field itself.  This
makes a definition self-verifying without creating a recursive hash equation.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Mapping


def canonical_json(value: Any) -> str:
    """Return deterministic UTF-8 JSON text.

    Floats are serialized by Python's JSON encoder.  UGTS 3.6 therefore treats
    the serialized decimal representation as part of the schema contract.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def without_content_hash(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a deep copy of *record* without its top-level content hash."""

    cloned = copy.deepcopy(dict(record))
    cloned.pop("content_hash", None)
    return cloned


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def definition_hash(record: Mapping[str, Any]) -> str:
    """Compute the UGTS content address of a definition record."""

    return sha256_text(canonical_json(without_content_hash(record)))


def attach_content_hash(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *record* with a correct ``content_hash`` value."""

    out = without_content_hash(record)
    out["content_hash"] = definition_hash(out)
    return out


def verify_content_hash(record: Mapping[str, Any]) -> bool:
    expected = record.get("content_hash")
    return isinstance(expected, str) and expected == definition_hash(record)
