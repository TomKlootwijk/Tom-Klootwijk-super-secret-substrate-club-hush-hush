"""UGTS authority-chain mapping for chess moves and replay lineage."""
from __future__ import annotations

from dataclasses import dataclass

from .constants import EMPTY, color_name, opposite, piece_color, piece_type, square_name
from .hashing import state_sha256
from .move import Move
from .position import Position
from .rules import apply_move, in_check, is_square_attacked, legal_moves, move_to_san


@dataclass(frozen=True, slots=True)
class MoveProposal:
    proposal_id: str
    source_hash: str
    move_uci: str
    side: str
    support_ok: bool
    compatibility_ok: bool
    guard_ok: bool
    reason_codes: tuple[str, ...]

    @property
    def verified(self) -> bool:
        return self.support_ok and self.compatibility_ok and self.guard_ok

    def to_dict(self) -> dict[str, object]:
        return {
            "proposal_id": self.proposal_id,
            "source_hash": self.source_hash,
            "move_uci": self.move_uci,
            "side": self.side,
            "support_ok": self.support_ok,
            "compatibility_ok": self.compatibility_ok,
            "guard_ok": self.guard_ok,
            "verified": self.verified,
            "reason_codes": list(self.reason_codes),
        }


@dataclass(frozen=True, slots=True)
class MoveEvent:
    sequence: int
    proposal_id: str
    move_uci: str
    move_san: str
    pre_hash: str
    post_hash: str
    side: str
    captured_piece: str | None
    promotion: str | None
    check: bool
    lineage_label: str

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "proposal_id": self.proposal_id,
            "move_uci": self.move_uci,
            "move_san": self.move_san,
            "pre_hash": self.pre_hash,
            "post_hash": self.post_hash,
            "side": self.side,
            "captured_piece": self.captured_piece,
            "promotion": self.promotion,
            "check": self.check,
            "lineage_label": self.lineage_label,
        }


def _pseudo_support(position: Position, move: Move) -> bool:
    # The generated legal set is the authoritative implementation. This
    # coarse predicate exists to expose the UGTS stages and reason codes.
    if not (0 <= move.from_sq < 64 and 0 <= move.to_sq < 64):
        return False
    moving = position.board[move.from_sq]
    return moving != EMPTY and move.from_sq != move.to_sq


def propose_move(position: Position, move: Move, *, proposal_id: str | None = None) -> MoveProposal:
    reasons: list[str] = []
    support_ok = _pseudo_support(position, move)
    if not support_ok:
        reasons.append("outside_piece_move_support")
    moving = position.board[move.from_sq] if 0 <= move.from_sq < 64 else EMPTY
    compatibility_ok = support_ok and piece_color(moving) == position.turn
    if not compatibility_ok:
        reasons.append("side_or_occupancy_incompatible")
    legal = legal_moves(position)
    guard_ok = move in legal
    if not guard_ok:
        reasons.append("king_safety_or_special_rule_guard_failed")
    source_hash = state_sha256(position)
    pid = proposal_id or f"move:{source_hash[:12]}:{move.uci()}"
    return MoveProposal(
        proposal_id=pid,
        source_hash=source_hash,
        move_uci=move.uci(),
        side=color_name(position.turn),
        support_ok=support_ok,
        compatibility_ok=compatibility_ok,
        guard_ok=guard_ok,
        reason_codes=tuple(reasons),
    )


def commit_move(position: Position, move: Move, *, sequence: int = 1, proposal_id: str | None = None) -> tuple[Position, MoveEvent]:
    proposal = propose_move(position, move, proposal_id=proposal_id)
    if not proposal.verified:
        raise ValueError(f"unverified move proposal: {proposal.to_dict()}")
    moving = position.board[move.from_sq]
    captured = position.board[move.to_sq]
    if move.is_en_passant:
        captured = "p" if position.turn == 0 else "P"
    san = move_to_san(position, move)
    child = apply_move(position, move)
    event = MoveEvent(
        sequence=sequence,
        proposal_id=proposal.proposal_id,
        move_uci=move.uci(),
        move_san=san,
        pre_hash=proposal.source_hash,
        post_hash=state_sha256(child),
        side=color_name(position.turn),
        captured_piece=None if captured == EMPTY else captured,
        promotion=move.promotion.upper() or None,
        check=in_check(child),
        lineage_label=f"ply:{sequence}:{piece_type(moving)}:{square_name(move.from_sq)}->{square_name(move.to_sq)}",
    )
    return child, event


def replay(initial: Position, events: list[dict[str, object]]) -> Position:
    from .rules import parse_uci_move

    current = initial
    expected_sequence = 1
    for record in events:
        sequence = int(record["sequence"])
        if sequence != expected_sequence:
            raise ValueError(f"event sequence discontinuity: expected {expected_sequence}, got {sequence}")
        if record.get("pre_hash") != state_sha256(current):
            raise ValueError(f"pre-state hash mismatch at sequence {sequence}")
        move = parse_uci_move(current, str(record["move_uci"]))
        current, event = commit_move(current, move, sequence=sequence, proposal_id=str(record.get("proposal_id") or ""))
        if record.get("post_hash") != event.post_hash:
            raise ValueError(f"post-state hash mismatch at sequence {sequence}")
        expected_sequence += 1
    return current
