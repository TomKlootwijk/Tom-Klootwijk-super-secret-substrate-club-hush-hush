"""Immutable Go state with exact repetition context."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import BLACK, WHITE
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
        if type(self.board) is not bytes:
            raise TypeError("board must be immutable bytes")
        if len(self.board) != expected:
            raise ValueError(f"board has {len(self.board)} points, expected {expected}")
        if type(self.to_play) is not int:
            raise TypeError("to_play must be an integer")
        if self.to_play not in (1, 2):
            raise ValueError("to_play must be 1 (black) or 2 (white)")
        if type(self.passes) is not int:
            raise TypeError("passes must be an integer")
        if not 0 <= self.passes <= rules.passes_to_end:
            raise ValueError(
                f"passes must be in 0..{rules.passes_to_end} for a reachable state"
            )
        if type(self.ply) is not int:
            raise TypeError("ply must be an integer")
        if self.ply < 0:
            raise ValueError("ply cannot be negative")
        if any(point not in (0, 1, 2) for point in self.board):
            raise ValueError("board contains an invalid point value")
        if self.previous_board is not None:
            if type(self.previous_board) is not bytes:
                raise TypeError("previous_board must be immutable bytes or None")
            if len(self.previous_board) != expected:
                raise ValueError("previous_board length does not match board size")
            if any(point not in (0, 1, 2) for point in self.previous_board):
                raise ValueError("previous_board contains an invalid point value")

        if type(self.seen) is not frozenset:
            raise TypeError("seen must be a frozenset of immutable byte tokens")
        token_length = expected + (1 if rules.superko == "situational_superko" else 0)
        for token in self.seen:
            if type(token) is not bytes:
                raise TypeError("repetition tokens must be immutable bytes")
            if len(token) != token_length:
                raise ValueError("repetition token length does not match rules")
            if any(point not in (0, 1, 2) for point in token[:expected]):
                raise ValueError("repetition token contains an invalid point value")
            if rules.superko == "situational_superko" and token[-1] not in (
                BLACK,
                WHITE,
            ):
                raise ValueError("situational-superko token has invalid player")
        if rules.superko in {"positional_superko", "situational_superko"}:
            current_token = repetition_token(self.board, self.to_play, rules)
            if current_token not in self.seen:
                raise ValueError("superko history must contain current state token")
            if self.previous_board is not None:
                previous_to_play = WHITE if self.to_play == BLACK else BLACK
                previous_token = repetition_token(
                    self.previous_board, previous_to_play, rules
                )
                if previous_token not in self.seen:
                    raise ValueError("superko history must contain the previous board")

    def exact_key(self) -> tuple:
        """Collision-free state key for correctness-first reference search."""
        return (
            self.board,
            self.to_play,
            self.passes,
            self.previous_board,
            tuple(sorted(self.seen)),
        )
