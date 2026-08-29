"""Core constants and coordinate helpers for UGTS Chess."""
from __future__ import annotations

from typing import Final

WHITE: Final[int] = 0
BLACK: Final[int] = 1
COLORS: Final[tuple[int, int]] = (WHITE, BLACK)

EMPTY: Final[str] = "."
PIECES: Final[str] = "PNBRQKpnbrqk"
WHITE_PIECES: Final[str] = "PNBRQK"
BLACK_PIECES: Final[str] = "pnbrqk"

WK: Final[int] = 1
WQ: Final[int] = 2
BK: Final[int] = 4
BQ: Final[int] = 8
ALL_CASTLING: Final[int] = WK | WQ | BK | BQ

FILES: Final[str] = "abcdefgh"
RANKS: Final[str] = "12345678"

PIECE_VALUES: Final[dict[str, int]] = {
    "P": 100,
    "N": 320,
    "B": 330,
    "R": 500,
    "Q": 900,
    "K": 0,
}

PROMOTIONS: Final[tuple[str, ...]] = ("q", "r", "b", "n")


def opposite(color: int) -> int:
    return BLACK if color == WHITE else WHITE


def piece_color(piece: str) -> int | None:
    if piece in WHITE_PIECES:
        return WHITE
    if piece in BLACK_PIECES:
        return BLACK
    return None


def piece_type(piece: str) -> str:
    return piece.upper()


def square(file_index: int, rank_index: int) -> int:
    if not (0 <= file_index < 8 and 0 <= rank_index < 8):
        raise ValueError(f"square out of range: file={file_index}, rank={rank_index}")
    return rank_index * 8 + file_index


def file_of(sq: int) -> int:
    return sq & 7


def rank_of(sq: int) -> int:
    return sq >> 3


def square_name(sq: int) -> str:
    if not 0 <= sq < 64:
        raise ValueError(f"square out of range: {sq}")
    return FILES[file_of(sq)] + RANKS[rank_of(sq)]


def parse_square(name: str) -> int:
    if len(name) != 2 or name[0] not in FILES or name[1] not in RANKS:
        raise ValueError(f"invalid square: {name!r}")
    return square(FILES.index(name[0]), RANKS.index(name[1]))


def color_name(color: int) -> str:
    if color == WHITE:
        return "white"
    if color == BLACK:
        return "black"
    raise ValueError(f"invalid color: {color}")
