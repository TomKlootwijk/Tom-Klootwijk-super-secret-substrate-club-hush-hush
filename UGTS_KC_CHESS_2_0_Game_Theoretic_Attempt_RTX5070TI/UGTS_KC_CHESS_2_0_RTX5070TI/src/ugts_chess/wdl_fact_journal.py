"""Unified major-v2 journal for verified seed and derived WDL facts.

Version 1 of the verified overlay embeds a complete standalone WDL bundle in
every record.  That is an excellent portable authority boundary, but copying
child proof subgraphs into every parent is not solution-scale.  This module
defines a separate major-v2 journal.  A v2 fact is either:

* ``seed`` -- one independently verified canonical v2 WDL bundle; or
* ``derivation`` -- a compact one-hop proof referencing exact *earlier* v2
  facts by both contiguous record index and full record-content SHA-256.

The journal never resolves a dependency by node id or "latest value".  Replay
is strictly forward, while derivation references are strictly backward, so a
fact is visible only after every dependency has already passed independent
replay.  Exact DAG edge occurrences bind each move action; distinct UCI
actions remain distinct even when they transpose to one child node.

Physical framing follows the proven v1 discipline but uses new magic/version
bytes.  Every append is canonical JSON protected by SHA-256, CRC32 and a
payload hash chain, fsynced, and then fully read back through the retained file
descriptor.  Recovery first preserves an incomplete suffix in a durable
content-addressed sidecar.  Structurally complete invalid frames are never
truncated.  As with v1, upward corruption of the final length field is
indistinguishable from an incomplete write; explicit recovery preserves that
entire suspect suffix before truncating the active journal.

Like any local append-only file without an external witness, a clean rollback
to an earlier valid prefix cannot be detected from the file alone.  Persist a
:class:`FactJournalHead` outside the journal and require it on later opens.
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
from typing import Any, BinaryIO, Iterator, Mapping, Sequence
import zlib

from .frontier import (
    FrontierRecoveryError,
    FrontierWriterLockedError,
    _SidecarWriterLock,
    _fsync_parent_directory,
    _preserve_invalid_suffix,
    _write_all,
)
from .game_state import (
    RULE_PROFILE_ID,
    automatic_status,
    current_claim_actions,
    game_state_sha256,
    intended_move_claims,
    validate_history_reachability,
)
from .game_theory import WDL
from .hashing import canonical_json_bytes
from .proof_dag import (
    DAGEdge,
    DAGNode,
    ProofDAG,
    ProofDAGError,
    node_identity_sha256,
)
from .rules import apply_move, legal_moves
from .verified_overlay import (
    CERTIFICATE_ENCODING,
    MAX_CERTIFICATE_BYTES,
    VerifiedCertificateOverlay,
    _authoritative_first_frontier_content,
    _verify_certificate_for_node,
)
from .wdl import invert_child


FACT_FORMAT_MAJOR = 2
FACT_FORMAT_MINOR = 0
FACT_RECORD_SCHEMA = "ugts-chess-verified-wdl-fact-2.0"
FACT_HEAD_SCHEMA = "ugts-chess-wdl-fact-journal-head-2.0"
SEED_EVIDENCE_SCHEMA = "ugts-chess-wdl-seed-evidence-1.0"
DERIVATION_EVIDENCE_SCHEMA = "ugts-chess-wdl-derivation-evidence-1.0"
SEED_VERIFIER_PROFILE = "ugts-chess-wdl-bundle-seed-verifier-1.0"
DERIVATION_VERIFIER_PROFILE = "ugts-chess-wdl-fact-derivation-verifier-1.0"

FILE_MAGIC = b"UGTSWF02"
RECORD_MAGIC = b"UWF2"
MAX_RULE_PROFILE_BYTES = 4096
MAX_DERIVATION_EVIDENCE_BYTES = 16 * 1024 * 1024
MAX_FACT_PAYLOAD_BYTES = 768 * 1024 * 1024
MAX_DERIVATION_DEPENDENCIES = 512
MAX_PROOF_HEIGHT = 2**31 - 1

_HEADER_PREFIX = struct.Struct(">8sHHI")
_RECORD_PREFIX = struct.Struct(">4sQ")
_CRC32 = struct.Struct(">I")
_SHA256_SIZE = 32

HEADER_PREFIX_SIZE = _HEADER_PREFIX.size
RECORD_PREFIX_SIZE = _RECORD_PREFIX.size
RECORD_SHA256_SIZE = _SHA256_SIZE
RECORD_CRC32_SIZE = _CRC32.size

_FACT_KEYS = frozenset(
    {
        "schema",
        "record_index",
        "previous_fact_sha256",
        "kind",
        "node_sha256",
        "first_frontier_content_sha256",
        "rule_profile_id",
        "fen",
        "history_counts",
        "position_sha256",
        "game_state_sha256",
        "claimed_wdl",
        "proof_height",
        "evidence_sha256",
        "evidence",
    }
)
_SEED_KEYS = frozenset(
    {
        "schema",
        "certificate_encoding",
        "certificate_size",
        "certificate_sha256",
        "certificate_base64",
        "root_certificate_hash",
        "verifier_profile",
        "verifier_result",
    }
)
_DERIVATION_KEYS = frozenset(
    {
        "schema",
        "root_value",
        "proof_height",
        "derivation_code",
        "move_dependencies",
    }
)
_DEPENDENCY_KEYS = frozenset(
    {
        "uci",
        "dag_edge_record_index",
        "dag_edge_content_sha256",
        "child_node_sha256",
        "fact_record_index",
        "fact_content_sha256",
        "child_wdl",
        "child_proof_height",
    }
)
_AUTOMATIC_CODES = frozenset(
    {
        "checkmate",
        "stalemate",
        "dead_position",
        "seventy_five_move",
        "fivefold_repetition",
    }
)
_DERIVATION_CODES = _AUTOMATIC_CODES | {
    "winning_move_witness",
    "all_legal_moves_lose",
    "draw_action_and_no_winning_move",
}


class WDLFactJournalError(Exception):
    """Base class for v2 fact-journal failures."""


class WDLFactJournalIntegrityError(WDLFactJournalError):
    """Raised when a complete journal replay fails closed."""

    def __init__(self, report: "FactScanResult") -> None:
        self.report = report
        issue = report.issue
        detail = "unknown integrity failure" if issue is None else issue.message
        super().__init__(
            f"WDL fact-journal integrity failure at byte {report.failure_offset}; "
            f"last good byte {report.last_good_offset}: {detail}"
        )


class WDLFactJournalRecoveryError(WDLFactJournalError):
    """Raised when an invalid journal cannot be safely recovered."""


class WDLFactJournalWriterLockedError(WDLFactJournalError):
    """Raised when another process owns the journal writer lock."""


class WDLFactConflictError(WDLFactJournalError):
    """Raised when one exact DAG node is offered different evidence."""


class WDLFactCommitError(WDLFactJournalError):
    """Raised after a durable append cannot be replayed exactly."""


class WDLFactRollbackError(WDLFactJournalError):
    """Raised when an external head is absent from the live journal prefix."""


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


def _require_nonnegative_int(
    value: object,
    *,
    label: str,
    maximum: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    if maximum is not None and value > maximum:
        raise ValueError(f"{label} exceeds maximum {maximum}")
    return value


def _freeze_json(value: Any, *, where: str = "evidence") -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        raise ValueError(f"{where} may not contain floating-point values")
    if isinstance(value, list):
        return tuple(
            _freeze_json(item, where=f"{where}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{where} object keys must be strings")
        return MappingProxyType(
            {
                key: _freeze_json(item, where=f"{where}.{key}")
                for key, item in value.items()
            }
        )
    raise ValueError(f"{where} contains unsupported JSON type {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _history_from_payload(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, list):
        raise ValueError("fact history_counts must be a list")
    pairs: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("fact history entry must be a two-item list")
        key, count = item
        if not _is_sha256_hex(key):
            raise ValueError("fact history key is not lowercase SHA-256")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
            raise ValueError("fact history count must be an integer in 1..5")
        pairs.append((key, count))
    if pairs != sorted(pairs) or len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("fact history entries must be unique and sorted")
    return tuple(pairs)


def _crc32(parts: Sequence[bytes]) -> int:
    value = 0
    for part in parts:
        value = zlib.crc32(part, value)
    return value & 0xFFFFFFFF


@dataclass(frozen=True, slots=True)
class VerifiedWDLFact:
    """One exact seed or backward-referenced derived WDL fact."""

    record_index: int
    previous_fact_sha256: str | None
    kind: str
    node_sha256: str
    first_frontier_content_sha256: str
    rule_profile_id: str
    fen: str
    history_counts: tuple[tuple[str, int], ...]
    position_sha256: str
    game_state_sha256: str
    claimed_wdl: WDL
    proof_height: int
    evidence_sha256: str
    evidence: Any
    verifier_profile: str
    verifier_result: Mapping[str, object]
    seed_certificate_bytes: bytes | None = None

    def payload_record(self) -> dict[str, object]:
        return {
            "schema": FACT_RECORD_SCHEMA,
            "record_index": self.record_index,
            "previous_fact_sha256": self.previous_fact_sha256,
            "kind": self.kind,
            "node_sha256": self.node_sha256,
            "first_frontier_content_sha256": self.first_frontier_content_sha256,
            "rule_profile_id": self.rule_profile_id,
            "fen": self.fen,
            "history_counts": [[key, count] for key, count in self.history_counts],
            "position_sha256": self.position_sha256,
            "game_state_sha256": self.game_state_sha256,
            "claimed_wdl": self.claimed_wdl.value,
            "proof_height": self.proof_height,
            "evidence_sha256": self.evidence_sha256,
            "evidence": _thaw_json(self.evidence),
        }

    def payload_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload_record())


@dataclass(frozen=True, slots=True)
class FactEntry:
    record_index: int
    frame_offset: int
    frame_end_offset: int
    payload_offset: int
    payload_length: int
    sha256_offset: int
    crc32_offset: int
    content_sha256: str
    crc32: int
    fact: VerifiedWDLFact


@dataclass(frozen=True, slots=True)
class FactHeader:
    format_major: int
    format_minor: int
    rule_profile_id: str
    header_size: int


@dataclass(frozen=True, slots=True)
class FactIssue:
    code: str
    offset: int
    message: str
    recoverable_tail: bool
    expected_bytes: int | None = None
    actual_bytes: int | None = None


@dataclass(frozen=True, slots=True)
class FactScanResult:
    path: Path
    file_size: int
    header: FactHeader | None
    record_count: int
    last_good_offset: int
    entries: tuple[FactEntry, ...] = ()
    issue: FactIssue | None = None

    @property
    def valid(self) -> bool:
        return self.issue is None

    @property
    def failure_offset(self) -> int | None:
        return None if self.issue is None else self.issue.offset

    def require_valid(self) -> "FactScanResult":
        if self.issue is not None:
            raise WDLFactJournalIntegrityError(self)
        return self


@dataclass(frozen=True, slots=True)
class FactRecoveryResult:
    before: FactScanResult
    after: FactScanResult
    truncated_bytes: int
    preserved_suffix_path: Path | None = None
    preserved_suffix_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class FactAppendResult:
    entry: FactEntry
    appended: bool


@dataclass(frozen=True, slots=True)
class FactJournalHead:
    """Externally retainable rollback witness for one verified prefix."""

    rule_profile_id: str
    record_count: int
    head_content_sha256: str | None
    file_size: int

    def record(self) -> dict[str, object]:
        return {
            "schema": FACT_HEAD_SCHEMA,
            "rule_profile_id": self.rule_profile_id,
            "record_count": self.record_count,
            "head_content_sha256": self.head_content_sha256,
            "file_size": self.file_size,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @classmethod
    def from_bytes(cls, value: bytes | bytearray | memoryview) -> "FactJournalHead":
        snapshot = bytes(value)
        try:
            raw = json.loads(snapshot)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(f"fact-head snapshot is not UTF-8 JSON: {exc}") from exc
        if not isinstance(raw, dict) or canonical_json_bytes(raw) != snapshot:
            raise ValueError("fact-head snapshot is not a canonical JSON object")
        if set(raw) != {
            "schema",
            "rule_profile_id",
            "record_count",
            "head_content_sha256",
            "file_size",
        }:
            raise ValueError("fact-head snapshot has missing or unexpected fields")
        if raw.get("schema") != FACT_HEAD_SCHEMA:
            raise ValueError("fact-head snapshot schema mismatch")
        if raw.get("rule_profile_id") != RULE_PROFILE_ID:
            raise ValueError("fact-head snapshot rule profile mismatch")
        count = _require_nonnegative_int(raw.get("record_count"), label="record_count")
        size = _require_nonnegative_int(raw.get("file_size"), label="file_size")
        head = raw.get("head_content_sha256")
        if (count == 0) != (head is None):
            raise ValueError("fact-head hash presence does not match record count")
        if head is not None:
            head = _require_sha256(head, label="fact-head content hash")
        result = cls(RULE_PROFILE_ID, count, head, size)
        if result.canonical_bytes() != snapshot:
            raise ValueError("fact-head snapshot differs from exact reconstruction")
        return result


@dataclass(frozen=True, slots=True)
class FactMigrationResult:
    source_record_count: int
    imported_count: int
    already_present_count: int
    source_head_content_sha256: str | None
    destination_head: FactJournalHead


def _issue(
    code: str,
    offset: int,
    message: str,
    *,
    recoverable_tail: bool,
    expected_bytes: int | None = None,
    actual_bytes: int | None = None,
) -> FactIssue:
    return FactIssue(
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
        FACT_FORMAT_MAJOR,
        FACT_FORMAT_MINOR,
        len(profile),
    )
    return prefix + profile + _CRC32.pack(_crc32((prefix, profile)))


def _read_header(
    stream: BinaryIO,
    file_size: int,
) -> tuple[FactHeader | None, FactIssue | None]:
    stream.seek(0)
    prefix = stream.read(min(HEADER_PREFIX_SIZE, file_size))
    if len(prefix) != HEADER_PREFIX_SIZE:
        return None, _issue(
            "torn_header",
            0,
            "incomplete WDL fact-journal header",
            recoverable_tail=False,
            expected_bytes=HEADER_PREFIX_SIZE,
            actual_bytes=len(prefix),
        )
    magic, major, minor, profile_length = _HEADER_PREFIX.unpack(prefix)
    if magic != FILE_MAGIC:
        return None, _issue(
            "file_magic_mismatch",
            0,
            "WDL fact-journal magic does not match",
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
            "incomplete WDL fact-journal header body",
            recoverable_tail=False,
            expected_bytes=remaining_size,
            actual_bytes=len(remaining),
        )
    profile_bytes = remaining[:profile_length]
    stored_crc = _CRC32.unpack(remaining[profile_length:])[0]
    if stored_crc != _crc32((prefix, profile_bytes)):
        return None, _issue(
            "header_crc32_mismatch",
            HEADER_PREFIX_SIZE + profile_length,
            "WDL fact-journal header CRC32 mismatch",
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
    header = FactHeader(
        major,
        minor,
        profile,
        HEADER_PREFIX_SIZE + remaining_size,
    )
    if major != FACT_FORMAT_MAJOR or minor > FACT_FORMAT_MINOR:
        return header, _issue(
            "unsupported_format_version",
            8,
            f"unsupported WDL fact-journal format {major}.{minor}",
            recoverable_tail=False,
        )
    if profile != RULE_PROFILE_ID:
        return header, _issue(
            "rule_profile_mismatch",
            HEADER_PREFIX_SIZE,
            f"unsupported WDL fact-journal rule profile {profile!r}",
            recoverable_tail=False,
        )
    return header, None


def _bundle_proof_height(bundle: Mapping[str, object]) -> int:
    """Return the longest retained move-reference path in a verified bundle."""

    raw_nodes = bundle.get("nodes")
    root_hash = bundle.get("root_certificate_hash")
    if not isinstance(raw_nodes, list) or not isinstance(root_hash, str):
        raise ValueError("verified seed bundle has malformed graph fields")
    by_hash: dict[str, Mapping[str, object]] = {}
    ordered: list[tuple[int, str, Mapping[str, object]]] = []
    for raw in raw_nodes:
        if not isinstance(raw, Mapping):
            raise ValueError("verified seed bundle contains a non-object node")
        certificate_hash = _require_sha256(
            raw.get("certificate_hash"),
            label="seed node certificate hash",
        )
        if certificate_hash in by_hash:
            raise ValueError("verified seed bundle contains duplicate node hashes")
        depth = _require_nonnegative_int(
            raw.get("depth_remaining"),
            label="seed node depth",
        )
        by_hash[certificate_hash] = raw
        ordered.append((depth, certificate_hash, raw))
    if root_hash not in by_hash:
        raise ValueError("verified seed root certificate is missing")

    heights: dict[str, int] = {}
    for _, certificate_hash, record in sorted(ordered):
        raw_children = record.get("children")
        if not isinstance(raw_children, list):
            raise ValueError("verified seed node children are malformed")
        child_heights: list[int] = []
        for child in raw_children:
            if not isinstance(child, Mapping):
                raise ValueError("verified seed child is malformed")
            child_hash = child.get("child_certificate_hash")
            if child_hash is None:
                continue
            if not isinstance(child_hash, str) or child_hash not in heights:
                raise ValueError("verified seed graph is cyclic or not depth-decreasing")
            child_heights.append(heights[child_hash])
        height = 0 if not child_heights else 1 + max(child_heights)
        if height > MAX_PROOF_HEIGHT:
            raise ValueError("verified seed proof height exceeds the maximum")
        heights[certificate_hash] = height
    return heights[root_hash]


def _strict_seed_evidence(
    raw: object,
    *,
    dag: ProofDAG,
    node_sha256: str,
) -> tuple[
    dict[str, object],
    DAGNode,
    str,
    WDL,
    int,
    str,
    dict[str, object],
    bytes,
]:
    if not isinstance(raw, dict) or set(raw) != _SEED_KEYS:
        raise ValueError("seed evidence has missing or unexpected fields")
    if raw.get("schema") != SEED_EVIDENCE_SCHEMA:
        raise ValueError("seed evidence schema mismatch")
    if raw.get("certificate_encoding") != CERTIFICATE_ENCODING:
        raise ValueError("seed certificate encoding mismatch")
    if raw.get("verifier_profile") != SEED_VERIFIER_PROFILE:
        raise ValueError("seed verifier profile mismatch")
    size = _require_nonnegative_int(
        raw.get("certificate_size"),
        label="seed certificate size",
        maximum=MAX_CERTIFICATE_BYTES,
    )
    if size == 0:
        raise ValueError("seed certificate may not be empty")
    stored_sha256 = _require_sha256(
        raw.get("certificate_sha256"),
        label="seed certificate hash",
    )
    stored_root_hash = _require_sha256(
        raw.get("root_certificate_hash"),
        label="seed root certificate hash",
    )
    encoded = raw.get("certificate_base64")
    if not isinstance(encoded, str):
        raise ValueError("seed certificate is not base64 text")
    try:
        certificate_bytes = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ValueError("seed certificate base64 is invalid") from exc
    if len(certificate_bytes) != size:
        raise ValueError("seed certificate byte count mismatch")
    if base64.b64encode(certificate_bytes).decode("ascii") != encoded:
        raise ValueError("seed certificate base64 is not canonical")
    if hashlib.sha256(certificate_bytes).hexdigest() != stored_sha256:
        raise ValueError("seed certificate SHA-256 mismatch")

    node, frontier_hash, claimed_wdl, root_hash, result, bundle = (
        _verify_certificate_for_node(dag, node_sha256, certificate_bytes)
    )
    if root_hash != stored_root_hash:
        raise ValueError("seed root certificate hash mismatch")
    stored_result = raw.get("verifier_result")
    if (
        not isinstance(stored_result, dict)
        or canonical_json_bytes(stored_result) != canonical_json_bytes(result)
    ):
        raise ValueError("seed verifier result does not match independent replay")
    proof_height = _bundle_proof_height(bundle)
    reconstructed = {
        "schema": SEED_EVIDENCE_SCHEMA,
        "certificate_encoding": CERTIFICATE_ENCODING,
        "certificate_size": len(certificate_bytes),
        "certificate_sha256": stored_sha256,
        "certificate_base64": base64.b64encode(certificate_bytes).decode("ascii"),
        "root_certificate_hash": root_hash,
        "verifier_profile": SEED_VERIFIER_PROFILE,
        "verifier_result": dict(result),
    }
    if canonical_json_bytes(reconstructed) != canonical_json_bytes(raw):
        raise ValueError("seed evidence differs from exact reconstruction")
    return (
        reconstructed,
        node,
        frontier_hash,
        claimed_wdl,
        proof_height,
        root_hash,
        dict(result),
        certificate_bytes,
    )


def _strict_derivation_structure(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict) or set(raw) != _DERIVATION_KEYS:
        raise ValueError("derivation evidence has missing or unexpected fields")
    if raw.get("schema") != DERIVATION_EVIDENCE_SCHEMA:
        raise ValueError("derivation evidence schema mismatch")
    root_value_raw = raw.get("root_value")
    try:
        root_value = WDL(root_value_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("derivation root_value is invalid") from exc
    if root_value == WDL.UNKNOWN:
        raise ValueError("UNKNOWN cannot be a derivation fact")
    proof_height = _require_nonnegative_int(
        raw.get("proof_height"),
        label="derivation proof_height",
        maximum=MAX_PROOF_HEIGHT,
    )
    code = raw.get("derivation_code")
    if not isinstance(code, str) or code not in _DERIVATION_CODES:
        raise ValueError("derivation code is unsupported")
    dependencies = raw.get("move_dependencies")
    if not isinstance(dependencies, list):
        raise ValueError("derivation move_dependencies must be a list")
    if len(dependencies) > MAX_DERIVATION_DEPENDENCIES:
        raise ValueError("derivation dependency count exceeds the maximum")

    normalized_dependencies: list[dict[str, object]] = []
    seen_uci: set[str] = set()
    for dependency in dependencies:
        if not isinstance(dependency, dict) or set(dependency) != _DEPENDENCY_KEYS:
            raise ValueError("derivation dependency has missing or unexpected fields")
        uci = dependency.get("uci")
        if not isinstance(uci, str) or not uci or uci in seen_uci:
            raise ValueError("derivation dependency UCI is invalid or duplicate")
        seen_uci.add(uci)
        edge_index = _require_nonnegative_int(
            dependency.get("dag_edge_record_index"),
            label="DAG edge record index",
        )
        edge_hash = _require_sha256(
            dependency.get("dag_edge_content_sha256"),
            label="DAG edge content hash",
        )
        child_node_sha256 = _require_sha256(
            dependency.get("child_node_sha256"),
            label="dependency child node hash",
        )
        fact_index = _require_nonnegative_int(
            dependency.get("fact_record_index"),
            label="dependency fact record index",
        )
        fact_hash = _require_sha256(
            dependency.get("fact_content_sha256"),
            label="dependency fact content hash",
        )
        try:
            child_wdl = WDL(dependency.get("child_wdl"))
        except (TypeError, ValueError) as exc:
            raise ValueError("dependency child WDL is invalid") from exc
        if child_wdl == WDL.UNKNOWN:
            raise ValueError("dependency child WDL may not be UNKNOWN")
        child_height = _require_nonnegative_int(
            dependency.get("child_proof_height"),
            label="dependency child proof height",
            maximum=MAX_PROOF_HEIGHT,
        )
        normalized_dependencies.append(
            {
                "uci": uci,
                "dag_edge_record_index": edge_index,
                "dag_edge_content_sha256": edge_hash,
                "child_node_sha256": child_node_sha256,
                "fact_record_index": fact_index,
                "fact_content_sha256": fact_hash,
                "child_wdl": child_wdl.value,
                "child_proof_height": child_height,
            }
        )
    if [item["uci"] for item in normalized_dependencies] != sorted(seen_uci):
        raise ValueError("derivation dependencies are not in canonical UCI order")
    normalized = {
        "schema": DERIVATION_EVIDENCE_SCHEMA,
        "root_value": root_value.value,
        "proof_height": proof_height,
        "derivation_code": code,
        "move_dependencies": normalized_dependencies,
    }
    if canonical_json_bytes(normalized) != canonical_json_bytes(raw):
        raise ValueError("derivation evidence differs from exact reconstruction")
    return normalized


def canonical_derivation_evidence_bytes(
    *,
    root_value: WDL | str,
    proof_height: int,
    derivation_code: str,
    move_dependencies: Sequence[Mapping[str, object]],
) -> bytes:
    """Build strict, deterministically UCI-sorted derivation evidence bytes."""

    value = root_value.value if isinstance(root_value, WDL) else root_value
    dependencies = [dict(item) for item in move_dependencies]
    dependencies.sort(key=lambda item: str(item.get("uci", "")))
    raw: dict[str, object] = {
        "schema": DERIVATION_EVIDENCE_SCHEMA,
        "root_value": value,
        "proof_height": proof_height,
        "derivation_code": derivation_code,
        "move_dependencies": dependencies,
    }
    normalized = _strict_derivation_structure(raw)
    encoded = canonical_json_bytes(normalized)
    if len(encoded) > MAX_DERIVATION_EVIDENCE_BYTES:
        raise ValueError("derivation evidence exceeds the byte-size maximum")
    return encoded


@dataclass(frozen=True, slots=True)
class _ExactMoveOccurrence:
    uci: str
    edge: DAGEdge
    child: DAGNode


def _exact_outgoing_occurrences(
    dag: ProofDAG,
    node: DAGNode,
) -> tuple[tuple[str, ...], dict[str, _ExactMoveOccurrence]]:
    """Replay every occurrence and select the earliest exact edge per UCI."""

    moves = sorted(legal_moves(node.position), key=lambda move: move.uci())
    legal_uci = tuple(move.uci() for move in moves)
    by_uci = {move.uci(): move for move in moves}
    expected: dict[str, tuple[str, object, object]] = {}
    for move in moves:
        child_position = apply_move(node.position, move)
        child_history = node.history.push(child_position)
        expected[move.uci()] = (
            node_identity_sha256(
                child_position,
                child_history,
                rule_profile_id=node.rule_profile_id,
            ),
            child_position,
            child_history,
        )

    occurrences: dict[str, list[_ExactMoveOccurrence]] = {}
    node_cache: dict[str, DAGNode] = {}
    for edge in dag.outgoing_edges(node.node_sha256):
        action = edge.action
        if (
            not isinstance(action, dict)
            or set(action) != {"kind", "uci"}
            or action.get("kind") != "move"
            or not isinstance(action.get("uci"), str)
        ):
            raise ValueError("outgoing DAG occurrence is not a canonical move action")
        uci = action["uci"]
        if uci not in by_uci:
            raise ValueError(f"outgoing DAG occurrence names illegal move {uci!r}")
        expected_sha, child_position, child_history = expected[uci]
        child = node_cache.get(edge.child_node_sha256)
        if child is None:
            child = dag.get_node(edge.child_node_sha256)
            if child is None:
                raise ValueError("outgoing DAG occurrence references an absent child")
            node_cache[child.node_sha256] = child
        if (
            edge.parent_node_sha256 != node.node_sha256
            or child.node_sha256 != expected_sha
            or child.position != child_position
            or child.fen != child_position.to_fen()  # type: ignore[union-attr]
            or child.history != child_history
            or child.rule_profile_id != node.rule_profile_id
            or child.game_state_sha256
            != game_state_sha256(child_position, child_history)  # type: ignore[arg-type]
        ):
            raise ValueError(f"outgoing DAG occurrence for {uci} fails exact replay")
        occurrences.setdefault(uci, []).append(_ExactMoveOccurrence(uci, edge, child))

    canonical: dict[str, _ExactMoveOccurrence] = {}
    for uci, items in occurrences.items():
        child_hashes = {item.child.node_sha256 for item in items}
        if len(child_hashes) != 1:
            raise ValueError(f"duplicate DAG occurrences for {uci} are ambiguous")
        canonical[uci] = min(
            items,
            key=lambda item: (
                item.edge.frontier_record_index,
                item.edge.frontier_content_sha256,
            ),
        )
    return legal_uci, canonical


def _verify_derivation_for_node(
    dag: ProofDAG,
    node_sha256: str,
    evidence_bytes: bytes,
    *,
    prior_entries: Sequence[FactEntry],
    current_record_index: int,
) -> tuple[
    dict[str, object],
    DAGNode,
    str,
    WDL,
    int,
    dict[str, object],
]:
    if len(evidence_bytes) > MAX_DERIVATION_EVIDENCE_BYTES:
        raise ValueError("derivation evidence exceeds the byte-size maximum")
    try:
        decoded = json.loads(evidence_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"derivation evidence is not UTF-8 JSON: {exc}") from exc
    if not isinstance(decoded, dict) or canonical_json_bytes(decoded) != evidence_bytes:
        raise ValueError("derivation evidence is not canonical bare JSON")
    evidence = _strict_derivation_structure(decoded)
    node_sha256 = _require_sha256(node_sha256, label="target DAG node hash")
    node = dag.get_node(node_sha256)
    if node is None:
        raise ValueError("derivation references an unknown DAG node")
    if node.rule_profile_id != RULE_PROFILE_ID or node.wdl != WDL.UNKNOWN:
        raise ValueError("target DAG node is not canonical authoritative UNKNOWN")
    validate_history_reachability(node.position, node.history)
    frontier_hash = _authoritative_first_frontier_content(dag, node)

    legal_uci, occurrence_by_uci = _exact_outgoing_occurrences(dag, node)
    moves_by_uci = {
        move.uci(): move
        for move in sorted(legal_moves(node.position), key=lambda move: move.uci())
    }
    automatic = automatic_status(node.position, node.history)
    current_claims = current_claim_actions(node.position, node.history)
    root_value = WDL(str(evidence["root_value"]))
    stored_height = int(evidence["proof_height"])
    code = str(evidence["derivation_code"])
    dependencies = evidence["move_dependencies"]
    assert isinstance(dependencies, list)

    resolved: dict[str, tuple[FactEntry, _ExactMoveOccurrence]] = {}
    for dependency in dependencies:
        assert isinstance(dependency, dict)
        uci = str(dependency["uci"])
        occurrence = occurrence_by_uci.get(uci)
        if occurrence is None:
            raise ValueError(f"derivation move {uci!r} lacks an exact DAG occurrence")
        if (
            dependency["dag_edge_record_index"]
            != occurrence.edge.frontier_record_index
            or dependency["dag_edge_content_sha256"]
            != occurrence.edge.frontier_content_sha256
        ):
            raise ValueError(f"derivation move {uci!r} does not name its earliest DAG edge")
        if dependency["child_node_sha256"] != occurrence.child.node_sha256:
            raise ValueError(f"derivation move {uci!r} child-node identity mismatch")

        fact_index = int(dependency["fact_record_index"])
        if fact_index >= current_record_index or fact_index >= len(prior_entries):
            raise ValueError("derivation fact reference is not strictly backward")
        entry = prior_entries[fact_index]
        if entry.record_index != fact_index:
            raise ValueError("derivation fact reference index is not contiguous")
        if dependency["fact_content_sha256"] != entry.content_sha256:
            raise ValueError("derivation fact content hash mismatch")
        fact = entry.fact
        if fact.node_sha256 != occurrence.child.node_sha256:
            raise ValueError("derivation fact is bound to a different exact child node")
        if dependency["child_wdl"] != fact.claimed_wdl.value:
            raise ValueError("derivation child WDL differs from the referenced fact")
        if dependency["child_proof_height"] != fact.proof_height:
            raise ValueError("derivation child proof height differs from the referenced fact")
        resolved[uci] = (entry, occurrence)

    if automatic.terminal:
        if code != automatic.code or dependencies:
            raise ValueError("automatic terminal derivation has an invalid code or dependency")
        expected_value = WDL.LOSS if automatic.code == "checkmate" else WDL.DRAW
        if root_value != expected_value or stored_height != 0:
            raise ValueError("automatic terminal derivation has wrong WDL or proof height")
    else:
        if code in _AUTOMATIC_CODES:
            raise ValueError("nonterminal derivation uses an automatic terminal code")
        if not dependencies:
            raise ValueError("nonterminal derivation has no move dependencies")
        expected_height = 1 + max(entry.fact.proof_height for entry, _ in resolved.values())
        if expected_height > MAX_PROOF_HEIGHT or stored_height != expected_height:
            raise ValueError("derivation proof height does not match its dependencies")

        if code == "winning_move_witness":
            if len(dependencies) != 1 or root_value != WDL.WIN:
                raise ValueError("WIN derivation must contain exactly one move witness")
            only_entry = next(iter(resolved.values()))[0]
            if invert_child(only_entry.fact.claimed_wdl) != WDL.WIN:
                raise ValueError("WIN witness does not reference a child LOSS")
        else:
            if tuple(resolved) != legal_uci:
                raise ValueError("LOSS/DRAW derivation lacks complete canonical UCI coverage")
            converted = tuple(
                invert_child(resolved[uci][0].fact.claimed_wdl) for uci in legal_uci
            )
            has_draw_action = bool(current_claims)
            for uci in legal_uci:
                move = moves_by_uci[uci]
                child_position = apply_move(node.position, move)
                child_history = node.history.push(child_position)
                if intended_move_claims(child_position, child_history):
                    has_draw_action = True
            has_draw = has_draw_action or any(value == WDL.DRAW for value in converted)
            if code == "all_legal_moves_lose":
                if (
                    root_value != WDL.LOSS
                    or has_draw
                    or not converted
                    or not all(value == WDL.LOSS for value in converted)
                ):
                    raise ValueError("LOSS derivation fails complete aggregation")
            elif code == "draw_action_and_no_winning_move":
                if (
                    root_value != WDL.DRAW
                    or not converted
                    or any(value == WDL.WIN for value in converted)
                    or not has_draw
                ):
                    raise ValueError("DRAW derivation fails complete aggregation")
            else:
                raise ValueError("nonterminal derivation code is invalid")

    result: dict[str, object] = {
        "valid": True,
        "kind": "derivation",
        "root_value": root_value.value,
        "root_exact": True,
        "proof_height": stored_height,
        "derivation_code": code,
        "dependency_count": len(dependencies),
    }
    return evidence, node, frontier_hash, root_value, stored_height, result


def _new_seed_fact(
    dag: ProofDAG,
    *,
    node_sha256: str,
    certificate_bytes: bytes,
    record_index: int,
    previous_fact_sha256: str | None,
) -> VerifiedWDLFact:
    node, frontier_hash, claimed_wdl, root_hash, result, bundle = (
        _verify_certificate_for_node(dag, node_sha256, certificate_bytes)
    )
    proof_height = _bundle_proof_height(bundle)
    certificate_sha256 = hashlib.sha256(certificate_bytes).hexdigest()
    evidence: dict[str, object] = {
        "schema": SEED_EVIDENCE_SCHEMA,
        "certificate_encoding": CERTIFICATE_ENCODING,
        "certificate_size": len(certificate_bytes),
        "certificate_sha256": certificate_sha256,
        "certificate_base64": base64.b64encode(certificate_bytes).decode("ascii"),
        "root_certificate_hash": root_hash,
        "verifier_profile": SEED_VERIFIER_PROFILE,
        "verifier_result": dict(result),
    }
    evidence_bytes = canonical_json_bytes(evidence)
    return VerifiedWDLFact(
        record_index=record_index,
        previous_fact_sha256=previous_fact_sha256,
        kind="seed",
        node_sha256=node.node_sha256,
        first_frontier_content_sha256=frontier_hash,
        rule_profile_id=node.rule_profile_id,
        fen=node.fen,
        history_counts=node.history.counts,
        position_sha256=node.position_sha256,
        game_state_sha256=node.game_state_sha256,
        claimed_wdl=claimed_wdl,
        proof_height=proof_height,
        evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        evidence=_freeze_json(evidence),
        verifier_profile=SEED_VERIFIER_PROFILE,
        verifier_result=MappingProxyType(dict(result)),
        seed_certificate_bytes=certificate_bytes,
    )


def _new_derivation_fact(
    dag: ProofDAG,
    *,
    node_sha256: str,
    evidence_bytes: bytes,
    prior_entries: Sequence[FactEntry],
    record_index: int,
    previous_fact_sha256: str | None,
) -> VerifiedWDLFact:
    evidence, node, frontier_hash, claimed_wdl, proof_height, result = (
        _verify_derivation_for_node(
            dag,
            node_sha256,
            evidence_bytes,
            prior_entries=prior_entries,
            current_record_index=record_index,
        )
    )
    return VerifiedWDLFact(
        record_index=record_index,
        previous_fact_sha256=previous_fact_sha256,
        kind="derivation",
        node_sha256=node.node_sha256,
        first_frontier_content_sha256=frontier_hash,
        rule_profile_id=node.rule_profile_id,
        fen=node.fen,
        history_counts=node.history.counts,
        position_sha256=node.position_sha256,
        game_state_sha256=node.game_state_sha256,
        claimed_wdl=claimed_wdl,
        proof_height=proof_height,
        evidence_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        evidence=_freeze_json(evidence),
        verifier_profile=DERIVATION_VERIFIER_PROFILE,
        verifier_result=MappingProxyType(dict(result)),
    )


def _decode_fact(
    payload: bytes,
    dag: ProofDAG,
    *,
    expected_record_index: int,
    expected_previous_fact_sha256: str | None,
    prior_entries: Sequence[FactEntry],
) -> VerifiedWDLFact:
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"fact payload is not UTF-8 JSON: {exc}") from exc
    if not isinstance(raw, dict) or canonical_json_bytes(raw) != payload:
        raise ValueError("fact payload is not a canonical JSON object")
    if set(raw) != _FACT_KEYS:
        raise ValueError("fact record has missing or unexpected fields")
    if raw.get("schema") != FACT_RECORD_SCHEMA:
        raise ValueError("fact record schema mismatch")
    record_index = _require_nonnegative_int(
        raw.get("record_index"),
        label="fact record index",
    )
    if record_index != expected_record_index:
        raise ValueError("fact record index is not contiguous")
    if raw.get("previous_fact_sha256") != expected_previous_fact_sha256:
        raise ValueError("fact record hash chain is broken")
    if raw.get("rule_profile_id") != RULE_PROFILE_ID:
        raise ValueError("fact record rule profile mismatch")
    kind = raw.get("kind")
    if kind not in {"seed", "derivation"}:
        raise ValueError("fact record kind is unsupported")
    node_sha256 = _require_sha256(raw.get("node_sha256"), label="fact node hash")
    stored_frontier_hash = _require_sha256(
        raw.get("first_frontier_content_sha256"),
        label="fact first frontier hash",
    )
    stored_position_hash = _require_sha256(
        raw.get("position_sha256"),
        label="fact position hash",
    )
    stored_game_hash = _require_sha256(
        raw.get("game_state_sha256"),
        label="fact game-state hash",
    )
    stored_evidence_hash = _require_sha256(
        raw.get("evidence_sha256"),
        label="fact evidence hash",
    )
    history = _history_from_payload(raw.get("history_counts"))
    stored_height = _require_nonnegative_int(
        raw.get("proof_height"),
        label="fact proof height",
        maximum=MAX_PROOF_HEIGHT,
    )
    try:
        stored_wdl = WDL(raw.get("claimed_wdl"))
    except (TypeError, ValueError) as exc:
        raise ValueError("fact claimed WDL is invalid") from exc
    if stored_wdl == WDL.UNKNOWN:
        raise ValueError("UNKNOWN may not be stored as a verified fact")
    raw_evidence = raw.get("evidence")
    if not isinstance(raw_evidence, dict):
        raise ValueError("fact evidence is not an object")
    evidence_bytes = canonical_json_bytes(raw_evidence)
    if hashlib.sha256(evidence_bytes).hexdigest() != stored_evidence_hash:
        raise ValueError("fact evidence SHA-256 mismatch")

    seed_certificate_bytes: bytes | None = None
    if kind == "seed":
        (
            evidence,
            node,
            frontier_hash,
            claimed_wdl,
            proof_height,
            _,
            result,
            seed_certificate_bytes,
        ) = _strict_seed_evidence(
            raw_evidence,
            dag=dag,
            node_sha256=node_sha256,
        )
        verifier_profile = SEED_VERIFIER_PROFILE
    else:
        (
            evidence,
            node,
            frontier_hash,
            claimed_wdl,
            proof_height,
            result,
        ) = _verify_derivation_for_node(
            dag,
            node_sha256,
            evidence_bytes,
            prior_entries=prior_entries,
            current_record_index=expected_record_index,
        )
        verifier_profile = DERIVATION_VERIFIER_PROFILE

    if raw.get("fen") != node.fen:
        raise ValueError("fact exact FEN does not match the DAG node")
    if history != node.history.counts:
        raise ValueError("fact history does not match the DAG node")
    if stored_frontier_hash != frontier_hash:
        raise ValueError("fact first frontier content address is stale or forged")
    if stored_position_hash != node.position_sha256:
        raise ValueError("fact position hash does not match the DAG node")
    if stored_game_hash != node.game_state_sha256:
        raise ValueError("fact game-state hash does not match the DAG node")
    if stored_wdl != claimed_wdl:
        raise ValueError("fact claimed WDL does not match independent verification")
    if stored_height != proof_height:
        raise ValueError("fact proof height does not match independent verification")

    reconstructed = VerifiedWDLFact(
        record_index=expected_record_index,
        previous_fact_sha256=expected_previous_fact_sha256,
        kind=str(kind),
        node_sha256=node.node_sha256,
        first_frontier_content_sha256=frontier_hash,
        rule_profile_id=node.rule_profile_id,
        fen=node.fen,
        history_counts=node.history.counts,
        position_sha256=node.position_sha256,
        game_state_sha256=node.game_state_sha256,
        claimed_wdl=claimed_wdl,
        proof_height=proof_height,
        evidence_sha256=hashlib.sha256(canonical_json_bytes(evidence)).hexdigest(),
        evidence=_freeze_json(evidence),
        verifier_profile=verifier_profile,
        verifier_result=MappingProxyType(dict(result)),
        seed_certificate_bytes=seed_certificate_bytes,
    )
    if reconstructed.payload_bytes() != payload:
        raise ValueError("fact payload differs from exact reconstructed binding")
    return reconstructed


def _encode_frame(fact: VerifiedWDLFact) -> tuple[bytes, str, int]:
    payload = fact.payload_bytes()
    if len(payload) > MAX_FACT_PAYLOAD_BYTES:
        raise ValueError(
            f"fact payload is {len(payload)} bytes; maximum is "
            f"{MAX_FACT_PAYLOAD_BYTES}"
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
    if file_size - offset < RECORD_PREFIX_SIZE:
        return False
    stream.seek(offset)
    prefix = stream.read(RECORD_PREFIX_SIZE)
    magic, payload_length = _RECORD_PREFIX.unpack(prefix)
    if magic != RECORD_MAGIC or payload_length > MAX_FACT_PAYLOAD_BYTES:
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
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        return False
    return (
        isinstance(raw, dict)
        and canonical_json_bytes(raw) == payload
        and raw.get("schema") == FACT_RECORD_SCHEMA
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
    previous_fact_sha256: str | None,
    prior_entries: Sequence[FactEntry],
    scan_for_valid_suffix: bool = True,
) -> tuple[FactEntry | None, FactIssue | None]:
    start = stream.tell()
    if start == file_size:
        return None, None
    if start > file_size:
        return None, _issue(
            "record_offset_past_eof",
            start,
            "fact record offset is past EOF",
            recoverable_tail=False,
        )
    prefix = stream.read(min(RECORD_PREFIX_SIZE, file_size - start))
    if len(prefix) != RECORD_PREFIX_SIZE:
        return None, _issue(
            "torn_record_prefix",
            start,
            "incomplete WDL fact-record prefix",
            recoverable_tail=True,
            expected_bytes=RECORD_PREFIX_SIZE,
            actual_bytes=len(prefix),
        )
    magic, payload_length = _RECORD_PREFIX.unpack(prefix)
    if magic != RECORD_MAGIC:
        return None, _issue(
            "record_magic_mismatch",
            start,
            "WDL fact-record magic does not match",
            recoverable_tail=False,
        )
    if payload_length > MAX_FACT_PAYLOAD_BYTES:
        return None, _issue(
            "record_length_invalid",
            start + 4,
            f"fact payload length {payload_length} exceeds the maximum",
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
            "incomplete WDL fact-record body"
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
            "WDL fact-record CRC32 mismatch",
            recoverable_tail=False,
        )
    if digest != hashlib.sha256(payload).digest():
        return None, _issue(
            "record_sha256_mismatch",
            start,
            "WDL fact-record SHA-256 mismatch",
            recoverable_tail=False,
        )
    try:
        fact = _decode_fact(
            payload,
            dag,
            expected_record_index=record_index,
            expected_previous_fact_sha256=previous_fact_sha256,
            prior_entries=prior_entries,
        )
    except (ProofDAGError, RecursionError, TypeError, ValueError) as exc:
        return None, _issue(
            "record_semantic_invalid",
            start + RECORD_PREFIX_SIZE,
            f"WDL fact-record failed replay: {exc}",
            recoverable_tail=False,
        )
    end = start + RECORD_PREFIX_SIZE + body_size
    return (
        FactEntry(
            record_index=record_index,
            frame_offset=start,
            frame_end_offset=end,
            payload_offset=start + RECORD_PREFIX_SIZE,
            payload_length=payload_length,
            sha256_offset=start + RECORD_PREFIX_SIZE + payload_length,
            crc32_offset=end - RECORD_CRC32_SIZE,
            content_sha256=digest.hex(),
            crc32=stored_crc,
            fact=fact,
        ),
        None,
    )


def _scan_fact_stream(
    path: Path,
    stream: BinaryIO,
    dag: ProofDAG,
) -> FactScanResult:
    start_stat = os.fstat(stream.fileno())
    file_size = start_stat.st_size
    entries: list[FactEntry] = []
    header, header_issue = _read_header(stream, file_size)
    if header_issue is not None:
        return FactScanResult(path, file_size, header, 0, 0, issue=header_issue)
    assert header is not None
    last_good = header.header_size
    previous: str | None = None
    seen_nodes: set[str] = set()
    for record_index in range(2**63 - 1):
        stream.seek(last_good)
        entry, record_issue = _read_record(
            stream,
            file_size=file_size,
            dag=dag,
            record_index=record_index,
            previous_fact_sha256=previous,
            prior_entries=entries,
        )
        if record_issue is not None:
            return FactScanResult(
                path,
                file_size,
                header,
                len(entries),
                last_good,
                tuple(entries),
                record_issue,
            )
        if entry is None:
            break
        if entry.fact.node_sha256 in seen_nodes:
            issue = _issue(
                "duplicate_node_fact",
                entry.frame_offset,
                "journal contains a second fact for one exact DAG node",
                recoverable_tail=False,
            )
            return FactScanResult(
                path,
                file_size,
                header,
                len(entries),
                last_good,
                tuple(entries),
                issue,
            )
        seen_nodes.add(entry.fact.node_sha256)
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
            "WDL fact journal changed during replay",
            recoverable_tail=False,
        )
        return FactScanResult(
            path,
            file_size,
            header,
            len(entries),
            last_good,
            tuple(entries),
            issue,
        )
    return FactScanResult(
        path,
        file_size,
        header,
        len(entries),
        last_good,
        tuple(entries),
    )


def verify_wdl_fact_journal(
    path: str | os.PathLike[str],
    dag: ProofDAG,
) -> FactScanResult:
    """Fully replay a v2 fact journal against an open, audited ProofDAG."""

    journal_path = Path(path)
    try:
        with journal_path.open("rb", buffering=0) as stream:
            try:
                initially_same = os.path.samestat(
                    os.stat(journal_path),
                    os.fstat(stream.fileno()),
                )
            except OSError as exc:
                return FactScanResult(
                    journal_path,
                    os.fstat(stream.fileno()).st_size,
                    None,
                    0,
                    0,
                    issue=_issue(
                        "path_unavailable_before_read",
                        0,
                        f"cannot bind fact-journal path before replay: {exc}",
                        recoverable_tail=False,
                    ),
                )
            if not initially_same:
                return FactScanResult(
                    journal_path,
                    os.fstat(stream.fileno()).st_size,
                    None,
                    0,
                    0,
                    issue=_issue(
                        "path_replaced_before_read",
                        0,
                        "fact-journal path does not name the file opened for replay",
                        recoverable_tail=False,
                    ),
                )
            report = _scan_fact_stream(journal_path, stream, dag)
            try:
                same_file = os.path.samestat(
                    os.stat(journal_path),
                    os.fstat(stream.fileno()),
                )
            except OSError as exc:
                return FactScanResult(
                    journal_path,
                    report.file_size,
                    report.header,
                    report.record_count,
                    report.last_good_offset,
                    report.entries,
                    _issue(
                        "path_unavailable_after_read",
                        report.last_good_offset,
                        f"cannot rebind fact-journal path after replay: {exc}",
                        recoverable_tail=False,
                    ),
                )
            if not same_file:
                return FactScanResult(
                    journal_path,
                    report.file_size,
                    report.header,
                    report.record_count,
                    report.last_good_offset,
                    report.entries,
                    _issue(
                        "path_replaced_during_read",
                        report.last_good_offset,
                        "fact-journal path no longer names the replayed file",
                        recoverable_tail=False,
                    ),
                )
            return report
    except OSError as exc:
        return FactScanResult(
            journal_path,
            0,
            None,
            0,
            0,
            issue=_issue(
                "file_unavailable",
                0,
                f"WDL fact-journal file is unavailable: {exc}",
                recoverable_tail=False,
            ),
        )


class WDLFactJournal:
    """Exclusive append handle for unified seed and derivation facts."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        dag: ProofDAG,
        *,
        required_head: FactJournalHead | None = None,
    ) -> None:
        if not isinstance(dag, ProofDAG) or dag.closed:
            raise TypeError("dag must be an open ProofDAG")
        if dag.rule_profile_id != RULE_PROFILE_ID:
            raise ValueError("fact journal supports only the canonical rule profile")
        canonical_required: FactJournalHead | None = None
        if required_head is not None:
            if not isinstance(required_head, FactJournalHead):
                raise TypeError("required_head must be a FactJournalHead")
            canonical_required = FactJournalHead.from_bytes(
                required_head.canonical_bytes()
            )
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.dag = dag
        self._thread_lock = threading.Lock()
        self._writer_lock = _SidecarWriterLock(self.path)
        self.lock_path = self._writer_lock.path
        self._stream: BinaryIO | None = None
        self._failed = False
        self._entries: list[FactEntry] = []
        self._entries_by_node: dict[str, FactEntry] = {}
        try:
            self._writer_lock.acquire()
        except FrontierWriterLockedError as exc:
            raise WDLFactJournalWriterLockedError(
                f"another writer owns WDL fact-journal lock {self.lock_path}"
            ) from exc
        try:
            if (
                canonical_required is not None
                and canonical_required.record_count > 0
                and not self.path.exists()
            ):
                raise WDLFactRollbackError(
                    "externally anchored fact journal is missing"
                )
            header_bytes = _encode_header()
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

            self._stream = self.path.open("r+b", buffering=0)
            report = _scan_fact_stream(self.path, self._stream, self.dag)
            report.require_valid()
            self._entries = list(report.entries)
            self._entries_by_node = {
                entry.fact.node_sha256: entry for entry in report.entries
            }
            self._next_offset = report.file_size
            self._next_index = report.record_count
            self._previous_fact_sha256 = (
                None if not report.entries else report.entries[-1].content_sha256
            )
            self._require_path_matches_stream()
            if canonical_required is not None:
                self._require_head_in_report(canonical_required, report)
        except BaseException:
            if self._stream is not None:
                self._stream.close()
                self._stream = None
            self._writer_lock.release()
            raise

    @property
    def closed(self) -> bool:
        return self._stream is None or self._stream.closed

    def _require_path_matches_stream(self) -> None:
        assert self._stream is not None
        try:
            path_stat = os.stat(self.path)
            stream_stat = os.fstat(self._stream.fileno())
        except OSError as exc:
            raise WDLFactJournalError(
                f"cannot bind fact-journal path to retained file: {exc}"
            ) from exc
        if not os.path.samestat(path_stat, stream_stat):
            raise WDLFactJournalError(
                "fact-journal path no longer names the audited open file"
            )

    def _check_live_boundary(self) -> None:
        if self.closed:
            raise WDLFactJournalError("WDL fact journal is closed")
        if self._failed:
            raise WDLFactCommitError(
                "WDL fact journal is unusable after a failed append; reopen it"
            )
        assert self._stream is not None
        self._require_path_matches_stream()
        current_size = os.fstat(self._stream.fileno()).st_size
        if current_size != self._next_offset:
            self._failed = True
            raise WDLFactJournalIntegrityError(
                FactScanResult(
                    self.path,
                    current_size,
                    None,
                    len(self._entries),
                    self._next_offset,
                    tuple(self._entries),
                    _issue(
                        "file_changed_while_open",
                        self._next_offset,
                        "WDL fact-journal bytes changed outside the audited writer",
                        recoverable_tail=False,
                    ),
                )
            )

    @staticmethod
    def _entry_seal(entry: FactEntry) -> tuple[object, ...]:
        return (
            entry.record_index,
            entry.frame_offset,
            entry.frame_end_offset,
            entry.content_sha256,
            entry.crc32,
            entry.fact.kind,
            entry.fact.node_sha256,
            entry.fact.claimed_wdl.value,
            entry.fact.proof_height,
            entry.fact.evidence_sha256,
        )

    def _replay_live_journal(self) -> FactScanResult:
        try:
            self._check_live_boundary()
            assert self._stream is not None
            report = _scan_fact_stream(self.path, self._stream, self.dag)
            report.require_valid()
            expected = tuple(self._entry_seal(entry) for entry in self._entries)
            actual = tuple(self._entry_seal(entry) for entry in report.entries)
            if (
                report.file_size != self._next_offset
                or report.record_count != self._next_index
                or actual != expected
            ):
                raise WDLFactJournalIntegrityError(
                    FactScanResult(
                        self.path,
                        report.file_size,
                        report.header,
                        report.record_count,
                        report.last_good_offset,
                        report.entries,
                        _issue(
                            "audited_state_divergence",
                            report.last_good_offset,
                            "full replay differs from the retained audited state",
                            recoverable_tail=False,
                        ),
                    )
                )
            self._require_path_matches_stream()
            return report
        except BaseException:
            self._failed = True
            raise

    @staticmethod
    def _same_evidence(left: VerifiedWDLFact, right: VerifiedWDLFact) -> bool:
        return (
            left.kind == right.kind
            and left.node_sha256 == right.node_sha256
            and left.claimed_wdl == right.claimed_wdl
            and left.proof_height == right.proof_height
            and left.evidence_sha256 == right.evidence_sha256
            and canonical_json_bytes(_thaw_json(left.evidence))
            == canonical_json_bytes(_thaw_json(right.evidence))
        )

    def _append_fact_locked(
        self,
        fact: VerifiedWDLFact,
        replay: FactScanResult,
    ) -> FactAppendResult:
        replay_by_node = {
            entry.fact.node_sha256: entry for entry in replay.entries
        }
        existing = replay_by_node.get(fact.node_sha256)
        if existing is not None:
            if self._same_evidence(existing.fact, fact):
                return FactAppendResult(existing, False)
            raise WDLFactConflictError(
                "DAG node already has a different verified WDL fact"
            )

        frame, content_sha256, crc = _encode_frame(fact)
        frame_offset = self._next_offset
        assert self._stream is not None
        try:
            self._stream.seek(frame_offset)
            _write_all(self._stream, frame)
            self._stream.flush()
            os.fsync(self._stream.fileno())
        except BaseException:
            self._failed = True
            raise
        frame_end = frame_offset + len(frame)
        provisional = FactEntry(
            record_index=self._next_index,
            frame_offset=frame_offset,
            frame_end_offset=frame_end,
            payload_offset=frame_offset + RECORD_PREFIX_SIZE,
            payload_length=len(fact.payload_bytes()),
            sha256_offset=frame_end - RECORD_CRC32_SIZE - RECORD_SHA256_SIZE,
            crc32_offset=frame_end - RECORD_CRC32_SIZE,
            content_sha256=content_sha256,
            crc32=crc,
            fact=fact,
        )
        try:
            self._require_path_matches_stream()
            report = _scan_fact_stream(self.path, self._stream, self.dag)
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
                raise WDLFactJournalError(
                    "durable WDL fact append does not match exact replay"
                )
            audited = report.entries[-1]
        except BaseException as exc:
            self._failed = True
            raise WDLFactCommitError(
                "WDL fact append is durable but replay failed; reopen the journal"
            ) from exc
        self._entries.append(audited)
        self._entries_by_node[audited.fact.node_sha256] = audited
        self._next_offset = frame_end
        self._next_index += 1
        self._previous_fact_sha256 = audited.content_sha256
        return FactAppendResult(audited, True)

    def append_seed_certificate(
        self,
        node_sha256: str,
        certificate_bytes: bytes | bytearray | memoryview,
    ) -> FactAppendResult:
        """Independently verify and append one canonical standalone WDL seed."""

        if not isinstance(certificate_bytes, (bytes, bytearray, memoryview)):
            raise TypeError("certificate_bytes must be bytes-like")
        snapshot = bytes(certificate_bytes)
        if not snapshot or len(snapshot) > MAX_CERTIFICATE_BYTES:
            raise ValueError("seed certificate size is outside the supported range")
        with self._thread_lock:
            replay = self._replay_live_journal()
            fact = _new_seed_fact(
                self.dag,
                node_sha256=node_sha256,
                certificate_bytes=snapshot,
                record_index=self._next_index,
                previous_fact_sha256=self._previous_fact_sha256,
            )
            return self._append_fact_locked(fact, replay)

    def append_derivation(
        self,
        node_sha256: str,
        evidence_bytes: bytes | bytearray | memoryview,
    ) -> FactAppendResult:
        """Verify a canonical one-hop derivation against the audited prefix."""

        if not isinstance(evidence_bytes, (bytes, bytearray, memoryview)):
            raise TypeError("evidence_bytes must be bytes-like")
        snapshot = bytes(evidence_bytes)
        if not snapshot or len(snapshot) > MAX_DERIVATION_EVIDENCE_BYTES:
            raise ValueError("derivation evidence size is outside the supported range")
        with self._thread_lock:
            replay = self._replay_live_journal()
            fact = _new_derivation_fact(
                self.dag,
                node_sha256=node_sha256,
                evidence_bytes=snapshot,
                prior_entries=replay.entries,
                record_index=self._next_index,
                previous_fact_sha256=self._previous_fact_sha256,
            )
            return self._append_fact_locked(fact, replay)

    def get_fact(self, node_sha256: str) -> VerifiedWDLFact | None:
        node_sha256 = _require_sha256(node_sha256, label="DAG node hash")
        with self._thread_lock:
            report = self._replay_live_journal()
            for entry in report.entries:
                if entry.fact.node_sha256 == node_sha256:
                    return entry.fact
            return None

    def effective_wdl(self, node_sha256: str) -> WDL:
        node_sha256 = _require_sha256(node_sha256, label="DAG node hash")
        if self.dag.get_node(node_sha256) is None:
            raise ValueError("unknown DAG node")
        fact = self.get_fact(node_sha256)
        return WDL.UNKNOWN if fact is None else fact.claimed_wdl

    def iter_entries(self) -> Iterator[FactEntry]:
        with self._thread_lock:
            report = self._replay_live_journal()
            entries = tuple(report.entries)
        return iter(entries)

    def audit(self) -> FactScanResult:
        with self._thread_lock:
            return self._replay_live_journal()

    @staticmethod
    def _head_from_report(report: FactScanResult) -> FactJournalHead:
        report.require_valid()
        return FactJournalHead(
            rule_profile_id=RULE_PROFILE_ID,
            record_count=report.record_count,
            head_content_sha256=(
                None if not report.entries else report.entries[-1].content_sha256
            ),
            file_size=report.file_size,
        )

    @staticmethod
    def _require_head_in_report(
        required: FactJournalHead,
        report: FactScanResult,
    ) -> None:
        if not isinstance(required, FactJournalHead):
            raise TypeError("required_head must be a FactJournalHead")
        canonical = FactJournalHead.from_bytes(required.canonical_bytes())
        if canonical.rule_profile_id != RULE_PROFILE_ID:
            raise WDLFactRollbackError("external head rule profile mismatch")
        if canonical.record_count > report.record_count:
            raise WDLFactRollbackError("journal is shorter than the external head")
        assert report.header is not None
        if canonical.record_count == 0:
            if (
                canonical.head_content_sha256 is not None
                or canonical.file_size != report.header.header_size
            ):
                raise WDLFactRollbackError("external empty head is malformed")
            return
        anchored = report.entries[canonical.record_count - 1]
        if (
            anchored.content_sha256 != canonical.head_content_sha256
            or anchored.frame_end_offset != canonical.file_size
        ):
            raise WDLFactRollbackError(
                "external head does not occur at the required journal prefix"
            )

    def head_snapshot(self) -> FactJournalHead:
        with self._thread_lock:
            return self._head_from_report(self._replay_live_journal())

    def require_external_head(self, required: FactJournalHead) -> FactJournalHead:
        with self._thread_lock:
            report = self._replay_live_journal()
            self._require_head_in_report(required, report)
            return self._head_from_report(report)

    def migrate_v1_overlay(
        self,
        source: VerifiedCertificateOverlay,
    ) -> FactMigrationResult:
        """Reverify and embed every v1 certificate; never retain a v1 reference."""

        if not isinstance(source, VerifiedCertificateOverlay) or source.closed:
            raise TypeError("source must be an open VerifiedCertificateOverlay")
        if source.dag is not self.dag:
            raise ValueError("source overlay and destination journal use different DAGs")
        source_report = source.audit().require_valid()
        imported = 0
        already_present = 0
        for source_entry in source_report.entries:
            result = self.append_seed_certificate(
                source_entry.binding.node_sha256,
                source_entry.binding.certificate_bytes,
            )
            if result.appended:
                imported += 1
            else:
                already_present += 1
        return FactMigrationResult(
            source_record_count=source_report.record_count,
            imported_count=imported,
            already_present_count=already_present,
            source_head_content_sha256=(
                None
                if not source_report.entries
                else source_report.entries[-1].content_sha256
            ),
            destination_head=self.head_snapshot(),
        )

    def close(self) -> None:
        with self._thread_lock:
            try:
                if self._stream is not None and not self._stream.closed:
                    self._stream.close()
            finally:
                self._stream = None
                self._writer_lock.release()

    def __enter__(self) -> "WDLFactJournal":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


