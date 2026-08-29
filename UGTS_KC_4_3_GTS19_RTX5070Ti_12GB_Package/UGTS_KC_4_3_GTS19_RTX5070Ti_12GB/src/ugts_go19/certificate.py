"""Recomputation certificates for exact tiny-board results."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .constants import PASS, move_to_coord
from .digests import canonical_json_bytes, sha256_hex, state_digest
from .engine import IllegalMove, apply_move
from .exact import ExactSolver
from .rules import Rules
from .score import area_score2
from .state import State

CERTIFICATE_FORMAT = "UGTS-GO-RECOMPUTE-CERT-v1"


def _certificate_result(result: Any, rules: Rules) -> dict[str, Any]:
    payload = result.as_dict(rules)
    # Wall-clock timing is useful run evidence but is not proof-authoritative.
    # Excluding it makes identical recomputation certificates byte-stable.
    payload["stats"].pop("elapsed_seconds", None)
    return payload


def _verify_result_metadata(
    claimed: Any,
    recomputed: Any,
    state: State,
    rules: Rules,
    node_budget: int | None,
) -> None:
    if not isinstance(claimed, dict):
        raise ValueError("certificate result must be an object")

    value2 = claimed.get("value2")
    if type(value2) is not int or value2 != recomputed.value2:
        raise ValueError("certificate value does not match exact recomputation")
    if claimed.get("value_points") != value2 / 2.0:
        raise ValueError("certificate value_points is inconsistent with value2")
    expected_winner = "black" if value2 > 0 else "white" if value2 < 0 else "draw"
    if claimed.get("winner") != expected_winner:
        raise ValueError("certificate winner is inconsistent with value2")

    best_move = claimed.get("best_move")
    if type(best_move) is not int:
        raise ValueError("certificate best_move must be an integer")
    if claimed.get("best_move_coord") != move_to_coord(best_move, rules.size):
        raise ValueError("certificate best_move coordinate is inconsistent")
    if state.is_terminal(rules):
        if best_move != PASS:
            raise ValueError("terminal certificate root must use pass sentinel")
    else:
        try:
            best_child = apply_move(state, best_move, rules)
        except IllegalMove as exc:
            raise ValueError("certificate best_move is illegal") from exc
        child_result = ExactSolver(rules, node_budget=node_budget).solve(best_child)
        if child_result.value2 != value2:
            raise ValueError("certificate best_move is not exact-optimal")

    variation = claimed.get("principal_variation")
    coordinates = claimed.get("principal_variation_coords")
    complete = claimed.get("principal_variation_complete")
    if not isinstance(variation, list) or any(type(move) is not int for move in variation):
        raise ValueError("certificate principal_variation must contain integers")
    if not isinstance(coordinates, list) or coordinates != [
        move_to_coord(move, rules.size) for move in variation
    ]:
        raise ValueError("certificate principal-variation coordinates are inconsistent")
    if type(complete) is not bool:
        raise ValueError("certificate principal_variation_complete must be boolean")
    if variation and variation[0] != best_move:
        raise ValueError("certificate principal variation disagrees with best_move")

    pv_state = state
    for move in variation:
        try:
            pv_state = apply_move(pv_state, move, rules)
        except IllegalMove as exc:
            raise ValueError("certificate principal variation contains an illegal move") from exc
    if complete:
        if not pv_state.is_terminal(rules):
            raise ValueError("complete principal variation is not terminal")
        if area_score2(pv_state.board, rules) != value2:
            raise ValueError("complete principal variation has the wrong terminal value")

    stats = claimed.get("stats")
    expected_stat_keys = {
        "nodes",
        "terminals",
        "cutoffs",
        "tt_hits",
        "tt_entries",
        "max_ply",
    }
    if not isinstance(stats, dict) or set(stats) != expected_stat_keys:
        raise ValueError("certificate stats has a noncanonical shape")
    if any(type(value) is not int or value < 0 for value in stats.values()):
        raise ValueError("certificate stats must be nonnegative integers")


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
    state.validate(rules)
    if state_digest(state, rules) != certificate["root"]["digest"]:
        raise ValueError("root state digest mismatch")
    result = ExactSolver(rules, node_budget=node_budget).solve(state)
    _verify_result_metadata(
        certificate.get("result"), result, state, rules, node_budget
    )
    return {
        "verified": True,
        "value2": result.value2,
        "root_digest": certificate["root"]["digest"],
        "certificate_sha256": provided_hash,
        "stats": result.stats.as_dict(),
    }


def load_certificate(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
