"""Game-theoretic proof obligations for classical chess.

The records separate position identity from history-correct game-state identity.
A 64-bit cache key or a heuristic score can prioritize work, but only a verified
certificate may set an obligation's WDL value.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .game_state import HistoryContext, game_state_sha256
from .hashing import state_sha256
from .position import Position, START_FEN
from .rules import apply_move, legal_moves, move_to_san


class WDL(str, Enum):
    WIN = "win"
    DRAW = "draw"
    LOSS = "loss"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProofObligation:
    obligation_id: str
    parent_fen: str
    parent_position_sha256: str
    parent_game_state_sha256: str
    parent_history_counts: tuple[tuple[str, int], ...]
    move_uci: str
    move_san: str
    child_fen: str
    child_position_sha256: str
    child_game_state_sha256: str
    child_history_counts: tuple[tuple[str, int], ...]
    child_side_to_move: str
    wdl: WDL = WDL.UNKNOWN
    verification: str = "unverified"

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": "ugts-chess-proof-obligation-2.0",
            "obligation_id": self.obligation_id,
            "parent": {
                "fen": self.parent_fen,
                "position_sha256": self.parent_position_sha256,
                "game_state_sha256": self.parent_game_state_sha256,
                "history_counts": [[key, count] for key, count in self.parent_history_counts],
            },
            "action": {"kind": "move", "uci": self.move_uci, "san": self.move_san},
            "child": {
                "fen": self.child_fen,
                "position_sha256": self.child_position_sha256,
                "game_state_sha256": self.child_game_state_sha256,
                "history_counts": [[key, count] for key, count in self.child_history_counts],
                "side_to_move": self.child_side_to_move,
            },
            "wdl": self.wdl.value,
            "verification": self.verification,
            "target": "exact-full-game-WDL-under-declared-FIDE-profile",
            "proof_rule": (
                "The child WDL is from the child side-to-move perspective. "
                "It becomes authoritative only after an independent checker accepts a complete certificate."
            ),
        }


def root_obligations(
    position: Position | None = None,
    history: HistoryContext | None = None,
) -> list[ProofObligation]:
    position = position or Position.from_fen(START_FEN)
    history = history or HistoryContext.initial(position)
    parent_position_hash = state_sha256(position)
    parent_game_hash = game_state_sha256(position, history)
    obligations: list[ProofObligation] = []
    moves = sorted(legal_moves(position), key=lambda move: move.uci())
    for index, move in enumerate(moves, start=1):
        child = apply_move(position, move)
        child_history = history.push(child)
        obligations.append(
            ProofObligation(
                obligation_id=f"root-{index:02d}-{move.uci()}",
                parent_fen=position.to_fen(),
                parent_position_sha256=parent_position_hash,
                parent_game_state_sha256=parent_game_hash,
                parent_history_counts=history.counts,
                move_uci=move.uci(),
                move_san=move_to_san(position, move),
                child_fen=child.to_fen(),
                child_position_sha256=state_sha256(child),
                child_game_state_sha256=game_state_sha256(child, child_history),
                child_history_counts=child_history.counts,
                child_side_to_move="white" if child.turn == 0 else "black",
            )
        )
    return obligations


def aggregate_root_wdl(child_outcomes: Iterable[WDL | str]) -> WDL:
    """Aggregate initial-position children into the root WDL.

    Child values are from the child side-to-move perspective.  Therefore one
    verified child LOSS proves a root WIN.  Root LOSS or DRAW requires every
    child to be resolved; UNKNOWN is otherwise contagious.
    """

    values = [value if isinstance(value, WDL) else WDL(value) for value in child_outcomes]
    if not values:
        return WDL.UNKNOWN
    if any(value == WDL.LOSS for value in values):
        return WDL.WIN
    if any(value == WDL.UNKNOWN for value in values):
        return WDL.UNKNOWN
    if all(value == WDL.WIN for value in values):
        return WDL.LOSS
    if any(value == WDL.DRAW for value in values):
        return WDL.DRAW
    return WDL.UNKNOWN
