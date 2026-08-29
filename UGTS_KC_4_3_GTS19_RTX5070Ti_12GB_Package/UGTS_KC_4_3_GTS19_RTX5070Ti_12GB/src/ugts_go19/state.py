"""Immutable Go state with exact repetition context."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import BLACK
from .rules import Rules


def repetition_token(board: bytes, next_to_play: int, rules: Rules) -> bytes:
    if rules.superko == "situational_superko":
        return board + bytes((next_to_play,))
    return board


@dataclass(frozen=True, slots=True)
class State:
    board: bytes
    to_play: int
    passes: int
    seen: frozenset[bytes]
    previous_board: bytes | None
    ply: int = 0

    @classmethod
    def initial(cls, rules: Rules) -> "State":
        board = bytes(rules.size * rules.size)
        token = repetition_token(board, BLACK, rules)
        return cls(
            board=board,
            to_play=BLACK,
            passes=0,
            seen=frozenset((token,)),
            previous_board=None,
            ply=0,
        )

    def is_terminal(self, rules: Rules) -> bool:
        return self.passes >= rules.passes_to_end

    def validate(self, rules: Rules) -> None:
        expected = rules.size * rules.size
        if len(self.board) != expected:
            raise ValueError(f"board has {len(self.board)} points, expected {expected}")
        if self.to_play not in (1, 2):
            raise ValueError("to_play must be 1 (black) or 2 (white)")
        if self.passes < 0:
            raise ValueError("passes cannot be negative")
        if any(point not in (0, 1, 2) for point in self.board):
            raise ValueError("board contains an invalid point value")

    def exact_key(self) -> tuple:
        """Collision-free state key for correctness-first reference search."""
        return (
            self.board,
            self.to_play,
            self.passes,
            self.previous_board,
            tuple(sorted(self.seen)),
        )
