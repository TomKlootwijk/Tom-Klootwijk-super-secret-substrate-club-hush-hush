"""Proof-carrying bounded mate solver and independent verifier."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .constants import WHITE, color_name, opposite
from .game_state import RULE_PROFILE_ID
from .hashing import repetition_key, state_sha256
from .position import Position
from .rules import apply_move, in_check, insufficient_material, legal_moves, move_to_san, parse_uci_move


@dataclass(frozen=True, slots=True)
class MateProofResult:
    status: str
    attacker: int
    max_plies: int
    explored_nodes: int
    certificate: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return self.certificate


class MateProver:
    def __init__(self, *, node_budget: int = 2_000_000) -> None:
        self.node_budget = node_budget
        self.nodes = 0
        self.memo: dict[
            tuple[str, int, int, tuple[tuple[str, int], ...]],
            tuple[bool, dict[str, Any] | None],
        ] = {}

    def _order(self, position: Position, moves: list[Any]) -> list[Any]:
        def key(move: Any) -> tuple[int, int, int, str]:
            child = apply_move(position, move)
            child_legal = legal_moves(child)
            mate = int(in_check(child) and not child_legal)
            check = int(in_check(child))
            return (mate, check, int(move.is_capture or bool(move.promotion)), move.uci())

        return sorted(moves, key=key, reverse=True)

    def _prove(
        self,
        position: Position,
        attacker: int,
        plies_left: int,
        path_counts: dict[str, int],
    ) -> tuple[bool, dict[str, Any] | None]:
        self.nodes += 1
        if self.nodes > self.node_budget:
            raise RuntimeError("mate proof node budget exceeded")

        pos_hash = state_sha256(position)
        legal = legal_moves(position)
        if not legal:
            if in_check(position) and opposite(position.turn) == attacker:
                return True, {
                    "role": "terminal",
                    "fen": position.to_fen(),
                    "hash": pos_hash,
                    "result": "checkmate",
                    "winner": color_name(attacker),
                }
            return False, None

        if plies_left <= 0:
            return False, None
        rep_key = repetition_key(position)
        occurrences = path_counts.get(rep_key, 0)
        # Automatic draws terminate the line for both sides.  Claimable draws
        # are optional actions and defeat a mate proof only when owned by the
        # defender; the attacker may decline a draw claim and continue mating.
        if position.halfmove_clock >= 150 or occurrences >= 5 or insufficient_material(position):
            return False, None
        if position.turn != attacker and (position.halfmove_clock >= 100 or occurrences >= 3):
            return False, None

        # Repetition claims depend on every prior position count, not only the
        # count of the current position.  A position/depth-only memo entry can
        # therefore be unsound when reached through a different history.
        memo_key = (pos_hash, plies_left, attacker, tuple(sorted(path_counts.items())))
        if memo_key in self.memo:
            return self.memo[memo_key]

        role = "OR" if position.turn == attacker else "AND"
        ordered = self._order(position, legal)
        if role == "OR":
            for move in ordered:
                child = apply_move(position, move)
                child_key = repetition_key(child)
                path_counts[child_key] = path_counts.get(child_key, 0) + 1
                ok, child_node = self._prove(child, attacker, plies_left - 1, path_counts)
                path_counts[child_key] -= 1
                if path_counts[child_key] == 0:
                    del path_counts[child_key]
                if ok and child_node is not None:
                    node = {
                        "role": "OR",
                        "fen": position.to_fen(),
                        "hash": pos_hash,
                        "side": color_name(position.turn),
                        "move": move.uci(),
                        "san": move_to_san(position, move),
                        "child": child_node,
                    }
                    result = (True, node)
                    self.memo[memo_key] = result
                    return result
            result = (False, None)
        else:
            replies: list[dict[str, Any]] = []
            for move in ordered:
                child = apply_move(position, move)
                child_key = repetition_key(child)
                path_counts[child_key] = path_counts.get(child_key, 0) + 1
                # The defender may claim before executing an intended move that
                # creates the third repetition or completes 50 moves each.
                if child.halfmove_clock >= 100 or path_counts[child_key] >= 3:
                    path_counts[child_key] -= 1
                    if path_counts[child_key] == 0:
                        del path_counts[child_key]
                    result = (False, None)
                    self.memo[memo_key] = result
                    return result
                ok, child_node = self._prove(child, attacker, plies_left - 1, path_counts)
                path_counts[child_key] -= 1
                if path_counts[child_key] == 0:
                    del path_counts[child_key]
                if not ok or child_node is None:
                    result = (False, None)
                    self.memo[memo_key] = result
                    return result
                replies.append({
                    "move": move.uci(),
                    "san": move_to_san(position, move),
                    "child": child_node,
                })
            result = (
                True,
                {
                    "role": "AND",
                    "fen": position.to_fen(),
                    "hash": pos_hash,
                    "side": color_name(position.turn),
                    "replies": replies,
                },
            )
        self.memo[memo_key] = result
        return result

    def prove(self, position: Position, *, max_plies: int, attacker: int | None = None) -> MateProofResult:
        if max_plies < 1:
            raise ValueError("max_plies must be at least 1")
        attacker = position.turn if attacker is None else attacker
        self.nodes = 0
        self.memo.clear()
        root_rep = repetition_key(position)
        ok, tree = self._prove(position, attacker, max_plies, {root_rep: 1})
        status = "proved" if ok else "not_forced_within_horizon"
        certificate: dict[str, Any] = {
            "$schema": "ugts-chess-mate-proof-2.0",
            "schema_version": "2.0.0",
            "rules_profile": "fide-classical-2023-claims-as-actions-v2",
            "root_history_counts": [[root_rep, 1]],
            "status": status,
            "root_fen": position.to_fen(),
            "root_hash": state_sha256(position),
            "attacker": color_name(attacker),
            "max_plies": max_plies,
            "explored_nodes": self.nodes,
            "proof_semantics": "OR nodes choose one legal attacker move; AND nodes enumerate every legal defender reply and reject defender draw-claim actions; leaves are checkmate.",
            "tree": tree,
        }
        return MateProofResult(status, attacker, max_plies, self.nodes, certificate)


def _verify_node(position: Position, node: dict[str, Any], attacker: int, depth: int, max_plies: int, path_counts: dict[str, int]) -> int:
    if depth > max_plies:
        raise ValueError("proof exceeds declared ply horizon")
    if node.get("fen") != position.to_fen():
        raise ValueError(f"FEN mismatch at depth {depth}")
    if node.get("hash") != state_sha256(position):
        raise ValueError(f"state hash mismatch at depth {depth}")
    role = node.get("role")
    legal = legal_moves(position)
    rep_key = repetition_key(position)
    occurrences = path_counts.get(rep_key, 0)
    # Checkmate and stalemate end the game before automatic draw rules are
    # considered.  In particular, FIDE 9.6.2 makes a mating move decisive even
    # when it also completes the 75-move threshold.
    if not legal:
        if role != "terminal":
            raise ValueError("non-terminal proof node has no legal moves")
        if not in_check(position):
            raise ValueError("terminal node is not checkmate")
        if opposite(position.turn) != attacker:
            raise ValueError("terminal mate winner is not the declared attacker")
        if node.get("result") != "checkmate":
            raise ValueError("terminal result must be checkmate")
        if node.get("winner") != color_name(attacker):
            raise ValueError("terminal winner field does not match the declared attacker")
        return 1
    if role == "terminal":
        raise ValueError("terminal node is not checkmate")
    if position.halfmove_clock >= 150 or occurrences >= 5 or insufficient_material(position):
        raise ValueError("mate proof crosses an automatic draw")
    if position.turn != attacker and (position.halfmove_clock >= 100 or occurrences >= 3):
        raise ValueError("defender has an available draw claim")
    expected_role = "OR" if position.turn == attacker else "AND"
    if role != expected_role:
        raise ValueError(f"expected {expected_role} node, got {role}")
    if node.get("side") != color_name(position.turn):
        raise ValueError("proof node side field does not match the position")
    if role == "OR":
        move_text = node.get("move")
        if not isinstance(move_text, str):
            raise ValueError("OR node lacks selected move")
        move = parse_uci_move(position, move_text)
        if node.get("san") != move_to_san(position, move):
            raise ValueError("OR node SAN does not match the selected move")
        child = node.get("child")
        if not isinstance(child, dict):
            raise ValueError("OR node lacks child")
        child_position = apply_move(position, move)
        child_key = repetition_key(child_position)
        path_counts[child_key] = path_counts.get(child_key, 0) + 1
        try:
            return 1 + _verify_node(child_position, child, attacker, depth + 1, max_plies, path_counts)
        finally:
            path_counts[child_key] -= 1
            if path_counts[child_key] == 0:
                del path_counts[child_key]

    replies = node.get("replies")
    if not isinstance(replies, list):
        raise ValueError("AND node lacks replies")
    supplied = [item.get("move") for item in replies if isinstance(item, dict)]
    legal_uci = sorted(move.uci() for move in legal)
    if sorted(supplied) != legal_uci:
        missing = sorted(set(legal_uci) - set(supplied))
        extra = sorted(set(supplied) - set(legal_uci))
        raise ValueError(f"AND node reply coverage mismatch; missing={missing}, extra={extra}")
    count = 1
    by_uci = {move.uci(): move for move in legal}
    for item in replies:
        if not isinstance(item, dict) or not isinstance(item.get("child"), dict):
            raise ValueError("malformed AND reply")
        move = by_uci[str(item["move"])]
        if item.get("san") != move_to_san(position, move):
            raise ValueError("AND reply SAN does not match the legal move")
        child_position = apply_move(position, move)
        child_key = repetition_key(child_position)
        path_counts[child_key] = path_counts.get(child_key, 0) + 1
        try:
            if child_position.halfmove_clock >= 100 or path_counts[child_key] >= 3:
                raise ValueError("defender has an intended-move draw claim")
            count += _verify_node(child_position, item["child"], attacker, depth + 1, max_plies, path_counts)
        finally:
            path_counts[child_key] -= 1
            if path_counts[child_key] == 0:
                del path_counts[child_key]
    return count


def verify_mate_certificate(certificate: dict[str, Any]) -> dict[str, Any]:
    if certificate.get("$schema") != "ugts-chess-mate-proof-2.0":
        raise ValueError("unsupported mate-proof schema")
    if certificate.get("schema_version") != "2.0.0":
        raise ValueError("unsupported mate-proof schema version")
    if certificate.get("rules_profile") != RULE_PROFILE_ID:
        raise ValueError("unsupported mate-proof rules profile")
    if certificate.get("status") != "proved":
        raise ValueError("only proved certificates can be verified")
    root = Position.from_fen(str(certificate["root_fen"]))
    if certificate.get("root_hash") != state_sha256(root):
        raise ValueError("root hash mismatch")
    attacker_name = certificate.get("attacker")
    attacker = WHITE if attacker_name == "white" else 1 if attacker_name == "black" else -1
    if attacker not in (0, 1):
        raise ValueError("invalid attacker")
    max_plies_value = certificate.get("max_plies")
    if isinstance(max_plies_value, bool) or not isinstance(max_plies_value, int) or max_plies_value < 1:
        raise ValueError("max_plies must be a positive integer")
    max_plies = max_plies_value
    tree = certificate.get("tree")
    if not isinstance(tree, dict):
        raise ValueError("certificate lacks proof tree")
    root_key = repetition_key(root)
    history_record = certificate.get("root_history_counts")
    if not isinstance(history_record, list):
        raise ValueError("root_history_counts must be an explicit list")
    pairs: list[tuple[str, int]] = []
    for item in history_record:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("root_history_counts contains a malformed entry")
        key, count = item
        if not isinstance(key, str) or len(key) != 64 or any(character not in "0123456789abcdef" for character in key):
            raise ValueError("root history repetition key must be a lowercase SHA-256 digest")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
            raise ValueError("root history occurrence counts must be integers in 1..5")
        pairs.append((key, count))
    if pairs != sorted(pairs) or len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("root_history_counts must be unique and sorted")
    path_counts = dict(pairs)
    if path_counts.get(root_key, 0) < 1:
        raise ValueError("root history omits the root position")
    nodes = _verify_node(root, tree, attacker, 0, max_plies, path_counts)
    return {
        "valid": True,
        "verified_nodes": nodes,
        "root_hash": state_sha256(root),
        "attacker": color_name(attacker),
        "max_plies": max_plies,
    }
