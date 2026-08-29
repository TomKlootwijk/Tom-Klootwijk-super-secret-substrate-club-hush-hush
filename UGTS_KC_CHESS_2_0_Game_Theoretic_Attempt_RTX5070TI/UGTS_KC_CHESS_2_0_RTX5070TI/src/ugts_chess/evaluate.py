"""Deterministic classical evaluation for bounded forward search."""
from __future__ import annotations

from .constants import BLACK, EMPTY, PIECE_VALUES, WHITE, file_of, piece_color, piece_type, rank_of
from .position import Position

# Small, transparent heuristics. Search correctness for mate scores does not
# depend on these values; they only order non-terminal choices.
CENTER = (27, 28, 35, 36)
EXTENDED_CENTER = (18, 19, 20, 21, 26, 29, 34, 37, 42, 43, 44, 45)


def _piece_square(piece: str, sq: int) -> int:
    kind = piece_type(piece)
    color = piece_color(piece)
    assert color is not None
    rank = rank_of(sq) if color == WHITE else 7 - rank_of(sq)
    file_index = file_of(sq)
    score = 0
    if sq in CENTER:
        score += 18
    elif sq in EXTENDED_CENTER:
        score += 8
    if kind == "P":
        score += rank * 9
        if file_index in (3, 4):
            score += 6
    elif kind == "N":
        score += 4 * (3 - abs(3.5 - file_index)) + 4 * (3 - abs(3.5 - rank))
    elif kind == "B":
        score += 3 * rank
    elif kind == "R":
        score += 2 * rank
    elif kind == "Q":
        score += 1 * rank
    elif kind == "K":
        # Prefer shelter in the opening/middlegame; endgame centralization is
        # deliberately left to search and tablebases.
        score -= 4 * max(0, rank - 1)
    return int(score)


def evaluate_white(position: Position) -> int:
    score = 0
    bishops = {WHITE: 0, BLACK: 0}
    for sq, piece in enumerate(position.board):
        if piece == EMPTY:
            continue
        color = piece_color(piece)
        assert color is not None
        value = PIECE_VALUES[piece_type(piece)] + _piece_square(piece, sq)
        if piece_type(piece) == "B":
            bishops[color] += 1
        score += value if color == WHITE else -value
    if bishops[WHITE] >= 2:
        score += 25
    if bishops[BLACK] >= 2:
        score -= 25
    return score


def evaluate(position: Position) -> int:
    score = evaluate_white(position)
    return score if position.turn == WHITE else -score
