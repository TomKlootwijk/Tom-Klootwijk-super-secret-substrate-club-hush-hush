"""Independent ranked-partition replay for the bundled KQK/KRK tables.

The existing tablebase probe is useful candidate data, but it is not proof
authority.  This module treats the complete dense table as a certificate and
reconstructs its finite game graph with the canonical chess rule oracle.  It
does not call the tablebase validity, successor, generation, or probe helpers.

Decisive cells are justified by a strictly decreasing DTM rank.  DRAW cells
may be cyclic, but must have no move to a child LOSS and must retain at least
one DRAW continuation (including a capture into exact KvK dead material).
Only a complete successful replay produces a canonical externally retainable
head.  No result from this module promotes a WDL fact.
"""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import struct
import threading
import time
from typing import Final, Mapping, Sequence
import zlib

from .constants import EMPTY, opposite
from .game_state import RULE_PROFILE_ID
from .hashing import canonical_json_bytes
from .position import Position
from .rules import apply_move, in_check, insufficient_material, legal_moves


KXK_PARTITION_LEMMA_HEAD_SCHEMA: Final = (
    "ugts-chess-kxk-ranked-partition-lemma-head-1.0"
)
KXK_PARTITION_LEMMA_VERIFIER_PROFILE: Final = (
    "ugts-chess-kxk-ranked-partition-full-replay-1.0"
)
KXK_BASE_GAME_PROFILE: Final = (
    "orthodox-kxk-checkmate-stalemate-infinite-play-draw-1.0"
)
KXK_SOURCE_SCHEMA: Final = "ugts-kc-chess-kxk-tablebase-1.0"

ADDRESS_BITS: Final = 19
ADDRESS_COUNT: Final = 64 * 64 * 64 * 2
_MAGIC: Final = b"UGTSKXK1"
_HEADER: Final = struct.Struct("<8sB3xI")
DECODED_BYTES: Final = _HEADER.size + 2 * ADDRESS_COUNT

_INVALID: Final = 0
_WIN: Final = 1
_LOSS: Final = 2
_DRAW: Final = 3
_OUTCOME_NAMES: Final = {
    _INVALID: "invalid",
    _WIN: "win",
    _LOSS: "loss",
    _DRAW: "draw",
}

MAX_TRANSPORT_BYTES: Final = 4 * 1024 * 1024
MAX_METADATA_BYTES: Final = 64 * 1024
MAX_RANK: Final = 255
MAX_LEGAL_SUCCESSORS: Final = 256

_SEMANTICS: Final = (
    "Outcome is from the side-to-move perspective; DTM counts plies to "
    "checkmate under optimal play."
)
_FIFTY_MOVE_BOUNDARY: Final = (
    "KQK/KRK wins represented here complete within the observed maximum "
    "DTM, below 100 plies."
)

_HEAD_KEYS: Final = frozenset(
    {
        "schema",
        "verifier_profile",
        "rules_profile_id",
        "base_game_profile",
        "source_schema",
        "piece",
        "material",
        "address_bits",
        "address_count",
        "transport_size",
        "transport_sha256",
        "metadata_size",
        "metadata_sha256",
        "decoded_size",
        "decoded_sha256",
        "valid_positions",
        "invalid_positions",
        "win_positions",
        "loss_positions",
        "draw_positions",
        "initial_checkmates",
        "initial_stalemates",
        "legal_transition_count",
        "capture_draw_exit_count",
        "max_rank",
    }
)
_METADATA_KEYS: Final = frozenset(
    {
        "address_bits",
        "address_count",
        "fifty_move_boundary",
        "file_bytes",
        "initial_checkmates",
        "initial_stalemates",
        "material",
        "max_dtm_plies",
        "outcome_counts",
        "piece",
        "raw_payload_bytes",
        "schema",
        "semantics",
        "sha256",
        "valid_positions",
    }
)
_OUTCOME_COUNT_KEYS: Final = frozenset({"invalid", "win", "loss", "draw"})


class KXKPartitionLemmaError(Exception):
    """Base class for independent KXK partition verification failures."""


class KXKPartitionLemmaIntegrityError(KXKPartitionLemmaError):
    """Raised when source bytes do not prove the ranked partition."""


class KXKPartitionLemmaSourceChangedError(KXKPartitionLemmaError):
    """Raised when a source path changes during a verification capture."""