def migrate_verified_overlay_v1(
    source: VerifiedCertificateOverlay,
    destination: WDLFactJournal,
) -> FactMigrationResult:
    """Public deterministic v1-to-v2 migration wrapper."""

    if not isinstance(destination, WDLFactJournal) or destination.closed:
        raise TypeError("destination must be an open WDLFactJournal")
    return destination.migrate_v1_overlay(source)


def recover_wdl_fact_journal(
    path: str | os.PathLike[str],
    dag: ProofDAG,
) -> FactRecoveryResult:
    """Preserve and truncate only an incomplete final physical frame."""

    journal_path = Path(path)
    writer_lock = _SidecarWriterLock(journal_path)
    try:
        writer_lock.acquire()
    except FrontierWriterLockedError as exc:
        raise WDLFactJournalWriterLockedError(
            f"another writer owns WDL fact-journal lock {writer_lock.path}"
        ) from exc
    try:
        try:
            stream = journal_path.open("r+b", buffering=0)
        except OSError as exc:
            raise WDLFactJournalRecoveryError(
                f"cannot open WDL fact journal for recovery: {exc}"
            ) from exc
        with stream:
            try:
                if not os.path.samestat(
                    os.stat(journal_path),
                    os.fstat(stream.fileno()),
                ):
                    raise WDLFactJournalRecoveryError(
                        "fact-journal path changed before recovery scan"
                    )
            except OSError as exc:
                raise WDLFactJournalRecoveryError(
                    f"cannot bind recovery path to fact journal: {exc}"
                ) from exc
            before = _scan_fact_stream(journal_path, stream, dag)
            try:
                if not os.path.samestat(
                    os.stat(journal_path),
                    os.fstat(stream.fileno()),
                ):
                    raise WDLFactJournalRecoveryError(
                        "fact-journal path changed during recovery scan"
                    )
            except OSError as exc:
                raise WDLFactJournalRecoveryError(
                    f"cannot rebind recovery path after scan: {exc}"
                ) from exc
            if before.valid:
                return FactRecoveryResult(before, before, 0)
            assert before.issue is not None
            if before.header is None or not before.issue.recoverable_tail:
                raise WDLFactJournalRecoveryError(
                    f"cannot truncate fact journal for {before.issue.code}: "
                    f"{before.issue.message}"
                )
            if os.fstat(stream.fileno()).st_size != before.file_size:
                raise WDLFactJournalRecoveryError(
                    "fact journal changed after the recovery scan"
                )
            try:
                recovery_path, recovery_sha256 = _preserve_invalid_suffix(
                    journal_path,
                    stream,
                    start_offset=before.last_good_offset,
                    file_size=before.file_size,
                )
            except (FrontierRecoveryError, OSError) as exc:
                raise WDLFactJournalRecoveryError(
                    f"cannot preserve invalid fact-journal suffix: {exc}"
                ) from exc
            stream.truncate(before.last_good_offset)
            stream.flush()
            os.fsync(stream.fileno())
            try:
                if not os.path.samestat(
                    os.stat(journal_path),
                    os.fstat(stream.fileno()),
                ):
                    raise WDLFactJournalRecoveryError(
                        "fact-journal path changed during recovery"
                    )
            except OSError as exc:
                raise WDLFactJournalRecoveryError(
                    f"cannot rebind recovery path after truncation: {exc}"
                ) from exc
            after = _scan_fact_stream(journal_path, stream, dag)
            after.require_valid()
            return FactRecoveryResult(
                before,
                after,
                before.file_size - before.last_good_offset,
                recovery_path,
                recovery_sha256,
            )
    finally:
        writer_lock.release()


