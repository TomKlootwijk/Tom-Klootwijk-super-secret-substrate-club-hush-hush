"""Independent Python verifier for UGYUVS1 ``.ugsp4c`` camera evidence.

The implementation follows ``native/ugtc4d/YUV_SEED_CAPTURE_FORMAT.md`` but
does not call or bind the C++ reader.  It regenerates the UGLUT2-driven UGTRV1
address program with the Python substrate oracle, validates both durable commit
slots, replays canonical novelty blocks, and reconstructs the authoritative
dense Camera2 YUV420 planes and sensor timestamps exactly.

No RGB conversion, inferred geometry, image completion, MP4, or MediaCodec
operation occurs here.  A non-predicted camera byte remains stored evidence.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct
from typing import Any, BinaryIO

from .chrono_substrate import (
    ChronoSubstrateError,
    SubstrateTraversalRecipe,
    derive_substrate_traversal,
)
from .gsp4_camera_codeword import (
    DenseYuv420Frame,
    GSP4_CAMERA_LINEAGE_NAMESPACE,
)
from .scatter import combine_seed


FILE_MAGIC = b"UGYUVS1\0"
FRAME_MAGIC = b"UGYFRM1\0"
BLOCK_MAGIC = b"UGNBLK1\0"
TERMINAL_MAGIC = b"UGYEND1\0"
COMMIT_MAGIC = b"UGCMIT1\0"

FILE_HEADER_BYTES = 512
STATIC_HEADER_BYTES = 256
COMMIT_SLOT_BYTES = 128
COMMIT_SLOT_OFFSETS = (256, 384)
STATIC_DIGEST_OFFSET = 208
COMMIT_DIGEST_OFFSET = 80
FRAME_HEADER_BYTES = 384
FRAME_CONTENT_DIGEST_OFFSET = 304
FRAME_PRE_SUBSTRATE_DIGEST_OFFSET = 336
FRAME_NOVELTY_EVENT_COUNT_OFFSET = 368
BLOCK_HEADER_BYTES = 192
BLOCK_CONTENT_DIGEST_OFFSET = 104
BLOCK_PREDICTOR_OFFSET = 136
BLOCK_REPRESENTATION_OFFSET = 140
BLOCK_LINEAGE_DIGEST_OFFSET = 144
TERMINAL_HEADER_BYTES = 192
TERMINAL_CONTENT_DIGEST_OFFSET = 144
ALIGNMENT = 64

FILE_FLAGS = 1
COMMIT_FINAL = 1
FRAME_CHECKPOINT = 1
NO_PREVIOUS_ORDINAL = 0xFFFFFFFF
UGCODE24_420_PROFILE = 1
SAMPLE_BITS = 8

REPRESENTATION_ZERO = 0
REPRESENTATION_DENSE = 1
REPRESENTATION_SPARSE_BITMASK = 2
REPRESENTATION_SPARSE_GAPS = 3
REPRESENTATION_NAMES = (
    "ZERO",
    "DENSE",
    "SPARSE_BITMASK",
    "SPARSE_GAPS",
)

PREDICTOR_PREVIOUS_SAME_ADDRESS = 2
PREDICTOR_RAW_EXACT_LANE = 4
INT64_MIN = -(1 << 63)
ZERO_SHA256 = bytes(32)

_LINEAGE_DOMAIN = b"UGYUVS1-GSP4-codeword-lineage-v1\0"
_RECIPE_DOMAIN = b"UGYUVS1-UGCODE24-420-seed-recipe-v1\0"
_STATE_DOMAIN = b"UGYUVS1-executable-seed-state-v1\0"
_LEDGER_DOMAIN = b"UGYUVS1-Python-verification-ledger-v1\0"
_OPERATOR_MEANING = (
    "UGCODE24-420-v1:luma-address-codeword=[Y(x,y),U(floor(x/2),floor(y/2)),"
    "V(floor(x/2),floor(y/2))];storage=UGTRV1-luma-order;"
    "chroma-owner=even-x-even-y-once;novelty=mod256-mask-nonzero-values"
).encode("ascii") + b"\0"


class Ugyuvs1Error(ValueError):
    """A UGYUVS1 capture failed a structural or exact-replay invariant."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise Ugyuvs1Error(message)


def _sha256(data: bytes | bytearray | memoryview) -> bytes:
    return hashlib.sha256(data).digest()


def _hash_zero_range(data: bytes, offset: int, count: int) -> bytes:
    _require(0 <= offset <= len(data) and 0 <= count <= len(data) - offset,
             "digest zero range escapes its record")
    digest = hashlib.sha256()
    digest.update(data[:offset])
    digest.update(bytes(count))
    digest.update(data[offset + count :])
    return digest.digest()


def _hash_header_payload_zero_range(
    header: bytes,
    offset: int,
    count: int,
    payload: bytes,
) -> bytes:
    digest = hashlib.sha256()
    digest.update(header[:offset])
    digest.update(bytes(count))
    digest.update(header[offset + count :])
    digest.update(payload)
    return digest.digest()


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _i64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<q", data, offset)[0]


def _digest(data: bytes, offset: int) -> bytes:
    return data[offset : offset + 32]


def _align_up(value: int) -> int:
    return (int(value) + ALIGNMENT - 1) // ALIGNMENT * ALIGNMENT


def _read_exact(stream: BinaryIO, size: int, label: str) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise Ugyuvs1Error(f"{label} is truncated")
    return data


