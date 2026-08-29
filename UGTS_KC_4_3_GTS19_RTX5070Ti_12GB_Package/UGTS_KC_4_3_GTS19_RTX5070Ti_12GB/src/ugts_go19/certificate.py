"""Recomputation certificates for exact tiny-board results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .digests import canonical_json_bytes, sha256_hex, state_digest
from .exact import ExactSolver
from .rules import Rules
from .state import State

CERTIFICATE_FORMAT = "UGTS-GO-RECOMPUTE-CERT-v2"


def _certificate_result(result: Any, rules: Rules) -> dict[str, Any]:
    del rules
    return {
        "value2": result.value2,
        "value_points": result.value2 / 2.0,
        "winner": (
            "black" if result.value2 > 0 else "white" if result.value2 < 0 else "draw"
        ),
    }


def _verify_result_claim(claimed: Any, recomputed: Any) -> None:
    expected_keys = {"value2", "value_points", "winner"}
    if not isinstance(claimed, dict) or set(claimed) != expected_keys:
        raise ValueError("certificate result has a noncanonical shape")
    value2 = claimed["value2"]
    if type(value2) is not int or value2 != recomputed.value2:
        raise ValueError("certificate value does not match exact recomputation")
    if type(claimed["value_points"]) is not float:
        raise ValueError("certificate value_points must be a JSON number")
    if claimed["value_points"] != value2 / 2.0:
        raise ValueError("certificate value_points is inconsistent with value2")
    expected_winner = "black" if value2 > 0 else "white" if value2 < 0 else "draw"
    if claimed["winner"] != expected_winner:
        raise ValueError("certificate winner is inconsistent with value2")


def make_certificate(
    rules: Rules,
    state: State,
    *,
    node_budget: int | None = None,
) -> dict[str, Any]:
    solver = ExactSolver(rules, node_budget=node_budget)
    result = solver.solve(state)
    result_payload = _certificate_result(result, rules)
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
        "result": result_payload,
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
    expected_keys = {
        "board_hex",
        "to_play",
        "passes",
        "seen_hex",
        "previous_board_hex",
        "ply",
        "digest",
    }
    if not isinstance(root, dict) or set(root) != expected_keys:
        raise ValueError("certificate root has a noncanonical shape")
    if type(root["board_hex"]) is not str:
        raise ValueError("certificate board_hex must be a string")
    if type(root["to_play"]) is not int or type(root["passes"]) is not int:
        raise ValueError("certificate player/pass fields must be integers")
    if type(root["ply"]) is not int:
        raise ValueError("certificate ply must be an integer")
    if not isinstance(root["seen_hex"], list) or any(
        type(item) is not str for item in root["seen_hex"]
    ):
        raise ValueError("certificate seen_hex must be a string array")
    if root["seen_hex"] != sorted(set(root["seen_hex"])):
        raise ValueError("certificate seen_hex must be sorted and unique")
    previous = root["previous_board_hex"]
    if previous is not None and type(previous) is not str:
        raise ValueError("certificate previous_board_hex must be a string or null")
    if type(root["digest"]) is not str:
        raise ValueError("certificate root digest must be a string")
    return State(
        board=bytes.fromhex(root["board_hex"]),
        to_play=root["to_play"],
        passes=root["passes"],
        seen=frozenset(bytes.fromhex(item) for item in root["seen_hex"]),
        previous_board=(
            bytes.fromhex(previous) if previous is not None else None
        ),
        ply=root["ply"],
    )


def verify_certificate(
    certificate: dict[str, Any], *, node_budget: int | None = None
) -> dict[str, Any]:
    expected_top_keys = {
        "format",
        "rules",
        "root",
        "result",
        "verification",
        "certificate_sha256",
    }
    if not isinstance(certificate, dict) or set(certificate) != expected_top_keys:
        raise ValueError("certificate has a noncanonical top-level shape")
    if certificate.get("format") != CERTIFICATE_FORMAT:
        raise ValueError("unsupported certificate format")
    provided_hash = certificate.get("certificate_sha256")
    unhashed = dict(certificate)
    unhashed.pop("certificate_sha256", None)
    calculated_hash = sha256_hex(canonical_json_bytes(unhashed))
    if provided_hash != calculated_hash:
        raise ValueError("certificate digest mismatch")

    expected_verification = {
        "method": "independent deterministic recomputation",
        "requires_exact_history": True,
        "standalone_strategy_tree": False,
    }
    if certificate["verification"] != expected_verification:
        raise ValueError("certificate verification descriptor is noncanonical")

    rules = Rules.from_dict(certificate["rules"])
    state = _state_from_certificate(certificate["root"])
    state.validate(rules)
    if state_digest(state, rules) != certificate["root"]["digest"]:
        raise ValueError("root state digest mismatch")
    result = ExactSolver(rules, node_budget=node_budget).solve(state)
    _verify_result_claim(certificate.get("result"), result)
    return {
        "verified": True,
        "value2": result.value2,
        "root_digest": certificate["root"]["digest"],
        "certificate_sha256": provided_hash,
        "stats": result.stats.as_dict(),
    }


def load_certificate(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
