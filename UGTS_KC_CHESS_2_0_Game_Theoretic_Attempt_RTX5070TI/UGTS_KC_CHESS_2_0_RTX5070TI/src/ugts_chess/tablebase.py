"""Exact three-piece KQK/KRK retrograde tablebases.

The dense key is deliberately simple and auditable:
    index = (((strong_king * 64) + strong_piece) * 64 + weak_king) * 2 + side
It occupies 19 address bits. Each table stores one outcome byte and one
DTM byte per address. Invalid cells remain explicit; gzip supplies the
transport compression.
"""
from __future__ import annotations

import gzip
import hashlib
import heapq
import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from .constants import BLACK, EMPTY, WHITE, color_name, file_of, opposite, piece_color, rank_of
from .move import Move
from .position import Position
from .rules import apply_move, legal_moves, move_to_san

ADDRESS_COUNT = 64 * 64 * 64 * 2
MAGIC = b"UGTSKXK1"
HEADER = struct.Struct("<8sB3xI")

INVALID = 0
WIN = 1
LOSS = 2
DRAW = 3
UNKNOWN = 4
OUTCOME_NAMES = {INVALID: "invalid", WIN: "win", LOSS: "loss", DRAW: "draw", UNKNOWN: "unknown"}

KING_DELTAS = ((1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1))
ROOK_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))
BISHOP_DIRS = ((1, 1), (1, -1), (-1, 1), (-1, -1))


def encode_state(strong_king: int, strong_piece: int, weak_king: int, side: int) -> int:
    return (((strong_king * 64) + strong_piece) * 64 + weak_king) * 2 + side


def decode_state(index: int) -> tuple[int, int, int, int]:
    side = index & 1
    value = index >> 1
    weak_king = value & 63
    value >>= 6
    strong_piece = value & 63
    strong_king = value >> 6
    return strong_king, strong_piece, weak_king, side


def _inside(file_index: int, rank_index: int) -> bool:
    return 0 <= file_index < 8 and 0 <= rank_index < 8


def _adjacent(a: int, b: int) -> bool:
    return max(abs(file_of(a) - file_of(b)), abs(rank_of(a) - rank_of(b))) <= 1


def _directions(piece: str) -> tuple[tuple[int, int], ...]:
    if piece == "Q":
        return ROOK_DIRS + BISHOP_DIRS
    if piece == "R":
        return ROOK_DIRS
    raise ValueError("tablebase piece must be Q or R")


def _piece_attacks(piece_sq: int, target_sq: int, blocker_sq: int, piece: str) -> bool:
    pf, pr = file_of(piece_sq), rank_of(piece_sq)
    tf, tr = file_of(target_sq), rank_of(target_sq)
    df = tf - pf
    dr = tr - pr
    if df == 0 and dr != 0:
        step_f, step_r = 0, 1 if dr > 0 else -1
    elif dr == 0 and df != 0:
        step_f, step_r = 1 if df > 0 else -1, 0
    elif piece == "Q" and abs(df) == abs(dr) and df != 0:
        step_f, step_r = (1 if df > 0 else -1), (1 if dr > 0 else -1)
    else:
        return False
    f, r = pf + step_f, pr + step_r
    while (f, r) != (tf, tr):
        if r * 8 + f == blocker_sq:
            return False
        f += step_f
        r += step_r
    return True


def _valid(strong_king: int, strong_piece: int, weak_king: int, side: int, piece: str) -> bool:
    if strong_king == strong_piece or strong_king == weak_king or strong_piece == weak_king:
        return False
    if _adjacent(strong_king, weak_king):
        return False
    # If the strong side is to move, the weak side just moved and may not have
    # left its king in check. If the weak side is to move, a check is legal.
    if side == WHITE and _piece_attacks(strong_piece, weak_king, strong_king, piece):
        return False
    return True


