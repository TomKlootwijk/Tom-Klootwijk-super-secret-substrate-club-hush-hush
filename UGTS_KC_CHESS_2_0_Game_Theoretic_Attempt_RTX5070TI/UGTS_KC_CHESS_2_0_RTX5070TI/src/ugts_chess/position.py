"""Immutable chess position, FEN parsing and canonical records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .constants import (
    ALL_CASTLING,
    BK,
    BQ,
    EMPTY,
    PIECES,
    WHITE,
    BLACK,
    WK,
    WQ,
    color_name,
    parse_square,
    piece_color,
    rank_of,
    square_name,
)

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

_CASTLE_TO_CHAR = ((WK, "K"), (WQ, "Q"), (BK, "k"), (BQ, "q"))
_CHAR_TO_CASTLE = {char: bit for bit, char in _CASTLE_TO_CHAR}


@dataclass(frozen=True, slots=True)
class Position:
    board: tuple[str, ...]
    turn: int = WHITE
    castling: int = ALL_CASTLING
    ep_square: int = -1
    halfmove_clock: int = 0
    fullmove_number: int = 1

    def __post_init__(self) -> None:
        if len(self.board) != 64:
            raise ValueError(f"board must contain 64 squares, got {len(self.board)}")
        if any(piece != EMPTY and piece not in PIECES for piece in self.board):
            bad = [piece for piece in self.board if piece != EMPTY and piece not in PIECES]
            raise ValueError(f"invalid board pieces: {bad}")
        if self.turn not in (WHITE, BLACK):
            raise ValueError("turn must be WHITE or BLACK")
        if self.castling & ~ALL_CASTLING:
            raise ValueError("castling mask has unsupported bits")
        if self.ep_square != -1 and not 0 <= self.ep_square < 64:
            raise ValueError("en-passant square out of range")
        if self.ep_square != -1 and rank_of(self.ep_square) not in (2, 5):
            raise ValueError("en-passant target must be on rank 3 or 6")
        if self.halfmove_clock < 0:
            raise ValueError("halfmove clock must be non-negative")
        if self.fullmove_number < 1:
            raise ValueError("fullmove number must be at least 1")

    @classmethod
    def initial(cls) -> "Position":
        return cls.from_fen(START_FEN)

    @classmethod
    def from_fen(cls, fen: str, *, strict: bool = True) -> "Position":
        fields = fen.strip().split()
        if len(fields) != 6:
            raise ValueError("FEN must contain exactly six fields")
        placement, turn_token, castling_token, ep_token, half_token, full_token = fields

        rows = placement.split("/")
        if len(rows) != 8:
            raise ValueError("FEN placement must contain eight ranks")
        board = [EMPTY] * 64
        for fen_rank, row in enumerate(rows):
            rank = 7 - fen_rank
            file_index = 0
            for char in row:
                if char.isdigit():
                    count = int(char)
                    if count < 1 or count > 8:
                        raise ValueError("FEN empty-square run must be 1..8")
                    file_index += count
                elif char in PIECES:
                    if file_index >= 8:
                        raise ValueError("FEN rank overflows eight files")
                    board[rank * 8 + file_index] = char
                    file_index += 1
                else:
                    raise ValueError(f"invalid FEN placement token: {char!r}")
            if file_index != 8:
                raise ValueError(f"FEN rank {8 - fen_rank} expands to {file_index}, not 8")

        if turn_token == "w":
            turn = WHITE
        elif turn_token == "b":
            turn = BLACK
        else:
            raise ValueError("FEN side-to-move field must be w or b")

        castling = 0
        if castling_token != "-":
            seen: set[str] = set()
            for char in castling_token:
                if char not in _CHAR_TO_CASTLE or char in seen:
                    raise ValueError(f"invalid castling rights: {castling_token!r}")
                seen.add(char)
                castling |= _CHAR_TO_CASTLE[char]

        ep_square = -1 if ep_token == "-" else parse_square(ep_token)
        try:
            halfmove = int(half_token)
            fullmove = int(full_token)
        except ValueError as exc:
            raise ValueError("FEN move counters must be integers") from exc

        position = cls(tuple(board), turn, castling, ep_square, halfmove, fullmove)
        if strict:
            position.validate_structure()
        return position

    def validate_structure(self) -> None:
        if self.board.count("K") != 1 or self.board.count("k") != 1:
            raise ValueError("position must contain exactly one white king and one black king")
        for sq, piece in enumerate(self.board):
            if piece.upper() == "P" and rank_of(sq) in (0, 7):
                raise ValueError("pawns may not remain on the first or eighth rank")
        # Castling rights may only name kings/rooks on their home squares.
        expected = {
            WK: (4, "K", 7, "R"),
            WQ: (4, "K", 0, "R"),
            BK: (60, "k", 63, "r"),
            BQ: (60, "k", 56, "r"),
        }
        for bit, (king_sq, king, rook_sq, rook) in expected.items():
            if self.castling & bit and (self.board[king_sq] != king or self.board[rook_sq] != rook):
                raise ValueError(f"castling right {bit} conflicts with board placement")
        if self.ep_square != -1:
            expected_rank = 5 if self.turn == WHITE else 2
            if rank_of(self.ep_square) != expected_rank:
                raise ValueError("en-passant target rank conflicts with side to move")

    def king_square(self, color: int) -> int:
        king = "K" if color == WHITE else "k"
        try:
            return self.board.index(king)
        except ValueError as exc:
            raise ValueError(f"missing {color_name(color)} king") from exc

    def piece_at(self, sq: int) -> str:
        return self.board[sq]

    def pieces(self, color: int | None = None) -> Iterable[tuple[int, str]]:
        for sq, piece in enumerate(self.board):
            if piece == EMPTY:
                continue
            if color is None or piece_color(piece) == color:
                yield sq, piece

    def to_fen(self) -> str:
        ranks: list[str] = []
        for rank in range(7, -1, -1):
            run = 0
            chunks: list[str] = []
            for file_index in range(8):
                piece = self.board[rank * 8 + file_index]
                if piece == EMPTY:
                    run += 1
                else:
                    if run:
                        chunks.append(str(run))
                        run = 0
                    chunks.append(piece)
            if run:
                chunks.append(str(run))
            ranks.append("".join(chunks))
        castling = "".join(char for bit, char in _CASTLE_TO_CHAR if self.castling & bit) or "-"
        ep = "-" if self.ep_square == -1 else square_name(self.ep_square)
        turn = "w" if self.turn == WHITE else "b"
        return f"{'/'.join(ranks)} {turn} {castling} {ep} {self.halfmove_clock} {self.fullmove_number}"

    def state_record(self, *, include_counters: bool = True) -> dict[str, object]:
        record: dict[str, object] = {
            "board": "".join(self.board),
            "turn": "white" if self.turn == WHITE else "black",
            "castling": "".join(char for bit, char in _CASTLE_TO_CHAR if self.castling & bit),
            "ep_square": None if self.ep_square == -1 else square_name(self.ep_square),
        }
        if include_counters:
            record["halfmove_clock"] = self.halfmove_clock
            record["fullmove_number"] = self.fullmove_number
        return record

    def ascii(self, *, coordinates: bool = True) -> str:
        rows: list[str] = []
        for rank in range(7, -1, -1):
            contents = " ".join(self.board[rank * 8 : rank * 8 + 8])
            rows.append(f"{rank + 1}  {contents}" if coordinates else contents)
        if coordinates:
            rows.append("   a b c d e f g h")
        return "\n".join(rows)

    def with_board(self, board: list[str] | tuple[str, ...], **changes: object) -> "Position":
        data = {
            "board": tuple(board),
            "turn": self.turn,
            "castling": self.castling,
            "ep_square": self.ep_square,
            "halfmove_clock": self.halfmove_clock,
            "fullmove_number": self.fullmove_number,
        }
        data.update(changes)
        return Position(**data)  # type: ignore[arg-type]