def _file_sha256(path: Path, *, limit: int | None = None) -> str:
    remaining = limit
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while remaining is None or remaining:
            count = 1024 * 1024 if remaining is None else min(1024 * 1024, remaining)
            block = stream.read(count)
            if not block:
                break
            digest.update(block)
            if remaining is not None:
                remaining -= len(block)
    if remaining not in (None, 0):
        raise Ugyuvs1Error("capture is shorter than its committed prefix")
    return digest.hexdigest()


def _append_uleb128(output: bytearray, value: int) -> None:
    _require(value >= 0, "negative ULEB128 value")
    while True:
        lane = value & 0x7F
        value >>= 7
        if value:
            output.append(lane | 0x80)
        else:
            output.append(lane)
            return


def _read_canonical_uleb128(data: bytes, position: int) -> tuple[int, int]:
    start = position
    result = 0
    shift = 0
    while True:
        _require(position < len(data), "SPARSE_GAPS ULEB128 is truncated")
        lane = data[position]
        position += 1
        _require(shift < 64, "SPARSE_GAPS ULEB128 overflows uint64")
        result |= (lane & 0x7F) << shift
        if not lane & 0x80:
            _require(position == start + 1 or lane != 0,
                     "SPARSE_GAPS ULEB128 is not minimally encoded")
            return result, position
        shift += 7