def _successors(index: int, piece: str) -> list[int]:
    strong_king, strong_piece, weak_king, side = decode_state(index)
    result: list[int] = []
    if side == WHITE:
        kf, kr = file_of(strong_king), rank_of(strong_king)
        for df, dr in KING_DELTAS:
            f, r = kf + df, kr + dr
            if not _inside(f, r):
                continue
            target = r * 8 + f
            if target in (strong_piece, weak_king) or _adjacent(target, weak_king):
                continue
            result.append(encode_state(target, strong_piece, weak_king, BLACK))

        pf, pr = file_of(strong_piece), rank_of(strong_piece)
        for df, dr in _directions(piece):
            f, r = pf + df, pr + dr
            while _inside(f, r):
                target = r * 8 + f
                if target == strong_king:
                    break
                if target == weak_king:
                    break  # kings are not captured
                result.append(encode_state(strong_king, target, weak_king, BLACK))
                f += df
                r += dr
    else:
        kf, kr = file_of(weak_king), rank_of(weak_king)
        for df, dr in KING_DELTAS:
            f, r = kf + df, kr + dr
            if not _inside(f, r):
                continue
            target = r * 8 + f
            if target == strong_king or _adjacent(target, strong_king):
                continue
            if target == strong_piece:
                result.append(-1)  # Capture the major piece: K versus K draw.
                continue
            if _piece_attacks(strong_piece, target, strong_king, piece):
                continue
            result.append(encode_state(strong_king, strong_piece, target, WHITE))
    return result


def _predecessors(index: int, piece: str) -> Iterator[int]:
    strong_king, strong_piece, weak_king, side = decode_state(index)
    if side == BLACK:
        # White moved last: reverse either king or major-piece motion.
        kf, kr = file_of(strong_king), rank_of(strong_king)
        for df, dr in KING_DELTAS:
            f, r = kf + df, kr + dr
            if not _inside(f, r):
                continue
            source = r * 8 + f
            candidate = encode_state(source, strong_piece, weak_king, WHITE)
            if _valid(source, strong_piece, weak_king, WHITE, piece):
                yield candidate

        pf, pr = file_of(strong_piece), rank_of(strong_piece)
        for df, dr in _directions(piece):
            f, r = pf + df, pr + dr
            while _inside(f, r):
                source = r * 8 + f
                if source in (strong_king, weak_king):
                    break
                candidate = encode_state(strong_king, source, weak_king, WHITE)
                if _valid(strong_king, source, weak_king, WHITE, piece):
                    yield candidate
                f += df
                r += dr
    else:
        # Black moved last: reverse one legal king step. The current state is
        # already safe for the weak king by the validity rule.
        kf, kr = file_of(weak_king), rank_of(weak_king)
        for df, dr in KING_DELTAS:
            f, r = kf + df, kr + dr
            if not _inside(f, r):
                continue
            source = r * 8 + f
            if source in (strong_king, strong_piece):
                continue
            candidate = encode_state(strong_king, strong_piece, source, BLACK)
            if _valid(strong_king, strong_piece, source, BLACK, piece):
                yield candidate


@dataclass(frozen=True, slots=True)
class TablebaseProbe:
    material: str
    outcome: str
    dtm_plies: int | None
    side_to_move: str
    strong_side: str
    exact: bool
    key: int

    def to_dict(self) -> dict[str, object]:
        return {
            "material": self.material,
            "outcome": self.outcome,
            "dtm_plies": self.dtm_plies,
            "side_to_move": self.side_to_move,
            "strong_side": self.strong_side,
            "exact": self.exact,
            "key": self.key,
        }


