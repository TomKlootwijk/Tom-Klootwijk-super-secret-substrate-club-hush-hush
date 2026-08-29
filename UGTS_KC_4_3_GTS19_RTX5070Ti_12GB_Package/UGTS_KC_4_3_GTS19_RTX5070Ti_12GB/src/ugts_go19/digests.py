"""Content addressing and deterministic hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .rules import Rules
from .state import State


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def board_digest(board: bytes) -> str:
    return sha256_hex(board)


def history_digest(state: State) -> str:
    digest = hashlib.sha256()
    for token in sorted(state.seen):
        digest.update(len(token).to_bytes(2, "big"))
        digest.update(token)
    return digest.hexdigest()


def state_digest(state: State, rules: Rules) -> str:
    payload = {
        "board": state.board.hex(),
        "to_play": state.to_play,
        "passes": state.passes,
        "seen": [token.hex() for token in sorted(state.seen)],
        "rules": rules.as_dict(),
    }
    return sha256_hex(canonical_json_bytes(payload))