def _splitmix64_numpy(value: Any, np: Any) -> Any:
    golden = np.uint64(0x9E3779B97F4A7C15)
    with np.errstate(over="ignore"):
        value = value.astype(np.uint64, copy=False) + golden
        value = (value ^ (value >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        value = (value ^ (value >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return value ^ (value >> np.uint64(31))


def _combine_seed_numpy(seed: int, value: Any, np: Any) -> Any:
    seed_lane = np.uint64(seed & ((1 << 64) - 1))
    golden = np.uint64(0x9E3779B97F4A7C15)
    with np.errstate(over="ignore"):
        mixed = (
            _splitmix64_numpy(value, np)
            + golden
            + (seed_lane << np.uint64(6))
            + (seed_lane >> np.uint64(2))
        )
        return _splitmix64_numpy(seed_lane ^ mixed, np)


def _gsp4_mix32_numpy(value: Any, np: Any) -> Any:
    with np.errstate(over="ignore"):
        value = value.astype(np.uint32, copy=False)
        value = value ^ (value >> np.uint32(16))
        value = value * np.uint32(0x7FEB352D)
        value = value ^ (value >> np.uint32(15))
        value = value * np.uint32(0x846CA68B)
        return value ^ (value >> np.uint32(16))


@dataclass(frozen=True)
class Ugyuvs1Commit:
    """One structurally valid durable commit slot."""

    slot_index: int
    generation: int
    finalized: bool
    frame_count: int
    committed_end: int
    last_sensor_timestamp_ns: int
    terminal_sha256: bytes


@dataclass(frozen=True)
class Ugyuvs1Inspection:
    """Header and selected-commit facts established before frame replay."""

    path: Path
    actual_bytes: int
    width: int
    height: int
    checkpoint_interval: int
    novelty_block_luma_addresses: int
    root_seed: int
    traversal_recipe_seed: int
    record_offset: int
    literal_uglut2_bytes: int
    literal_uglut2_sha256: str
    traversal_sha256: str
    recipe_sha256: str
    static_header_sha256: str
    generation: int
    selected_commit_slot: int
    committed_frames: int
    committed_bytes: int
    finalized: bool
    recovered_incomplete: bool
    uncommitted_tail_bytes: int
    terminal_record_sha256: str


@dataclass(frozen=True)
class Ugyuvs1Frame:
    """One byte-exact replayed Camera2 observation."""

    ordinal: int
    width: int
    height: int
    sensor_timestamp_ns: int
    frame_number: int
    y: bytes
    u: bytes
    v: bytes
    canonical_metadata: bytes
    checkpoint: bool
    novelty_event_count: int
    representation_counts: tuple[int, int, int, int]
    content_sha256: str
    pre_substrate_sha256: str

    @property
    def dense(self) -> DenseYuv420Frame:
        return DenseYuv420Frame(
            self.width,
            self.height,
            self.sensor_timestamp_ns,
            self.y,
            self.u,
            self.v,
        )

    @property
    def authoritative_bytes(self) -> int:
        return len(self.y) + len(self.u) + len(self.v)

    def receipt(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal,
            "sensor_timestamp_ns": self.sensor_timestamp_ns,
            "frame_number": self.frame_number,
            "checkpoint": self.checkpoint,
            "authoritative_bytes": self.authoritative_bytes,
            "novelty_event_count": self.novelty_event_count,
            "representations": {
                name: self.representation_counts[index]
                for index, name in enumerate(REPRESENTATION_NAMES)
            },
            "y_sha256": hashlib.sha256(self.y).hexdigest(),
            "u_sha256": hashlib.sha256(self.u).hexdigest(),
            "v_sha256": hashlib.sha256(self.v).hexdigest(),
            "metadata_sha256": hashlib.sha256(self.canonical_metadata).hexdigest(),
            "pre_substrate_sha256": self.pre_substrate_sha256,
            "frame_record_sha256": self.content_sha256,
        }


@dataclass(frozen=True)
class Ugyuvs1Verification:
    """Complete strict replay receipt without retaining dense planes."""

    inspection: Ugyuvs1Inspection
    file_sha256: str
    committed_prefix_sha256: str
    frame_ledger_sha256: str
    total_authoritative_bytes: int
    total_novelty_events: int
    representation_counts: tuple[int, int, int, int]
    frames: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        inspection = self.inspection
        return {
            "schema": "ugyuvs1-python-verification-v1",
            "status": "PASS",
            "path": str(inspection.path),
            "file_sha256": self.file_sha256,
            "committed_prefix_sha256": self.committed_prefix_sha256,
            "frame_ledger_sha256": self.frame_ledger_sha256,
            "actual_bytes": inspection.actual_bytes,
            "committed_bytes": inspection.committed_bytes,
            "uncommitted_tail_bytes": inspection.uncommitted_tail_bytes,
            "finalized": inspection.finalized,
            "recovered_incomplete": inspection.recovered_incomplete,
            "generation": inspection.generation,
            "selected_commit_slot": inspection.selected_commit_slot,
            "width": inspection.width,
            "height": inspection.height,
            "profile": "UGCODE24_420_CAMERA_EXACT",
            "committed_frames": inspection.committed_frames,
            "authoritative_bytes_per_frame": (
                inspection.width * inspection.height * 3 // 2
            ),
            "total_authoritative_bytes": self.total_authoritative_bytes,
            "total_novelty_events": self.total_novelty_events,
            "representations": {
                name: self.representation_counts[index]
                for index, name in enumerate(REPRESENTATION_NAMES)
            },
            "root_seed": inspection.root_seed,
            "traversal_recipe_seed": inspection.traversal_recipe_seed,
            "literal_uglut2_bytes": inspection.literal_uglut2_bytes,
            "literal_uglut2_sha256": inspection.literal_uglut2_sha256,
            "traversal_sha256": inspection.traversal_sha256,
            "recipe_sha256": inspection.recipe_sha256,
            "static_header_sha256": inspection.static_header_sha256,
            "terminal_record_sha256": inspection.terminal_record_sha256,
            "frames": list(self.frames),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


def _parse_commit(
    slot: bytes,
    *,
    slot_index: int,
    record_offset: int,
    actual_bytes: int,
) -> Ugyuvs1Commit | None:
    if len(slot) != COMMIT_SLOT_BYTES or slot[:8] != COMMIT_MAGIC:
        return None
    if _digest(slot, COMMIT_DIGEST_OFFSET) != _hash_zero_range(
        slot, COMMIT_DIGEST_OFFSET, 32
    ):
        return None
    generation = _u64(slot, 8)
    flags = _u32(slot, 16)
    if (
        generation == 0
        or flags & ~COMMIT_FINAL
        or _u32(slot, 20) != 0
        or any(slot[112:128])
    ):
        return None
    finalized = bool(flags & COMMIT_FINAL)
    frame_count = _u64(slot, 24)
    committed_end = _u64(slot, 32)
    last_pts = _i64(slot, 40)
    terminal = _digest(slot, 48)
    empty_end = record_offset + (TERMINAL_HEADER_BYTES if finalized else 0)
    if committed_end < record_offset or committed_end > actual_bytes:
        return None
    if frame_count == 0 and (
        committed_end != empty_end
        or last_pts != INT64_MIN
        or (not any(terminal) if finalized else any(terminal))
    ):
        return None
    return Ugyuvs1Commit(
        slot_index,
        generation,
        finalized,
        frame_count,
        committed_end,
        last_pts,
        terminal,
    )


class Ugyuvs1Capture:
    """Parse and strictly replay one UGYUVS1 file without the native reader."""

    def __init__(self, path: str | Path, *, require_final: bool = False) -> None:
        self.path = Path(path)
        try:
            actual_bytes = self.path.stat().st_size
        except OSError as error:
            raise Ugyuvs1Error(f"cannot stat capture: {self.path}") from error
        _require(actual_bytes >= FILE_HEADER_BYTES, "file header is truncated")
        with self.path.open("rb") as stream:
            header = _read_exact(stream, FILE_HEADER_BYTES, "file header")
            self._parse_static_header(header, actual_bytes, stream)

        commits = [
            _parse_commit(
                header[offset : offset + COMMIT_SLOT_BYTES],
                slot_index=index,
                record_offset=self.record_offset,
                actual_bytes=actual_bytes,
            )
            for index, offset in enumerate(COMMIT_SLOT_OFFSETS)
        ]
        valid = [item for item in commits if item is not None]
        _require(bool(valid), "neither crash-safe commit slot is valid")
        # The C++ ABI chooses slot 1 when equal generations are encountered.
        self.commit = max(valid, key=lambda item: (item.generation, item.slot_index))
        final_name = self.path.name.endswith(".ugsp4c")
        if final_name:
            _require(self.commit.finalized,
                     "completed .ugsp4c lacks a valid FINAL commit")
        if require_final:
            _require(self.commit.finalized,
                     "verification requires a valid FINAL commit")
        _require(
            not self.commit.finalized or self.commit.committed_end == actual_bytes,
            "FINAL commit does not cover the complete file",
        )
        self.inspection = Ugyuvs1Inspection(
            path=self.path.resolve(),
            actual_bytes=actual_bytes,
            width=self.width,
            height=self.height,
            checkpoint_interval=self.checkpoint_interval,
            novelty_block_luma_addresses=self.block_luma_addresses,
            root_seed=self.root_seed,
            traversal_recipe_seed=self.recipe_seed,
            record_offset=self.record_offset,
            literal_uglut2_bytes=len(self.literal_uglut2),
            literal_uglut2_sha256=self.uglut2_sha.hex(),
            traversal_sha256=self.traversal_sha.hex(),
            recipe_sha256=self.recipe_sha.hex(),
            static_header_sha256=self.static_sha.hex(),
            generation=self.commit.generation,
            selected_commit_slot=self.commit.slot_index,
            committed_frames=self.commit.frame_count,
            committed_bytes=self.commit.committed_end,
            finalized=self.commit.finalized,
            recovered_incomplete=not self.commit.finalized,
            uncommitted_tail_bytes=actual_bytes - self.commit.committed_end,
            terminal_record_sha256=self.commit.terminal_sha256.hex(),
        )

    def _parse_static_header(
        self,
        header: bytes,
        actual_bytes: int,
        stream: BinaryIO,
    ) -> None:
        _require(header[:8] == FILE_MAGIC, "file magic mismatch")
        _require(
            _u16(header, 8) == 1
            and _u16(header, 10) == 0
            and _u32(header, 12) == FILE_HEADER_BYTES,
            "unsupported file version/header",
        )
        _require(_u32(header, 16) == FILE_FLAGS,
                 "file flags do not require zero-novelty omission")
        self.width = _u32(header, 20)
        self.height = _u32(header, 24)
        _require(
            2 <= self.width <= 65_534
            and 2 <= self.height <= 65_534
            and not self.width & 1
            and not self.height & 1,
            "capture dimensions are not valid YUV420",
        )
        _require(
            _u32(header, 28) == self.width // 2
            and _u32(header, 32) == self.height // 2
            and _u32(header, 36) == UGCODE24_420_PROFILE
            and _u32(header, 40) == SAMPLE_BITS,
            "logical UGCODE24-420 profile mismatch",
        )
        self.checkpoint_interval = _u32(header, 44)
        self.block_luma_addresses = _u32(header, 48)
        lut_bytes = _u32(header, 52)
        self.root_seed = _u64(header, 56)
        self.recipe_seed = _u64(header, 64)
        self.record_offset = _u64(header, 72)
        _require(
            self.checkpoint_interval >= 1
            and 1 <= self.block_luma_addresses <= 65_536,
            "capture checkpoint/block profile is invalid",
        )
        _require(
            self.record_offset == _align_up(FILE_HEADER_BYTES + lut_bytes)
            and self.record_offset <= actual_bytes,
            "record data offset is noncanonical",
        )
        _require(not any(header[240:256]), "static reserved bytes are nonzero")
        static_header = header[:STATIC_HEADER_BYTES]
        self.static_sha = _digest(header, STATIC_DIGEST_OFFSET)
        _require(
            self.static_sha
            == _hash_zero_range(static_header, STATIC_DIGEST_OFFSET, 32),
            "static header SHA-256 mismatch",
        )
        self.literal_uglut2 = _read_exact(stream, lut_bytes, "UGLUT2 dependency")
        padding = _read_exact(
            stream,
            self.record_offset - FILE_HEADER_BYTES - lut_bytes,
            "UGLUT2 alignment padding",
        )
        _require(not any(padding), "UGLUT2 alignment padding is nonzero")
        self.uglut2_sha = _sha256(self.literal_uglut2)
        self.traversal_sha = _digest(header, 112)
        _require(self.uglut2_sha == _digest(header, 80),
                 "literal UGLUT2 SHA-256 mismatch")
        recipe = SubstrateTraversalRecipe(
            self.width,
            self.height,
            self.root_seed,
            self.recipe_seed,
            self.uglut2_sha.hex(),
            self.traversal_sha.hex(),
        )
        try:
            self.traversal = derive_substrate_traversal(
                recipe,
                self.literal_uglut2,
                verify_digest=True,
            )
        except ChronoSubstrateError as error:
            raise Ugyuvs1Error(f"seed traversal regeneration failed: {error}") from error
        recipe_preimage = bytearray(_RECIPE_DOMAIN)
        recipe_preimage.extend(
            struct.pack(
                "<IIIQQ",
                self.width,
                self.height,
                UGCODE24_420_PROFILE,
                self.root_seed,
                self.recipe_seed,
            )
        )
        recipe_preimage.extend(self.uglut2_sha)
        recipe_preimage.extend(self.traversal_sha)
        self.recipe_sha = _sha256(recipe_preimage)
        _require(
            self.recipe_sha == _digest(header, 144)
            and _sha256(_OPERATOR_MEANING) == _digest(header, 176),
            "seed recipe/operator digest mismatch",
        )
        self._prepare_address_program()

    def _prepare_address_program(self) -> None:
        try:
            import numpy as np
        except ImportError as error:
            raise Ugyuvs1Error("UGYUVS1 replay requires NumPy") from error
        traversal = np.asarray(self.traversal, dtype=np.uint32)
        cartesian = traversal.astype(np.uint64)
        row = cartesian // np.uint64(self.width)
        column = cartesian % np.uint64(self.width)
        owner = ((row & np.uint64(1)) == 0) & ((column & np.uint64(1)) == 0)
        owner_count = int(np.count_nonzero(owner))
        expected_owners = self.width * self.height // 4
        _require(owner_count == expected_owners,
                 "regenerated traversal has the wrong chroma owner count")
        owner_prefix = np.cumsum(owner.astype(np.uint64)) - owner.astype(np.uint64)
        lane_start = np.arange(traversal.size, dtype=np.uint64) + owner_prefix * 2
        owner_ordinals = np.flatnonzero(owner)
        chroma = (
            (row[owner] // np.uint64(2)) * np.uint64(self.width // 2)
            + column[owner] // np.uint64(2)
        ).astype(np.uint32)
        _require(np.unique(chroma).size == expected_owners,
                 "regenerated traversal repeats a chroma owner")

        session = combine_seed(self.root_seed, self.recipe_seed)
        prefix = combine_seed(session, GSP4_CAMERA_LINEAGE_NAMESPACE)
        persistent = _combine_seed_numpy(prefix, cartesian, np)
        self._np = np
        self._traversal = traversal
        self._owner = owner
        self._owner_ordinals = owner_ordinals
        self._chroma_addresses = chroma
        self._lane_start = lane_start
        self._lineage_seeds = (persistent & np.uint64(0xFFFFFFFF)).astype(np.uint32)

    def _lineage_digest(self, frame_ordinal: int, first: int, count: int) -> bytes:
        np = self._np
        seeds = self._lineage_seeds[first : first + count]
        routed = _gsp4_mix32_numpy(seeds ^ np.uint32(frame_ordinal), np)
        pairs = np.empty(count * 2, dtype="<u4")
        pairs[0::2] = seeds
        pairs[1::2] = routed
        digest = hashlib.sha256()
        digest.update(_LINEAGE_DOMAIN)
        digest.update(struct.pack("<III", frame_ordinal, first, count))
        digest.update(pairs.tobytes())
        return digest.digest()

    def _decode_block(
        self,
        payload: bytes,
        *,
        novelty_position: int,
        novelty_bytes: int,
        frame_ordinal: int,
        block_ordinal: int,
        checkpoint: bool,
    ) -> tuple[bytes, int, int, int]:
        _require(
            novelty_position + BLOCK_HEADER_BYTES <= novelty_bytes,
            "novelty block header is truncated",
        )
        header = payload[novelty_position : novelty_position + BLOCK_HEADER_BYTES]
        _require(
            header[:8] == BLOCK_MAGIC
            and _u16(header, 8) == 1
            and _u16(header, 10) == 0
            and _u32(header, 12) == BLOCK_HEADER_BYTES
            and _u32(header, 16) == block_ordinal,
            "novelty block ABI mismatch",
        )
        first = _u32(header, 20)
        luma_count = _u32(header, 24)
        logical_count = _u32(header, 28)
        auxiliary_count = _u32(header, 32)
        value_count = _u32(header, 36)
        predictor = _u32(header, BLOCK_PREDICTOR_OFFSET)
        representation = _u32(header, BLOCK_REPRESENTATION_OFFSET)
        y_bytes = self.width * self.height
        expected_first = block_ordinal * self.block_luma_addresses
        expected_luma = min(self.block_luma_addresses, y_bytes - expected_first)
        _require(
            first == expected_first and luma_count == expected_luma,
            "novelty block luma range mismatch",
        )
        owner_count = int(
            self._np.count_nonzero(self._owner[first : first + luma_count])
        )
        expected_symbols = luma_count + owner_count * 2
        end = novelty_position + BLOCK_HEADER_BYTES + auxiliary_count + value_count
        expected_predictor = (
            PREDICTOR_RAW_EXACT_LANE
            if checkpoint
            else PREDICTOR_PREVIOUS_SAME_ADDRESS
        )
        _require(
            logical_count == expected_symbols
            and end <= novelty_bytes
            and predictor == expected_predictor
            and 0 <= representation <= REPRESENTATION_SPARSE_GAPS
            and _digest(header, BLOCK_LINEAGE_DIGEST_OFFSET)
            == self._lineage_digest(frame_ordinal, first, luma_count)
            and not any(header[176:192]),
            "novelty block sizes, lineage, predictor, or reserved bytes mismatch",
        )
        payload_start = novelty_position + BLOCK_HEADER_BYTES
        auxiliary = payload[payload_start : payload_start + auxiliary_count]
        values = payload[payload_start + auxiliary_count : end]
        logical = bytearray(expected_symbols)
        if representation == REPRESENTATION_ZERO:
            _require(not auxiliary and not values,
                     "ZERO novelty block carries a payload")
        elif representation == REPRESENTATION_DENSE:
            _require(not auxiliary and len(values) == expected_symbols,
                     "DENSE novelty block length mismatch")
            logical[:] = values
        elif representation == REPRESENTATION_SPARSE_BITMASK:
            expected_mask = (expected_symbols + 7) // 8
            _require(len(auxiliary) == expected_mask,
                     "SPARSE_BITMASK occupancy length mismatch")
            if expected_symbols & 7:
                used_bits = expected_symbols & 7
                _require(
                    auxiliary[-1] & ~((1 << used_bits) - 1) == 0,
                    "SPARSE_BITMASK padding bits are nonzero",
                )
            bits = self._np.unpackbits(
                self._np.frombuffer(auxiliary, dtype=self._np.uint8),
                bitorder="little",
            )[:expected_symbols]
            indexes = self._np.flatnonzero(bits)
            _require(len(indexes) == len(values) and not any(value == 0 for value in values),
                     "SPARSE_BITMASK nonzero stream is invalid")
            logical_array = self._np.frombuffer(logical, dtype=self._np.uint8)
            logical_array[indexes] = self._np.frombuffer(values, dtype=self._np.uint8)
        else:
            _require(bool(values), "SPARSE_GAPS requires at least one novelty event")
            gap_position = 0
            value_position = 0
            next_ordinal = 0
            while gap_position < len(auxiliary):
                _require(value_position < len(values),
                         "SPARSE_GAPS has more indexes than values")
                gap, gap_position = _read_canonical_uleb128(auxiliary, gap_position)
                _require(gap <= expected_symbols - next_ordinal,
                         "SPARSE_GAPS address escapes the logical block")
                symbol = next_ordinal + gap
                _require(symbol < expected_symbols and values[value_position] != 0,
                         "SPARSE_GAPS nonzero event is invalid")
                logical[symbol] = values[value_position]
                value_position += 1
                next_ordinal = symbol + 1
            _require(value_position == len(values),
                     "novelty value count disagrees with SPARSE_GAPS indexes")

        logical_bytes = bytes(logical)
        event_count = len(logical_bytes) - logical_bytes.count(0)
        if representation != REPRESENTATION_DENSE:
            _require(event_count == len(values), "sparse novelty event count mismatch")
        event_indexes = self._np.flatnonzero(
            self._np.frombuffer(logical_bytes, dtype=self._np.uint8)
        )
        if event_count:
            gap_values = event_indexes.astype(self._np.int64, copy=True)
            gap_values[1:] -= event_indexes[:-1] + 1
            gap_encoded_bytes = event_count
            threshold = 1 << 7
            while threshold <= expected_symbols:
                gap_encoded_bytes += int(self._np.count_nonzero(gap_values >= threshold))
                threshold <<= 7
        else:
            gap_values = event_indexes
            gap_encoded_bytes = 0
        canonical_representation = REPRESENTATION_ZERO
        canonical_bytes = 0
        if event_count:
            canonical_representation = REPRESENTATION_DENSE
            canonical_bytes = expected_symbols
            bitmask_bytes = (expected_symbols + 7) // 8 + event_count
            if bitmask_bytes < canonical_bytes:
                canonical_representation = REPRESENTATION_SPARSE_BITMASK
                canonical_bytes = bitmask_bytes
            gap_bytes = gap_encoded_bytes + event_count
            if gap_bytes < canonical_bytes:
                canonical_representation = REPRESENTATION_SPARSE_GAPS
                canonical_bytes = gap_bytes
        canonical_gaps = b""
        if canonical_representation == REPRESENTATION_SPARSE_GAPS:
            encoded = bytearray()
            for gap in gap_values:
                _append_uleb128(encoded, int(gap))
            canonical_gaps = bytes(encoded)
        _require(
            representation == canonical_representation
            and auxiliary_count + value_count == canonical_bytes
            and (
                representation != REPRESENTATION_SPARSE_GAPS
                or auxiliary == canonical_gaps
            ),
            "novelty representation is not the canonical byte-smallest choice",
        )
        _require(
            _digest(header, 40) == _sha256(logical_bytes)
            and _digest(header, 72) == _sha256(values),
            "novelty block logical/value SHA-256 mismatch",
        )
        block_record = payload[novelty_position:end]
        _require(
            _digest(header, BLOCK_CONTENT_DIGEST_OFFSET)
            == _hash_zero_range(block_record, BLOCK_CONTENT_DIGEST_OFFSET, 32),
            "novelty block content SHA-256 mismatch",
        )
        return logical_bytes, end, event_count, representation

    def _reconstruct(
        self,
        base_y: bytes,
        base_u: bytes,
        base_v: bytes,
        residual: bytes,
    ) -> tuple[bytes, bytes, bytes]:
        np = self._np
        lanes = np.frombuffer(residual, dtype=np.uint8)
        _require(len(lanes) == self.width * self.height * 3 // 2,
                 "logical residual byte count mismatch")
        y = np.frombuffer(base_y, dtype=np.uint8).copy()
        u = np.frombuffer(base_u, dtype=np.uint8).copy()
        v = np.frombuffer(base_v, dtype=np.uint8).copy()
        y[self._traversal] = y[self._traversal] + lanes[self._lane_start]
        owner_starts = self._lane_start[self._owner_ordinals]
        u[self._chroma_addresses] = (
            u[self._chroma_addresses] + lanes[owner_starts + 1]
        )
        v[self._chroma_addresses] = (
            v[self._chroma_addresses] + lanes[owner_starts + 2]
        )
        return y.tobytes(), u.tobytes(), v.tobytes()

    def iter_frames(self) -> Iterator[Ugyuvs1Frame]:
        """Strictly replay the selected committed prefix, yielding exact frames."""

        y_bytes = self.width * self.height
        c_bytes = y_bytes // 4
        logical_symbols = y_bytes + c_bytes * 2
        zero_y = bytes(y_bytes)
        zero_u = bytes(c_bytes)
        zero_v = bytes(c_bytes)
        zero_y_sha = _sha256(zero_y)
        zero_u_sha = _sha256(zero_u)
        zero_v_sha = _sha256(zero_v)
        previous_y = zero_y
        previous_u = zero_u
        previous_v = zero_v
        previous_y_sha = zero_y_sha
        previous_u_sha = zero_u_sha
        previous_v_sha = zero_v_sha
        previous_pts = INT64_MIN
        chain_sha = ZERO_SHA256
        consumed_bytes = self.record_offset

        with self.path.open("rb") as stream:
            stream.seek(self.record_offset)
            for frame_index in range(self.commit.frame_count):
                _require(
                    consumed_bytes + FRAME_HEADER_BYTES <= self.commit.committed_end,
                    "frame header escapes the committed prefix",
                )
                header = _read_exact(stream, FRAME_HEADER_BYTES, "frame header")
                consumed_bytes += FRAME_HEADER_BYTES
                _require(
                    header[:8] == FRAME_MAGIC
                    and _u16(header, 8) == 1
                    and _u16(header, 10) == 0
                    and _u32(header, 12) == FRAME_HEADER_BYTES,
                    "unsupported frame header",
                )
                flags = _u32(header, 16)
                ordinal = _u32(header, 20)
                previous_ordinal = _u32(header, 24)
                block_count = _u32(header, 28)
                sensor_pts = _i64(header, 32)
                frame_number = _i64(header, 40)
                payload_bytes = _u64(header, 48)
                novelty_bytes = _u64(header, 56)
                metadata_count = _u64(header, 64)
                stored_logical_symbols = _u64(header, 72)
                _require(
                    flags <= FRAME_CHECKPOINT
                    and ordinal == frame_index
                    and sensor_pts >= 0
                    and sensor_pts > previous_pts
                    and payload_bytes == novelty_bytes + metadata_count
                    and stored_logical_symbols == logical_symbols
                    and payload_bytes
                    <= logical_symbols * 2
                    + block_count * BLOCK_HEADER_BYTES
                    + metadata_count,
                    "frame scalar fields are invalid",
                )
                checkpoint = bool(flags & FRAME_CHECKPOINT)
                _require(
                    checkpoint == (ordinal % self.checkpoint_interval == 0)
                    and (
                        previous_ordinal == NO_PREVIOUS_ORDINAL
                        if checkpoint
                        else previous_ordinal == ordinal - 1
                    ),
                    "frame checkpoint/dependency schedule mismatch",
                )
                _require(
                    _digest(header, 240) == chain_sha and not any(header[376:384]),
                    "frame chain/reserved bytes mismatch",
                )
                _require(
                    consumed_bytes + payload_bytes <= self.commit.committed_end,
                    "frame payload escapes the committed prefix",
                )
                payload = _read_exact(stream, payload_bytes, "frame payload")
                consumed_bytes += payload_bytes
                content_sha = _digest(header, FRAME_CONTENT_DIGEST_OFFSET)
                _require(
                    content_sha
                    == _hash_header_payload_zero_range(
                        header,
                        FRAME_CONTENT_DIGEST_OFFSET,
                        32,
                        payload,
                    ),
                    "frame content SHA-256 mismatch",
                )

                base_y = zero_y if checkpoint else previous_y
                base_u = zero_u if checkpoint else previous_u
                base_v = zero_v if checkpoint else previous_v
                state_preimage = bytearray(_STATE_DOMAIN)
                state_preimage.extend(self.static_sha)
                state_preimage.extend(self.recipe_sha)
                state_preimage.extend(
                    struct.pack(
                        "<IIQq",
                        ordinal,
                        previous_ordinal,
                        sensor_pts,
                        frame_number,
                    )
                )
                state_preimage.extend(zero_y_sha if checkpoint else previous_y_sha)
                state_preimage.extend(zero_u_sha if checkpoint else previous_u_sha)
                state_preimage.extend(zero_v_sha if checkpoint else previous_v_sha)
                _require(
                    _digest(header, 272) == _sha256(state_preimage),
                    "executable seed state SHA-256 mismatch",
                )

                expected_blocks = (
                    y_bytes + self.block_luma_addresses - 1
                ) // self.block_luma_addresses
                _require(block_count == expected_blocks,
                         "novelty block count mismatch")
                residual = bytearray()
                novelty_position = 0
                novelty_events = 0
                representation_counts = [0, 0, 0, 0]
                for block_ordinal in range(block_count):
                    logical, novelty_position, events, representation = self._decode_block(
                        payload,
                        novelty_position=novelty_position,
                        novelty_bytes=novelty_bytes,
                        frame_ordinal=ordinal,
                        block_ordinal=block_ordinal,
                        checkpoint=checkpoint,
                    )
                    residual.extend(logical)
                    novelty_events += events
                    representation_counts[representation] += 1
                residual_bytes = bytes(residual)
                _require(
                    novelty_position == novelty_bytes
                    and len(residual_bytes) == logical_symbols
                    and novelty_events == _u64(
                        header, FRAME_NOVELTY_EVENT_COUNT_OFFSET
                    )
                    and _digest(header, 176) == _sha256(residual_bytes),
                    "novelty residual/owner invariant mismatch",
                )
                metadata = payload[novelty_bytes:]
                _require(
                    len(metadata) == metadata_count
                    and _digest(header, 208) == _sha256(metadata),
                    "canonical metadata length/SHA-256 mismatch",
                )
                y, u, v = self._reconstruct(
                    base_y,
                    base_u,
                    base_v,
                    residual_bytes,
                )
                y_sha = _sha256(y)
                u_sha = _sha256(u)
                v_sha = _sha256(v)
                preimage = struct.pack("<QII", sensor_pts, self.width, self.height)
                pre_substrate_sha = _sha256(preimage + y + u + v)
                _require(
                    y_sha == _digest(header, 80)
                    and u_sha == _digest(header, 112)
                    and v_sha == _digest(header, 144)
                    and pre_substrate_sha
                    == _digest(header, FRAME_PRE_SUBSTRATE_DIGEST_OFFSET),
                    "pre-entropy dense plane SHA-256 mismatch",
                )
                yield Ugyuvs1Frame(
                    ordinal=ordinal,
                    width=self.width,
                    height=self.height,
                    sensor_timestamp_ns=sensor_pts,
                    frame_number=frame_number,
                    y=y,
                    u=u,
                    v=v,
                    canonical_metadata=metadata,
                    checkpoint=checkpoint,
                    novelty_event_count=novelty_events,
                    representation_counts=tuple(representation_counts),
                    content_sha256=content_sha.hex(),
                    pre_substrate_sha256=pre_substrate_sha.hex(),
                )
                previous_y = y
                previous_u = u
                previous_v = v
                previous_y_sha = y_sha
                previous_u_sha = u_sha
                previous_v_sha = v_sha
                previous_pts = sensor_pts
                chain_sha = content_sha

            if self.commit.finalized:
                _require(
                    consumed_bytes + TERMINAL_HEADER_BYTES <= self.commit.committed_end,
                    "terminal record escapes the committed prefix",
                )
                terminal = _read_exact(stream, TERMINAL_HEADER_BYTES, "terminal record")
                consumed_bytes += TERMINAL_HEADER_BYTES
                _require(
                    terminal[:8] == TERMINAL_MAGIC
                    and _u16(terminal, 8) == 1
                    and _u16(terminal, 10) == 0
                    and _u32(terminal, 12) == TERMINAL_HEADER_BYTES
                    and _u32(terminal, 16) == 0
                    and _u32(terminal, 20) == 0
                    and _u64(terminal, 24) == self.commit.frame_count
                    and _u64(terminal, 32) + TERMINAL_HEADER_BYTES
                    == self.commit.committed_end
                    and _i64(terminal, 40) == previous_pts
                    and _digest(terminal, 48) == chain_sha
                    and _digest(terminal, 80) == self.static_sha
                    and _digest(terminal, 112) == self.recipe_sha
                    and not any(terminal[176:192]),
                    "terminal record fields are invalid",
                )
                terminal_sha = _digest(terminal, TERMINAL_CONTENT_DIGEST_OFFSET)
                _require(
                    terminal_sha
                    == _hash_zero_range(
                        terminal,
                        TERMINAL_CONTENT_DIGEST_OFFSET,
                        32,
                    )
                    and terminal_sha == self.commit.terminal_sha256,
                    "terminal record SHA-256/commit gate mismatch",
                )
                chain_sha = terminal_sha
            _require(
                consumed_bytes == self.commit.committed_end
                and chain_sha == self.commit.terminal_sha256
                and (
                    self.commit.frame_count == 0
                    or previous_pts == self.commit.last_sensor_timestamp_ns
                ),
                "commit slot does not match replayed record chain",
            )

    def verify(
        self,
        *,
        consume: Callable[[Ugyuvs1Frame], None] | None = None,
    ) -> Ugyuvs1Verification:
        """Replay the full committed prefix and return a hash-only frame ledger."""

        frames: list[dict[str, Any]] = []
        representations = [0, 0, 0, 0]
        total_authoritative_bytes = 0
        total_novelty_events = 0
        ledger = hashlib.sha256()
        ledger.update(_LEDGER_DOMAIN)
        for frame in self.iter_frames():
            receipt = frame.receipt()
            frames.append(receipt)
            total_authoritative_bytes += frame.authoritative_bytes
            total_novelty_events += frame.novelty_event_count
            for index, count in enumerate(frame.representation_counts):
                representations[index] += count
            ledger.update(
                struct.pack(
                    "<IQq",
                    frame.ordinal,
                    frame.sensor_timestamp_ns,
                    frame.frame_number,
                )
            )
            ledger.update(bytes.fromhex(frame.pre_substrate_sha256))
            ledger.update(_sha256(frame.canonical_metadata))
            ledger.update(bytes.fromhex(frame.content_sha256))
            if consume is not None:
                consume(frame)
        return Ugyuvs1Verification(
            inspection=self.inspection,
            file_sha256=_file_sha256(self.path),
            committed_prefix_sha256=_file_sha256(
                self.path,
                limit=self.commit.committed_end,
            ),
            frame_ledger_sha256=ledger.hexdigest(),
            total_authoritative_bytes=total_authoritative_bytes,
            total_novelty_events=total_novelty_events,
            representation_counts=tuple(representations),
            frames=tuple(frames),
        )


def verify_ugsp4c(
    path: str | Path,
    *,
    allow_partial: bool = False,
    consume: Callable[[Ugyuvs1Frame], None] | None = None,
) -> Ugyuvs1Verification:
    """Strictly verify a pulled POCO capture using only the Python reader.

    FINAL is required by default.  ``allow_partial=True`` admits a file whose
    name is not ``.ugsp4c`` and verifies only its newest durable commit prefix;
    any uncommitted crash tail is reported and ignored.
    """

    capture = Ugyuvs1Capture(path, require_final=not allow_partial)
    return capture.verify(consume=consume)


__all__ = [
    "REPRESENTATION_NAMES",
    "Ugyuvs1Capture",
    "Ugyuvs1Commit",
    "Ugyuvs1Error",
    "Ugyuvs1Frame",
    "Ugyuvs1Inspection",
    "Ugyuvs1Verification",
    "verify_ugsp4c",
]