__all__ = [
    "DERIVATION_EVIDENCE_SCHEMA",
    "DERIVATION_VERIFIER_PROFILE",
    "FACT_FORMAT_MAJOR",
    "FACT_FORMAT_MINOR",
    "FACT_HEAD_SCHEMA",
    "FACT_RECORD_SCHEMA",
    "FILE_MAGIC",
    "FactAppendResult",
    "FactEntry",
    "FactHeader",
    "FactIssue",
    "FactJournalHead",
    "FactMigrationResult",
    "FactRecoveryResult",
    "FactScanResult",
    "MAX_DERIVATION_DEPENDENCIES",
    "MAX_DERIVATION_EVIDENCE_BYTES",
    "MAX_FACT_PAYLOAD_BYTES",
    "MAX_PROOF_HEIGHT",
    "RECORD_MAGIC",
    "RECORD_PREFIX_SIZE",
    "SEED_EVIDENCE_SCHEMA",
    "SEED_VERIFIER_PROFILE",
    "VerifiedWDLFact",
    "WDLFactCommitError",
    "WDLFactConflictError",
    "WDLFactJournal",
    "WDLFactJournalError",
    "WDLFactJournalIntegrityError",
    "WDLFactJournalRecoveryError",
    "WDLFactJournalWriterLockedError",
    "WDLFactRollbackError",
    "canonical_derivation_evidence_bytes",
    "migrate_verified_overlay_v1",
    "recover_wdl_fact_journal",
    "verify_wdl_fact_journal",
]