@dataclass(slots=True)
class KXKTablebase:
    piece: str
    outcomes: bytes
    dtm: bytes
    metadata: dict[str, object]

    @classmethod
    def load(cls, path: str | Path) -> "KXKTablebase":
        path = Path(path)
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as handle:  # type: ignore[arg-type]
            header = handle.read(HEADER.size)
            if len(header) != HEADER.size:
                raise ValueError("truncated tablebase header")
            magic, piece_code, count = HEADER.unpack(header)
            if magic != MAGIC or count != ADDRESS_COUNT:
                raise ValueError("unsupported tablebase format")
            outcomes = handle.read(ADDRESS_COUNT)
            dtm = handle.read(ADDRESS_COUNT)
            if len(outcomes) != ADDRESS_COUNT or len(dtm) != ADDRESS_COUNT:
                raise ValueError("truncated tablebase payload")
            if handle.read(1):
                raise ValueError("unexpected bytes after tablebase payload")
        metadata_path = path.with_suffix("") if path.suffix == ".gz" else path
        metadata_path = metadata_path.with_suffix(metadata_path.suffix + ".json")
        metadata: dict[str, object] = {}
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return cls(chr(piece_code), outcomes, dtm, metadata)

    def raw_probe(self, strong_king: int, strong_piece: int, weak_king: int, side: int) -> tuple[int, int]:
        key = encode_state(strong_king, strong_piece, weak_king, side)
        return self.outcomes[key], self.dtm[key]

    def probe(self, position: Position) -> TablebaseProbe:
        normalized = normalize_kxk_position(position, self.piece)
        if normalized is None:
            raise ValueError(f"position is not K{self.piece}K material")
        strong_king, strong_piece, weak_king, side, strong_color = normalized
        key = encode_state(strong_king, strong_piece, weak_king, side)
        outcome_code = self.outcomes[key]
        if outcome_code == INVALID:
            raise ValueError("position maps to an invalid/unreachable tablebase cell")
        dtm = self.dtm[key] if outcome_code in (WIN, LOSS) else None
        return TablebaseProbe(
            material=f"K{self.piece}K",
            outcome=OUTCOME_NAMES[outcome_code],
            dtm_plies=dtm,
            side_to_move=color_name(position.turn),
            strong_side=color_name(strong_color),
            exact=True,
            key=key,
        )

    def best_moves(self, position: Position) -> list[dict[str, object]]:
        root = self.probe(position)
        candidates: list[tuple[int, str, Move, TablebaseProbe]] = []
        for move in legal_moves(position):
            child = apply_move(position, move)
            try:
                child_probe = self.probe(child)
            except ValueError:
                # A weak-king capture of the major piece exits to K versus K.
                child_probe = TablebaseProbe(
                    material="KvK",
                    outcome="draw",
                    dtm_plies=None,
                    side_to_move=color_name(child.turn),
                    strong_side=root.strong_side,
                    exact=True,
                    key=-1,
                )
            rank = 99_999
            if root.outcome == "win" and child_probe.outcome == "loss":
                rank = child_probe.dtm_plies or 0
            elif root.outcome == "loss" and child_probe.outcome == "win":
                rank = -(child_probe.dtm_plies or 0)  # maximize delay
            elif root.outcome == "draw" and child_probe.outcome == "draw":
                rank = 0
            candidates.append((rank, move.uci(), move, child_probe))
        if not candidates:
            return []
        if root.outcome == "win":
            best_rank = min(rank for rank, _, _, _ in candidates)
        elif root.outcome == "loss":
            best_rank = min(rank for rank, _, _, _ in candidates)
        else:
            drawing = [rank for rank, _, _, probe in candidates if probe.outcome == "draw"]
            best_rank = min(drawing) if drawing else min(rank for rank, _, _, _ in candidates)
        result: list[dict[str, object]] = []
        for rank, _, move, child_probe in candidates:
            if rank != best_rank:
                continue
            result.append({
                "move": move.uci(),
                "san": move_to_san(position, move),
                "child": child_probe.to_dict(),
            })
        return result


def normalize_kxk_position(position: Position, piece: str) -> tuple[int, int, int, int, int] | None:
    piece = piece.upper()
    if piece not in ("Q", "R"):
        raise ValueError("piece must be Q or R")
    occupied = [(sq, p) for sq, p in enumerate(position.board) if p != EMPTY]
    if len(occupied) != 3 or position.castling or position.ep_square != -1:
        return None
    white = {p.upper() for _, p in occupied if piece_color(p) == WHITE}
    black = {p.upper() for _, p in occupied if piece_color(p) == BLACK}
    if white == {"K", piece} and black == {"K"}:
        strong_color = WHITE
        strong_king = position.board.index("K")
        strong_piece = position.board.index(piece)
        weak_king = position.board.index("k")
        side = WHITE if position.turn == WHITE else BLACK
    elif black == {"K", piece} and white == {"K"}:
        strong_color = BLACK
        # Rotate 180 degrees and swap colors to the white-strong canonical table.
        strong_king = 63 - position.board.index("k")
        strong_piece = 63 - position.board.index(piece.lower())
        weak_king = 63 - position.board.index("K")
        side = WHITE if position.turn == BLACK else BLACK
    else:
        return None
    return strong_king, strong_piece, weak_king, side, strong_color


