"""History-correct classical-chess state identity and draw-claim semantics.

Chess 1.0 treated claimable draws as terminal when requested.  Chess 2.0
models them as optional legal actions: a player may claim a draw, but may
continue when a winning continuation exists.  Automatic fivefold repetition,
75-move draws, stalemate, checkmate, and the implemented exact dead-position
subset remain terminal.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
from typing import Iterable

from .hashing import canonical_json_bytes, repetition_key, repetition_record
from .position import Position
from .rules import in_check, insufficient_material, legal_moves
from .constants import opposite

RULE_PROFILE_ID = "fide-classical-2023-claims-as-actions-v2"


@dataclass(frozen=True, slots=True)
class HistoryContext:
    """Exact repetition-count context for the explored line.

    Counts, not a 64-bit checksum, are authoritative for repetition.  The
    ordered move/event lineage lives separately; the game-theoretic rule only
    needs the number of occurrences of each FIDE repetition identity.
    """

    counts: tuple[tuple[str, int], ...]

    @classmethod
    def initial(cls, position: Position) -> "HistoryContext":
        return cls(((repetition_key(position), 1),))

    @classmethod
    def from_keys(cls, keys: Iterable[str]) -> "HistoryContext":
        counter = Counter(keys)
        return cls(tuple(sorted((key, int(value)) for key, value in counter.items() if value > 0)))

    def as_counter(self) -> Counter[str]:
        return Counter(dict(self.counts))

    def occurrence(self, position: Position) -> int:
        key = repetition_key(position)
        for candidate, count in self.counts:
            if candidate == key:
                return count
        return 0

    def push(self, position: Position) -> "HistoryContext":
        counter = self.as_counter()
        counter[repetition_key(position)] += 1
        return HistoryContext(tuple(sorted(counter.items())))

    def record(self) -> list[list[object]]:
        return [[key, count] for key, count in self.counts]

    def digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.record())).hexdigest()


def validate_history_reachability(position: Position, history: HistoryContext) -> None:
    """Reject count summaries that necessarily describe play after game end.

    ``HistoryContext`` intentionally stores unordered repetition counts, not a
    chronological game score.  It therefore cannot prove full historical
    reachability.  It can prove one important state impossible: once any
    position has occurred five times, the automatic fivefold draw ends the
    game while that position is current, so it cannot later appear as a
    non-current history entry.

    A count of five for the current position remains admissible here.  The
    caller must pass it through ``automatic_status`` so checkmate/stalemate
    precedence and automatic-draw semantics are applied normally.
    """

    if not isinstance(position, Position):
        raise TypeError("position must be a Position")
    if not isinstance(history, HistoryContext):
        raise TypeError("history must be a HistoryContext")
    current_key = repetition_key(position)
    if history.occurrence(position) < 1:
        raise ValueError("history context does not contain the current position")
    for key, count in history.counts:
        if key != current_key and count >= 5:
            raise ValueError(
                "history contains a non-current position at five occurrences; "
                "the game had already ended automatically"
            )


@dataclass(frozen=True, slots=True)
class AutomaticStatus:
    terminal: bool
    code: str
    winner: int | None = None
    detail: str = ""

    def record(self) -> dict[str, object]:
        return {
            "terminal": self.terminal,
            "code": self.code,
            "winner": self.winner,
            "detail": self.detail,
        }


def automatic_status(position: Position, history: HistoryContext) -> AutomaticStatus:
    """Return only forced terminal outcomes under the declared FIDE profile."""

    moves = legal_moves(position)
    if not moves:
        if in_check(position):
            return AutomaticStatus(True, "checkmate", opposite(position.turn), "in check with no legal move")
        return AutomaticStatus(True, "stalemate", None, "not in check with no legal move")
    if insufficient_material(position):
        return AutomaticStatus(True, "dead_position", None, "implemented exact dead-position subset")
    # Checkmate already took precedence above, matching FIDE 9.6.2.
    if position.halfmove_clock >= 150:
        return AutomaticStatus(True, "seventy_five_move", None, "automatic 75-move draw")
    if history.occurrence(position) >= 5:
        return AutomaticStatus(True, "fivefold_repetition", None, "automatic fivefold draw")
    return AutomaticStatus(False, "ongoing")


def current_claim_actions(position: Position, history: HistoryContext) -> tuple[str, ...]:
    """Return draw claims immediately available in the current position."""

    actions: list[str] = []
    if history.occurrence(position) >= 3:
        actions.append("claim_threefold_current")
    if position.halfmove_clock >= 100:
        actions.append("claim_fifty_move_current")
    return tuple(actions)


def intended_move_claims(child: Position, child_history: HistoryContext) -> tuple[str, ...]:
    """Return claims available by declaring the move that creates ``child``.

    FIDE Articles 9.2.1 and 9.3.1 permit a player to claim before executing an
    intended move that would produce the third repetition or complete the
    50-move threshold.  For game value this is a draw action owned by the
    mover, not a forced terminal child.
    """

    actions: list[str] = []
    if child_history.occurrence(child) >= 3:
        actions.append("claim_threefold_by_move")
    if child.halfmove_clock >= 100:
        actions.append("claim_fifty_move_by_move")
    return tuple(actions)


def game_state_record(position: Position, history: HistoryContext) -> dict[str, object]:
    """Return the game-theoretic rule state used for proof identity.

    ``fullmove_number`` is FEN/replay metadata and does not alter legal actions or
    terminal rules, so it is intentionally excluded.  En-passant is normalized
    through the same FIDE legal-right test used by repetition identity.  The
    exact serialized FEN and full position hash remain available beside this
    semantic proof-state hash in obligations and lineage records.
    """

    rule_position = repetition_record(position)
    rule_position["halfmove_clock"] = min(position.halfmove_clock, 150)
    return {
        "rule_profile": RULE_PROFILE_ID,
        "position": rule_position,
        "history_counts": history.record(),
    }


def game_state_sha256(position: Position, history: HistoryContext) -> str:
    return hashlib.sha256(canonical_json_bytes(game_state_record(position, history))).hexdigest()
