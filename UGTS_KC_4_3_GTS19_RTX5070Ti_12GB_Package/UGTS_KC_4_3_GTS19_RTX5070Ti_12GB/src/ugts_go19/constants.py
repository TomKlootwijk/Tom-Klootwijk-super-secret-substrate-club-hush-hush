"""Core constants and coordinate conversion."""

from __future__ import annotations

EMPTY = 0
BLACK = 1
WHITE = 2
PASS = -1

_GO_COLUMNS = "ABCDEFGHJKLMNOPQRST"  # I is omitted by Go convention.


def other(color: int) -> int:
    if color == BLACK:
        return WHITE
    if color == WHITE:
        return BLACK
    raise ValueError(f"invalid color: {color}")


def color_name(color: int) -> str:
    if color == BLACK:
        return "black"
    if color == WHITE:
        return "white"
    if color == EMPTY:
        return "empty"
    raise ValueError(f"invalid color: {color}")


def move_to_coord(move: int, size: int) -> str:
    if move == PASS:
        return "pass"
    if not 0 <= move < size * size:
        raise ValueError(f"move {move} outside {size}x{size}")
    x = move % size
    y = move // size
    if size > len(_GO_COLUMNS):
        return f"({x},{y})"
    return f"{_GO_COLUMNS[x]}{size - y}"


def coord_to_move(coord: str, size: int) -> int:
    text = coord.strip().upper()
    if text in {"PASS", "P"}:
        return PASS
    if text.startswith("(") and text.endswith(")"):
        x_text, y_text = text[1:-1].split(",", 1)
        x, y = int(x_text), int(y_text)
    else:
        if len(text) < 2:
            raise ValueError(f"invalid coordinate: {coord!r}")
        column = text[0]
        if column not in _GO_COLUMNS[:size]:
            raise ValueError(f"invalid coordinate column: {column}")
        x = _GO_COLUMNS.index(column)
        row = int(text[1:])
        y = size - row
    if not (0 <= x < size and 0 <= y < size):
        raise ValueError(f"coordinate outside {size}x{size}: {coord!r}")
    return y * size + x
