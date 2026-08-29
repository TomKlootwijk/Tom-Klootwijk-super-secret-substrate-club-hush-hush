"""Crash-detecting append-only storage for reconstructible frontier states.

The journal deliberately keeps the complete FEN and exact repetition-count
context in every record.  SHA-256 is a content address, not a replacement for
that state, and a compact 64-bit index is never authoritative here.

File layout (all integers are big endian)::

    header-prefix  = magic[8], major:u16, minor:u16, profile_length:u32
    header         = header-prefix, profile[profile_length], crc32:u32
    record-prefix  = magic[4], payload_length:u32
    record         = record-prefix, canonical-json payload,
                     content-sha256[32], crc32:u32

The record CRC covers the prefix, payload and stored SHA-256.  The SHA-256 is
over the canonical payload alone and is the stable DAG/content identity.
Readers stop at the first invalid frame.  Strict iteration raises rather than
silently accepting a valid prefix; :func:`verify_frontier` reports the exact
last-good/truncation boundary.  :func:`truncate_corrupt_tail` only removes an
incomplete physical tail after durably preserving the exact suspect suffix in
a content-addressed recovery sidecar.  Integrity failures in complete frames,
or an apparently torn frame followed by any independently valid frame, require
operator restoration rather than truncation.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import threading
from types import MappingProxyType
from typing import Any, BinaryIO, Iterator, Mapping
import zlib

from .game_state import (
    HistoryContext,
    RULE_PROFILE_ID,
    game_state_record,
    validate_history_reachability,
)
from .hashing import canonical_json_bytes, state_sha256
from .position import Position


FRONTIER_FORMAT_MAJOR = 1
FRONTIER_FORMAT_MINOR = 0
FRONTIER_RECORD_SCHEMA = "ugts-chess-frontier-record-1.0"

FILE_MAGIC = b"UGTSFRN1"
RECORD_MAGIC = b"UFR1"
MAX_RULE_PROFILE_BYTES = 4096
MAX_RECORD_PAYLOAD_BYTES = 64 * 1024 * 1024

_HEADER_PREFIX = struct.Struct(">8sHHI")
_RECORD_PREFIX = struct.Struct(">4sI")
_CRC32 = struct.Struct(">I")
_SHA256_BYTES = 32

# Public sizes are useful to a future on-disk index without exposing the
# private Struct instances themselves.
HEADER_PREFIX_SIZE = _HEADER_PREFIX.size
RECORD_PREFIX_SIZE = _RECORD_PREFIX.size
RECORD_SHA256_SIZE = _SHA256_BYTES
RECORD_CRC32_SIZE = _CRC32.size


class FrontierError(Exception):
    """Base class for frontier format and durability errors."""


class FrontierIntegrityError(FrontierError):
    """Raised when strict reading encounters an invalid journal."""

    def __init__(self, report: "FrontierScanResult") -> None:
        self.report = report
        issue = report.issue
        detail = "unknown integrity failure" if issue is None else issue.message
        super().__init__(
            f"frontier integrity failure at byte {report.failure_offset}; "
            f"last good byte {report.last_good_offset}: {detail}"
        )


class FrontierRecoveryError(FrontierError):
    """Raised when a journal cannot safely be truncated to a valid prefix."""


class FrontierWriterLockedError(FrontierError):
    """Raised when another process already owns the journal's writer lock."""


class _SidecarWriterLock:
    """Portable, crash-released exclusive lock on a persistent sidecar byte.

    The inert sidecar is intentionally retained after release.  Deleting a
    lock path creates a race in which a new process can lock the old inode
    while a third process creates and locks a replacement.  Keeping the file
    makes every writer contend on the same object, while the operating system
    releases the actual byte/file lock automatically on process termination.
    """

    def __init__(self, frontier_path: Path) -> None:
        # Resolve relative components and symlinks so ordinary path aliases
        # converge on one sidecar.  Separate hard links remain a documented
        # filesystem-level limitation because they have distinct path names.
        canonical_path = frontier_path.resolve(strict=False)
        self.path = canonical_path.with_name(canonical_path.name + ".writer.lock")
        self._stream: BinaryIO | None = None
        self._locked = False

    def acquire(self) -> None:
        if self._stream is not None:
            raise FrontierError("writer sidecar lock is already open")
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        descriptor = os.open(self.path, flags, 0o600)
        stream = os.fdopen(descriptor, "r+b", buffering=0)
        try:
            if os.fstat(stream.fileno()).st_size < 1:
                stream.seek(0)
                _write_all(stream, b"\0")
                stream.flush()
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise FrontierWriterLockedError(
                f"another writer owns frontier lock {self.path}"
            ) from exc
        except BaseException:
            stream.close()
            raise
        self._stream = stream
        self._locked = True

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        try:
            if self._locked:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        finally:
            self._locked = False
            self._stream = None
            stream.close()


