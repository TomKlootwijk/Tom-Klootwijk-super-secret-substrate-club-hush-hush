"""Content addressing and deterministic hashing."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .rules import Rules
from .state import State

PROOF_STATE_FORMAT = "UGTS-GO-STATE-v1"


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


def canonical_proof_state_payload(state: State, rules: Rules) -> dict[str, Any]:
    """Return the collision-independent semantic state shared with C++.

    ``ply`` is intentionally absent: it is campaign metadata rather than a
    component of game-state equality. Profile labels are likewise omitted in
    favor of the complete semantic rule tuple.
    """

    state.validate(rules)
    return {
        "board_hex": state.board.hex(),
        "format": PROOF_STATE_FORMAT,
        "passes": state.passes,
        "previous_board_hex": (
            state.previous_board.hex() if state.previous_board is not None else None
        ),
        "rules": {
            "allow_suicide": rules.allow_suicide,
            "komi2": rules.komi2,
            "passes_to_end": rules.passes_to_end,
            "scoring": rules.scoring,
            "size": rules.size,
            "superko": rules.superko,
        },
        "seen_hex": [token.hex() for token in sorted(state.seen)],
        "to_play": state.to_play,
    }


def canonical_proof_state_json(state: State, rules: Rules) -> str:
    return canonical_json_bytes(canonical_proof_state_payload(state, rules)).decode(
        "utf-8"
    )


def state_digest(state: State, rules: Rules) -> str:
    payload = {
        "board": state.board.hex(),
        "to_play": state.to_play,
        "passes": state.passes,
        "seen": [token.hex() for token in sorted(state.seen)],
        "rules": rules.as_dict(),
    }
    # Preserve the canonical initial-root digest while distinguishing the
    # previous-board lineage whenever one exists (required by simple ko and the
    # complete cross-profile state identity).
    if state.previous_board is not None:
        payload["previous_board"] = state.previous_board.hex()
    return sha256_hex(canonical_json_bytes(payload))