class KXKPartitionLemmaHeadMismatchError(KXKPartitionLemmaError):
    """Raised when replay does not reproduce an externally retained head."""

    def __init__(
        self,
        message: str,
        *,
        expected: "KXKPartitionLemmaHead",
        current: "KXKPartitionLemmaHead",
    ) -> None:
        self.expected = expected
        self.current = current
        super().__init__(message)


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_sha256(value: object, *, label: str) -> str:
    if not _is_sha256_hex(value):
        raise ValueError(f"{label} must be lowercase SHA-256 hex")
    return value


def _require_int(
    value: object,
    *,
    label: str,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{label} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} exceeds maximum {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class KXKPartitionLemmaHead:
    """Canonical commitment to one completely replayed KXK partition."""

    verifier_profile: str
    rules_profile_id: str
    base_game_profile: str
    source_schema: str
    piece: str
    material: str
    address_bits: int
    address_count: int
    transport_size: int
    transport_sha256: str
    metadata_size: int
    metadata_sha256: str
    decoded_size: int
    decoded_sha256: str
    valid_positions: int
    invalid_positions: int
    win_positions: int
    loss_positions: int
    draw_positions: int
    initial_checkmates: int
    initial_stalemates: int
    legal_transition_count: int
    capture_draw_exit_count: int
    max_rank: int

    def __post_init__(self) -> None:
        if self.verifier_profile != KXK_PARTITION_LEMMA_VERIFIER_PROFILE:
            raise ValueError("KXK lemma head verifier profile mismatch")
        if self.rules_profile_id != RULE_PROFILE_ID:
            raise ValueError("KXK lemma head rule profile mismatch")
        if self.base_game_profile != KXK_BASE_GAME_PROFILE:
            raise ValueError("KXK lemma head base-game profile mismatch")
        if self.source_schema != KXK_SOURCE_SCHEMA:
            raise ValueError("KXK lemma head source schema mismatch")
        if self.piece not in {"Q", "R"}:
            raise ValueError("KXK lemma head piece must be Q or R")
        if self.material != f"K{self.piece}K":
            raise ValueError("KXK lemma head material/piece mismatch")
        if self.address_bits != ADDRESS_BITS or self.address_count != ADDRESS_COUNT:
            raise ValueError("KXK lemma head address domain mismatch")
        if self.decoded_size != DECODED_BYTES:
            raise ValueError("KXK lemma head decoded size mismatch")

        transport_size = _require_int(
            self.transport_size,
            label="transport_size",
            minimum=1,
            maximum=MAX_TRANSPORT_BYTES,
        )
        metadata_size = _require_int(
            self.metadata_size,
            label="metadata_size",
            minimum=1,
            maximum=MAX_METADATA_BYTES,
        )
        if transport_size != self.transport_size or metadata_size != self.metadata_size:
            raise AssertionError("validated KXK head sizes changed unexpectedly")
        for label, value in (
            ("transport_sha256", self.transport_sha256),
            ("metadata_sha256", self.metadata_sha256),
            ("decoded_sha256", self.decoded_sha256),
        ):
            _require_sha256(value, label=label)

        counts = (
            _require_int(
                self.valid_positions,
                label="valid_positions",
                maximum=ADDRESS_COUNT,
            ),
            _require_int(
                self.invalid_positions,
                label="invalid_positions",
                maximum=ADDRESS_COUNT,
            ),
            _require_int(
                self.win_positions,
                label="win_positions",
                maximum=ADDRESS_COUNT,
            ),
            _require_int(
                self.loss_positions,
                label="loss_positions",
                maximum=ADDRESS_COUNT,
            ),
            _require_int(
                self.draw_positions,
                label="draw_positions",
                maximum=ADDRESS_COUNT,
            ),
        )
        valid, invalid, wins, losses, draws = counts
        if valid + invalid != ADDRESS_COUNT:
            raise ValueError("KXK lemma head valid/invalid counts do not cover the domain")
        if wins + losses + draws != valid:
            raise ValueError("KXK lemma head WDL counts do not cover valid positions")
        _require_int(
            self.initial_checkmates,
            label="initial_checkmates",
            maximum=losses,
        )
        _require_int(
            self.initial_stalemates,
            label="initial_stalemates",
            maximum=draws,
        )
        _require_int(
            self.legal_transition_count,
            label="legal_transition_count",
        )
        exits = _require_int(
            self.capture_draw_exit_count,
            label="capture_draw_exit_count",
        )
        if exits > self.legal_transition_count:
            raise ValueError("KXK lemma head has more exits than legal transitions")
        _require_int(self.max_rank, label="max_rank", maximum=MAX_RANK)

    def record(self) -> dict[str, object]:
        return {
            "schema": KXK_PARTITION_LEMMA_HEAD_SCHEMA,
            "verifier_profile": self.verifier_profile,
            "rules_profile_id": self.rules_profile_id,
            "base_game_profile": self.base_game_profile,
            "source_schema": self.source_schema,
            "piece": self.piece,
            "material": self.material,
            "address_bits": self.address_bits,
            "address_count": self.address_count,
            "transport_size": self.transport_size,
            "transport_sha256": self.transport_sha256,
            "metadata_size": self.metadata_size,
            "metadata_sha256": self.metadata_sha256,
            "decoded_size": self.decoded_size,
            "decoded_sha256": self.decoded_sha256,
            "valid_positions": self.valid_positions,
            "invalid_positions": self.invalid_positions,
            "win_positions": self.win_positions,
            "loss_positions": self.loss_positions,
            "draw_positions": self.draw_positions,
            "initial_checkmates": self.initial_checkmates,
            "initial_stalemates": self.initial_stalemates,
            "legal_transition_count": self.legal_transition_count,
            "capture_draw_exit_count": self.capture_draw_exit_count,
            "max_rank": self.max_rank,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @property
    def head_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @classmethod
    def from_bytes(
        cls,
        value: bytes | bytearray | memoryview,
    ) -> "KXKPartitionLemmaHead":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("KXK lemma head must be bytes-like")
        snapshot = bytes(value)
        try:
            raw = json.loads(snapshot)
            reconstructed = canonical_json_bytes(raw)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(f"KXK lemma head is not canonical UTF-8 JSON: {exc}") from exc
        if not isinstance(raw, dict) or reconstructed != snapshot:
            raise ValueError("KXK lemma head is not a canonical JSON object")
        if set(raw) != _HEAD_KEYS:
            raise ValueError("KXK lemma head has missing or unexpected fields")
        if raw.get("schema") != KXK_PARTITION_LEMMA_HEAD_SCHEMA:
            raise ValueError("KXK lemma head schema mismatch")
        result = cls(
            verifier_profile=raw.get("verifier_profile"),  # type: ignore[arg-type]
            rules_profile_id=raw.get("rules_profile_id"),  # type: ignore[arg-type]
            base_game_profile=raw.get("base_game_profile"),  # type: ignore[arg-type]
            source_schema=raw.get("source_schema"),  # type: ignore[arg-type]
            piece=raw.get("piece"),  # type: ignore[arg-type]
            material=raw.get("material"),  # type: ignore[arg-type]
            address_bits=raw.get("address_bits"),  # type: ignore[arg-type]
            address_count=raw.get("address_count"),  # type: ignore[arg-type]
            transport_size=raw.get("transport_size"),  # type: ignore[arg-type]
            transport_sha256=raw.get("transport_sha256"),  # type: ignore[arg-type]
            metadata_size=raw.get("metadata_size"),  # type: ignore[arg-type]
            metadata_sha256=raw.get("metadata_sha256"),  # type: ignore[arg-type]
            decoded_size=raw.get("decoded_size"),  # type: ignore[arg-type]
            decoded_sha256=raw.get("decoded_sha256"),  # type: ignore[arg-type]
            valid_positions=raw.get("valid_positions"),  # type: ignore[arg-type]
            invalid_positions=raw.get("invalid_positions"),  # type: ignore[arg-type]
            win_positions=raw.get("win_positions"),  # type: ignore[arg-type]
            loss_positions=raw.get("loss_positions"),  # type: ignore[arg-type]
            draw_positions=raw.get("draw_positions"),  # type: ignore[arg-type]
            initial_checkmates=raw.get("initial_checkmates"),  # type: ignore[arg-type]
            initial_stalemates=raw.get("initial_stalemates"),  # type: ignore[arg-type]
            legal_transition_count=raw.get("legal_transition_count"),  # type: ignore[arg-type]
            capture_draw_exit_count=raw.get("capture_draw_exit_count"),  # type: ignore[arg-type]
            max_rank=raw.get("max_rank"),  # type: ignore[arg-type]
        )
        if result.canonical_bytes() != snapshot:
            raise ValueError("KXK lemma head differs from exact reconstruction")
        return result


@dataclass(frozen=True, slots=True)
class KXKPartitionLemmaVerification:
    """Operational result; only ``head`` is externally retainable authority."""

    head: KXKPartitionLemmaHead
    cache_hit: bool
    elapsed_seconds: float


@dataclass(frozen=True, slots=True)
class _FileIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    content: bytes
    sha256: str
    identity: _FileIdentity


@dataclass(frozen=True, slots=True)
class _ReplayMetrics:
    valid_positions: int
    invalid_positions: int
    win_positions: int
    loss_positions: int
    draw_positions: int
    initial_checkmates: int
    initial_stalemates: int
    legal_transition_count: int
    capture_draw_exit_count: int
    max_rank: int


_CACHE_LOCK = threading.RLock()
_VERIFIED_CACHE: dict[tuple[str, str], KXKPartitionLemmaHead] = {}


def clear_kxk_partition_lemma_cache() -> None:
    """Drop the non-authoritative process-local replay cache."""

    with _CACHE_LOCK:
        _VERIFIED_CACHE.clear()


def _identity(stat_result: os.stat_result) -> _FileIdentity:
    return _FileIdentity(
        int(stat_result.st_dev),
        int(stat_result.st_ino),
        int(stat_result.st_size),
        int(stat_result.st_mtime_ns),
    )


def _read_bounded(stream: object, *, maximum: int, label: str) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(1024 * 1024, maximum + 1 - total))  # type: ignore[attr-defined]
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum:
            raise KXKPartitionLemmaIntegrityError(
                f"{label} exceeds maximum byte size {maximum}"
            )


def _stable_snapshot(path: str | Path, *, maximum: int, label: str) -> _FileSnapshot:
    source = Path(path)
    try:
        with source.open("rb", buffering=0) as stream:
            before = _identity(os.fstat(stream.fileno()))
            if before.size <= 0 or before.size > maximum:
                raise KXKPartitionLemmaIntegrityError(
                    f"{label} size is outside 1..{maximum} bytes"
                )
            first = _read_bounded(stream, maximum=maximum, label=label)
            middle = _identity(os.fstat(stream.fileno()))
            stream.seek(0)
            second = _read_bounded(stream, maximum=maximum, label=label)
            after = _identity(os.fstat(stream.fileno()))
    except KXKPartitionLemmaError:
        raise
    except OSError as exc:
        raise KXKPartitionLemmaSourceChangedError(
            f"cannot capture stable {label}: {exc}"
        ) from exc
    if before != middle or middle != after or first != second:
        raise KXKPartitionLemmaSourceChangedError(
            f"{label} changed during exact double-read capture"
        )
    if len(first) != before.size:
        raise KXKPartitionLemmaSourceChangedError(
            f"{label} byte count differs from retained file identity"
        )
    snapshot = _FileSnapshot(
        source,
        first,
        hashlib.sha256(first).hexdigest(),
        before,
    )
    _confirm_snapshot(snapshot, label=label)
    return snapshot


def _confirm_snapshot(snapshot: _FileSnapshot, *, label: str) -> None:
    try:
        current = _identity(os.stat(snapshot.path))
    except OSError as exc:
        raise KXKPartitionLemmaSourceChangedError(
            f"cannot rebind {label} path after capture: {exc}"
        ) from exc
    if current != snapshot.identity:
        raise KXKPartitionLemmaSourceChangedError(
            f"{label} path no longer names the captured immutable source"
        )


def _json_object_no_duplicates(pairs: Sequence[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _strict_metadata(
    metadata_bytes: bytes,
    *,
    piece: str,
    transport_size: int,
    transport_sha256: str,
) -> dict[str, object]:
    try:
        decoded = json.loads(
            metadata_bytes,
            object_pairs_hook=_json_object_no_duplicates,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise KXKPartitionLemmaIntegrityError(
            f"KXK metadata is not strict UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(decoded, dict) or set(decoded) != _METADATA_KEYS:
        raise KXKPartitionLemmaIntegrityError(
            "KXK metadata has missing or unexpected fields"
        )
    expected_scalars: Mapping[str, object] = {
        "schema": KXK_SOURCE_SCHEMA,
        "piece": piece,
        "material": f"K{piece}K",
        "address_bits": ADDRESS_BITS,
        "address_count": ADDRESS_COUNT,
        "raw_payload_bytes": DECODED_BYTES,
        "file_bytes": transport_size,
        "sha256": transport_sha256,
        "semantics": _SEMANTICS,
        "fifty_move_boundary": _FIFTY_MOVE_BOUNDARY,
    }
    for key, expected in expected_scalars.items():
        if decoded.get(key) != expected or (
            isinstance(expected, int) and isinstance(decoded.get(key), bool)
        ):
            raise KXKPartitionLemmaIntegrityError(
                f"KXK metadata field {key!r} is not canonical"
            )
    for key, maximum in (
        ("valid_positions", ADDRESS_COUNT),
        ("initial_checkmates", ADDRESS_COUNT),
        ("initial_stalemates", ADDRESS_COUNT),
        ("max_dtm_plies", MAX_RANK),
    ):
        try:
            _require_int(decoded.get(key), label=f"metadata {key}", maximum=maximum)
        except ValueError as exc:
            raise KXKPartitionLemmaIntegrityError(str(exc)) from exc
    counts = decoded.get("outcome_counts")
    if not isinstance(counts, dict) or set(counts) != _OUTCOME_COUNT_KEYS:
        raise KXKPartitionLemmaIntegrityError("KXK metadata outcome counts are malformed")
    for key in sorted(_OUTCOME_COUNT_KEYS):
        try:
            _require_int(
                counts.get(key),
                label=f"metadata outcome count {key}",
                maximum=ADDRESS_COUNT,
            )
        except ValueError as exc:
            raise KXKPartitionLemmaIntegrityError(str(exc)) from exc
    if sum(int(counts[key]) for key in _OUTCOME_COUNT_KEYS) != ADDRESS_COUNT:
        raise KXKPartitionLemmaIntegrityError(
            "KXK metadata outcome counts do not cover the address domain"
        )
    return decoded


def _decode_transport(transport: bytes, *, piece: str) -> bytes:
    try:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        decoded = decompressor.decompress(transport, DECODED_BYTES + 1)
        if decompressor.unconsumed_tail or len(decoded) > DECODED_BYTES:
            raise KXKPartitionLemmaIntegrityError(
                "KXK gzip expands beyond the exact decoded size"
            )
        decoded += decompressor.flush()
    except KXKPartitionLemmaError:
        raise
    except zlib.error as exc:
        raise KXKPartitionLemmaIntegrityError(
            f"KXK transport is not a strict gzip stream: {exc}"
        ) from exc
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or len(decoded) != DECODED_BYTES
    ):
        raise KXKPartitionLemmaIntegrityError(
            "KXK transport is truncated, concatenated, or has the wrong decoded size"
        )
    try:
        magic, piece_code, count = _HEADER.unpack(decoded[: _HEADER.size])
    except struct.error as exc:
        raise KXKPartitionLemmaIntegrityError("KXK decoded header is truncated") from exc
    if magic != _MAGIC or piece_code != ord(piece) or count != ADDRESS_COUNT:
        raise KXKPartitionLemmaIntegrityError("KXK decoded header is unsupported")
    return decoded


def _decode_key(index: int) -> tuple[int, int, int, int]:
    side = index & 1
    value = index >> 1
    weak_king = value & 63
    value >>= 6
    strong_piece = value & 63
    strong_king = value >> 6
    return strong_king, strong_piece, weak_king, side


def _encode_key(strong_king: int, strong_piece: int, weak_king: int, side: int) -> int:
    return (((strong_king * 64) + strong_piece) * 64 + weak_king) * 2 + side


def _canonical_position(index: int, piece: str) -> Position | None:
    strong_king, strong_piece, weak_king, side = _decode_key(index)
    if len({strong_king, strong_piece, weak_king}) != 3:
        return None
    board = [EMPTY] * 64
    board[strong_king] = "K"
    board[strong_piece] = piece
    board[weak_king] = "k"
    position = Position(tuple(board), side, 0, -1, 0, 1)
    # A legal chess position cannot have the side that just moved still in
    # check.  This one canonical rule-oracle predicate also rejects adjacent
    # kings and replaces the tablebase module's private validity routine.
    if in_check(position, opposite(position.turn)):
        return None
    return position


def _child_cell(
    child: Position,
    *,
    piece: str,
    outcomes: bytes,
    ranks: bytes,
    parent_index: int,
) -> tuple[int, int, bool]:
    if piece not in child.board:
        occupied = sorted(item for item in child.board if item != EMPTY)
        if occupied != ["K", "k"] or not insufficient_material(child):
            raise KXKPartitionLemmaIntegrityError(
                f"cell {parent_index} exits K{piece}K without exact KvK draw material"
            )
        return _DRAW, 0, True
    try:
        strong_king = child.board.index("K")
        strong_piece = child.board.index(piece)
        weak_king = child.board.index("k")
    except ValueError as exc:
        raise KXKPartitionLemmaIntegrityError(
            f"cell {parent_index} legal successor has malformed K{piece}K material"
        ) from exc
    child_index = _encode_key(
        strong_king,
        strong_piece,
        weak_king,
        child.turn,
    )
    if not 0 <= child_index < ADDRESS_COUNT:
        raise KXKPartitionLemmaIntegrityError(
            f"cell {parent_index} legal successor key is out of range"
        )
    outcome = outcomes[child_index]
    rank = ranks[child_index]
    if outcome not in {_WIN, _LOSS, _DRAW}:
        raise KXKPartitionLemmaIntegrityError(
            f"cell {parent_index} legal successor {child_index} is not a valid exact cell"
        )
    return outcome, rank, False


def _check_rank_equation(
    *,
    index: int,
    outcome: int,
    rank: int,
    terminal: str | None,
    children: Sequence[tuple[int, int]],
) -> None:
    """Check one local ranked-game equation; kept small for hostile fixtures."""

    if terminal == "checkmate":
        if children or outcome != _LOSS or rank != 0:
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} checkmate is not exact LOSS rank zero"
            )
        return
    if terminal == "stalemate":
        if children or outcome != _DRAW or rank != 0:
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} stalemate is not exact DRAW rank zero"
            )
        return
    if terminal is not None:
        raise KXKPartitionLemmaIntegrityError(
            f"cell {index} has unsupported terminal code {terminal!r}"
        )
    if not children:
        raise KXKPartitionLemmaIntegrityError(
            f"cell {index} is nonterminal without legal successors"
        )

    if outcome == _WIN:
        losing_ranks = [child_rank for child, child_rank in children if child == _LOSS]
        if not losing_ranks or rank != min(losing_ranks) + 1:
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} WIN rank does not descend exactly to a LOSS witness"
            )
    elif outcome == _LOSS:
        if any(child != _WIN for child, _ in children):
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} LOSS does not have complete WIN-child coverage"
            )
        if rank != max(child_rank for _, child_rank in children) + 1:
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} LOSS rank does not exceed every WIN child exactly"
            )
    elif outcome == _DRAW:
        if rank != 0:
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} DRAW carries a nonzero decisive rank"
            )
        if any(child == _LOSS for child, _ in children):
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} DRAW has a winning move to child LOSS"
            )
        if not any(child == _DRAW for child, _ in children):
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} DRAW has no closed DRAW continuation"
            )
    else:
        raise KXKPartitionLemmaIntegrityError(
            f"cell {index} has unsupported outcome byte {outcome}"
        )


