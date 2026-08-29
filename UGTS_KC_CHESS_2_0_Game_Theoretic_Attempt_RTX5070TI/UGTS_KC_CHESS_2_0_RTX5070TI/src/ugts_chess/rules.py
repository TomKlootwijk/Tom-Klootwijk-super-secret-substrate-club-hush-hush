"""FIDE-style legal move kernel and deterministic transitions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Iterator

from .constants import (
    BK,
    BLACK,
    BQ,
    EMPTY,
    PROMOTIONS,
    WHITE,
    WK,
    WQ,
    file_of,
    opposite,
    piece_color,
    piece_type,
    rank_of,
    square_name,
)
from .hashing import repetition_key
from .move import (
    FLAG_CAPTURE,
    FLAG_CASTLE,
    FLAG_DOUBLE_PAWN,
    FLAG_EN_PASSANT,
    FLAG_PROMOTION,
    Move,
)
from .position import Position

KNIGHT_DELTAS = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
KING_DELTAS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ROOK_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
QUEEN_DIRS = BISHOP_DIRS + ROOK_DIRS


@dataclass(frozen=True, slots=True)
class PositionStatus:
    terminal: bool
    code: str
    winner: int | None = None
    claimable: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "terminal": self.terminal,
            "code": self.code,
            "winner": None if self.winner is None else ("white" if self.winner == WHITE else "black"),
            "claimable": self.claimable,
            "detail": self.detail,
        }


def _inside(file_index: int, rank_index: int) -> bool:
    return 0 <= file_index < 8 and 0 <= rank_index < 8


def is_square_attacked(position: Position, sq: int, by_color: int) -> bool:
    board = position.board
    file_index = file_of(sq)
    rank = rank_of(sq)

    # Pawns: look backward from the target to possible attackers.
    pawn = "P" if by_color == WHITE else "p"
    source_rank = rank - 1 if by_color == WHITE else rank + 1
    for source_file in (file_index - 1, file_index + 1):
        if _inside(source_file, source_rank) and board[source_rank * 8 + source_file] == pawn:
            return True

    knight = "N" if by_color == WHITE else "n"
    for df, dr in KNIGHT_DELTAS:
        f, r = file_index + df, rank + dr
        if _inside(f, r) and board[r * 8 + f] == knight:
            return True

    king = "K" if by_color == WHITE else "k"
    for df, dr in KING_DELTAS:
        f, r = file_index + df, rank + dr
        if _inside(f, r) and board[r * 8 + f] == king:
            return True

    bishop = "B" if by_color == WHITE else "b"
    rook = "R" if by_color == WHITE else "r"
    queen = "Q" if by_color == WHITE else "q"
    for df, dr in BISHOP_DIRS:
        f, r = file_index + df, rank + dr
        while _inside(f, r):
            piece = board[r * 8 + f]
            if piece != EMPTY:
                if piece in (bishop, queen):
                    return True
                break
            f += df
            r += dr
    for df, dr in ROOK_DIRS:
        f, r = file_index + df, rank + dr
        while _inside(f, r):
            piece = board[r * 8 + f]
            if piece != EMPTY:
                if piece in (rook, queen):
                    return True
                break
            f += df
            r += dr
    return False


def in_check(position: Position, color: int | None = None) -> bool:
    color = position.turn if color is None else color
    return is_square_attacked(position, position.king_square(color), opposite(color))


def _add_pawn_moves(position: Position, sq: int, piece: str, out: list[Move]) -> None:
    color = piece_color(piece)
    assert color is not None
    board = position.board
    file_index, rank = file_of(sq), rank_of(sq)
    direction = 1 if color == WHITE else -1
    step = direction * 8
    start_rank = 1 if color == WHITE else 6
    promotion_from_rank = 6 if color == WHITE else 1

    one = sq + step
    if 0 <= one < 64 and board[one] == EMPTY:
        if rank == promotion_from_rank:
            for promotion in PROMOTIONS:
                out.append(Move(sq, one, promotion, FLAG_PROMOTION))
        else:
            out.append(Move(sq, one))
            two = sq + 2 * step
            if rank == start_rank and board[two] == EMPTY:
                out.append(Move(sq, two, flags=FLAG_DOUBLE_PAWN))

    target_rank = rank + direction
    if not 0 <= target_rank < 8:
        return
    for df in (-1, 1):
        target_file = file_index + df
        if not 0 <= target_file < 8:
            continue
        target = target_rank * 8 + target_file
        target_piece = board[target]
        if target_piece != EMPTY and piece_color(target_piece) == opposite(color) and piece_type(target_piece) != "K":
            flags = FLAG_CAPTURE
            if rank == promotion_from_rank:
                flags |= FLAG_PROMOTION
                for promotion in PROMOTIONS:
                    out.append(Move(sq, target, promotion, flags))
            else:
                out.append(Move(sq, target, flags=flags))
        elif target == position.ep_square:
            captured_sq = target - step
            expected = "p" if color == WHITE else "P"
            if board[captured_sq] == expected:
                out.append(Move(sq, target, flags=FLAG_CAPTURE | FLAG_EN_PASSANT))


def _add_leaper_moves(position: Position, sq: int, piece: str, deltas: Iterable[tuple[int, int]], out: list[Move]) -> None:
    color = piece_color(piece)
    assert color is not None
    board = position.board
    file_index, rank = file_of(sq), rank_of(sq)
    for df, dr in deltas:
        f, r = file_index + df, rank + dr
        if not _inside(f, r):
            continue
        target = r * 8 + f
        occupant = board[target]
        if occupant == EMPTY:
            out.append(Move(sq, target))
        elif piece_color(occupant) == opposite(color) and piece_type(occupant) != "K":
            out.append(Move(sq, target, flags=FLAG_CAPTURE))


def _add_slider_moves(position: Position, sq: int, piece: str, directions: Iterable[tuple[int, int]], out: list[Move]) -> None:
    color = piece_color(piece)
    assert color is not None
    board = position.board
    file_index, rank = file_of(sq), rank_of(sq)
    for df, dr in directions:
        f, r = file_index + df, rank + dr
        while _inside(f, r):
            target = r * 8 + f
            occupant = board[target]
            if occupant == EMPTY:
                out.append(Move(sq, target))
            else:
                if piece_color(occupant) == opposite(color) and piece_type(occupant) != "K":
                    out.append(Move(sq, target, flags=FLAG_CAPTURE))
                break
            f += df
            r += dr


def _add_castling(position: Position, sq: int, piece: str, out: list[Move]) -> None:
    color = piece_color(piece)
    assert color is not None
    board = position.board
    enemy = opposite(color)
    if color == WHITE and sq == 4 and piece == "K":
        if position.castling & WK:
            if board[5] == board[6] == EMPTY and board[7] == "R":
                if not any(is_square_attacked(position, s, enemy) for s in (4, 5, 6)):
                    out.append(Move(4, 6, flags=FLAG_CASTLE))
        if position.castling & WQ:
            if board[1] == board[2] == board[3] == EMPTY and board[0] == "R":
                if not any(is_square_attacked(position, s, enemy) for s in (4, 3, 2)):
                    out.append(Move(4, 2, flags=FLAG_CASTLE))
    elif color == BLACK and sq == 60 and piece == "k":
        if position.castling & BK:
            if board[61] == board[62] == EMPTY and board[63] == "r":
                if not any(is_square_attacked(position, s, enemy) for s in (60, 61, 62)):
                    out.append(Move(60, 62, flags=FLAG_CASTLE))
        if position.castling & BQ:
            if board[57] == board[58] == board[59] == EMPTY and board[56] == "r":
                if not any(is_square_attacked(position, s, enemy) for s in (60, 59, 58)):
                    out.append(Move(60, 58, flags=FLAG_CASTLE))


def pseudo_legal_moves(position: Position) -> list[Move]:
    out: list[Move] = []
    for sq, piece in position.pieces(position.turn):
        kind = piece_type(piece)
        if kind == "P":
            _add_pawn_moves(position, sq, piece, out)
        elif kind == "N":
            _add_leaper_moves(position, sq, piece, KNIGHT_DELTAS, out)
        elif kind == "B":
            _add_slider_moves(position, sq, piece, BISHOP_DIRS, out)
        elif kind == "R":
            _add_slider_moves(position, sq, piece, ROOK_DIRS, out)
        elif kind == "Q":
            _add_slider_moves(position, sq, piece, QUEEN_DIRS, out)
        elif kind == "K":
            _add_leaper_moves(position, sq, piece, KING_DELTAS, out)
            _add_castling(position, sq, piece, out)
    return out


def apply_move(position: Position, move: Move, *, validate_turn_piece: bool = True) -> Position:
    board = list(position.board)
    moving = board[move.from_sq]
    if moving == EMPTY:
        raise ValueError(f"no piece on {square_name(move.from_sq)}")
    mover = piece_color(moving)
    if validate_turn_piece and mover != position.turn:
        raise ValueError("move source does not belong to side to move")
    captured = board[move.to_sq]
    if captured != EMPTY and piece_type(captured) == "K":
        raise ValueError("the king is never captured; checkmate ends the game")

    board[move.from_sq] = EMPTY
    if move.is_en_passant:
        capture_sq = move.to_sq - 8 if mover == WHITE else move.to_sq + 8
        captured = board[capture_sq]
        board[capture_sq] = EMPTY
    board[move.to_sq] = moving

    if move.is_castle:
        if move.to_sq == 6:  # White king side
            board[7], board[5] = EMPTY, "R"
        elif move.to_sq == 2:
            board[0], board[3] = EMPTY, "R"
        elif move.to_sq == 62:
            board[63], board[61] = EMPTY, "r"
        elif move.to_sq == 58:
            board[56], board[59] = EMPTY, "r"
        else:
            raise ValueError("invalid castling destination")

    if move.promotion:
        if piece_type(moving) != "P":
            raise ValueError("only a pawn may promote")
        promoted = move.promotion.upper() if mover == WHITE else move.promotion.lower()
        if promoted.upper() not in ("Q", "R", "B", "N"):
            raise ValueError("unsupported promotion piece")
        board[move.to_sq] = promoted

    castling = position.castling
    if moving == "K":
        castling &= ~(WK | WQ)
    elif moving == "k":
        castling &= ~(BK | BQ)
    elif moving == "R":
        if move.from_sq == 0:
            castling &= ~WQ
        elif move.from_sq == 7:
            castling &= ~WK
    elif moving == "r":
        if move.from_sq == 56:
            castling &= ~BQ
        elif move.from_sq == 63:
            castling &= ~BK

    # Capturing an unmoved rook removes the corresponding right.
    if captured == "R":
        if move.to_sq == 0:
            castling &= ~WQ
        elif move.to_sq == 7:
            castling &= ~WK
    elif captured == "r":
        if move.to_sq == 56:
            castling &= ~BQ
        elif move.to_sq == 63:
            castling &= ~BK

    ep_square = -1
    if move.is_double_pawn:
        ep_square = (move.from_sq + move.to_sq) // 2

    halfmove = 0 if piece_type(moving) == "P" or captured != EMPTY else position.halfmove_clock + 1
    fullmove = position.fullmove_number + (1 if position.turn == BLACK else 0)
    return Position(tuple(board), opposite(position.turn), castling, ep_square, halfmove, fullmove)


def legal_moves(position: Position) -> list[Move]:
    moves: list[Move] = []
    mover = position.turn
    for move in pseudo_legal_moves(position):
        child = apply_move(position, move)
        if not in_check(child, mover):
            moves.append(move)
    moves.sort(key=lambda m: m.uci())
    return moves


def is_legal_move(position: Position, move: Move) -> bool:
    return move in legal_moves(position)


def parse_uci_move(position: Position, text: str) -> Move:
    token = text.strip().lower()
    matches = [move for move in legal_moves(position) if move.uci() == token]
    if len(matches) != 1:
        raise ValueError(f"{text!r} is not a unique legal move in {position.to_fen()}")
    return matches[0]


def apply_uci(position: Position, text: str) -> Position:
    return apply_move(position, parse_uci_move(position, text))


def move_gives_check(position: Position, move: Move) -> bool:
    return in_check(apply_move(position, move))


def _same_piece_candidates(position: Position, move: Move) -> list[Move]:
    moving = position.board[move.from_sq]
    return [
        candidate
        for candidate in legal_moves(position)
        if candidate.to_sq == move.to_sq
        and candidate.from_sq != move.from_sq
        and piece_type(position.board[candidate.from_sq]) == piece_type(moving)
    ]


def move_to_san(position: Position, move: Move) -> str:
    if move not in legal_moves(position):
        raise ValueError("SAN requested for an illegal move")
    moving = position.board[move.from_sq]
    kind = piece_type(moving)
    if move.is_castle:
        san = "O-O" if file_of(move.to_sq) == 6 else "O-O-O"
    else:
        capture = move.is_capture
        if kind == "P":
            prefix = ""
            if capture:
                prefix = chr(ord("a") + file_of(move.from_sq))
        else:
            prefix = kind
            candidates = _same_piece_candidates(position, move)
            if candidates:
                same_file = any(file_of(c.from_sq) == file_of(move.from_sq) for c in candidates)
                same_rank = any(rank_of(c.from_sq) == rank_of(move.from_sq) for c in candidates)
                if not same_file:
                    prefix += chr(ord("a") + file_of(move.from_sq))
                elif not same_rank:
                    prefix += str(rank_of(move.from_sq) + 1)
                else:
                    prefix += square_name(move.from_sq)
        san = prefix + ("x" if capture else "") + square_name(move.to_sq)
        if move.promotion:
            san += "=" + move.promotion.upper()
    child = apply_move(position, move)
    child_moves = legal_moves(child)
    if in_check(child):
        san += "#" if not child_moves else "+"
    return san


def insufficient_material(position: Position) -> bool:
    # Conservative exact subset of FIDE dead positions used by most engines.
    non_kings = [(sq, piece) for sq, piece in position.pieces() if piece_type(piece) != "K"]
    if not non_kings:
        return True
    if any(piece_type(piece) in ("P", "R", "Q") for _, piece in non_kings):
        return False
    if len(non_kings) == 1 and piece_type(non_kings[0][1]) in ("B", "N"):
        return True
    # Only bishops, all on the same square color: no mating position is possible.
    if all(piece_type(piece) == "B" for _, piece in non_kings):
        square_colors = {(file_of(sq) + rank_of(sq)) & 1 for sq, _ in non_kings}
        return len(square_colors) == 1
    return False


def position_status(
    position: Position,
    *,
    history_keys: Iterable[str] | None = None,
    claim_draws: bool = True,
) -> PositionStatus:
    moves = legal_moves(position)
    if not moves:
        if in_check(position):
            return PositionStatus(True, "checkmate", winner=opposite(position.turn), detail="side to move is in check with no legal move")
        return PositionStatus(True, "stalemate", detail="side to move is not in check and has no legal move")
    if insufficient_material(position):
        return PositionStatus(True, "dead_position", detail="insufficient material under the implemented exact subset")
    if position.halfmove_clock >= 150:
        return PositionStatus(True, "seventy_five_move", detail="75 moves by each player without pawn move or capture")
    if history_keys is not None:
        key = repetition_key(position)
        count = sum(1 for item in history_keys if item == key)
        if count >= 5:
            return PositionStatus(True, "fivefold_repetition", detail="same position occurred at least five times")
        if claim_draws and count >= 3:
            return PositionStatus(True, "threefold_repetition", claimable=True, detail="same position occurred at least three times")
    if claim_draws and position.halfmove_clock >= 100:
        return PositionStatus(True, "fifty_move_claim", claimable=True, detail="50 moves by each player without pawn move or capture")
    return PositionStatus(False, "ongoing")


def perft(position: Position, depth: int) -> int:
    if depth < 0:
        raise ValueError("perft depth must be non-negative")
    if depth == 0:
        return 1
    total = 0
    for move in legal_moves(position):
        total += perft(apply_move(position, move), depth - 1)
    return total


def perft_divide(position: Position, depth: int) -> dict[str, int]:
    if depth < 1:
        raise ValueError("perft divide depth must be at least 1")
    result: dict[str, int] = {}
    for move in legal_moves(position):
        result[move.uci()] = perft(apply_move(position, move), depth - 1)
    return dict(sorted(result.items()))
