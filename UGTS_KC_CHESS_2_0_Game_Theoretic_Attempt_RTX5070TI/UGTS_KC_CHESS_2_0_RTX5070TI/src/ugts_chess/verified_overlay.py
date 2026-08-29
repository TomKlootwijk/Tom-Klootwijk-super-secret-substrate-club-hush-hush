"""Append-only verified-certificate facts layered over an immutable ProofDAG.

The base :class:`~ugts_chess.proof_dag.ProofDAG` deliberately stores every
node as ``UNKNOWN``.  This module is the only promotion layer: it embeds the
exact canonical WDL-certificate bytes in a checksummed, hash-chained journal
and exposes a non-UNKNOWN value only after replaying the journal and running
the independent WDL verifier again.

File layout (all integers are big endian)::

    header-prefix = magic[8], major:u16, minor:u16, profile_length:u32
    header        = header-prefix, rule-profile[profile_length], crc32:u32
    frame-prefix  = magic[4], payload_length:u64
    frame         = frame-prefix, canonical-json payload,
                    payload-sha256[32], crc32:u32

The payload embeds base64 of the *canonical bare certificate bundle bytes*.
Its SHA-256, size, verifier result, exact full FEN, complete history, semantic
game-state identity, DAG node content address, and the first authoritative
frontier occurrence are all bound conjunctively.  A compact key, SQLite row,
GPU result, or mutable caller object is never accepted as proof authority.

Opening an existing journal takes an OS writer lock, scans every byte, checks
the record hash chain, reconstructs every referenced DAG node/frontier entry,
and re-runs :func:`ugts_chess.wdl.verify_wdl_certificate`.  A torn physical
tail is rejected until :func:`recover_verified_overlay` first preserves the
exact suffix in a durable content-addressed sidecar and then truncates it.
Complete-frame corruption is never truncated.

Threat boundary: the hash chain detects edits to retained records but, like an
ordinary append-only log without an external witness, cannot detect a clean
rollback that removes a whole valid suffix together with every reference to
it.  Deployment that needs rollback resistance must retain the latest
``(record_count, content_sha256)`` head outside this journal.  The inherited
sidecar lock canonicalizes symlink/relative aliases but separate hard links to
the journal can still create distinct lock paths; do not expose hard-link
aliases to cooperating writers.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import struct
import threading
from types import MappingProxyType
from typing import BinaryIO, Iterator, Mapping
import zlib

from .frontier import (
    FrontierRecoveryError,
    FrontierWriterLockedError,
    _SidecarWriterLock,
    _fsync_parent_directory,
    _preserve_invalid_suffix,
    _write_all,
)
from .game_state import RULE_PROFILE_ID
from .game_theory import WDL
from .hashing import canonical_json_bytes
from .proof_dag import DAGNode, ProofDAG, ProofDAGError
from .wdl import BUNDLE_SCHEMA, NODE_SCHEMA, verify_wdl_certificate


OVERLAY_FORMAT_MAJOR = 1
OVERLAY_FORMAT_MINOR = 0
OVERLAY_RECORD_SCHEMA = "ugts-chess-verified-certificate-binding-1.0"
OVERLAY_RECORD_COMMITMENT_SCHEMA = (
    "ugts-chess-verified-overlay-record-commitment-1.0"
)
OVERLAY_HEAD_COMMITMENT_SCHEMA = "ugts-chess-verified-overlay-head-commitment-1.0"
CERTIFICATE_ENCODING = "canonical-json-utf8"
CERTIFICATE_VERIFIER_PROFILE = (
    "ugts-chess-wdl-verifier-2.0+overlay-exact-root-1.0"
)

FILE_MAGIC = b"UGTSVCO1"
RECORD_MAGIC = b"UVC1"
MAX_RULE_PROFILE_BYTES = 4096
# The current verifier materializes one JSON bundle in memory.  Keep the disk
# parser bounded consistently; future sharded proof formats need a new schema.
MAX_CERTIFICATE_BYTES = 512 * 1024 * 1024
MAX_RECORD_PAYLOAD_BYTES = 768 * 1024 * 1024

_HEADER_PREFIX = struct.Struct(">8sHHI")
_RECORD_PREFIX = struct.Struct(">4sQ")
_CRC32 = struct.Struct(">I")
_SHA256_SIZE = 32

HEADER_PREFIX_SIZE = _HEADER_PREFIX.size
RECORD_PREFIX_SIZE = _RECORD_PREFIX.size
RECORD_SHA256_SIZE = _SHA256_SIZE
RECORD_CRC32_SIZE = _CRC32.size

_BUNDLE_KEYS = frozenset(
    {
        "schema",
        "rules_profile",
        "root_certificate_hash",
        "root_state_hash",
        "root_value",
        "root_exact",
        "max_plies",
        "nodes",
    }
)
_NODE_KEYS = frozenset(
    {
        "schema",
        "state_hash",
        "fen",
        "history_counts",
        "depth_remaining",
        "value",
        "terminal_code",
        "current_claim_actions",
        "legal_move_count",
        "coverage",
        "children",
        "exact",
        "certificate_hash",
    }
)
_CHILD_KEYS = frozenset(
    {
        "action_id",
        "kind",
        "move",
        "san",
        "claim_code",
        "child_state_hash",
        "child_value",
        "value_for_parent",
        "child_certificate_hash",
        "exact",
    }
)
_RECORD_KEYS = frozenset(
    {
        "schema",
        "record_index",
        "previous_record_sha256",
        "node_sha256",
        "frontier_content_sha256",
        "rule_profile_id",
        "fen",
        "history_counts",
        "position_sha256",
        "game_state_sha256",
        "claimed_wdl",
        "certificate_encoding",
        "certificate_size",
        "certificate_sha256",
        "certificate_base64",
        "root_certificate_hash",
        "verifier_profile",
        "verifier_result",
    }
)
_RECORD_COMMITMENT_KEYS = frozenset(
    {
        "schema",
        "format_major",
        "format_minor",
        "rule_profile_id",
        "record_index",
        "record_content_sha256",
        "previous_record_sha256",
        "node_sha256",
        "frontier_content_sha256",
        "position_sha256",
        "game_state_sha256",
        "claimed_wdl",
        "certificate_sha256",
        "root_certificate_hash",
    }
)
_HEAD_COMMITMENT_KEYS = frozenset(
    {
        "schema",
        "format_major",
        "format_minor",
        "rule_profile_id",
        "header_sha256",
        "record_count",
        "head_record_sha256",
        "journal_size_bytes",
    }
)


class VerifiedOverlayError(Exception):
    """Base class for verified-certificate overlay failures."""


class VerifiedOverlayIntegrityError(VerifiedOverlayError):
    """Raised when a journal fails structural or semantic replay."""

    def __init__(self, report: "OverlayScanResult") -> None:
        self.report = report
        issue = report.issue
        detail = "unknown integrity failure" if issue is None else issue.message
        super().__init__(
            f"verified overlay integrity failure at byte {report.failure_offset}; "
            f"last good byte {report.last_good_offset}: {detail}"
        )


class VerifiedOverlayRecoveryError(VerifiedOverlayError):
    """Raised when an overlay cannot be safely recovered."""


class VerifiedOverlayWriterLockedError(VerifiedOverlayError):
    """Raised when another process owns the overlay writer lock."""


class VerifiedOverlayConflictError(VerifiedOverlayError):
    """Raised when a node is offered a second, non-identical certificate."""


class VerifiedOverlayCommitError(VerifiedOverlayError):
    """Raised when a durable append could not be read back and audited."""


class VerifiedOverlayHeadMismatchError(VerifiedOverlayError):
    """Raised when a required external/prefix head is absent from a snapshot."""


class VerifiedOverlayReferenceError(VerifiedOverlayError):
    """Raised when a compact reference does not resolve to its exact record."""


@dataclass(frozen=True, slots=True)
class VerifiedCertificateBinding:
    """One exact, independently checked node-value fact."""

    record_index: int
    previous_record_sha256: str | None
    node_sha256: str
    frontier_content_sha256: str
    rule_profile_id: str
    fen: str
    history_counts: tuple[tuple[str, int], ...]
    position_sha256: str
    game_state_sha256: str
    claimed_wdl: WDL
    certificate_size: int
    certificate_sha256: str
    certificate_bytes: bytes
    root_certificate_hash: str
    verifier_profile: str
    verifier_result: Mapping[str, object]

    def payload_record(self) -> dict[str, object]:
        return {
            "schema": OVERLAY_RECORD_SCHEMA,
            "record_index": self.record_index,
            "previous_record_sha256": self.previous_record_sha256,
            "node_sha256": self.node_sha256,
            "frontier_content_sha256": self.frontier_content_sha256,
            "rule_profile_id": self.rule_profile_id,
            "fen": self.fen,
            "history_counts": [[key, count] for key, count in self.history_counts],
            "position_sha256": self.position_sha256,
            "game_state_sha256": self.game_state_sha256,
            "claimed_wdl": self.claimed_wdl.value,
            "certificate_encoding": CERTIFICATE_ENCODING,
            "certificate_size": self.certificate_size,
            "certificate_sha256": self.certificate_sha256,
            "certificate_base64": base64.b64encode(self.certificate_bytes).decode("ascii"),
            "root_certificate_hash": self.root_certificate_hash,
            "verifier_profile": self.verifier_profile,
            "verifier_result": dict(self.verifier_result),
        }

    def payload_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload_record())


@dataclass(frozen=True, slots=True)
class OverlayEntry:
    record_index: int
    frame_offset: int
    frame_end_offset: int
    payload_offset: int
    payload_length: int
    sha256_offset: int
    crc32_offset: int
    content_sha256: str
    crc32: int
    binding: VerifiedCertificateBinding


@dataclass(frozen=True, slots=True)
class OverlayHeader:
    format_major: int
    format_minor: int
    rule_profile_id: str
    header_size: int


@dataclass(frozen=True, slots=True)
class OverlayIssue:
    code: str
    offset: int
    message: str
    recoverable_tail: bool
    expected_bytes: int | None = None
    actual_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class OverlayScanResult:
    path: Path
    file_size: int
    header: OverlayHeader | None
    record_count: int
    last_good_offset: int
    entries: tuple[OverlayEntry, ...] = ()
    issue: OverlayIssue | None = None

    @property
    def valid(self) -> bool:
        return self.issue is None

    @property
    def failure_offset(self) -> int | None:
        return None if self.issue is None else self.issue.offset

    def require_valid(self) -> "OverlayScanResult":
        if self.issue is not None:
            raise VerifiedOverlayIntegrityError(self)
        return self


@dataclass(frozen=True, slots=True)
class OverlayRecoveryResult:
    before: OverlayScanResult
    after: OverlayScanResult
    truncated_bytes: int
    preserved_suffix_path: Path | None = None
    preserved_suffix_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class OverlayAppendResult:
    entry: OverlayEntry
    appended: bool


@dataclass(frozen=True, slots=True)
class OverlayRecordCommitment:
    """Stable logical address and semantic summary of one audited v1 record.

    Frame offsets and CRC values are intentionally absent: they are transport
    details.  ``(record_index, record_content_sha256)`` is the authoritative
    record address, while the remaining fields make substitution mistakes
    explicit before a caller consumes the resolved full binding.
    """

    format_major: int
    format_minor: int
    rule_profile_id: str
    record_index: int
    record_content_sha256: str
    previous_record_sha256: str | None
    node_sha256: str
    frontier_content_sha256: str
    position_sha256: str
    game_state_sha256: str
    claimed_wdl: WDL
    certificate_sha256: str
    root_certificate_hash: str

    def __post_init__(self) -> None:
        if (
            isinstance(self.format_major, bool)
            or not isinstance(self.format_major, int)
            or self.format_major != OVERLAY_FORMAT_MAJOR
            or isinstance(self.format_minor, bool)
            or not isinstance(self.format_minor, int)
            or self.format_minor != OVERLAY_FORMAT_MINOR
        ):
            raise ValueError("record commitment has an unsupported overlay format")
        if self.rule_profile_id != RULE_PROFILE_ID:
            raise ValueError("record commitment has an unsupported rule profile")
        if (
            isinstance(self.record_index, bool)
            or not isinstance(self.record_index, int)
            or self.record_index < 0
        ):
            raise ValueError("record commitment index must be a non-negative integer")
        _require_sha256(
            self.record_content_sha256,
            label="record commitment content hash",
        )
        if self.record_index == 0:
            if self.previous_record_sha256 is not None:
                raise ValueError("first record commitment must have no predecessor")
        else:
            _require_sha256(
                self.previous_record_sha256,
                label="record commitment predecessor hash",
            )
        for label, value in (
            ("record commitment node hash", self.node_sha256),
            ("record commitment frontier hash", self.frontier_content_sha256),
            ("record commitment position hash", self.position_sha256),
            ("record commitment game-state hash", self.game_state_sha256),
            ("record commitment certificate hash", self.certificate_sha256),
            ("record commitment root certificate hash", self.root_certificate_hash),
        ):
            _require_sha256(value, label=label)
        if not isinstance(self.claimed_wdl, WDL) or self.claimed_wdl == WDL.UNKNOWN:
            raise ValueError("record commitment WDL must be an exact non-UNKNOWN value")

    def record(self) -> dict[str, object]:
        return {
            "schema": OVERLAY_RECORD_COMMITMENT_SCHEMA,
            "format_major": self.format_major,
            "format_minor": self.format_minor,
            "rule_profile_id": self.rule_profile_id,
            "record_index": self.record_index,
            "record_content_sha256": self.record_content_sha256,
            "previous_record_sha256": self.previous_record_sha256,
            "node_sha256": self.node_sha256,
            "frontier_content_sha256": self.frontier_content_sha256,
            "position_sha256": self.position_sha256,
            "game_state_sha256": self.game_state_sha256,
            "claimed_wdl": self.claimed_wdl.value,
            "certificate_sha256": self.certificate_sha256,
            "root_certificate_hash": self.root_certificate_hash,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @classmethod
    def from_canonical_bytes(
        cls,
        value: bytes | bytearray | memoryview,
    ) -> "OverlayRecordCommitment":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("record commitment must be bytes-like")
        snapshot = bytes(value)
        try:
            raw = json.loads(snapshot)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"record commitment is not UTF-8 JSON: {exc}") from exc
        if not isinstance(raw, dict) or canonical_json_bytes(raw) != snapshot:
            raise ValueError("record commitment is not a canonical JSON object")
        if set(raw) != _RECORD_COMMITMENT_KEYS:
            raise ValueError("record commitment has missing or unexpected fields")
        if raw.get("schema") != OVERLAY_RECORD_COMMITMENT_SCHEMA:
            raise ValueError("record commitment schema mismatch")
        try:
            claimed_wdl = WDL(raw["claimed_wdl"])
        except (KeyError, ValueError) as exc:
            raise ValueError("record commitment has an invalid WDL") from exc
        commitment = cls(
            format_major=raw["format_major"],
            format_minor=raw["format_minor"],
            rule_profile_id=raw["rule_profile_id"],
            record_index=raw["record_index"],
            record_content_sha256=raw["record_content_sha256"],
            previous_record_sha256=raw["previous_record_sha256"],
            node_sha256=raw["node_sha256"],
            frontier_content_sha256=raw["frontier_content_sha256"],
            position_sha256=raw["position_sha256"],
            game_state_sha256=raw["game_state_sha256"],
            claimed_wdl=claimed_wdl,
            certificate_sha256=raw["certificate_sha256"],
            root_certificate_hash=raw["root_certificate_hash"],
        )
        if commitment.canonical_bytes() != snapshot:
            raise ValueError("record commitment differs from exact reconstruction")
        return commitment


@dataclass(frozen=True, slots=True)
class OverlayHeadCommitment:
    """Externally retainable commitment to one valid journal prefix."""

    format_major: int
    format_minor: int
    rule_profile_id: str
    header_sha256: str
    record_count: int
    head_record_sha256: str | None
    journal_size_bytes: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.format_major, bool)
            or not isinstance(self.format_major, int)
            or self.format_major != OVERLAY_FORMAT_MAJOR
            or isinstance(self.format_minor, bool)
            or not isinstance(self.format_minor, int)
            or self.format_minor != OVERLAY_FORMAT_MINOR
        ):
            raise ValueError("head commitment has an unsupported overlay format")
        if self.rule_profile_id != RULE_PROFILE_ID:
            raise ValueError("head commitment has an unsupported rule profile")
        _require_sha256(self.header_sha256, label="head commitment header hash")
        if (
            isinstance(self.record_count, bool)
            or not isinstance(self.record_count, int)
            or self.record_count < 0
        ):
            raise ValueError("head commitment count must be a non-negative integer")
        if self.record_count == 0:
            if self.head_record_sha256 is not None:
                raise ValueError("empty head commitment must have no record hash")
        else:
            _require_sha256(
                self.head_record_sha256,
                label="head commitment record hash",
            )
        if (
            isinstance(self.journal_size_bytes, bool)
            or not isinstance(self.journal_size_bytes, int)
            or self.journal_size_bytes <= 0
        ):
            raise ValueError("head commitment journal size must be a positive integer")

    def record(self) -> dict[str, object]:
        return {
            "schema": OVERLAY_HEAD_COMMITMENT_SCHEMA,
            "format_major": self.format_major,
            "format_minor": self.format_minor,
            "rule_profile_id": self.rule_profile_id,
            "header_sha256": self.header_sha256,
            "record_count": self.record_count,
            "head_record_sha256": self.head_record_sha256,
            "journal_size_bytes": self.journal_size_bytes,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @classmethod
    def from_canonical_bytes(
        cls,
        value: bytes | bytearray | memoryview,
    ) -> "OverlayHeadCommitment":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("head commitment must be bytes-like")
        snapshot = bytes(value)
        try:
            raw = json.loads(snapshot)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"head commitment is not UTF-8 JSON: {exc}") from exc
        if not isinstance(raw, dict) or canonical_json_bytes(raw) != snapshot:
            raise ValueError("head commitment is not a canonical JSON object")
        if set(raw) != _HEAD_COMMITMENT_KEYS:
            raise ValueError("head commitment has missing or unexpected fields")
        if raw.get("schema") != OVERLAY_HEAD_COMMITMENT_SCHEMA:
            raise ValueError("head commitment schema mismatch")
        commitment = cls(
            format_major=raw["format_major"],
            format_minor=raw["format_minor"],
            rule_profile_id=raw["rule_profile_id"],
            header_sha256=raw["header_sha256"],
            record_count=raw["record_count"],
            head_record_sha256=raw["head_record_sha256"],
            journal_size_bytes=raw["journal_size_bytes"],
        )
        if commitment.canonical_bytes() != snapshot:
            raise ValueError("head commitment differs from exact reconstruction")
        return commitment


@dataclass(frozen=True, slots=True)
class AuditedOverlayRecord:
    """One commitment paired with the full binding replayed from disk."""

    commitment: OverlayRecordCommitment
    binding: VerifiedCertificateBinding
    frame_end_offset: int


@dataclass(frozen=True, slots=True)
class AuditedOverlaySnapshot:
    """Immutable commitments produced by one complete retained-fd replay."""

    head: OverlayHeadCommitment
    records: tuple[AuditedOverlayRecord, ...]
    header_size: int

    @staticmethod
    def _coerce_head(
        value: OverlayHeadCommitment | bytes | bytearray | memoryview,
    ) -> OverlayHeadCommitment:
        if isinstance(value, OverlayHeadCommitment):
            return value
        return OverlayHeadCommitment.from_canonical_bytes(value)

    def require_head(
        self,
        required: OverlayHeadCommitment | bytes | bytearray | memoryview,
        *,
        allow_extension: bool = True,
    ) -> OverlayHeadCommitment:
        """Require ``required`` to be this head or an exact retained prefix."""

        commitment = self._coerce_head(required)
        if (
            commitment.format_major != self.head.format_major
            or commitment.format_minor != self.head.format_minor
            or commitment.rule_profile_id != self.head.rule_profile_id
            or commitment.header_sha256 != self.head.header_sha256
        ):
            raise VerifiedOverlayHeadMismatchError(
                "required head belongs to a different overlay format/profile/header"
            )
        if commitment.record_count > self.head.record_count:
            raise VerifiedOverlayHeadMismatchError(
                "required overlay head is ahead of the audited journal"
            )
        if not allow_extension and commitment.record_count != self.head.record_count:
            raise VerifiedOverlayHeadMismatchError(
                "audited journal extends beyond the required exact head"
            )
        if commitment.record_count == 0:
            expected_hash = None
            expected_size = self.header_size
        else:
            record = self.records[commitment.record_count - 1]
            expected_hash = record.commitment.record_content_sha256
            expected_size = record.frame_end_offset
        if (
            commitment.head_record_sha256 != expected_hash
            or commitment.journal_size_bytes != expected_size
        ):
            raise VerifiedOverlayHeadMismatchError(
                "required overlay head is not an exact audited prefix"
            )
        return commitment

    def resolve_reference(
        self,
        reference: OverlayRecordCommitment | bytes | bytearray | memoryview,
        *,
        anchor: OverlayHeadCommitment | bytes | bytearray | memoryview | None = None,
    ) -> AuditedOverlayRecord:
        """Resolve an exact index/hash reference within an explicitly bounded head."""

        commitment = (
            reference
            if isinstance(reference, OverlayRecordCommitment)
            else OverlayRecordCommitment.from_canonical_bytes(reference)
        )
        bounded_head = self.head if anchor is None else self.require_head(anchor)
        if commitment.record_index >= bounded_head.record_count:
            raise VerifiedOverlayReferenceError(
                "record reference lies outside its committed overlay head"
            )
        actual = self.records[commitment.record_index]
        if actual.commitment.canonical_bytes() != commitment.canonical_bytes():
            raise VerifiedOverlayReferenceError(
                "record reference index/hash/semantics do not match the audited record"
            )
        return actual

    def reference_for_node(self, node_sha256: str) -> OverlayRecordCommitment | None:
        node_sha256 = _require_sha256(node_sha256, label="DAG node content address")
        for record in self.records:
            if record.commitment.node_sha256 == node_sha256:
                return record.commitment
        return None


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


def _crc32(parts: tuple[bytes, ...]) -> int:
    value = 0
    for part in parts:
        value = zlib.crc32(part, value)
    return value & 0xFFFFFFFF


def _issue(
    code: str,
    offset: int,
    message: str,
    *,
    recoverable_tail: bool,
    expected_bytes: int | None = None,
    actual_bytes: int | None = None,
) -> OverlayIssue:
    return OverlayIssue(
        code,
        offset,
        message,
        recoverable_tail,
        expected_bytes,
        actual_bytes,
    )


def _encode_header() -> bytes:
    profile = RULE_PROFILE_ID.encode("utf-8")
    prefix = _HEADER_PREFIX.pack(
        FILE_MAGIC,
        OVERLAY_FORMAT_MAJOR,
        OVERLAY_FORMAT_MINOR,
        len(profile),
    )
    return prefix + profile + _CRC32.pack(_crc32((prefix, profile)))


def _read_header(
    stream: BinaryIO,
    file_size: int,
) -> tuple[OverlayHeader | None, OverlayIssue | None]:
    stream.seek(0)
    prefix = stream.read(min(HEADER_PREFIX_SIZE, file_size))
    if len(prefix) != HEADER_PREFIX_SIZE:
        return None, _issue(
            "torn_header",
            0,
            "incomplete verified-overlay header",
            recoverable_tail=False,
            expected_bytes=HEADER_PREFIX_SIZE,
            actual_bytes=len(prefix),
        )
    magic, major, minor, profile_length = _HEADER_PREFIX.unpack(prefix)
    if magic != FILE_MAGIC:
        return None, _issue(
            "file_magic_mismatch",
            0,
            "verified-overlay file magic does not match",
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
            "incomplete verified-overlay header body",
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
            "verified-overlay header CRC32 mismatch",
            recoverable_tail=False,
        )
    try:
        profile = profile_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, _issue(
            "rule_profile_invalid",
            HEADER_PREFIX_SIZE,
            f"invalid rule-profile UTF-8: {exc}",
            recoverable_tail=False,
        )
    header_size = HEADER_PREFIX_SIZE + remaining_size
    header = OverlayHeader(major, minor, profile, header_size)
    if major != OVERLAY_FORMAT_MAJOR or minor > OVERLAY_FORMAT_MINOR:
        return header, _issue(
            "unsupported_format_version",
            8,
            f"unsupported verified-overlay format {major}.{minor}",
            recoverable_tail=False,
        )
    if profile != RULE_PROFILE_ID:
        return header, _issue(
            "rule_profile_mismatch",
            HEADER_PREFIX_SIZE,
            f"unsupported verified-overlay rule profile {profile!r}",
            recoverable_tail=False,
        )
    return header, None


def _strict_certificate_bundle(certificate_bytes: bytes) -> dict[str, object]:
    if len(certificate_bytes) > MAX_CERTIFICATE_BYTES:
        raise ValueError(
            f"certificate is {len(certificate_bytes)} bytes; maximum is "
            f"{MAX_CERTIFICATE_BYTES}"
        )
    try:
        decoded = json.loads(certificate_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"certificate bytes are not UTF-8 JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("certificate bundle must be a JSON object")
    if canonical_json_bytes(decoded) != certificate_bytes:
        raise ValueError("certificate bytes are not the canonical bare JSON bundle")
    if set(decoded) != _BUNDLE_KEYS:
        raise ValueError("certificate bundle has missing or unexpected fields")
    if decoded.get("schema") != BUNDLE_SCHEMA:
        raise ValueError("certificate bundle schema mismatch")
    if decoded.get("rules_profile") != RULE_PROFILE_ID:
        raise ValueError("certificate bundle rule profile mismatch")
    nodes = decoded.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("certificate bundle contains no nodes")
    hashes: list[str] = []
    for node in nodes:
        if not isinstance(node, dict) or set(node) != _NODE_KEYS:
            raise ValueError("certificate node has missing or unexpected fields")
        if node.get("schema") != NODE_SCHEMA:
            raise ValueError("certificate node schema mismatch")
        certificate_hash = node.get("certificate_hash")
        if not _is_sha256_hex(certificate_hash):
            raise ValueError("certificate node hash is invalid")
        hashes.append(certificate_hash)
        children = node.get("children")
        if not isinstance(children, list):
            raise ValueError("certificate node children must be a list")
        for child in children:
            if not isinstance(child, dict) or set(child) != _CHILD_KEYS:
                raise ValueError("child obligation has missing or unexpected fields")
    if len(set(hashes)) != len(hashes) or hashes != sorted(hashes):
        raise ValueError("certificate nodes must be unique and hash-sorted")
    return decoded


def _authoritative_first_frontier_content(dag: ProofDAG, node: DAGNode) -> str:
    incoming = dag.incoming_edges(node.node_sha256)
    if not incoming:
        raise ValueError("DAG node has no authoritative frontier occurrence")
    first = min(incoming, key=lambda edge: edge.frontier_record_index)
    if first.frontier_record_index != node.first_frontier_record_index:
        raise ValueError("DAG node first frontier occurrence is inconsistent")
    return first.frontier_content_sha256


def _verify_certificate_for_node(
    dag: ProofDAG,
    node_sha256: str,
    certificate_bytes: bytes,
) -> tuple[DAGNode, str, WDL, str, dict[str, object], dict[str, object]]:
    node_sha256 = _require_sha256(node_sha256, label="DAG node content address")
    node = dag.get_node(node_sha256)
    if node is None:
        raise ValueError("certificate references an unknown DAG node")
    if node.rule_profile_id != RULE_PROFILE_ID or node.wdl != WDL.UNKNOWN:
        raise ValueError("base DAG node is not canonical authoritative UNKNOWN")

    bundle = _strict_certificate_bundle(certificate_bytes)
    result = verify_wdl_certificate(bundle, allow_unknown_root=False)
    if result.get("valid") is not True or result.get("root_exact") is not True:
        raise ValueError("certificate verifier did not accept an exact root")
    if result.get("unreferenced_nodes") != 0:
        raise ValueError("certificate bundle contains unreferenced nodes")
    try:
        claimed_wdl = WDL(result["root_value"])
    except (KeyError, ValueError) as exc:
        raise ValueError("certificate verifier returned an invalid root WDL") from exc
    if claimed_wdl == WDL.UNKNOWN:
        raise ValueError("UNKNOWN cannot be promoted into the verified overlay")

    root_hash = result.get("root_certificate_hash")
    if not _is_sha256_hex(root_hash) or root_hash != bundle.get("root_certificate_hash"):
        raise ValueError("certificate verifier root hash mismatch")
    root_records = [
        candidate
        for candidate in bundle["nodes"]
        if candidate.get("certificate_hash") == root_hash
    ]
    if len(root_records) != 1:
        raise ValueError("certificate root record is missing or ambiguous")
    root_record = root_records[0]

    # These are deliberately separate comparisons.  game_state_sha256 omits
    # the fullmove counter, so it cannot replace the exact canonical FEN.
    if root_record.get("fen") != node.fen:
        raise ValueError("certificate root FEN does not exactly match the DAG node")
    if root_record.get("history_counts") != node.history.record():
        raise ValueError("certificate root history does not exactly match the DAG node")
    if root_record.get("state_hash") != node.game_state_sha256:
        raise ValueError("certificate root game-state hash does not match the DAG node")
    if bundle.get("root_state_hash") != node.game_state_sha256:
        raise ValueError("certificate bundle root-state hash does not match the DAG node")
    if bundle.get("rules_profile") != node.rule_profile_id:
        raise ValueError("certificate rules profile does not match the DAG node")
    if root_record.get("exact") is not True or bundle.get("root_exact") is not True:
        raise ValueError("certificate root is not exact")
    if root_record.get("value") != claimed_wdl.value:
        raise ValueError("certificate root record WDL does not match verifier result")
    if bundle.get("root_value") != claimed_wdl.value:
        raise ValueError("certificate bundle root WDL does not match verifier result")

    frontier_content_sha256 = _authoritative_first_frontier_content(dag, node)
    return (
        node,
        frontier_content_sha256,
        claimed_wdl,
        root_hash,
        result,
        bundle,
    )


def _new_binding(
    dag: ProofDAG,
    *,
    node_sha256: str,
    certificate_bytes: bytes,
    record_index: int,
    previous_record_sha256: str | None,
) -> VerifiedCertificateBinding:
    node, frontier_hash, claimed_wdl, root_hash, result, _ = (
        _verify_certificate_for_node(dag, node_sha256, certificate_bytes)
    )
    return VerifiedCertificateBinding(
        record_index=record_index,
        previous_record_sha256=previous_record_sha256,
        node_sha256=node.node_sha256,
        frontier_content_sha256=frontier_hash,
        rule_profile_id=node.rule_profile_id,
        fen=node.fen,
        history_counts=node.history.counts,
        position_sha256=node.position_sha256,
        game_state_sha256=node.game_state_sha256,
        claimed_wdl=claimed_wdl,
        certificate_size=len(certificate_bytes),
        certificate_sha256=hashlib.sha256(certificate_bytes).hexdigest(),
        certificate_bytes=certificate_bytes,
        root_certificate_hash=root_hash,
        verifier_profile=CERTIFICATE_VERIFIER_PROFILE,
        verifier_result=MappingProxyType(dict(result)),
    )


def _history_from_payload(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, list):
        raise ValueError("overlay history_counts must be a list")
    pairs: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("overlay history entry must be a two-item list")
        key, count = item
        if not _is_sha256_hex(key):
            raise ValueError("overlay history key is not lowercase SHA-256")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
            raise ValueError("overlay history count must be an integer in 1..5")
        pairs.append((key, count))
    if pairs != sorted(pairs) or len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("overlay history entries must be unique and sorted")
    return tuple(pairs)


def _decode_binding(
    payload: bytes,
    dag: ProofDAG,
    *,
    expected_record_index: int,
    expected_previous_record_sha256: str | None,
) -> VerifiedCertificateBinding:
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"overlay payload is not UTF-8 JSON: {exc}") from exc
    if not isinstance(raw, dict) or canonical_json_bytes(raw) != payload:
        raise ValueError("overlay payload is not a canonical JSON object")
    if set(raw) != _RECORD_KEYS:
        raise ValueError("overlay record has missing or unexpected fields")
    if raw.get("schema") != OVERLAY_RECORD_SCHEMA:
        raise ValueError("overlay record schema mismatch")
    stored_record_index = raw.get("record_index")
    if (
        isinstance(stored_record_index, bool)
        or not isinstance(stored_record_index, int)
        or stored_record_index < 0
        or stored_record_index != expected_record_index
    ):
        raise ValueError("overlay record index is not contiguous")
    if raw.get("previous_record_sha256") != expected_previous_record_sha256:
        raise ValueError("overlay record hash chain is broken")
    if raw.get("rule_profile_id") != RULE_PROFILE_ID:
        raise ValueError("overlay record rule profile mismatch")
    if raw.get("certificate_encoding") != CERTIFICATE_ENCODING:
        raise ValueError("overlay certificate encoding mismatch")
    if raw.get("verifier_profile") != CERTIFICATE_VERIFIER_PROFILE:
        raise ValueError("overlay verifier profile mismatch")

    node_sha256 = _require_sha256(raw.get("node_sha256"), label="overlay node hash")
    stored_frontier_hash = _require_sha256(
        raw.get("frontier_content_sha256"),
        label="overlay frontier content hash",
    )
    stored_position_hash = _require_sha256(
        raw.get("position_sha256"),
        label="overlay position hash",
    )
    stored_game_hash = _require_sha256(
        raw.get("game_state_sha256"),
        label="overlay game-state hash",
    )
    stored_certificate_hash = _require_sha256(
        raw.get("certificate_sha256"),
        label="overlay certificate hash",
    )
    stored_root_hash = _require_sha256(
        raw.get("root_certificate_hash"),
        label="overlay root certificate hash",
    )
    history = _history_from_payload(raw.get("history_counts"))
    certificate_size = raw.get("certificate_size")
    if (
        isinstance(certificate_size, bool)
        or not isinstance(certificate_size, int)
        or not 0 < certificate_size <= MAX_CERTIFICATE_BYTES
    ):
        raise ValueError("overlay certificate size is invalid")
    certificate_base64 = raw.get("certificate_base64")
    if not isinstance(certificate_base64, str):
        raise ValueError("overlay certificate bytes are not base64 text")
    try:
        certificate_bytes = base64.b64decode(
            certificate_base64.encode("ascii"),
            validate=True,
        )
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("overlay certificate base64 is invalid") from exc
    if len(certificate_bytes) != certificate_size:
        raise ValueError("overlay certificate byte count mismatch")
    if base64.b64encode(certificate_bytes).decode("ascii") != certificate_base64:
        raise ValueError("overlay certificate base64 is not canonical")
    if hashlib.sha256(certificate_bytes).hexdigest() != stored_certificate_hash:
        raise ValueError("overlay certificate SHA-256 mismatch")

    node, frontier_hash, claimed_wdl, root_hash, result, _ = (
        _verify_certificate_for_node(dag, node_sha256, certificate_bytes)
    )
    if raw.get("fen") != node.fen:
        raise ValueError("overlay exact FEN does not match the DAG node")
    if history != node.history.counts:
        raise ValueError("overlay history does not match the DAG node")
    if stored_frontier_hash != frontier_hash:
        raise ValueError("overlay frontier content address is stale or forged")
    if stored_position_hash != node.position_sha256:
        raise ValueError("overlay position hash does not match the DAG node")
    if stored_game_hash != node.game_state_sha256:
        raise ValueError("overlay game-state hash does not match the DAG node")
    if raw.get("claimed_wdl") != claimed_wdl.value:
        raise ValueError("overlay claimed WDL does not match the certificate")
    if stored_root_hash != root_hash:
        raise ValueError("overlay root certificate hash mismatch")
    raw_verifier_result = raw.get("verifier_result")
    if (
        not isinstance(raw_verifier_result, dict)
        or canonical_json_bytes(raw_verifier_result) != canonical_json_bytes(result)
    ):
        raise ValueError("overlay verifier result does not match replay")

    reconstructed = VerifiedCertificateBinding(
        record_index=expected_record_index,
        previous_record_sha256=expected_previous_record_sha256,
        node_sha256=node.node_sha256,
        frontier_content_sha256=frontier_hash,
        rule_profile_id=node.rule_profile_id,
        fen=node.fen,
        history_counts=node.history.counts,
        position_sha256=node.position_sha256,
        game_state_sha256=node.game_state_sha256,
        claimed_wdl=claimed_wdl,
        certificate_size=certificate_size,
        certificate_sha256=stored_certificate_hash,
        certificate_bytes=certificate_bytes,
        root_certificate_hash=root_hash,
        verifier_profile=CERTIFICATE_VERIFIER_PROFILE,
        verifier_result=MappingProxyType(dict(result)),
    )
    # A field-by-field semantic check is intentionally followed by exact
    # canonical reconstruction.  This rejects Python equality aliases such as
    # false == 0 or 0.0 == 0 anywhere in nested verifier output.
    if reconstructed.payload_bytes() != payload:
        raise ValueError("overlay payload differs from exact reconstructed binding")
    return reconstructed


def _encode_frame(binding: VerifiedCertificateBinding) -> tuple[bytes, str, int]:
    payload = binding.payload_bytes()
    if len(payload) > MAX_RECORD_PAYLOAD_BYTES:
        raise ValueError(
            f"overlay record payload is {len(payload)} bytes; maximum is "
            f"{MAX_RECORD_PAYLOAD_BYTES}"
        )
    prefix = _RECORD_PREFIX.pack(RECORD_MAGIC, len(payload))
    digest = hashlib.sha256(payload).digest()
    crc = _crc32((prefix, payload, digest))
    return prefix + payload + digest + _CRC32.pack(crc), digest.hex(), crc


def _structurally_valid_frame_at(
    stream: BinaryIO,
    *,
    offset: int,
    file_size: int,
) -> bool:
    """Check an independent later frame without trusting its hash-chain fields."""

    if file_size - offset < RECORD_PREFIX_SIZE:
        return False
    stream.seek(offset)
    prefix = stream.read(RECORD_PREFIX_SIZE)
    magic, payload_length = _RECORD_PREFIX.unpack(prefix)
    if magic != RECORD_MAGIC or payload_length > MAX_RECORD_PAYLOAD_BYTES:
        return False
    body_size = payload_length + RECORD_SHA256_SIZE + RECORD_CRC32_SIZE
    if body_size > file_size - stream.tell():
        return False
    body = stream.read(body_size)
    payload = body[:payload_length]
    digest = body[payload_length : payload_length + RECORD_SHA256_SIZE]
    stored_crc = _CRC32.unpack(body[-RECORD_CRC32_SIZE:])[0]
    if stored_crc != _crc32((prefix, payload, digest)):
        return False
    if digest != hashlib.sha256(payload).digest():
        return False
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return (
        isinstance(raw, dict)
        and canonical_json_bytes(raw) == payload
        and raw.get("schema") == OVERLAY_RECORD_SCHEMA
    )


def _has_valid_frame_after(
    stream: BinaryIO,
    *,
    record_start: int,
    file_size: int,
) -> bool:
    original_offset = stream.tell()
    scan_offset = record_start + 1
    carry = b""
    try:
        while scan_offset < file_size:
            stream.seek(scan_offset)
            chunk = stream.read(min(1024 * 1024, file_size - scan_offset))
            if not chunk:
                return False
            window = carry + chunk
            window_offset = scan_offset - len(carry)
            search_from = 0
            while True:
                marker_index = window.find(RECORD_MAGIC, search_from)
                if marker_index < 0:
                    break
                candidate = window_offset + marker_index
                if candidate > record_start and _structurally_valid_frame_at(
                    stream,
                    offset=candidate,
                    file_size=file_size,
                ):
                    return True
                search_from = marker_index + 1
            carry = window[-(len(RECORD_MAGIC) - 1) :]
            scan_offset += len(chunk)
        return False
    finally:
        stream.seek(original_offset)


def _read_record(
    stream: BinaryIO,
    *,
    file_size: int,
    dag: ProofDAG,
    record_index: int,
    previous_record_sha256: str | None,
    scan_for_valid_suffix: bool = True,
) -> tuple[OverlayEntry | None, OverlayIssue | None]:
    start = stream.tell()
    if start == file_size:
        return None, None
    if start > file_size:
        return None, _issue(
            "record_offset_past_eof",
            start,
            "overlay record offset is past EOF",
            recoverable_tail=False,
        )
    prefix = stream.read(min(RECORD_PREFIX_SIZE, file_size - start))
    if len(prefix) != RECORD_PREFIX_SIZE:
        return None, _issue(
            "torn_record_prefix",
            start,
            "incomplete verified-overlay record prefix",
            recoverable_tail=True,
            expected_bytes=RECORD_PREFIX_SIZE,
            actual_bytes=len(prefix),
        )
    magic, payload_length = _RECORD_PREFIX.unpack(prefix)
    if magic != RECORD_MAGIC:
        return None, _issue(
            "record_magic_mismatch",
            start,
            "verified-overlay record magic does not match",
            recoverable_tail=False,
        )
    if payload_length > MAX_RECORD_PAYLOAD_BYTES:
        return None, _issue(
            "record_length_invalid",
            start + 4,
            f"overlay payload length {payload_length} exceeds the maximum",
            recoverable_tail=False,
        )
    body_size = payload_length + RECORD_SHA256_SIZE + RECORD_CRC32_SIZE
    available = max(0, file_size - stream.tell())
    body = stream.read(min(body_size, available))
    if len(body) != body_size:
        valid_suffix = scan_for_valid_suffix and _has_valid_frame_after(
            stream,
            record_start=start,
            file_size=file_size,
        )
        return None, _issue(
            "torn_record_body",
            start,
            "incomplete verified-overlay record body"
            + (
                "; a later independently valid frame makes truncation unsafe"
                if valid_suffix
                else ""
            ),
            recoverable_tail=not valid_suffix,
            expected_bytes=body_size,
            actual_bytes=len(body),
        )
    payload = body[:payload_length]
    digest = body[payload_length : payload_length + RECORD_SHA256_SIZE]
    stored_crc = _CRC32.unpack(body[-RECORD_CRC32_SIZE:])[0]
    if stored_crc != _crc32((prefix, payload, digest)):
        return None, _issue(
            "record_crc32_mismatch",
            start,
            "verified-overlay record CRC32 mismatch",
            recoverable_tail=False,
        )
    actual_digest = hashlib.sha256(payload).digest()
    if digest != actual_digest:
        return None, _issue(
            "record_sha256_mismatch",
            start,
            "verified-overlay record SHA-256 mismatch",
            recoverable_tail=False,
        )
    try:
        binding = _decode_binding(
            payload,
            dag,
            expected_record_index=record_index,
            expected_previous_record_sha256=previous_record_sha256,
        )
    except (ProofDAGError, TypeError, ValueError) as exc:
        return None, _issue(
            "record_semantic_invalid",
            start + RECORD_PREFIX_SIZE,
            f"verified-overlay record failed replay: {exc}",
            recoverable_tail=False,
        )
    end = start + RECORD_PREFIX_SIZE + body_size
    return (
        OverlayEntry(
            record_index=record_index,
            frame_offset=start,
            frame_end_offset=end,
            payload_offset=start + RECORD_PREFIX_SIZE,
            payload_length=payload_length,
            sha256_offset=start + RECORD_PREFIX_SIZE + payload_length,
            crc32_offset=end - RECORD_CRC32_SIZE,
            content_sha256=digest.hex(),
            crc32=stored_crc,
            binding=binding,
        ),
        None,
    )


def _scan_verified_overlay_stream(
    overlay_path: Path,
    stream: BinaryIO,
    dag: ProofDAG,
) -> OverlayScanResult:
    """Replay exactly one already-open file description.

    The caller may retain this same descriptor for appends.  Using ``fstat``
    before and after avoids the path-stat/open/path-stat swap window that
    would otherwise permit verification of one inode and use of another.
    """

    start_stat = os.fstat(stream.fileno())
    file_size = start_stat.st_size
    entries: list[OverlayEntry] = []
    header, header_issue = _read_header(stream, file_size)
    if header_issue is not None:
        return OverlayScanResult(
            overlay_path,
            file_size,
            header,
            0,
            0,
            issue=header_issue,
        )
    assert header is not None
    last_good = header.header_size
    previous: str | None = None
    seen_nodes: dict[str, str] = {}
    for record_index in range(2**63 - 1):
        stream.seek(last_good)
        entry, record_issue = _read_record(
            stream,
            file_size=file_size,
            dag=dag,
            record_index=record_index,
            previous_record_sha256=previous,
        )
        if record_issue is not None:
            return OverlayScanResult(
                overlay_path,
                file_size,
                header,
                len(entries),
                last_good,
                tuple(entries),
                record_issue,
            )
        if entry is None:
            break
        prior = seen_nodes.get(entry.binding.node_sha256)
        if prior is not None:
            issue = _issue(
                "duplicate_node_binding",
                entry.frame_offset,
                "overlay contains a second certificate for one DAG node",
                recoverable_tail=False,
            )
            return OverlayScanResult(
                overlay_path,
                file_size,
                header,
                len(entries),
                last_good,
                tuple(entries),
                issue,
            )
        seen_nodes[entry.binding.node_sha256] = entry.binding.certificate_sha256
        entries.append(entry)
        previous = entry.content_sha256
        last_good = entry.frame_end_offset

    end_stat = os.fstat(stream.fileno())
    start_identity = (
        start_stat.st_dev,
        start_stat.st_ino,
        start_stat.st_size,
        start_stat.st_mtime_ns,
        start_stat.st_ctime_ns,
    )
    end_identity = (
        end_stat.st_dev,
        end_stat.st_ino,
        end_stat.st_size,
        end_stat.st_mtime_ns,
        end_stat.st_ctime_ns,
    )
    if end_identity != start_identity:
        issue = _issue(
            "file_changed_during_read",
            file_size,
            "verified-overlay file changed during replay",
            recoverable_tail=False,
        )
        return OverlayScanResult(
            overlay_path,
            file_size,
            header,
            len(entries),
            last_good,
            tuple(entries),
            issue,
        )
    return OverlayScanResult(
        overlay_path,
        file_size,
        header,
        len(entries),
        last_good,
        tuple(entries),
    )


def verify_verified_overlay(
    path: str | os.PathLike[str],
    dag: ProofDAG,
) -> OverlayScanResult:
    """Fully replay an overlay against an already audited, live ProofDAG."""

    overlay_path = Path(path)
    try:
        with overlay_path.open("rb", buffering=0) as stream:
            try:
                initially_same = os.path.samestat(
                    os.stat(overlay_path),
                    os.fstat(stream.fileno()),
                )
            except OSError as exc:
                return OverlayScanResult(
                    overlay_path,
                    os.fstat(stream.fileno()).st_size,
                    None,
                    0,
                    0,
                    issue=_issue(
                        "path_unavailable_before_read",
                        0,
                        f"cannot bind overlay path before replay: {exc}",
                        recoverable_tail=False,
                    ),
                )
            if not initially_same:
                return OverlayScanResult(
                    overlay_path,
                    os.fstat(stream.fileno()).st_size,
                    None,
                    0,
                    0,
                    issue=_issue(
                        "path_replaced_before_read",
                        0,
                        "overlay path does not name the file opened for replay",
                        recoverable_tail=False,
                    ),
                )
            report = _scan_verified_overlay_stream(overlay_path, stream, dag)
            try:
                same_file = os.path.samestat(
                    os.stat(overlay_path),
                    os.fstat(stream.fileno()),
                )
            except OSError as exc:
                return OverlayScanResult(
                    overlay_path,
                    report.file_size,
                    report.header,
                    report.record_count,
                    report.last_good_offset,
                    report.entries,
                    _issue(
                        "path_unavailable_after_read",
                        report.last_good_offset,
                        f"cannot rebind overlay path after replay: {exc}",
                        recoverable_tail=False,
                    ),
                )
            if not same_file:
                return OverlayScanResult(
                    overlay_path,
                    report.file_size,
                    report.header,
                    report.record_count,
                    report.last_good_offset,
                    report.entries,
                    _issue(
                        "path_replaced_during_read",
                        report.last_good_offset,
                        "overlay path no longer names the file that was replayed",
                        recoverable_tail=False,
                    ),
                )
            return report
    except OSError as exc:
        return OverlayScanResult(
            overlay_path,
            0,
            None,
            0,
            0,
            issue=_issue(
                "file_unavailable",
                0,
                f"verified-overlay file is unavailable: {exc}",
                recoverable_tail=False,
            ),
        )


def _audited_snapshot_from_report(report: OverlayScanResult) -> AuditedOverlaySnapshot:
    report.require_valid()
    if report.header is None:
        raise VerifiedOverlayError("valid overlay replay has no header")
    header = report.header
    records: list[AuditedOverlayRecord] = []
    for entry in report.entries:
        binding = entry.binding
        commitment = OverlayRecordCommitment(
            format_major=header.format_major,
            format_minor=header.format_minor,
            rule_profile_id=header.rule_profile_id,
            record_index=entry.record_index,
            record_content_sha256=entry.content_sha256,
            previous_record_sha256=binding.previous_record_sha256,
            node_sha256=binding.node_sha256,
            frontier_content_sha256=binding.frontier_content_sha256,
            position_sha256=binding.position_sha256,
            game_state_sha256=binding.game_state_sha256,
            claimed_wdl=binding.claimed_wdl,
            certificate_sha256=binding.certificate_sha256,
            root_certificate_hash=binding.root_certificate_hash,
        )
        records.append(
            AuditedOverlayRecord(
                commitment=commitment,
                binding=binding,
                frame_end_offset=entry.frame_end_offset,
            )
        )
    head = OverlayHeadCommitment(
        format_major=header.format_major,
        format_minor=header.format_minor,
        rule_profile_id=header.rule_profile_id,
        header_sha256=hashlib.sha256(_encode_header()).hexdigest(),
        record_count=report.record_count,
        head_record_sha256=(
            None if not report.entries else report.entries[-1].content_sha256
        ),
        journal_size_bytes=report.file_size,
    )
    return AuditedOverlaySnapshot(
        head=head,
        records=tuple(records),
        header_size=header.header_size,
    )


class VerifiedCertificateOverlay:
    """Exclusive append handle for independently verified DAG node values."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        dag: ProofDAG,
    ) -> None:
        if not isinstance(dag, ProofDAG) or dag.closed:
            raise TypeError("dag must be an open ProofDAG")
        if dag.rule_profile_id != RULE_PROFILE_ID:
            raise ValueError("overlay supports only the canonical rule profile")
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.dag = dag
        self._thread_lock = threading.Lock()
        self._writer_lock = _SidecarWriterLock(self.path)
        self.lock_path = self._writer_lock.path
        self._stream: BinaryIO | None = None
        self._failed = False
        self._entries_by_node: dict[str, OverlayEntry] = {}
        self._entries: list[OverlayEntry] = []
        try:
            self._writer_lock.acquire()
        except FrontierWriterLockedError as exc:
            raise VerifiedOverlayWriterLockedError(
                f"another writer owns verified-overlay lock {self.lock_path}"
            ) from exc
        try:
            header = _encode_header()
            try:
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                if hasattr(os, "O_BINARY"):
                    flags |= os.O_BINARY
                descriptor = os.open(self.path, flags, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "wb", buffering=0) as created:
                    _write_all(created, header)
                    created.flush()
                    os.fsync(created.fileno())
                _fsync_parent_directory(self.path)

            # Audit and retain one exact file description.  There is no
            # scan(path X) -> open(path Y) window, even if the path is replaced
            # with another same-size inode between ordinary filesystem calls.
            self._stream = self.path.open("r+b", buffering=0)
            report = _scan_verified_overlay_stream(
                self.path,
                self._stream,
                self.dag,
            )
            report.require_valid()
            self._entries = list(report.entries)
            self._entries_by_node = {
                entry.binding.node_sha256: entry for entry in report.entries
            }
            self._next_offset = report.file_size
            self._next_index = report.record_count
            self._previous_record_sha256 = (
                None if not report.entries else report.entries[-1].content_sha256
            )
            self._require_path_matches_stream()
        except BaseException:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._writer_lock.release()
            raise

    @property
    def closed(self) -> bool:
        return self._stream is None or self._stream.closed

    def _check_live_boundary(self) -> None:
        if self.closed:
            raise VerifiedOverlayError("verified overlay is closed")
        if self._failed:
            raise VerifiedOverlayCommitError(
                "verified overlay is unusable after a failed append; reopen it"
            )
        assert self._stream is not None
        self._require_path_matches_stream()
        if os.fstat(self._stream.fileno()).st_size != self._next_offset:
            self._failed = True
            raise VerifiedOverlayIntegrityError(
                OverlayScanResult(
                    self.path,
                    os.fstat(self._stream.fileno()).st_size,
                    None,
                    len(self._entries),
                    self._next_offset,
                    tuple(self._entries),
                    _issue(
                        "file_changed_while_open",
                        self._next_offset,
                        "verified-overlay bytes changed outside the audited writer",
                        recoverable_tail=False,
                    ),
                )
            )

    def _require_path_matches_stream(self) -> None:
        """Reject rename/replacement of the authoritative journal path."""

        assert self._stream is not None
        try:
            path_stat = os.stat(self.path)
            stream_stat = os.fstat(self._stream.fileno())
        except OSError as exc:
            raise VerifiedOverlayError(
                f"cannot bind overlay path to its open file description: {exc}"
            ) from exc
        if not os.path.samestat(path_stat, stream_stat):
            raise VerifiedOverlayError(
                "verified-overlay path no longer names the audited open file"
            )

    @staticmethod
    def _entry_seal(entry: OverlayEntry) -> tuple[object, ...]:
        return (
            entry.record_index,
            entry.frame_offset,
            entry.frame_end_offset,
            entry.content_sha256,
            entry.crc32,
            entry.binding.node_sha256,
            entry.binding.certificate_sha256,
            entry.binding.claimed_wdl.value,
        )

    def _replay_live_journal(self) -> OverlayScanResult:
        """Full-audit the exact retained fd and compare it with live state."""

        try:
            self._check_live_boundary()
            assert self._stream is not None
            report = _scan_verified_overlay_stream(
                self.path,
                self._stream,
                self.dag,
            )
            report.require_valid()
            expected_seals = tuple(self._entry_seal(entry) for entry in self._entries)
            actual_seals = tuple(self._entry_seal(entry) for entry in report.entries)
            if (
                report.file_size != self._next_offset
                or report.record_count != self._next_index
                or actual_seals != expected_seals
            ):
                raise VerifiedOverlayIntegrityError(
                    OverlayScanResult(
                        self.path,
                        report.file_size,
                        report.header,
                        report.record_count,
                        report.last_good_offset,
                        report.entries,
                        _issue(
                            "audited_state_divergence",
                            report.last_good_offset,
                            "full overlay replay differs from the live audited state",
                            recoverable_tail=False,
                        ),
                    )
                )
            self._require_path_matches_stream()
            return report
        except BaseException:
            # Any global replay failure poisons the handle.  A caller cannot
            # query some other intact frame after the hash chain became invalid.
            self._failed = True
            raise

    def append_verified_certificate(
        self,
        node_sha256: str,
        certificate_bytes: bytes | bytearray | memoryview,
    ) -> OverlayAppendResult:
        """Verify and durably bind one canonical certificate byte snapshot.

        ``bytes(...)`` is called exactly once at the API boundary.  Parsing,
        hashing, verification, persistence, and readback all use that immutable
        snapshot, eliminating a path/file/mutable-buffer TOCTOU gap.
        """

        if not isinstance(certificate_bytes, (bytes, bytearray, memoryview)):
            raise TypeError("certificate_bytes must be bytes-like")
        certificate_snapshot = bytes(certificate_bytes)
        with self._thread_lock:
            replay = self._replay_live_journal()
            binding = _new_binding(
                self.dag,
                node_sha256=node_sha256,
                certificate_bytes=certificate_snapshot,
                record_index=self._next_index,
                previous_record_sha256=self._previous_record_sha256,
            )
            replay_by_node = {
                entry.binding.node_sha256: entry for entry in replay.entries
            }
            existing = replay_by_node.get(binding.node_sha256)
            if existing is not None:
                if (
                    existing.binding.certificate_sha256
                    == binding.certificate_sha256
                    and existing.binding.certificate_bytes == certificate_snapshot
                ):
                    return OverlayAppendResult(existing, False)
                raise VerifiedOverlayConflictError(
                    "DAG node already has a different verified certificate; "
                    "overlay facts are immutable"
                )

            frame, content_sha256, crc = _encode_frame(binding)
            frame_offset = self._next_offset
            assert self._stream is not None
            try:
                self._stream.seek(frame_offset)
                _write_all(self._stream, frame)
                self._stream.flush()
                # Promotion is never visible before a durability barrier.
                os.fsync(self._stream.fileno())
            except BaseException:
                self._failed = True
                raise
            frame_end = frame_offset + len(frame)
            provisional = OverlayEntry(
                record_index=self._next_index,
                frame_offset=frame_offset,
                frame_end_offset=frame_end,
                payload_offset=frame_offset + RECORD_PREFIX_SIZE,
                payload_length=len(binding.payload_bytes()),
                sha256_offset=frame_end - RECORD_CRC32_SIZE - RECORD_SHA256_SIZE,
                crc32_offset=frame_end - RECORD_CRC32_SIZE,
                content_sha256=content_sha256,
                crc32=crc,
                binding=binding,
            )
            try:
                self._require_path_matches_stream()
                report = _scan_verified_overlay_stream(
                    self.path,
                    self._stream,
                    self.dag,
                )
                report.require_valid()
                prior_seals = tuple(
                    self._entry_seal(entry) for entry in report.entries[:-1]
                )
                expected_prior = tuple(
                    self._entry_seal(entry) for entry in self._entries
                )
                if (
                    report.file_size != frame_end
                    or report.record_count != self._next_index + 1
                    or prior_seals != expected_prior
                    or not report.entries
                    or self._entry_seal(report.entries[-1])
                    != self._entry_seal(provisional)
                ):
                    raise VerifiedOverlayError(
                        "durable overlay append does not match exact replay"
                    )
                audited = report.entries[-1]
            except BaseException as exc:
                self._failed = True
                raise VerifiedOverlayCommitError(
                    "certificate append is durable but replay failed; reopen the overlay"
                ) from exc
            self._entries.append(audited)
            self._entries_by_node[audited.binding.node_sha256] = audited
            self._next_offset = frame_end
            self._next_index += 1
            self._previous_record_sha256 = audited.content_sha256
            return OverlayAppendResult(audited, True)

    def get_binding(self, node_sha256: str) -> VerifiedCertificateBinding | None:
        node_sha256 = _require_sha256(node_sha256, label="DAG node content address")
        with self._thread_lock:
            report = self._replay_live_journal()
            for entry in report.entries:
                if entry.binding.node_sha256 == node_sha256:
                    return entry.binding
            return None

    def effective_wdl(self, node_sha256: str) -> WDL:
        """Return an audited overlay fact, or UNKNOWN for an unpromoted DAG node."""

        node_sha256 = _require_sha256(node_sha256, label="DAG node content address")
        if self.dag.get_node(node_sha256) is None:
            raise ValueError("unknown DAG node")
        binding = self.get_binding(node_sha256)
        return WDL.UNKNOWN if binding is None else binding.claimed_wdl

    def iter_bindings(self) -> Iterator[VerifiedCertificateBinding]:
        with self._thread_lock:
            report = self._replay_live_journal()
            bindings = tuple(entry.binding for entry in report.entries)
        return iter(bindings)

    def audited_snapshot(self) -> AuditedOverlaySnapshot:
        """Return commitments from exactly one complete retained-fd replay."""

        with self._thread_lock:
            report = self._replay_live_journal()
            return _audited_snapshot_from_report(report)

    def head_commitment(self) -> OverlayHeadCommitment:
        """Return the externally retainable head of one audited snapshot."""

        return self.audited_snapshot().head

    def require_external_head(
        self,
        required: OverlayHeadCommitment | bytes | bytearray | memoryview,
        *,
        allow_extension: bool = True,
    ) -> AuditedOverlaySnapshot:
        """Fail closed unless the live journal contains an externally saved head.

        Keeping ``required`` outside the journal is what turns a clean removal
        of a valid suffix into detectable rollback.  With no external head,
        the v1 hash chain alone cannot distinguish that rollback from a journal
        that legitimately ended at the earlier record.
        """

        snapshot = self.audited_snapshot()
        snapshot.require_head(required, allow_extension=allow_extension)
        return snapshot

    def audit(self) -> OverlayScanResult:
        """Re-run a complete journal, DAG, and certificate audit."""

        with self._thread_lock:
            return self._replay_live_journal()

    def close(self) -> None:
        with self._thread_lock:
            try:
                if self._stream is not None and not self._stream.closed:
                    self._stream.close()
            finally:
                self._stream = None
                self._writer_lock.release()

    def __enter__(self) -> "VerifiedCertificateOverlay":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def recover_verified_overlay(
    path: str | os.PathLike[str],
    dag: ProofDAG,
) -> OverlayRecoveryResult:
    """Durably preserve and then truncate only an incomplete physical tail.

    Format 1.0 cannot distinguish a genuinely torn final write from upward
    bit corruption in that final frame's length field.  Recovery therefore
    preserves the *entire* suspect suffix in a content-addressed, fsynced
    sidecar before truncation.  A complete invalid frame, or any later
    independently valid frame, is never truncated.
    """

    overlay_path = Path(path)
    writer_lock = _SidecarWriterLock(overlay_path)
    try:
        writer_lock.acquire()
    except FrontierWriterLockedError as exc:
        raise VerifiedOverlayWriterLockedError(
            f"another writer owns verified-overlay lock {writer_lock.path}"
        ) from exc
    try:
        try:
            stream = overlay_path.open("r+b", buffering=0)
        except OSError as exc:
            raise VerifiedOverlayRecoveryError(
                f"cannot open overlay for recovery: {exc}"
            ) from exc
        with stream:
            # Scan, preserve, and truncate the same retained file description.
            # Size equality alone is not sufficient against a same-size path
            # replacement between the read-only scan and destructive open.
            try:
                if not os.path.samestat(os.stat(overlay_path), os.fstat(stream.fileno())):
                    raise VerifiedOverlayRecoveryError(
                        "overlay path changed before recovery scan"
                    )
            except OSError as exc:
                raise VerifiedOverlayRecoveryError(
                    f"cannot bind recovery path to open overlay: {exc}"
                ) from exc
            before = _scan_verified_overlay_stream(overlay_path, stream, dag)
            try:
                if not os.path.samestat(os.stat(overlay_path), os.fstat(stream.fileno())):
                    raise VerifiedOverlayRecoveryError(
                        "overlay path changed during recovery scan"
                    )
            except OSError as exc:
                raise VerifiedOverlayRecoveryError(
                    f"cannot rebind recovery path after scan: {exc}"
                ) from exc
            if before.valid:
                return OverlayRecoveryResult(before, before, 0)
            assert before.issue is not None
            if before.header is None or not before.issue.recoverable_tail:
                raise VerifiedOverlayRecoveryError(
                    f"cannot truncate overlay for {before.issue.code}: "
                    f"{before.issue.message}"
                )
            if os.fstat(stream.fileno()).st_size != before.file_size:
                raise VerifiedOverlayRecoveryError(
                    "overlay changed after the recovery scan"
                )
            try:
                recovery_path, recovery_sha256 = _preserve_invalid_suffix(
                    overlay_path,
                    stream,
                    start_offset=before.last_good_offset,
                    file_size=before.file_size,
                )
            except (FrontierRecoveryError, OSError) as exc:
                raise VerifiedOverlayRecoveryError(
                    f"cannot preserve corrupt overlay suffix: {exc}"
                ) from exc
            stream.truncate(before.last_good_offset)
            stream.flush()
            os.fsync(stream.fileno())
            try:
                if not os.path.samestat(os.stat(overlay_path), os.fstat(stream.fileno())):
                    raise VerifiedOverlayRecoveryError(
                        "overlay path changed during recovery"
                    )
            except OSError as exc:
                raise VerifiedOverlayRecoveryError(
                    f"cannot rebind recovery path after truncation: {exc}"
                ) from exc
            after = _scan_verified_overlay_stream(overlay_path, stream, dag)
            after.require_valid()
            return OverlayRecoveryResult(
                before,
                after,
                before.file_size - before.last_good_offset,
                recovery_path,
                recovery_sha256,
            )
    finally:
        writer_lock.release()