def _replay_partition(decoded: bytes, *, piece: str) -> _ReplayMetrics:
    outcomes = decoded[_HEADER.size : _HEADER.size + ADDRESS_COUNT]
    ranks = decoded[_HEADER.size + ADDRESS_COUNT :]
    if len(outcomes) != ADDRESS_COUNT or len(ranks) != ADDRESS_COUNT:
        raise KXKPartitionLemmaIntegrityError("KXK semantic arrays have wrong size")

    invalid = wins = losses = draws = 0
    checkmates = stalemates = transitions = capture_exits = 0
    maximum_rank = 0
    for index in range(ADDRESS_COUNT):
        outcome = outcomes[index]
        rank = ranks[index]
        position = _canonical_position(index, piece)
        if position is None:
            invalid += 1
            if outcome != _INVALID or rank != 0:
                raise KXKPartitionLemmaIntegrityError(
                    f"invalid cell {index} has noncanonical outcome/rank bytes"
                )
            continue
        if outcome not in {_WIN, _LOSS, _DRAW}:
            raise KXKPartitionLemmaIntegrityError(
                f"valid cell {index} is INVALID, UNKNOWN, or unsupported"
            )
        if outcome == _WIN:
            wins += 1
        elif outcome == _LOSS:
            losses += 1
        else:
            draws += 1
        maximum_rank = max(maximum_rank, rank)

        moves = legal_moves(position)
        if len(moves) > MAX_LEGAL_SUCCESSORS:
            raise KXKPartitionLemmaIntegrityError(
                f"cell {index} exceeds the legal-successor resource bound"
            )
        terminal: str | None = None
        children: list[tuple[int, int]] = []
        if not moves:
            terminal = "checkmate" if in_check(position) else "stalemate"
            if terminal == "checkmate":
                checkmates += 1
            else:
                stalemates += 1
        else:
            for move in moves:
                child = apply_move(position, move)
                child_outcome, child_rank, capture_exit = _child_cell(
                    child,
                    piece=piece,
                    outcomes=outcomes,
                    ranks=ranks,
                    parent_index=index,
                )
                children.append((child_outcome, child_rank))
                transitions += 1
                capture_exits += int(capture_exit)
        _check_rank_equation(
            index=index,
            outcome=outcome,
            rank=rank,
            terminal=terminal,
            children=children,
        )

    valid = wins + losses + draws
    return _ReplayMetrics(
        valid_positions=valid,
        invalid_positions=invalid,
        win_positions=wins,
        loss_positions=losses,
        draw_positions=draws,
        initial_checkmates=checkmates,
        initial_stalemates=stalemates,
        legal_transition_count=transitions,
        capture_draw_exit_count=capture_exits,
        max_rank=maximum_rank,
    )


