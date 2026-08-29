"""Canonical hashes and compact deterministic keys.

The 64-bit key is a cache/index key. The SHA-256 digest remains the
collision-resistant state identity used in proof and replay records.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from .constants import BLACK, EMPTY, WHITE, file_of, piece_color, rank_of
from .position import Position


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def state_sha256(position: Position, *, include_counters: bool = True) -> str:
    return hashlib.sha256(canonical_json_bytes(position.state_record(include_counters=include_counters))).hexdigest()


def compact_key64(position: Position, *, include_halfmove: bool = True) -> int:
    record = position.state_record(include_counters=False)
    if include_halfmove:
        record["halfmove_clock"] = min(position.halfmove_clock, 150)
    digest = hashlib.blake2b(
        canonical_json_bytes(record),
        digest_size=8,
        person=b"UGTSCHS1",
    ).digest()
    return int.from_bytes(digest, "big", signed=False)


def _ep_capture_sources(position: Position) -> Iterable[int]:
    if position.ep_square == -1:
        return ()
    ep = position.ep_square
    file_index = file_of(ep)
    rank = rank_of(ep)
    if position.turn == WHITE:
        source_rank = rank - 1
        pawn = "P"
    else:
        source_rank = rank + 1
        pawn = "p"
    sources: list[int] = []
    for source_file in (file_index - 1, file_index + 1):
        if 0 <= source_file < 8 and 0 <= source_rank < 8:
            sq = source_rank * 8 + source_file
            if position.board[sq] == pawn:
                sources.append(sq)
    return tuple(sources)


def repetition_record(position: Position) -> dict[str, object]:
    # FIDE position identity depends on side, placement, castling rights and
    # en-passant rights only when a *legal* en-passant capture is available.
    # An adjacent pawn is not sufficient when the capture would expose its own
    # king.  The local import avoids a module-import cycle while preserving the
    # exact legal-right distinction.
    ep = -1
    if position.ep_square != -1 and tuple(_ep_capture_sources(position)):
        from .rules import legal_moves  # local by design
        if any(move.is_en_passant for move in legal_moves(position)):
            ep = position.ep_square
    return {
        "board": "".join(position.board),
        "turn": position.turn,
        "castling": position.castling,
        "ep_square": ep,
    }


def repetition_key(position: Position) -> str:
    return hashlib.sha256(canonical_json_bytes(repetition_record(position))).hexdigest()


def material_signature(position: Position) -> str:
    white = sorted(piece.upper() for piece in position.board if piece != EMPTY and piece_color(piece) == WHITE)
    black = sorted(piece.upper() for piece in position.board if piece != EMPTY and piece_color(piece) == BLACK)
    return "".join(white) + "v" + "".join(black)