__all__ = [
    "AuditedOverlayRecord",
    "AuditedOverlaySnapshot",
    "CERTIFICATE_ENCODING",
    "CERTIFICATE_VERIFIER_PROFILE",
    "OVERLAY_FORMAT_MAJOR",
    "OVERLAY_FORMAT_MINOR",
    "OVERLAY_HEAD_COMMITMENT_SCHEMA",
    "OVERLAY_RECORD_COMMITMENT_SCHEMA",
    "OVERLAY_RECORD_SCHEMA",
    "OverlayAppendResult",
    "OverlayEntry",
    "OverlayHeader",
    "OverlayIssue",
    "OverlayHeadCommitment",
    "OverlayRecordCommitment",
    "OverlayRecoveryResult",
    "OverlayScanResult",
    "VerifiedCertificateBinding",
    "VerifiedCertificateOverlay",
    "VerifiedOverlayCommitError",
    "VerifiedOverlayConflictError",
    "VerifiedOverlayError",
    "VerifiedOverlayHeadMismatchError",
    "VerifiedOverlayIntegrityError",
    "VerifiedOverlayReferenceError",
    "VerifiedOverlayRecoveryError",
    "VerifiedOverlayWriterLockedError",
    "recover_verified_overlay",
    "verify_verified_overlay",
]