def _require_metadata_matches_replay(
    metadata: Mapping[str, object],
    metrics: _ReplayMetrics,
) -> None:
    expected_scalars = {
        "valid_positions": metrics.valid_positions,
        "initial_checkmates": metrics.initial_checkmates,
        "initial_stalemates": metrics.initial_stalemates,
        "max_dtm_plies": metrics.max_rank,
    }
    for key, expected in expected_scalars.items():
        if metadata.get(key) != expected:
            raise KXKPartitionLemmaIntegrityError(
                f"KXK metadata field {key!r} differs from full replay"
            )
    counts = metadata.get("outcome_counts")
    assert isinstance(counts, dict)
    expected_counts = {
        "invalid": metrics.invalid_positions,
        "win": metrics.win_positions,
        "loss": metrics.loss_positions,
        "draw": metrics.draw_positions,
    }
    if counts != expected_counts:
        raise KXKPartitionLemmaIntegrityError(
            "KXK metadata outcome counts differ from full replay"
        )


def _head_from_replay(
    *,
    piece: str,
    transport: _FileSnapshot,
    metadata: _FileSnapshot,
    decoded: bytes,
    metrics: _ReplayMetrics,
) -> KXKPartitionLemmaHead:
    return KXKPartitionLemmaHead(
        verifier_profile=KXK_PARTITION_LEMMA_VERIFIER_PROFILE,
        rules_profile_id=RULE_PROFILE_ID,
        base_game_profile=KXK_BASE_GAME_PROFILE,
        source_schema=KXK_SOURCE_SCHEMA,
        piece=piece,
        material=f"K{piece}K",
        address_bits=ADDRESS_BITS,
        address_count=ADDRESS_COUNT,
        transport_size=len(transport.content),
        transport_sha256=transport.sha256,
        metadata_size=len(metadata.content),
        metadata_sha256=metadata.sha256,
        decoded_size=len(decoded),
        decoded_sha256=hashlib.sha256(decoded).hexdigest(),
        valid_positions=metrics.valid_positions,
        invalid_positions=metrics.invalid_positions,
        win_positions=metrics.win_positions,
        loss_positions=metrics.loss_positions,
        draw_positions=metrics.draw_positions,
        initial_checkmates=metrics.initial_checkmates,
        initial_stalemates=metrics.initial_stalemates,
        legal_transition_count=metrics.legal_transition_count,
        capture_draw_exit_count=metrics.capture_draw_exit_count,
        max_rank=metrics.max_rank,
    )