def _is_sha256_hex(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _validate_rule_profile_id(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("rule profile ID must be a non-empty string")
    encoded = value.encode("utf-8")
    if len(encoded) > MAX_RULE_PROFILE_BYTES:
        raise ValueError("rule profile ID is too long")
    if "\x00" in value:
        raise ValueError("rule profile ID may not contain NUL")
    return value


def _freeze_json(value: Any, *, where: str = "metadata") -> Any:
    """Validate and detach a JSON value, returning an immutable equivalent."""

    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{where} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{where} object keys must be strings")
        frozen: dict[str, Any] = {}
        for key in sorted(value):
            frozen[key] = _freeze_json(value[key], where=f"{where}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, where=f"{where}[]") for item in value)
    raise ValueError(f"{where} contains unsupported JSON value {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _canonical_history(history: HistoryContext) -> HistoryContext:
    if not isinstance(history, HistoryContext):
        raise TypeError("history must be a HistoryContext")
    pairs: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in history.counts:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError("history entries must be (repetition_sha256, count) pairs")
        key, count = item
        if not _is_sha256_hex(key):
            raise ValueError("history repetition keys must be lowercase SHA-256 hex")
        if key in seen:
            raise ValueError(f"duplicate history repetition key: {key}")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
            raise ValueError("history repetition counts must be integers in the reachable range 1..5")
        seen.add(key)
        pairs.append((key, count))
    return HistoryContext(tuple(sorted(pairs)))


def _profiled_game_state_sha256(
    position: Position,
    history: HistoryContext,
    rule_profile_id: str,
) -> str:
    record = game_state_record(position, history)
    record["rule_profile"] = rule_profile_id
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


@dataclass(frozen=True, slots=True)
class FrontierRecord:
    """One fully reconstructible state and its incoming DAG-edge metadata.

    ``parent_content_sha256`` references another frontier record by its full
    content address.  ``action`` and ``lineage`` may hold any JSON value (the
    usual action is ``{"kind": "move", "uci": ..., "san": ...}``).  Values
    are detached and frozen at construction so later caller mutation cannot
    change the record's identity.
    """

    position: Position
    history: HistoryContext
    parent_content_sha256: str | None = None
    action: Any = None
    lineage: Any = None
    rule_profile_id: str = RULE_PROFILE_ID

    def __post_init__(self) -> None:
        if not isinstance(self.position, Position):
            raise TypeError("position must be a Position")
        # A stored frontier state must be usable by the exact rule oracle, not
        # merely parseable as a 64-square tuple.  Enforce this for locally
        # authored records as well as during independent decoding below.
        self.position.validate_structure()
        history = _canonical_history(self.history)
        validate_history_reachability(self.position, history)
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "rule_profile_id", _validate_rule_profile_id(self.rule_profile_id))
        if self.parent_content_sha256 is not None and not _is_sha256_hex(self.parent_content_sha256):
            raise ValueError("parent content address must be lowercase SHA-256 hex")
        object.__setattr__(self, "action", _freeze_json(self.action, where="action"))
        object.__setattr__(self, "lineage", _freeze_json(self.lineage, where="lineage"))

    @property
    def fen(self) -> str:
        return self.position.to_fen()

    @property
    def parent(self) -> str | None:
        """Short alias for the content-addressed parent reference."""

        return self.parent_content_sha256

    @property
    def position_sha256(self) -> str:
        return state_sha256(self.position)

    @property
    def game_state_sha256(self) -> str:
        return _profiled_game_state_sha256(self.position, self.history, self.rule_profile_id)

    def payload_record(self) -> dict[str, object]:
        return {
            "schema": FRONTIER_RECORD_SCHEMA,
            "rule_profile_id": self.rule_profile_id,
            "state": {
                "fen": self.fen,
                "position_sha256": self.position_sha256,
                "game_state_sha256": self.game_state_sha256,
                "history_counts": [[key, count] for key, count in self.history.counts],
            },
            "parent_content_sha256": self.parent_content_sha256,
            "action": _thaw_json(self.action),
            "lineage": _thaw_json(self.lineage),
        }

    def payload_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload_record())

    @property
    def content_sha256(self) -> str:
        return hashlib.sha256(self.payload_bytes()).hexdigest()


@dataclass(frozen=True, slots=True)
class FrontierHeader:
    format_major: int
    format_minor: int
    rule_profile_id: str
    header_size: int


@dataclass(frozen=True, slots=True)
class FrontierEntry:
    """A verified record together with stable byte offsets for disk indexes."""

    record_index: int | None
    frame_offset: int
    frame_end_offset: int
    payload_offset: int
    payload_length: int
    sha256_offset: int
    crc32_offset: int
    content_sha256: str
    crc32: int
    record: FrontierRecord

    @property
    def frame_length(self) -> int:
        return self.frame_end_offset - self.frame_offset


@dataclass(frozen=True, slots=True)
class FrontierIssue:
    code: str
    offset: int
    message: str
    recoverable_tail: bool
    expected_bytes: int | None = None
    actual_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class FrontierScanResult:
    path: Path
    file_size: int
    header: FrontierHeader | None
    record_count: int
    last_good_offset: int
    issue: FrontierIssue | None = None

    @property
    def valid(self) -> bool:
        return self.issue is None

    @property
    def complete(self) -> bool:
        return self.valid

    @property
    def failure_offset(self) -> int | None:
        return None if self.issue is None else self.issue.offset

    @property
    def truncation_boundary(self) -> int:
        """Byte offset at which an invalid suffix would be explicitly cut."""

        return self.last_good_offset

    @property
    def invalid_suffix_bytes(self) -> int:
        if self.issue is None:
            return 0
        return max(0, self.file_size - self.last_good_offset)

    def require_valid(self) -> "FrontierScanResult":
        if self.issue is not None:
            raise FrontierIntegrityError(self)
        return self


@dataclass(frozen=True, slots=True)
class FrontierRecoveryResult:
    before: FrontierScanResult
    after: FrontierScanResult
    truncated_bytes: int
    preserved_suffix_path: Path | None = None
    preserved_suffix_sha256: str | None = None


def _crc32(parts: tuple[bytes, ...]) -> int:
    value = 0
    for part in parts:
        value = zlib.crc32(part, value)
    return value & 0xFFFFFFFF


def _encode_header(rule_profile_id: str) -> bytes:
    profile = _validate_rule_profile_id(rule_profile_id).encode("utf-8")
    prefix = _HEADER_PREFIX.pack(
        FILE_MAGIC,
        FRONTIER_FORMAT_MAJOR,
        FRONTIER_FORMAT_MINOR,
        len(profile),
    )
    return prefix + profile + _CRC32.pack(_crc32((prefix, profile)))


def _issue(
    code: str,
    offset: int,
    message: str,
    *,
    recoverable_tail: bool,
    expected_bytes: int | None = None,
    actual_bytes: int | None = None,
) -> FrontierIssue:
    return FrontierIssue(code, offset, message, recoverable_tail, expected_bytes, actual_bytes)


def _read_header(
    stream: BinaryIO,
    file_size: int,
    expected_rule_profile_id: str | None,
) -> tuple[FrontierHeader | None, FrontierIssue | None]:
    stream.seek(0)
    prefix = stream.read(min(HEADER_PREFIX_SIZE, file_size))
    if len(prefix) != HEADER_PREFIX_SIZE:
        return None, _issue(
            "torn_header",
            0,
            f"incomplete frontier header: expected {HEADER_PREFIX_SIZE} prefix bytes, got {len(prefix)}",
            recoverable_tail=False,
            expected_bytes=HEADER_PREFIX_SIZE,
            actual_bytes=len(prefix),
        )
    magic, major, minor, profile_length = _HEADER_PREFIX.unpack(prefix)
    if magic != FILE_MAGIC:
        return None, _issue(
            "file_magic_mismatch",
            0,
            "frontier file magic does not match",
            recoverable_tail=False,
        )
    if profile_length == 0 or profile_length > MAX_RULE_PROFILE_BYTES:
        return None, _issue(
            "rule_profile_length_invalid",
            HEADER_PREFIX_SIZE - 4,
            f"invalid rule-profile byte length {profile_length}",
            recoverable_tail=False,
        )
    remaining_size = profile_length + RECORD_CRC32_SIZE
    remaining = stream.read(min(remaining_size, max(0, file_size - HEADER_PREFIX_SIZE)))
    if len(remaining) != remaining_size:
        return None, _issue(
            "torn_header",
            HEADER_PREFIX_SIZE,
            f"incomplete frontier header: expected {remaining_size} remaining bytes, got {len(remaining)}",
            recoverable_tail=False,
            expected_bytes=remaining_size,
            actual_bytes=len(remaining),
        )
    profile_bytes = remaining[:profile_length]
    stored_crc = _CRC32.unpack(remaining[profile_length:])[0]
    actual_crc = _crc32((prefix, profile_bytes))
    if stored_crc != actual_crc:
        return None, _issue(
            "header_crc32_mismatch",
            HEADER_PREFIX_SIZE + profile_length,
            f"header CRC32 mismatch: stored {stored_crc:08x}, computed {actual_crc:08x}",
            recoverable_tail=False,
        )
    try:
        profile = profile_bytes.decode("utf-8")
        _validate_rule_profile_id(profile)
    except (UnicodeDecodeError, ValueError) as exc:
        return None, _issue(
            "rule_profile_invalid",
            HEADER_PREFIX_SIZE,
            f"invalid rule-profile ID: {exc}",
            recoverable_tail=False,
        )
    header_size = HEADER_PREFIX_SIZE + remaining_size
    header = FrontierHeader(major, minor, profile, header_size)
    if major != FRONTIER_FORMAT_MAJOR or minor > FRONTIER_FORMAT_MINOR:
        return header, _issue(
            "unsupported_format_version",
            8,
            f"unsupported frontier format {major}.{minor}; reader supports "
            f"{FRONTIER_FORMAT_MAJOR}.0..{FRONTIER_FORMAT_MINOR}",
            recoverable_tail=False,
        )
    if expected_rule_profile_id is not None and profile != expected_rule_profile_id:
        return header, _issue(
            "rule_profile_mismatch",
            HEADER_PREFIX_SIZE,
            f"frontier rule profile {profile!r} does not match expected {expected_rule_profile_id!r}",
            recoverable_tail=False,
        )
    return header, None


def _history_from_payload(value: object) -> HistoryContext:
    if not isinstance(value, list):
        raise ValueError("history_counts must be an array")
    pairs: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("history_counts entries must be two-item arrays")
        key, count = item
        if not isinstance(key, str) or isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("history_counts entries must contain a string and integer")
        pairs.append((key, count))
    return _canonical_history(HistoryContext(tuple(pairs)))


def _decode_payload(payload_bytes: bytes, header: FrontierHeader) -> FrontierRecord:
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"payload is not UTF-8 canonical JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("payload root must be an object")
    if canonical_json_bytes(payload) != payload_bytes:
        raise ValueError("payload JSON is not in canonical encoding")
    required = {
        "schema",
        "rule_profile_id",
        "state",
        "parent_content_sha256",
        "action",
        "lineage",
    }
    if set(payload) != required:
        raise ValueError(
            f"payload fields differ from schema; missing={sorted(required - set(payload))}, "
            f"extra={sorted(set(payload) - required)}"
        )
    if payload["schema"] != FRONTIER_RECORD_SCHEMA:
        raise ValueError(f"unsupported record schema {payload['schema']!r}")
    profile = payload["rule_profile_id"]
    if not isinstance(profile, str) or profile != header.rule_profile_id:
        raise ValueError("record rule-profile ID does not match file header")
    state = payload["state"]
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    state_fields = {"fen", "position_sha256", "game_state_sha256", "history_counts"}
    if set(state) != state_fields:
        raise ValueError("state fields differ from frontier record schema")
    fen = state["fen"]
    if not isinstance(fen, str):
        raise ValueError("state FEN must be a string")
    position = Position.from_fen(fen, strict=True)
    if position.to_fen() != fen:
        raise ValueError("state FEN is not canonical")
    history = _history_from_payload(state["history_counts"])
    parent = payload["parent_content_sha256"]
    if parent is not None and not isinstance(parent, str):
        raise ValueError("parent content address must be a string or null")
    record = FrontierRecord(
        position=position,
        history=history,
        parent_content_sha256=parent,
        action=payload["action"],
        lineage=payload["lineage"],
        rule_profile_id=profile,
    )
    if state["position_sha256"] != record.position_sha256:
        raise ValueError("stored position SHA-256 does not match reconstructed FEN")
    if state["game_state_sha256"] != record.game_state_sha256:
        raise ValueError("stored game-state SHA-256 does not match reconstructed exact history")
    if record.payload_bytes() != payload_bytes:
        raise ValueError("payload does not round-trip through the reconstructible record")
    return record


def _encode_frame(record: FrontierRecord) -> tuple[bytes, str, int]:
    payload = record.payload_bytes()
    if len(payload) > MAX_RECORD_PAYLOAD_BYTES:
        raise ValueError(
            f"frontier record payload is {len(payload)} bytes; maximum is {MAX_RECORD_PAYLOAD_BYTES}"
        )
    prefix = _RECORD_PREFIX.pack(RECORD_MAGIC, len(payload))
    digest = hashlib.sha256(payload).digest()
    crc = _crc32((prefix, payload, digest))
    return prefix + payload + digest + _CRC32.pack(crc), digest.hex(), crc


def _read_record(
    stream: BinaryIO,
    *,
    file_size: int,
    header: FrontierHeader,
    record_index: int | None,
    scan_for_valid_suffix: bool = True,
) -> tuple[FrontierEntry | None, FrontierIssue | None]:
    start = stream.tell()
    if start == file_size:
        return None, None
    if start > file_size:
        return None, _issue(
            "record_offset_past_eof",
            start,
            "record offset is past the snapshotted end of file",
            recoverable_tail=False,
        )
    prefix_available = min(RECORD_PREFIX_SIZE, file_size - start)
    prefix = stream.read(prefix_available)
    if len(prefix) != RECORD_PREFIX_SIZE:
        return None, _issue(
            "torn_record_prefix",
            start,
            f"incomplete record prefix: expected {RECORD_PREFIX_SIZE} bytes, got {len(prefix)}",
            recoverable_tail=True,
            expected_bytes=RECORD_PREFIX_SIZE,
            actual_bytes=len(prefix),
        )
    magic, payload_length = _RECORD_PREFIX.unpack(prefix)
    if magic != RECORD_MAGIC:
        return None, _issue(
            "record_magic_mismatch",
            start,
            "record magic does not match at the sequential boundary",
            recoverable_tail=False,
        )
    if payload_length > MAX_RECORD_PAYLOAD_BYTES:
        return None, _issue(
            "record_length_invalid",
            start + 4,
            f"record payload length {payload_length} exceeds maximum {MAX_RECORD_PAYLOAD_BYTES}",
            recoverable_tail=False,
        )
    body_size = payload_length + RECORD_SHA256_SIZE + RECORD_CRC32_SIZE
    available = max(0, file_size - stream.tell())
    body = stream.read(min(body_size, available))
    if len(body) != body_size:
        valid_suffix = scan_for_valid_suffix and _has_valid_record_after(
            stream,
            record_start=start,
            file_size=file_size,
            header=header,
        )
        suffix_detail = (
            "; a later independently valid frame makes truncation unsafe"
            if valid_suffix
            else ""
        )
        return None, _issue(
            "torn_record_body",
            start,
            f"incomplete record body: expected {body_size} bytes, got {len(body)}"
            f"{suffix_detail}",
            recoverable_tail=not valid_suffix,
            expected_bytes=body_size,
            actual_bytes=len(body),
        )
    payload = body[:payload_length]
    digest = body[payload_length : payload_length + RECORD_SHA256_SIZE]
    stored_crc = _CRC32.unpack(body[-RECORD_CRC32_SIZE:])[0]
    actual_crc = _crc32((prefix, payload, digest))
    if stored_crc != actual_crc:
        return None, _issue(
            "record_crc32_mismatch",
            start,
            f"record CRC32 mismatch: stored {stored_crc:08x}, computed {actual_crc:08x}",
            recoverable_tail=False,
        )
    actual_digest = hashlib.sha256(payload).digest()
    if digest != actual_digest:
        return None, _issue(
            "record_sha256_mismatch",
            start,
            f"record content SHA-256 mismatch: stored {digest.hex()}, computed {actual_digest.hex()}",
            recoverable_tail=False,
        )
    try:
        record = _decode_payload(payload, header)
    except (TypeError, ValueError) as exc:
        return None, _issue(
            "record_payload_invalid",
            start + RECORD_PREFIX_SIZE,
            f"record payload failed reconstruction: {exc}",
            recoverable_tail=False,
        )
    end = start + RECORD_PREFIX_SIZE + body_size
    return (
        FrontierEntry(
            record_index=record_index,
            frame_offset=start,
            frame_end_offset=end,
            payload_offset=start + RECORD_PREFIX_SIZE,
            payload_length=payload_length,
            sha256_offset=start + RECORD_PREFIX_SIZE + payload_length,
            crc32_offset=end - RECORD_CRC32_SIZE,
            content_sha256=digest.hex(),
            crc32=stored_crc,
            record=record,
        ),
        None,
    )


def _has_valid_record_after(
    stream: BinaryIO,
    *,
    record_start: int,
    file_size: int,
    header: FrontierHeader,
) -> bool:
    """Conservatively detect a durable valid frame after an apparent tear.

    A corrupted payload length in a middle record can make the rest of a
    journal look like one incomplete body.  Before authorizing truncation,
    scan for any later frame that independently passes magic, bounds, CRC,
    SHA-256, canonical JSON, and state reconstruction.  A false positive only
    refuses automatic recovery; it never destroys bytes.
    """

    original_offset = stream.tell()
    scan_offset = record_start + 1
    carry = b""
    chunk_size = 1024 * 1024
    try:
        while scan_offset < file_size:
            stream.seek(scan_offset)
            chunk = stream.read(min(chunk_size, file_size - scan_offset))
            if not chunk:
                return False
            window = carry + chunk
            window_offset = scan_offset - len(carry)
            search_from = 0
            while True:
                marker_index = window.find(RECORD_MAGIC, search_from)
                if marker_index < 0:
                    break
                candidate_offset = window_offset + marker_index
                if candidate_offset > record_start:
                    stream.seek(candidate_offset)
                    entry, _ = _read_record(
                        stream,
                        file_size=file_size,
                        header=header,
                        record_index=None,
                        scan_for_valid_suffix=False,
                    )
                    if entry is not None:
                        return True
                search_from = marker_index + 1
            carry = window[-(len(RECORD_MAGIC) - 1) :]
            scan_offset += len(chunk)
        return False
    finally:
        stream.seek(original_offset)


def _changed_file_issue(file_size: int) -> FrontierIssue:
    return _issue(
        "file_changed_during_read",
        file_size,
        "frontier file size changed during the sequential read",
        recoverable_tail=False,
    )


class FrontierReader:
    """Sequential and random-access verified reader for one frontier journal."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        expected_rule_profile_id: str | None = RULE_PROFILE_ID,
    ) -> None:
        self.path = Path(path)
        self.expected_rule_profile_id = (
            None
            if expected_rule_profile_id is None
            else _validate_rule_profile_id(expected_rule_profile_id)
        )

    def verify(self) -> FrontierScanResult:
        return verify_frontier(
            self.path,
            expected_rule_profile_id=self.expected_rule_profile_id,
        )

    @property
    def header(self) -> FrontierHeader:
        with self.path.open("rb") as stream:
            file_size = os.fstat(stream.fileno()).st_size
            header, issue = _read_header(stream, file_size, self.expected_rule_profile_id)
        if issue is not None or header is None:
            raise FrontierIntegrityError(
                FrontierScanResult(self.path, file_size, header, 0, 0, issue)
            )
        return header

    def iter_entries(self) -> Iterator[FrontierEntry]:
        """Yield verified entries, then raise if any suffix is invalid."""

        with self.path.open("rb") as stream:
            file_size = os.fstat(stream.fileno()).st_size
            header, issue = _read_header(stream, file_size, self.expected_rule_profile_id)
            if issue is not None or header is None:
                raise FrontierIntegrityError(
                    FrontierScanResult(self.path, file_size, header, 0, 0, issue)
                )
            count = 0
            last_good = header.header_size
            stream.seek(last_good)
            while stream.tell() < file_size:
                entry, issue = _read_record(
                    stream,
                    file_size=file_size,
                    header=header,
                    record_index=count,
                )
                if issue is not None:
                    raise FrontierIntegrityError(
                        FrontierScanResult(
                            self.path,
                            file_size,
                            header,
                            count,
                            last_good,
                            issue,
                        )
                    )
                if entry is None:
                    break
                count += 1
                last_good = entry.frame_end_offset
                yield entry
            if os.fstat(stream.fileno()).st_size != file_size:
                raise FrontierIntegrityError(
                    FrontierScanResult(
                        self.path,
                        file_size,
                        header,
                        count,
                        last_good,
                        _changed_file_issue(file_size),
                    )
                )

    def iter_records(self) -> Iterator[FrontierRecord]:
        for entry in self.iter_entries():
            yield entry.record

    def __iter__(self) -> Iterator[FrontierRecord]:
        return self.iter_records()

    def read_entry_at(
        self,
        frame_offset: int,
        *,
        expected_content_sha256: str | None = None,
    ) -> FrontierEntry:
        """Verify and read one frame located by an external disk-backed index."""

        if isinstance(frame_offset, bool) or not isinstance(frame_offset, int) or frame_offset < 0:
            raise ValueError("frame offset must be a non-negative integer")
        if expected_content_sha256 is not None and not _is_sha256_hex(expected_content_sha256):
            raise ValueError("expected content address must be lowercase SHA-256 hex")
        with self.path.open("rb") as stream:
            file_size = os.fstat(stream.fileno()).st_size
            header, issue = _read_header(stream, file_size, self.expected_rule_profile_id)
            if issue is not None or header is None:
                raise FrontierIntegrityError(
                    FrontierScanResult(self.path, file_size, header, 0, 0, issue)
                )
            if frame_offset < header.header_size:
                raise ValueError("frame offset points inside the frontier header")
            stream.seek(frame_offset)
            entry, issue = _read_record(
                stream,
                file_size=file_size,
                header=header,
                record_index=None,
            )
            if issue is not None or entry is None:
                issue = issue or _issue(
                    "record_missing",
                    frame_offset,
                    "no record begins at the requested offset",
                    recoverable_tail=False,
                )
                raise FrontierIntegrityError(
                    FrontierScanResult(
                        self.path,
                        file_size,
                        header,
                        0,
                        frame_offset,
                        issue,
                    )
                )
            if (
                expected_content_sha256 is not None
                and entry.content_sha256 != expected_content_sha256
            ):
                address_issue = _issue(
                    "content_address_mismatch",
                    frame_offset,
                    f"indexed content address {expected_content_sha256} points to "
                    f"{entry.content_sha256}",
                    recoverable_tail=False,
                )
                raise FrontierIntegrityError(
                    FrontierScanResult(
                        self.path,
                        file_size,
                        header,
                        0,
                        frame_offset,
                        address_issue,
                    )
                )
            return entry

    def find_entry(self, content_sha256: str) -> FrontierEntry | None:
        """Linear verified lookup; external indexes should use ``read_entry_at``."""

        if not _is_sha256_hex(content_sha256):
            raise ValueError("content address must be lowercase SHA-256 hex")
        for entry in self.iter_entries():
            if entry.content_sha256 == content_sha256:
                return entry
        return None


def verify_frontier(
    path: str | os.PathLike[str],
    *,
    expected_rule_profile_id: str | None = RULE_PROFILE_ID,
) -> FrontierScanResult:
    """Sequentially verify the entire journal without retaining its records."""

    frontier_path = Path(path)
    expected = (
        None
        if expected_rule_profile_id is None
        else _validate_rule_profile_id(expected_rule_profile_id)
    )
    with frontier_path.open("rb") as stream:
        file_size = os.fstat(stream.fileno()).st_size
        header, issue = _read_header(stream, file_size, expected)
        if issue is not None or header is None:
            return FrontierScanResult(frontier_path, file_size, header, 0, 0, issue)
        count = 0
        last_good = header.header_size
        stream.seek(last_good)
        while stream.tell() < file_size:
            entry, issue = _read_record(
                stream,
                file_size=file_size,
                header=header,
                record_index=count,
            )
            if issue is not None:
                return FrontierScanResult(
                    frontier_path,
                    file_size,
                    header,
                    count,
                    last_good,
                    issue,
                )
            if entry is None:
                break
            count += 1
            last_good = entry.frame_end_offset
        if os.fstat(stream.fileno()).st_size != file_size:
            return FrontierScanResult(
                frontier_path,
                file_size,
                header,
                count,
                last_good,
                _changed_file_issue(file_size),
            )
        return FrontierScanResult(frontier_path, file_size, header, count, last_good)


def _write_all(stream: BinaryIO, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = stream.write(view)
        if written is None or written <= 0:
            raise OSError("short write while appending frontier frame")
        view = view[written:]


def _fsync_parent_directory(path: Path) -> None:
    """Persist a newly created journal's directory entry where supported.

    POSIX requires a directory fsync in addition to the new file's fsync for
    crash-durable creation.  Python/Windows does not expose a portable
    directory handle that ``os.fsync`` accepts; ``os.fsync`` on the created
    file still maps to ``FlushFileBuffers`` there.
    """

    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path.parent, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_exact_region(stream: BinaryIO, offset: int, length: int) -> str:
    """Hash exactly one file region or fail without accepting a short read."""

    original_offset = stream.tell()
    digest = hashlib.sha256()
    remaining = length
    try:
        stream.seek(offset)
        while remaining:
            block = stream.read(min(1024 * 1024, remaining))
            if not block:
                raise FrontierRecoveryError("frontier changed while preserving its corrupt suffix")
            digest.update(block)
            remaining -= len(block)
    finally:
        stream.seek(original_offset)
    return digest.hexdigest()


def _preserve_invalid_suffix(
    frontier_path: Path,
    frontier_stream: BinaryIO,
    *,
    start_offset: int,
    file_size: int,
) -> tuple[Path, str]:
    """Durably copy the exact suspect suffix before destructive truncation."""

    suffix_length = file_size - start_offset
    if suffix_length <= 0:
        raise FrontierRecoveryError("recovery suffix is empty")
    suffix_sha256 = _sha256_exact_region(frontier_stream, start_offset, suffix_length)
    recovery_path = frontier_path.with_name(
        f"{frontier_path.name}.recovery-{start_offset:016x}-{suffix_sha256}.bin"
    )

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    created = False
    try:
        try:
            descriptor = os.open(recovery_path, flags, 0o600)
        except FileExistsError:
            descriptor = None
        else:
            created = True
            copied_digest = hashlib.sha256()
            remaining = suffix_length
            frontier_stream.seek(start_offset)
            with os.fdopen(descriptor, "wb", buffering=0) as recovery_stream:
                while remaining:
                    block = frontier_stream.read(min(1024 * 1024, remaining))
                    if not block:
                        raise FrontierRecoveryError(
                            "frontier changed while copying its corrupt suffix"
                        )
                    _write_all(recovery_stream, block)
                    copied_digest.update(block)
                    remaining -= len(block)
                recovery_stream.flush()
                os.fsync(recovery_stream.fileno())
            if copied_digest.hexdigest() != suffix_sha256:
                raise FrontierRecoveryError("recovery suffix changed while it was copied")

        try:
            with recovery_path.open("r+b", buffering=0) as recovery_stream:
                if os.fstat(recovery_stream.fileno()).st_size != suffix_length:
                    raise FrontierRecoveryError("existing recovery sidecar has the wrong size")
                recovery_sha256 = _sha256_exact_region(recovery_stream, 0, suffix_length)
                if recovery_sha256 != suffix_sha256:
                    raise FrontierRecoveryError("existing recovery sidecar has the wrong SHA-256")
                os.fsync(recovery_stream.fileno())
        except OSError as exc:
            raise FrontierRecoveryError(f"recovery sidecar verification failed: {exc}") from exc
        _fsync_parent_directory(recovery_path)

        if os.fstat(frontier_stream.fileno()).st_size != file_size:
            raise FrontierRecoveryError("frontier changed while its corrupt suffix was preserved")
        if _sha256_exact_region(frontier_stream, start_offset, suffix_length) != suffix_sha256:
            raise FrontierRecoveryError("frontier suffix changed after preservation")
        return recovery_path, suffix_sha256
    except BaseException:
        if created:
            try:
                recovery_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


class FrontierWriter:
    """Exclusively locked append handle with verification before every reopen.

    New files receive a durable header.  Existing files are scanned in full
    before append; a corrupt or torn suffix must be explicitly recovered first.
    ``append`` fsyncs by default and can be batched by passing ``fsync=False``
    followed by :meth:`sync`.  A sidecar OS lock is held for the writer's
    lifetime, so another process cannot append or return stale byte offsets.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        rule_profile_id: str = RULE_PROFILE_ID,
        fsync_on_append: bool = True,
    ) -> None:
        self.path = Path(path)
        self.rule_profile_id = _validate_rule_profile_id(rule_profile_id)
        self.fsync_on_append = bool(fsync_on_append)
        self._lock = threading.Lock()
        self._stream: BinaryIO | None = None
        self._failed = False
        self._writer_lock = _SidecarWriterLock(self.path)
        self.lock_path = self._writer_lock.path
        self._writer_lock.acquire()
        try:
            header_bytes = _encode_header(self.rule_profile_id)
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_BINARY"):
                    flags |= os.O_BINARY
                descriptor = os.open(self.path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb", buffering=0) as created:
                    _write_all(created, header_bytes)
                    created.flush()
                    os.fsync(created.fileno())
                _fsync_parent_directory(self.path)

            report = verify_frontier(
                self.path,
                expected_rule_profile_id=self.rule_profile_id,
            )
            report.require_valid()
            self.header = report.header
            assert self.header is not None
            self._next_index = report.record_count
            self._next_offset = report.file_size
            self._stream = self.path.open("ab", buffering=0)
            if os.fstat(self._stream.fileno()).st_size != report.file_size:
                raise FrontierError("frontier changed between verification and append open")
        except BaseException:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._writer_lock.release()
            raise

    @property
    def closed(self) -> bool:
        return self._stream is None or self._stream.closed

    def append(
        self,
        record: FrontierRecord,
        *,
        fsync: bool | None = None,
    ) -> FrontierEntry:
        if not isinstance(record, FrontierRecord):
            raise TypeError("append expects a FrontierRecord")
        if record.rule_profile_id != self.rule_profile_id:
            raise ValueError(
                f"record rule profile {record.rule_profile_id!r} does not match "
                f"journal profile {self.rule_profile_id!r}"
            )
        frame, content_sha256, crc = _encode_frame(record)
        should_sync = self.fsync_on_append if fsync is None else bool(fsync)
        with self._lock:
            if self.closed:
                raise FrontierError("frontier writer is closed")
            if self._failed:
                raise FrontierError("frontier writer is unusable after a failed append")
            assert self._stream is not None
            current_size = os.fstat(self._stream.fileno()).st_size
            if current_size != self._next_offset:
                self._failed = True
                raise FrontierError("frontier changed outside this writer")
            frame_offset = self._next_offset
            try:
                _write_all(self._stream, frame)
                self._stream.flush()
                if should_sync:
                    os.fsync(self._stream.fileno())
            except BaseException:
                self._failed = True
                raise
            frame_end = frame_offset + len(frame)
            entry = FrontierEntry(
                record_index=self._next_index,
                frame_offset=frame_offset,
                frame_end_offset=frame_end,
                payload_offset=frame_offset + RECORD_PREFIX_SIZE,
                payload_length=len(record.payload_bytes()),
                sha256_offset=frame_end - RECORD_CRC32_SIZE - RECORD_SHA256_SIZE,
                crc32_offset=frame_end - RECORD_CRC32_SIZE,
                content_sha256=content_sha256,
                crc32=crc,
                record=record,
            )
            self._next_index += 1
            self._next_offset = frame_end
            return entry

    def sync(self) -> None:
        with self._lock:
            if self.closed:
                raise FrontierError("frontier writer is closed")
            if self._failed:
                raise FrontierError("frontier writer is unusable after a failed append")
            assert self._stream is not None
            self._stream.flush()
            os.fsync(self._stream.fileno())

    def close(self) -> None:
        with self._lock:
            try:
                if self._stream is not None and not self._stream.closed:
                    self._stream.close()
            finally:
                self._writer_lock.release()

    def __enter__(self) -> "FrontierWriter":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def truncate_corrupt_tail(
    path: str | os.PathLike[str],
    *,
    expected_rule_profile_id: str | None = RULE_PROFILE_ID,
    fsync: bool = True,
) -> FrontierRecoveryResult:
    """Explicitly preserve, then remove, an incomplete physical record tail.

    Header/version/profile failures and complete-frame integrity failures are
    never truncated.  An apparent torn body is also refused if any later frame
    independently validates, preventing mid-journal bitrot from erasing a
    durable authoritative suffix.  Because the v1 format cannot distinguish a
    torn final write from upward corruption of its length field, every removed
    suffix is first fsynced to a content-addressed recovery sidecar.
    """

    frontier_path = Path(path)
    writer_lock = _SidecarWriterLock(frontier_path)
    writer_lock.acquire()
    try:
        before = verify_frontier(
            frontier_path,
            expected_rule_profile_id=expected_rule_profile_id,
        )
        if before.valid:
            return FrontierRecoveryResult(before, before, 0)
        assert before.issue is not None
        if before.header is None or not before.issue.recoverable_tail:
            raise FrontierRecoveryError(
                f"cannot truncate frontier for {before.issue.code}: {before.issue.message}"
            )
        with frontier_path.open("r+b", buffering=0) as stream:
            current_size = os.fstat(stream.fileno()).st_size
            if current_size != before.file_size:
                raise FrontierRecoveryError("frontier changed after recovery scan")
            try:
                recovery_path, recovery_sha256 = _preserve_invalid_suffix(
                    frontier_path,
                    stream,
                    start_offset=before.last_good_offset,
                    file_size=before.file_size,
                )
            except FrontierRecoveryError:
                raise
            except OSError as exc:
                raise FrontierRecoveryError(f"cannot preserve corrupt suffix: {exc}") from exc
            stream.truncate(before.last_good_offset)
            stream.flush()
            if fsync:
                os.fsync(stream.fileno())
        after = verify_frontier(
            frontier_path,
            expected_rule_profile_id=expected_rule_profile_id,
        )
        after.require_valid()
        return FrontierRecoveryResult(
            before,
            after,
            before.file_size - before.last_good_offset,
            recovery_path,
            recovery_sha256,
        )
    finally:
        writer_lock.release()


# An integration-friendly verb for callers that treat explicit truncation as
# journal recovery.  It has exactly the same non-silent semantics.
recover_frontier = truncate_corrupt_tail


def read_frontier(
    path: str | os.PathLike[str],
    *,
    expected_rule_profile_id: str | None = RULE_PROFILE_ID,
) -> tuple[FrontierRecord, ...]:
    """Strict convenience reader for small journals and tests."""

    return tuple(
        FrontierReader(
            path,
            expected_rule_profile_id=expected_rule_profile_id,
        ).iter_records()
    )


__all__ = [
    "FILE_MAGIC",
    "FRONTIER_FORMAT_MAJOR",
    "FRONTIER_FORMAT_MINOR",
    "FRONTIER_RECORD_SCHEMA",
    "HEADER_PREFIX_SIZE",
    "MAX_RECORD_PAYLOAD_BYTES",
    "RECORD_CRC32_SIZE",
    "RECORD_MAGIC",
    "RECORD_PREFIX_SIZE",
    "RECORD_SHA256_SIZE",
    "FrontierEntry",
    "FrontierError",
    "FrontierHeader",
    "FrontierIntegrityError",
    "FrontierIssue",
    "FrontierReader",
    "FrontierRecord",
    "FrontierRecoveryError",
    "FrontierRecoveryResult",
    "FrontierScanResult",
    "FrontierWriter",
    "FrontierWriterLockedError",
    "read_frontier",
    "recover_frontier",
    "truncate_corrupt_tail",
    "verify_frontier",
]