def generate_tablebase(piece: str, output_path: str | Path) -> dict[str, object]:
    piece = piece.upper()
    if piece not in ("Q", "R"):
        raise ValueError("piece must be Q or R")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    outcomes = bytearray(ADDRESS_COUNT)
    dtm = bytearray(ADDRESS_COUNT)
    degree = bytearray(ADDRESS_COUNT)
    remaining = bytearray(ADDRESS_COUNT)
    max_child_dtm = bytearray(ADDRESS_COUNT)
    heap: list[tuple[int, int]] = []

    valid_count = 0
    initial_mates = 0
    initial_stalemates = 0
    for strong_king in range(64):
        for strong_piece in range(64):
            if strong_piece == strong_king:
                continue
            for weak_king in range(64):
                if weak_king in (strong_king, strong_piece) or _adjacent(strong_king, weak_king):
                    continue
                for side in (WHITE, BLACK):
                    if not _valid(strong_king, strong_piece, weak_king, side, piece):
                        continue
                    index = encode_state(strong_king, strong_piece, weak_king, side)
                    valid_count += 1
                    successors = _successors(index, piece)
                    deg = len(successors)
                    degree[index] = deg
                    remaining[index] = deg
                    if deg == 0:
                        if side == BLACK and _piece_attacks(strong_piece, weak_king, strong_king, piece):
                            outcomes[index] = LOSS
                            initial_mates += 1
                            heapq.heappush(heap, (0, index))
                        else:
                            outcomes[index] = DRAW
                            initial_stalemates += 1
                    else:
                        outcomes[index] = UNKNOWN

    resolved = 0
    while heap:
        distance, index = heapq.heappop(heap)
        if dtm[index] != distance or outcomes[index] not in (WIN, LOSS):
            continue
        resolved += 1
        outcome = outcomes[index]
        for predecessor in _predecessors(index, piece):
            if outcomes[predecessor] != UNKNOWN:
                continue
            if outcome == LOSS:
                outcomes[predecessor] = WIN
                next_distance = min(255, distance + 1)
                dtm[predecessor] = next_distance
                heapq.heappush(heap, (next_distance, predecessor))
            else:
                if remaining[predecessor] > 0:
                    remaining[predecessor] -= 1
                if distance > max_child_dtm[predecessor]:
                    max_child_dtm[predecessor] = distance
                if remaining[predecessor] == 0:
                    outcomes[predecessor] = LOSS
                    next_distance = min(255, max_child_dtm[predecessor] + 1)
                    dtm[predecessor] = next_distance
                    heapq.heappush(heap, (next_distance, predecessor))

    for index, outcome in enumerate(outcomes):
        if outcome == UNKNOWN:
            outcomes[index] = DRAW

    payload = HEADER.pack(MAGIC, ord(piece), ADDRESS_COUNT) + bytes(outcomes) + bytes(dtm)
    if output_path.suffix == ".gz":
        with output_path.open("wb") as raw:
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as handle:
                handle.write(payload)
    else:
        output_path.write_bytes(payload)

    counts = {name: 0 for name in ("invalid", "win", "loss", "draw")}
    max_dtm = 0
    for index, outcome in enumerate(outcomes):
        counts[OUTCOME_NAMES[outcome]] += 1
        if outcome in (WIN, LOSS):
            max_dtm = max(max_dtm, dtm[index])
    sha = hashlib.sha256(output_path.read_bytes()).hexdigest()
    metadata: dict[str, object] = {
        "schema": "ugts-kc-chess-kxk-tablebase-1.0",
        "piece": piece,
        "material": f"K{piece}K",
        "address_count": ADDRESS_COUNT,
        "address_bits": 19,
        "valid_positions": valid_count,
        "initial_checkmates": initial_mates,
        "initial_stalemates": initial_stalemates,
        "outcome_counts": counts,
        "max_dtm_plies": max_dtm,
        "raw_payload_bytes": len(payload),
        "file_bytes": output_path.stat().st_size,
        "sha256": sha,
        "semantics": "Outcome is from the side-to-move perspective; DTM counts plies to checkmate under optimal play.",
        "fifty_move_boundary": "KQK/KRK wins represented here complete within the observed maximum DTM, below 100 plies.",
    }
    metadata_path = output_path.with_suffix("") if output_path.suffix == ".gz" else output_path
    metadata_path = metadata_path.with_suffix(metadata_path.suffix + ".json")
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return metadata