def _canonical_required_head(
    required_head: KXKPartitionLemmaHead | None,
) -> KXKPartitionLemmaHead | None:
    if required_head is None:
        return None
    if not isinstance(required_head, KXKPartitionLemmaHead):
        raise TypeError("required_head must be a KXKPartitionLemmaHead or None")
    return KXKPartitionLemmaHead.from_bytes(required_head.canonical_bytes())


def verify_kxk_partition_files(
    transport_path: str | Path,
    metadata_path: str | Path,
    *,
    piece: str,
    required_head: KXKPartitionLemmaHead | None = None,
    use_cache: bool = True,
) -> KXKPartitionLemmaVerification:
    """Fully replay exact KXK source files and return their canonical head."""

    if not isinstance(piece, str) or piece.upper() not in {"Q", "R"}:
        raise ValueError("piece must be Q or R")
    if not isinstance(use_cache, bool):
        raise TypeError("use_cache must be a boolean")
    canonical_piece = piece.upper()
    expected = _canonical_required_head(required_head)
    start = time.monotonic()

    transport = _stable_snapshot(
        transport_path,
        maximum=MAX_TRANSPORT_BYTES,
        label="KXK transport",
    )
    metadata = _stable_snapshot(
        metadata_path,
        maximum=MAX_METADATA_BYTES,
        label="KXK metadata",
    )
    cache_key = (transport.sha256, metadata.sha256)
    cached: KXKPartitionLemmaHead | None = None
    if use_cache:
        with _CACHE_LOCK:
            cached = _VERIFIED_CACHE.get(cache_key)
    if cached is not None:
        if cached.piece != canonical_piece:
            raise KXKPartitionLemmaIntegrityError(
                "cached immutable sources are bound to a different KXK piece"
            )
        _confirm_snapshot(transport, label="KXK transport")
        _confirm_snapshot(metadata, label="KXK metadata")
        if expected is not None and cached != expected:
            raise KXKPartitionLemmaHeadMismatchError(
                "verified KXK source does not match the externally retained head",
                expected=expected,
                current=cached,
            )
        return KXKPartitionLemmaVerification(
            cached,
            cache_hit=True,
            elapsed_seconds=time.monotonic() - start,
        )

    decoded_metadata = _strict_metadata(
        metadata.content,
        piece=canonical_piece,
        transport_size=len(transport.content),
        transport_sha256=transport.sha256,
    )
    decoded = _decode_transport(transport.content, piece=canonical_piece)
    metrics = _replay_partition(decoded, piece=canonical_piece)
    _require_metadata_matches_replay(decoded_metadata, metrics)
    current = _head_from_replay(
        piece=canonical_piece,
        transport=transport,
        metadata=metadata,
        decoded=decoded,
        metrics=metrics,
    )
    _confirm_snapshot(transport, label="KXK transport")
    _confirm_snapshot(metadata, label="KXK metadata")
    if expected is not None and current != expected:
        raise KXKPartitionLemmaHeadMismatchError(
            "verified KXK source does not match the externally retained head",
            expected=expected,
            current=current,
        )
    if use_cache:
        with _CACHE_LOCK:
            prior = _VERIFIED_CACHE.setdefault(cache_key, current)
            if prior != current:
                raise KXKPartitionLemmaIntegrityError(
                    "immutable source hashes reproduced a different lemma head"
                )
    return KXKPartitionLemmaVerification(
        current,
        cache_hit=False,
        elapsed_seconds=time.monotonic() - start,
    )


