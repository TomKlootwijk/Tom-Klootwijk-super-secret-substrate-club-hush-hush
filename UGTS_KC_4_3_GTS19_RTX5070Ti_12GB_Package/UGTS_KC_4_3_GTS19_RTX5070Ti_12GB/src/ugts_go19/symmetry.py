"""D4 board symmetries, including exact-history canonicalization."""

from __future__ import annotations

from .rules import Rules
from .state import State


def transform_xy(x: int, y: int, size: int, symmetry: int) -> tuple[int, int]:
    n = size - 1
    if symmetry == 0:   # identity
        return x, y
    if symmetry == 1:   # rotate 90
        return n - y, x
    if symmetry == 2:   # rotate 180
        return n - x, n - y
    if symmetry == 3:   # rotate 270
        return y, n - x
    if symmetry == 4:   # mirror vertical axis
        return n - x, y
    if symmetry == 5:   # mirror then rotate 90
        return n - y, n - x
    if symmetry == 6:   # mirror horizontal axis
        return x, n - y
    if symmetry == 7:   # main diagonal
        return y, x
    raise ValueError("symmetry must be in 0..7")


def transform_move(move: int, size: int, symmetry: int) -> int:
    if move < 0:
        return move
    x, y = move % size, move // size
    tx, ty = transform_xy(x, y, size, symmetry)
    return ty * size + tx


def transform_board(board: bytes, size: int, symmetry: int) -> bytes:
    out = bytearray(len(board))
    for point, value in enumerate(board):
        x, y = point % size, point // size
        tx, ty = transform_xy(x, y, size, symmetry)
        out[ty * size + tx] = value
    return bytes(out)


def transform_token(token: bytes, rules: Rules, symmetry: int) -> bytes:
    points = rules.size * rules.size
    if len(token) == points:
        return transform_board(token, rules.size, symmetry)
    if len(token) == points + 1:
        return transform_board(token[:points], rules.size, symmetry) + token[-1:]
    raise ValueError("unexpected repetition token length")


def state_key_under_symmetry(state: State, rules: Rules, symmetry: int) -> tuple:
    board = transform_board(state.board, rules.size, symmetry)
    seen = tuple(sorted(transform_token(token, rules, symmetry) for token in state.seen))
    previous = (
        transform_board(state.previous_board, rules.size, symmetry)
        if state.previous_board is not None
        else None
    )
    return board, state.to_play, state.passes, previous, seen


def canonical_state_key(state: State, rules: Rules) -> tuple:
    return min(state_key_under_symmetry(state, rules, symmetry) for symmetry in range(8))
