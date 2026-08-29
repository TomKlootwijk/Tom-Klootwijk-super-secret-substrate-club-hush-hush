"""Recomputation certificates for exact tiny-board results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .digests import canonical_json_bytes, sha256_hex, state_digest
from .exact import ExactSolver
from .rules import Rules
from .state import State

CERTIFICATE_FORMAT = "UGTS-GO-RECOMPUTE-CERT-v1"


def make_certificate(
    rules: Rules,
    state: State,
    *,
    node_budget: int | None = None,
) -> dict[str, Any]:
    solver = ExactSolver(rules, node_budget=node_budget)
    result = solver.solve(state)
    payload: dict[str, Any] = {
        "format": CERTIFICATE_FORMAT,
        "rules": rules.as_dict(),
        "root": {
            "board_hex": state.board.hex(),
            "to_play": state.to_play,
            "passes": state.passes,
            "seen_hex": [token.hex() for token in sorted(state.seen)],
            "previous_board_hex": (
                state.previous_board.hex() if state.previous_board is not None else None
            ),
            "ply": state.ply,
            "digest": state_digest(state, rules),
        },
        "result": result.as_dict(rules),
        "verification": {
            "method": "independent deterministic recomputation",
            "requires_exact_history": True,
            "standalone_strategy_tree": False,
        },
    }
    payload["certificate_sha256"] = sha256_hex(canonical_json_bytes(payload))
    return payload


def save_certificate(path: str | Path, certificate: dict[str, Any]) -> None:
    Path(path).write_text(
        json.dumps(certificate, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _state_from_certificate(root: dict[str, Any]) -> State:
    return State(
        board=bytes.fromhex(root["board_hex"]),
        to_play=int(root["to_play"]),
        passes=int(root["passes"]),
        seen=frozenset(bytes.fromhex(item) for item in root["seen_hex"]),
        previous_board=(
            bytes.fromhex(root["previous_board_hex"])
            if root.get("previous_board_hex") is not None
            else None
        ),
        ply=int(root.get("ply", 0)),
    )


def verify_certificate(
    certificate: dict[str, Any], *, node_budget: int | None = None
) -> dict[str, Any]:
    if certificate.get("format") != CERTIFICATE_FORMAT:
        raise ValueError("unsupported certificate format")
    provided_hash = certificate.get("certificate_sha256")
    unhashed = dict(certificate)
    unhashed.pop("certificate_sha256", None)
    calculated_hash = sha256_hex(canonical_json_bytes(unhashed))
    if provided_hash != calculated_hash:
        raise ValueError("certificate digest mismatch")

    rules = Rules.from_dict(certificate["rules"])
    state = _state_from_certificate(certificate["root"])
    if state_digest(state, rules) != certificate["root"]["digest"]:
        raise ValueError("root state digest mismatch")
    result = ExactSolver(rules, node_budget=node_budget).solve(state)
    expected = int(certificate["result"]["value2"])
    if result.value2 != expected:
        raise ValueError(f"recomputed value {result.value2} != expected {expected}")
    return {
        "verified": True,
        "value2": result.value2,
        "root_digest": certificate["root"]["digest"],
        "certificate_sha256": provided_hash,
        "stats": result.stats.as_dict(),
    }


def load_certificate(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