def verify_bundled_kxk_partition(
    piece: str,
    *,
    required_head: KXKPartitionLemmaHead | None = None,
    use_cache: bool = True,
) -> KXKPartitionLemmaVerification:
    """Fully replay one bundled ``kqk.tb.gz`` or ``krk.tb.gz`` resource."""

    if not isinstance(piece, str) or piece.upper() not in {"Q", "R"}:
        raise ValueError("piece must be Q or R")
    canonical_piece = piece.upper()
    resource_name = "kqk.tb.gz" if canonical_piece == "Q" else "krk.tb.gz"
    metadata_name = resource_name.removesuffix(".gz") + ".json"
    package = resources.files("ugts_chess.resources")
    with ExitStack() as stack:
        transport = stack.enter_context(
            resources.as_file(package.joinpath(resource_name))
        )
        metadata = stack.enter_context(
            resources.as_file(package.joinpath(metadata_name))
        )
        return verify_kxk_partition_files(
            transport,
            metadata,
            piece=canonical_piece,
            required_head=required_head,
            use_cache=use_cache,
        )


__all__ = [
    "ADDRESS_BITS",
    "ADDRESS_COUNT",
    "DECODED_BYTES",
    "KXK_BASE_GAME_PROFILE",
    "KXK_PARTITION_LEMMA_HEAD_SCHEMA",
    "KXK_PARTITION_LEMMA_VERIFIER_PROFILE",
    "KXKPartitionLemmaError",
    "KXKPartitionLemmaHead",
    "KXKPartitionLemmaHeadMismatchError",
    "KXKPartitionLemmaIntegrityError",
    "KXKPartitionLemmaSourceChangedError",
    "KXKPartitionLemmaVerification",
    "clear_kxk_partition_lemma_cache",
    "verify_bundled_kxk_partition",
    "verify_kxk_partition_files",
]
