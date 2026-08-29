"""Integer-exact area scoring."""

from __future__ import annotations

from dataclasses import dataclass

from .constants import BLACK, EMPTY, WHITE
from .engine import neighbor_table
from .rules import Rules


@dataclass(frozen=True, slots=True)
class AreaScore:
    black_stones: int
    white_stones: int
    black_territory: int
    white_territory: int
    neutral: int
    komi2: int

    @property
    def black_area(self) -> int:
        return self.black_stones + self.black_territory

    @property
    def white_area(self) -> int:
        return self.white_stones + self.white_territory

    @property
    def score2(self) -> int:
        return 2 * (self.black_area - self.white_area) - self.komi2

    @property
    def winner(self) -> str:
        if self.score2 > 0:
            return "black"
        if self.score2 < 0:
            return "white"
        return "draw"


def area_score(board: bytes, rules: Rules) -> AreaScore:
    if type(board) is not bytes:
        raise TypeError("board must be immutable bytes")
    expected = rules.size * rules.size
    if len(board) != expected:
        raise ValueError(f"board has {len(board)} points, expected {expected}")
    if any(point not in (EMPTY, BLACK, WHITE) for point in board):
        raise ValueError("board contains an invalid point value")
    black_stones = board.count(BLACK)
    white_stones = board.count(WHITE)
    black_territory = 0
    white_territory = 0
    neutral = 0
    visited: set[int] = set()
    neighbors = neighbor_table(rules.size)

    for start, value in enumerate(board):
        if value != EMPTY or start in visited:
            continue
        region = {start}
        borders: set[int] = set()
        stack = [start]
        visited.add(start)
        while stack:
            point = stack.pop()
            for adjacent in neighbors[point]:
                adjacent_value = board[adjacent]
                if adjacent_value == EMPTY and adjacent not in visited:
                    visited.add(adjacent)
                    region.add(adjacent)
                    stack.append(adjacent)
                elif adjacent_value in (BLACK, WHITE):
                    borders.add(adjacent_value)
        if borders == {BLACK}:
            black_territory += len(region)
        elif borders == {WHITE}:
            white_territory += len(region)
        else:
            neutral += len(region)

    return AreaScore(
        black_stones=black_stones,
        white_stones=white_stones,
        black_territory=black_territory,
        white_territory=white_territory,
        neutral=neutral,
        komi2=rules.komi2,
    )


def area_score2(board: bytes, rules: Rules) -> int:
    return area_score(board, rules).score2


def possible_area_score2_bounds(rules: Rules) -> tuple[int, int]:
    """Return inclusive score2 extrema implied by board size and komi.

    Area difference is always in ``[-size**2, size**2]``.  Keeping this
    inexpensive envelope explicit lets serialized proof engines reject rule
    tuples whose terminal score arithmetic would overflow a signed-64 verifier.
    """

    points = rules.size * rules.size
    return -2 * points - rules.komi2, 2 * points - rules.komi2
