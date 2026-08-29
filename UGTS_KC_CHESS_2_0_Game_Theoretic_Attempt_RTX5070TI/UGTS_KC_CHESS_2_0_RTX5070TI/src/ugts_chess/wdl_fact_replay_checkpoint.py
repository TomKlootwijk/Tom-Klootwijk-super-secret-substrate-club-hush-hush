"""Authenticated acceleration checkpoints for the v2 WDL fact journal.

This module deliberately does *not* make a local cache authoritative.  A
checkpoint is usable only with an independently retained
:class:`WDLFactReplayCheckpointHead` produced by the trusted builder below.
The builder fully replays the fact journal while the cooperative writer is
excluded, captures a stable ProofDAG prefix, publishes an immutable
content-addressed sidecar, fsyncs it, and reads it back before returning the
small external head.

The first milestone verifies that the live journal still contains the exact
checkpointed raw-byte prefix and that the live ProofDAG contains the exact
captured prefix.  It does not yet replay or bless bytes appended after the
checkpoint.  Consequently the returned verification is a prefix result, not
a ``FactScanResult`` and not authority for a live suffix.

SHA-256 gives mutation detection relative to a trusted external anchor; it
does not prove that an arbitrary checkpoint and a freshly computed hash were
created by the trusted full-replay ceremony.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import BinaryIO, Final, Mapping, Sequence

from .frontier import (
    FrontierWriterLockedError,
    _SidecarWriterLock,
    _fsync_parent_directory,
    _write_all,
)
from .game_state import RULE_PROFILE_ID
from .game_theory import WDL
from .hashing import canonical_json_bytes
from .proof_dag import DAGEdge, ProofDAG
from .proof_dag_commitment import (
    ProofDAGHead,
    advance_proof_dag_manifest,
    audit_proof_dag_head,
    proof_dag_manifest_seed,
    require_external_dag_head,
)
from .wdl_fact_journal import (
    FactEntry,
    FactJournalHead,
    MAX_PROOF_HEIGHT,
    WDLFactJournalIntegrityError,
    _encode_header,
    _read_header,
    _scan_fact_stream,
)


CHECKPOINT_SCHEMA: Final = "ugts-chess-wdl-fact-replay-checkpoint-1.0"
CHECKPOINT_HEAD_SCHEMA: Final = "ugts-chess-wdl-fact-replay-checkpoint-head-1.0"
CHECKPOINT_FACT_SCHEMA: Final = "ugts-chess-wdl-fact-replay-summary-1.0"
CHECKPOINT_BUILDER_PROFILE: Final = (
    "ugts-chess-wdl-fact-replay-checkpoint-full-stable-builder-1.0"
)
CHECKPOINT_STATE_MANIFEST_SCHEMA: Final = (
    "ugts-chess-wdl-fact-replay-state-manifest-1.0"
)
CHECKPOINT_FILE_PREFIX: Final = "ugts-chess-wdl-fact-replay-checkpoint"

MAX_CHECKPOINT_BYTES: Final = 256 * 1024 * 1024
MAX_CHECKPOINT_HEAD_BYTES: Final = 64 * 1024
MAX_CHECKPOINT_FACTS: Final = 1_000_000
MAX_STABLE_CAPTURE_ATTEMPTS: Final = 4
_HASH_BLOCK_BYTES: Final = 1024 * 1024
_FACT_JOURNAL_HEADER_SIZE: Final = len(_encode_header())

_CHECKPOINT_KEYS: Final = frozenset(
    {
        "schema",
        "builder_profile",
        "rule_profile_id",
        "fact_journal_head",
        "proof_dag_head",
        "journal_prefix_sha256",
        "fact_state_manifest_sha256",
        "facts",
    }
)
_HEAD_KEYS: Final = frozenset(
    {
        "schema",
        "rule_profile_id",
        "checkpoint_size",
        "checkpoint_sha256",
        "journal_prefix_sha256",
        "fact_state_manifest_sha256",
        "fact_journal_head",
        "proof_dag_head",
    }
)
_FACT_KEYS: Final = frozenset(
    {
        "schema",
        "record_index",
        "content_sha256",
        "kind",
        "node_sha256",
        "first_frontier_content_sha256",
        "claimed_wdl",
        "proof_height",
        "evidence_sha256",
    }
)


class WDLFactReplayCheckpointError(Exception):
    """Base class for checkpoint construction and verification failures."""


class WDLFactReplayCheckpointIntegrityError(WDLFactReplayCheckpointError):
    """Raised when authenticated checkpoint or live-prefix bytes disagree."""


class WDLFactReplayCheckpointRollbackError(
    WDLFactReplayCheckpointIntegrityError
):
    """Raised when the live fact journal is shorter than the checkpoint."""


class WDLFactReplayCheckpointBusyError(WDLFactReplayCheckpointError):
    """Raised when an exclusive stable source capture cannot be obtained."""


class WDLFactReplayCheckpointPublicationError(WDLFactReplayCheckpointError):
    """Raised when an immutable durable sidecar cannot be published."""


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


def _canonical_fact_head(value: FactJournalHead) -> FactJournalHead:
    if not isinstance(value, FactJournalHead):
        raise TypeError("fact_journal_head must be a FactJournalHead")
    result = FactJournalHead.from_bytes(value.canonical_bytes())
    if result.record_count > MAX_CHECKPOINT_FACTS:
        raise ValueError("checkpoint fact head count exceeds the maximum")
    if result.file_size < _FACT_JOURNAL_HEADER_SIZE:
        raise ValueError("checkpoint fact head ends inside the journal header")
    return result


def _canonical_dag_head(value: ProofDAGHead) -> ProofDAGHead:
    if not isinstance(value, ProofDAGHead):
        raise TypeError("proof_dag_head must be a ProofDAGHead")
    return ProofDAGHead.from_bytes(value.canonical_bytes())


@dataclass(frozen=True, slots=True)
class CheckpointFactSummary:
    """Authenticated narrow prior-fact state; never a synthetic full fact."""

    record_index: int
    content_sha256: str
    kind: str
    node_sha256: str
    first_frontier_content_sha256: str
    claimed_wdl: WDL
    proof_height: int
    evidence_sha256: str

    def __post_init__(self) -> None:
        _require_nonnegative_int(self.record_index, label="record_index")
        _require_sha256(self.content_sha256, label="fact content hash")
        if self.kind not in {"seed", "derivation"}:
            raise ValueError("checkpoint fact kind is unsupported")
        _require_sha256(self.node_sha256, label="fact node hash")
        _require_sha256(
            self.first_frontier_content_sha256,
            label="first frontier content hash",
        )
        if not isinstance(self.claimed_wdl, WDL) or self.claimed_wdl == WDL.UNKNOWN:
            raise ValueError("checkpoint fact WDL must be exact")
        _require_nonnegative_int(
            self.proof_height,
            label="proof_height",
            maximum=MAX_PROOF_HEIGHT,
        )
        _require_sha256(self.evidence_sha256, label="fact evidence hash")

    def record(self) -> dict[str, object]:
        return {
            "schema": CHECKPOINT_FACT_SCHEMA,
            "record_index": self.record_index,
            "content_sha256": self.content_sha256,
            "kind": self.kind,
            "node_sha256": self.node_sha256,
            "first_frontier_content_sha256": self.first_frontier_content_sha256,
            "claimed_wdl": self.claimed_wdl.value,
            "proof_height": self.proof_height,
            "evidence_sha256": self.evidence_sha256,
        }

    @classmethod
    def from_record(cls, raw: object) -> "CheckpointFactSummary":
        if not isinstance(raw, dict) or set(raw) != _FACT_KEYS:
            raise ValueError("checkpoint fact has missing or unexpected fields")
        if raw.get("schema") != CHECKPOINT_FACT_SCHEMA:
            raise ValueError("checkpoint fact schema mismatch")
        try:
            claimed_wdl = WDL(raw.get("claimed_wdl"))
        except (TypeError, ValueError) as exc:
            raise ValueError("checkpoint fact WDL is invalid") from exc
        return cls(
            record_index=_require_nonnegative_int(
                raw.get("record_index"), label="record_index"
            ),
            content_sha256=_require_sha256(
                raw.get("content_sha256"), label="fact content hash"
            ),
            kind=raw.get("kind"),  # type: ignore[arg-type]
            node_sha256=_require_sha256(raw.get("node_sha256"), label="node hash"),
            first_frontier_content_sha256=_require_sha256(
                raw.get("first_frontier_content_sha256"),
                label="first frontier content hash",
            ),
            claimed_wdl=claimed_wdl,
            proof_height=_require_nonnegative_int(
                raw.get("proof_height"),
                label="proof_height",
                maximum=MAX_PROOF_HEIGHT,
            ),
            evidence_sha256=_require_sha256(
                raw.get("evidence_sha256"), label="evidence hash"
            ),
        )


def _state_manifest_seed() -> bytes:
    return hashlib.sha256(
        CHECKPOINT_STATE_MANIFEST_SCHEMA.encode("ascii") + b"\x00seed\x00"
    ).digest()


def _state_manifest(facts: Sequence[CheckpointFactSummary]) -> str:
    digest = _state_manifest_seed()
    for fact in facts:
        record = canonical_json_bytes(fact.record())
        step = hashlib.sha256()
        step.update(
            CHECKPOINT_STATE_MANIFEST_SCHEMA.encode("ascii") + b"\x00step\x00"
        )
        step.update(digest)
        step.update(len(record).to_bytes(8, "big"))
        step.update(record)
        digest = step.digest()
    return digest.hex()


@dataclass(frozen=True, slots=True)
class WDLFactReplayCheckpoint:
    fact_journal_head: FactJournalHead
    proof_dag_head: ProofDAGHead
    journal_prefix_sha256: str
    fact_state_manifest_sha256: str
    facts: tuple[CheckpointFactSummary, ...]

    def __post_init__(self) -> None:
        canonical_fact_head = _canonical_fact_head(self.fact_journal_head)
        canonical_dag_head = _canonical_dag_head(self.proof_dag_head)
        if canonical_fact_head != self.fact_journal_head:
            raise ValueError("checkpoint fact head is not canonical")
        if canonical_dag_head != self.proof_dag_head:
            raise ValueError("checkpoint ProofDAG head is not canonical")
        _require_sha256(self.journal_prefix_sha256, label="journal prefix hash")
        _require_sha256(
            self.fact_state_manifest_sha256,
            label="fact state manifest hash",
        )
        if not isinstance(self.facts, tuple):
            raise TypeError("checkpoint facts must be a tuple")
        if len(self.facts) > MAX_CHECKPOINT_FACTS:
            raise ValueError("checkpoint fact count exceeds the maximum")
        if len(self.facts) != canonical_fact_head.record_count:
            raise ValueError("checkpoint fact count differs from its journal head")
        seen_nodes: set[str] = set()
        for index, fact in enumerate(self.facts):
            if not isinstance(fact, CheckpointFactSummary):
                raise TypeError("checkpoint facts must be CheckpointFactSummary values")
            if fact.record_index != index:
                raise ValueError("checkpoint fact indexes are not contiguous")
            if fact.node_sha256 in seen_nodes:
                raise ValueError("checkpoint contains duplicate exact node facts")
            seen_nodes.add(fact.node_sha256)
        expected_last = None if not self.facts else self.facts[-1].content_sha256
        if canonical_fact_head.head_content_sha256 != expected_last:
            raise ValueError("checkpoint last fact hash differs from its journal head")
        if _state_manifest(self.facts) != self.fact_state_manifest_sha256:
            raise ValueError("checkpoint fact state manifest mismatch")

    def record(self) -> dict[str, object]:
        return {
            "schema": CHECKPOINT_SCHEMA,
            "builder_profile": CHECKPOINT_BUILDER_PROFILE,
            "rule_profile_id": RULE_PROFILE_ID,
            "fact_journal_head": self.fact_journal_head.record(),
            "proof_dag_head": self.proof_dag_head.record(),
            "journal_prefix_sha256": self.journal_prefix_sha256,
            "fact_state_manifest_sha256": self.fact_state_manifest_sha256,
            "facts": [fact.record() for fact in self.facts],
        }

    def canonical_bytes(self) -> bytes:
        snapshot = canonical_json_bytes(self.record())
        if not snapshot or len(snapshot) > MAX_CHECKPOINT_BYTES:
            raise ValueError("checkpoint byte size is outside the supported range")
        return snapshot

    @classmethod
    def from_bytes(
        cls, value: bytes | bytearray | memoryview
    ) -> "WDLFactReplayCheckpoint":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("checkpoint must be bytes-like")
        byte_size = value.nbytes if isinstance(value, memoryview) else len(value)
        if not byte_size or byte_size > MAX_CHECKPOINT_BYTES:
            raise ValueError("checkpoint byte size is outside the supported range")
        snapshot = bytes(value)
        try:
            raw = json.loads(snapshot)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(f"checkpoint is not UTF-8 JSON: {exc}") from exc
        if not isinstance(raw, dict) or canonical_json_bytes(raw) != snapshot:
            raise ValueError("checkpoint is not a canonical JSON object")
        if set(raw) != _CHECKPOINT_KEYS:
            raise ValueError("checkpoint has missing or unexpected fields")
        if raw.get("schema") != CHECKPOINT_SCHEMA:
            raise ValueError("checkpoint schema mismatch")
        if raw.get("builder_profile") != CHECKPOINT_BUILDER_PROFILE:
            raise ValueError("checkpoint builder profile mismatch")
        if raw.get("rule_profile_id") != RULE_PROFILE_ID:
            raise ValueError("checkpoint rule profile mismatch")
        raw_facts = raw.get("facts")
        if not isinstance(raw_facts, list):
            raise ValueError("checkpoint facts must be a list")
        if len(raw_facts) > MAX_CHECKPOINT_FACTS:
            raise ValueError("checkpoint fact count exceeds the maximum")
        raw_fact_head = raw.get("fact_journal_head")
        raw_dag_head = raw.get("proof_dag_head")
        if not isinstance(raw_fact_head, dict) or not isinstance(raw_dag_head, dict):
            raise ValueError("checkpoint heads must be objects")
        result = cls(
            fact_journal_head=FactJournalHead.from_bytes(
                canonical_json_bytes(raw_fact_head)
            ),
            proof_dag_head=ProofDAGHead.from_bytes(canonical_json_bytes(raw_dag_head)),
            journal_prefix_sha256=_require_sha256(
                raw.get("journal_prefix_sha256"), label="journal prefix hash"
            ),
            fact_state_manifest_sha256=_require_sha256(
                raw.get("fact_state_manifest_sha256"),
                label="fact state manifest hash",
            ),
            facts=tuple(CheckpointFactSummary.from_record(item) for item in raw_facts),
        )
        if result.canonical_bytes() != snapshot:
            raise ValueError("checkpoint differs from exact reconstruction")
        return result


@dataclass(frozen=True, slots=True)
class WDLFactReplayCheckpointHead:
    checkpoint_size: int
    checkpoint_sha256: str
    journal_prefix_sha256: str
    fact_state_manifest_sha256: str
    fact_journal_head: FactJournalHead
    proof_dag_head: ProofDAGHead

    def __post_init__(self) -> None:
        size = _require_nonnegative_int(
            self.checkpoint_size,
            label="checkpoint_size",
            maximum=MAX_CHECKPOINT_BYTES,
        )
        if size == 0:
            raise ValueError("checkpoint_size must be positive")
        _require_sha256(self.checkpoint_sha256, label="checkpoint hash")
        _require_sha256(self.journal_prefix_sha256, label="journal prefix hash")
        _require_sha256(
            self.fact_state_manifest_sha256,
            label="fact state manifest hash",
        )
        _canonical_fact_head(self.fact_journal_head)
        _canonical_dag_head(self.proof_dag_head)

    def record(self) -> dict[str, object]:
        return {
            "schema": CHECKPOINT_HEAD_SCHEMA,
            "rule_profile_id": RULE_PROFILE_ID,
            "checkpoint_size": self.checkpoint_size,
            "checkpoint_sha256": self.checkpoint_sha256,
            "journal_prefix_sha256": self.journal_prefix_sha256,
            "fact_state_manifest_sha256": self.fact_state_manifest_sha256,
            "fact_journal_head": self.fact_journal_head.record(),
            "proof_dag_head": self.proof_dag_head.record(),
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @classmethod
    def from_bytes(
        cls, value: bytes | bytearray | memoryview
    ) -> "WDLFactReplayCheckpointHead":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("checkpoint head must be bytes-like")
        byte_size = value.nbytes if isinstance(value, memoryview) else len(value)
        if not byte_size or byte_size > MAX_CHECKPOINT_HEAD_BYTES:
            raise ValueError("checkpoint head byte size is outside the supported range")
        snapshot = bytes(value)
        try:
            raw = json.loads(snapshot)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(f"checkpoint head is not UTF-8 JSON: {exc}") from exc
        if not isinstance(raw, dict) or canonical_json_bytes(raw) != snapshot:
            raise ValueError("checkpoint head is not a canonical JSON object")
        if set(raw) != _HEAD_KEYS:
            raise ValueError("checkpoint head has missing or unexpected fields")
        if raw.get("schema") != CHECKPOINT_HEAD_SCHEMA:
            raise ValueError("checkpoint head schema mismatch")
        if raw.get("rule_profile_id") != RULE_PROFILE_ID:
            raise ValueError("checkpoint head rule profile mismatch")
        raw_fact_head = raw.get("fact_journal_head")
        raw_dag_head = raw.get("proof_dag_head")
        if not isinstance(raw_fact_head, dict) or not isinstance(raw_dag_head, dict):
            raise ValueError("checkpoint head bindings must be objects")
        result = cls(
            checkpoint_size=_require_nonnegative_int(
                raw.get("checkpoint_size"),
                label="checkpoint_size",
                maximum=MAX_CHECKPOINT_BYTES,
            ),
            checkpoint_sha256=_require_sha256(
                raw.get("checkpoint_sha256"), label="checkpoint hash"
            ),
            journal_prefix_sha256=_require_sha256(
                raw.get("journal_prefix_sha256"), label="journal prefix hash"
            ),
            fact_state_manifest_sha256=_require_sha256(
                raw.get("fact_state_manifest_sha256"),
                label="fact state manifest hash",
            ),
            fact_journal_head=FactJournalHead.from_bytes(
                canonical_json_bytes(raw_fact_head)
            ),
            proof_dag_head=ProofDAGHead.from_bytes(canonical_json_bytes(raw_dag_head)),
        )
        if result.canonical_bytes() != snapshot:
            raise ValueError("checkpoint head differs from exact reconstruction")
        return result


@dataclass(frozen=True, slots=True)
class WDLFactReplayCheckpointPublication:
    path: Path
    checkpoint: WDLFactReplayCheckpoint
    head: WDLFactReplayCheckpointHead
    created: bool


@dataclass(frozen=True, slots=True)
class WDLFactReplayCheckpointPrefixVerification:
    """Verified checkpoint prefix only; says nothing about a live suffix."""

    checkpoint_path: Path
    checkpoint: WDLFactReplayCheckpoint
    required_head: WDLFactReplayCheckpointHead
    current_proof_dag_head: ProofDAGHead
    live_fact_file_size: int
    verified_prefix_size: int
    trailing_unverified_bytes: int


def _fact_head(entries: Sequence[FactEntry], *, file_size: int) -> FactJournalHead:
    return FactJournalHead(
        rule_profile_id=RULE_PROFILE_ID,
        record_count=len(entries),
        head_content_sha256=None if not entries else entries[-1].content_sha256,
        file_size=file_size,
    )


def _summary(entry: FactEntry) -> CheckpointFactSummary:
    fact = entry.fact
    return CheckpointFactSummary(
        record_index=entry.record_index,
        content_sha256=entry.content_sha256,
        kind=fact.kind,
        node_sha256=fact.node_sha256,
        first_frontier_content_sha256=fact.first_frontier_content_sha256,
        claimed_wdl=fact.claimed_wdl,
        proof_height=fact.proof_height,
        evidence_sha256=fact.evidence_sha256,
    )


def _stat_identity(stat_result: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def _hash_exact_prefix(stream: object, size: int) -> str:
    digest = hashlib.sha256()
    remaining = size
    stream.seek(0)  # type: ignore[attr-defined]
    while remaining:
        block = stream.read(min(_HASH_BLOCK_BYTES, remaining))  # type: ignore[attr-defined]
        if not block:
            raise WDLFactReplayCheckpointIntegrityError(
                "fact journal ended while hashing the checkpoint prefix"
            )
        digest.update(block)
        remaining -= len(block)
    return digest.hexdigest()


def _proof_prefix_head(
    edges: Sequence[DAGEdge],
    full_head: ProofDAGHead,
    required_count: int,
) -> ProofDAGHead:
    if required_count > len(edges):
        raise WDLFactReplayCheckpointIntegrityError(
            "fact replay references a DAG edge beyond the stable ProofDAG"
        )
    manifest = proof_dag_manifest_seed()
    nodes: set[str] = set()
    last_hash: str | None = None
    if edges:
        header_size = edges[0].frame_offset
    else:
        header_size = full_head.frontier_size
    frontier_size = header_size
    for expected_index, edge in enumerate(edges[:required_count]):
        if edge.frontier_record_index != expected_index:
            raise WDLFactReplayCheckpointIntegrityError(
                "ProofDAG edge indexes are not contiguous"
            )
        manifest = advance_proof_dag_manifest(manifest, edge)
        nodes.add(edge.child_node_sha256)
        last_hash = edge.frontier_content_sha256
        frontier_size = edge.frame_end_offset
    result = ProofDAGHead(
        rule_profile_id=RULE_PROFILE_ID,
        frontier_record_count=required_count,
        sqlite_edge_count=required_count,
        sqlite_node_count=len(nodes),
        frontier_size=frontier_size,
        last_frontier_content_sha256=last_hash,
        frontier_manifest_sha256=manifest.hex(),
    )
    if required_count == len(edges) and result != full_head:
        raise WDLFactReplayCheckpointIntegrityError(
            "reconstructed ProofDAG head differs from its stable audit"
        )
    return result


def _required_dag_prefix(
    entries: Sequence[FactEntry],
    edges: Sequence[DAGEdge],
) -> int:
    by_hash: dict[str, int] = {}
    for index, edge in enumerate(edges):
        if edge.frontier_record_index != index:
            raise WDLFactReplayCheckpointIntegrityError(
                "ProofDAG edge indexes are not contiguous"
            )
        by_hash.setdefault(edge.frontier_content_sha256, index)
    required = 0
    for entry in entries:
        first_index = by_hash.get(entry.fact.first_frontier_content_sha256)
        if first_index is None:
            raise WDLFactReplayCheckpointIntegrityError(
                "verified fact first occurrence is absent from the stable ProofDAG"
            )
        required = max(required, first_index + 1)
        if entry.fact.kind != "derivation":
            continue
        evidence = entry.fact.evidence
        if not isinstance(evidence, Mapping):
            raise WDLFactReplayCheckpointIntegrityError(
                "verified derivation evidence is not an object"
            )
        dependencies = evidence.get("move_dependencies")
        if not isinstance(dependencies, (tuple, list)):
            raise WDLFactReplayCheckpointIntegrityError(
                "verified derivation dependencies are not a sequence"
            )
        for dependency in dependencies:
            if not isinstance(dependency, Mapping):
                raise WDLFactReplayCheckpointIntegrityError(
                    "verified derivation dependency is not an object"
                )
            index = dependency.get("dag_edge_record_index")
            content_hash = dependency.get("dag_edge_content_sha256")
            if (
                isinstance(index, bool)
                or not isinstance(index, int)
                or index < 0
                or index >= len(edges)
                or edges[index].frontier_content_sha256 != content_hash
            ):
                raise WDLFactReplayCheckpointIntegrityError(
                    "verified derivation dependency lies beyond the stable ProofDAG"
                )
            required = max(required, index + 1)
    return required


def _capture_checkpoint(
    journal_path: Path,
    dag: ProofDAG,
) -> WDLFactReplayCheckpoint:
    if not isinstance(dag, ProofDAG) or dag.closed:
        raise TypeError("dag must be an open ProofDAG")
    if dag.rule_profile_id != RULE_PROFILE_ID:
        raise ValueError("checkpoint supports only the canonical rule profile")
    writer_lock = _SidecarWriterLock(journal_path)
    try:
        writer_lock.acquire()
    except FrontierWriterLockedError as exc:
        raise WDLFactReplayCheckpointBusyError(
            "fact journal writer must be closed before checkpoint capture"
        ) from exc
    try:
        for _ in range(MAX_STABLE_CAPTURE_ATTEMPTS):
            dag_before = audit_proof_dag_head(dag)
            try:
                with journal_path.open("rb", buffering=0) as stream:
                    start_stat = os.fstat(stream.fileno())
                    if not os.path.samestat(os.stat(journal_path), start_stat):
                        raise WDLFactReplayCheckpointIntegrityError(
                            "fact-journal path does not name the opened source"
                        )
                    report = _scan_fact_stream(journal_path, stream, dag)
                    try:
                        report.require_valid()
                    except WDLFactJournalIntegrityError as exc:
                        raise WDLFactReplayCheckpointIntegrityError(
                            "trusted checkpoint build requires a valid full fact replay"
                        ) from exc
                    raw_prefix_hash = _hash_exact_prefix(stream, report.file_size)
                    end_stat = os.fstat(stream.fileno())
                    if (
                        _stat_identity(start_stat) != _stat_identity(end_stat)
                        or not os.path.samestat(os.stat(journal_path), end_stat)
                    ):
                        continue
            except OSError as exc:
                raise WDLFactReplayCheckpointIntegrityError(
                    f"cannot capture fact-journal source: {exc}"
                ) from exc

            edges = tuple(dag.iter_edges())
            dag_after = audit_proof_dag_head(dag)
            if dag_before != dag_after or len(edges) != dag_after.frontier_record_count:
                continue
            required_count = _required_dag_prefix(report.entries, edges)
            proof_head = _proof_prefix_head(edges, dag_after, required_count)
            facts = tuple(_summary(entry) for entry in report.entries)
            manifest = _state_manifest(facts)
            return WDLFactReplayCheckpoint(
                fact_journal_head=_fact_head(
                    report.entries,
                    file_size=report.file_size,
                ),
                proof_dag_head=proof_head,
                journal_prefix_sha256=raw_prefix_hash,
                fact_state_manifest_sha256=manifest,
                facts=facts,
            )
        raise WDLFactReplayCheckpointBusyError(
            "ProofDAG changed repeatedly during stable checkpoint capture"
        )
    finally:
        writer_lock.release()


def _head_for(
    checkpoint: WDLFactReplayCheckpoint,
    checkpoint_bytes: bytes,
) -> WDLFactReplayCheckpointHead:
    return WDLFactReplayCheckpointHead(
        checkpoint_size=len(checkpoint_bytes),
        checkpoint_sha256=hashlib.sha256(checkpoint_bytes).hexdigest(),
        journal_prefix_sha256=checkpoint.journal_prefix_sha256,
        fact_state_manifest_sha256=checkpoint.fact_state_manifest_sha256,
        fact_journal_head=checkpoint.fact_journal_head,
        proof_dag_head=checkpoint.proof_dag_head,
    )


def _load_authenticated_checkpoint(
    checkpoint_path: Path,
    required_head: WDLFactReplayCheckpointHead,
) -> WDLFactReplayCheckpoint:
    canonical_head = WDLFactReplayCheckpointHead.from_bytes(
        required_head.canonical_bytes()
    )
    try:
        with checkpoint_path.open("rb", buffering=0) as stream:
            start_stat = os.fstat(stream.fileno())
            if not os.path.samestat(os.stat(checkpoint_path), start_stat):
                raise WDLFactReplayCheckpointIntegrityError(
                    "checkpoint path does not name the opened sidecar"
                )
            if start_stat.st_size != canonical_head.checkpoint_size:
                raise WDLFactReplayCheckpointIntegrityError(
                    "checkpoint size differs from the independently retained head"
                )
            if start_stat.st_size > MAX_CHECKPOINT_BYTES:
                raise WDLFactReplayCheckpointIntegrityError(
                    "checkpoint exceeds the byte-size maximum"
                )
            snapshot = stream.read(start_stat.st_size + 1)
            end_stat = os.fstat(stream.fileno())
            if (
                len(snapshot) != start_stat.st_size
                or _stat_identity(start_stat) != _stat_identity(end_stat)
                or not os.path.samestat(os.stat(checkpoint_path), end_stat)
            ):
                raise WDLFactReplayCheckpointIntegrityError(
                    "checkpoint changed during authenticated readback"
                )
    except OSError as exc:
        raise WDLFactReplayCheckpointIntegrityError(
            f"checkpoint sidecar is unavailable: {exc}"
        ) from exc
    if hashlib.sha256(snapshot).hexdigest() != canonical_head.checkpoint_sha256:
        raise WDLFactReplayCheckpointIntegrityError(
            "checkpoint SHA-256 differs from the independently retained head"
        )
    try:
        checkpoint = WDLFactReplayCheckpoint.from_bytes(snapshot)
    except (TypeError, ValueError) as exc:
        raise WDLFactReplayCheckpointIntegrityError(
            f"authenticated checkpoint body is invalid: {exc}"
        ) from exc
    if (
        checkpoint.journal_prefix_sha256 != canonical_head.journal_prefix_sha256
        or checkpoint.fact_state_manifest_sha256
        != canonical_head.fact_state_manifest_sha256
        or checkpoint.fact_journal_head != canonical_head.fact_journal_head
        or checkpoint.proof_dag_head != canonical_head.proof_dag_head
    ):
        raise WDLFactReplayCheckpointIntegrityError(
            "checkpoint body bindings differ from the independently retained head"
        )
    return checkpoint


def publish_wdl_fact_replay_checkpoint(
    checkpoint_directory: str | os.PathLike[str],
    journal_path: str | os.PathLike[str],
    dag: ProofDAG,
) -> WDLFactReplayCheckpointPublication:
    """Build, durably publish, and read back one immutable checkpoint.

    The returned head is safe to externalize only because this function first
    performed the trusted full stable replay.  Merely hashing arbitrary bytes
    does not provide the same provenance.
    """

    directory = Path(checkpoint_directory)
    directory.mkdir(parents=True, exist_ok=True)
    checkpoint = _capture_checkpoint(Path(journal_path), dag)
    snapshot = checkpoint.canonical_bytes()
    head = _head_for(checkpoint, snapshot)
    destination = directory / (
        f"{CHECKPOINT_FILE_PREFIX}-{head.checkpoint_sha256}.json"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{CHECKPOINT_FILE_PREFIX}-{head.checkpoint_sha256}-",
        suffix=".tmp",
        dir=directory,
    )
    temporary = Path(temporary_name)
    created = False
    try:
        with os.fdopen(descriptor, "w+b", buffering=0) as stream:
            _write_all(stream, snapshot)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
            created = True
        except FileExistsError:
            created = False
        except OSError as exc:
            raise WDLFactReplayCheckpointPublicationError(
                f"cannot publish immutable checkpoint sidecar: {exc}"
            ) from exc
        _fsync_parent_directory(destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    loaded = _load_authenticated_checkpoint(destination, head)
    if loaded != checkpoint:
        raise WDLFactReplayCheckpointPublicationError(
            "durable checkpoint readback differs from the captured state"
        )
    return WDLFactReplayCheckpointPublication(
        path=destination,
        checkpoint=checkpoint,
        head=head,
        created=created,
    )


def verify_wdl_fact_replay_checkpoint_prefix(
    journal_path: str | os.PathLike[str],
    dag: ProofDAG,
    checkpoint_path: str | os.PathLike[str],
    required_head: WDLFactReplayCheckpointHead,
) -> WDLFactReplayCheckpointPrefixVerification:
    """Verify only the authenticated checkpointed prefix of a live journal.

    This reads and hashes every prefix byte (O(prefix bytes)) but skips the
    expensive semantic replay already covered by the trusted checkpoint.  Any
    trailing bytes are explicitly reported as unverified and convey no WDL
    authority through this result.
    """

    if not isinstance(dag, ProofDAG) or dag.closed:
        raise TypeError("dag must be an open ProofDAG")
    if not isinstance(required_head, WDLFactReplayCheckpointHead):
        raise TypeError("required_head must be an independently retained checkpoint head")
    sidecar_path = Path(checkpoint_path)
    checkpoint = _load_authenticated_checkpoint(sidecar_path, required_head)
    current_dag_head = require_external_dag_head(dag, checkpoint.proof_dag_head)
    fact_path = Path(journal_path)
    boundary = checkpoint.fact_journal_head.file_size
    try:
        with fact_path.open("rb", buffering=0) as stream:
            start_stat = os.fstat(stream.fileno())
            if not os.path.samestat(os.stat(fact_path), start_stat):
                raise WDLFactReplayCheckpointIntegrityError(
                    "fact-journal path does not name the opened live source"
                )
            if start_stat.st_size < boundary:
                raise WDLFactReplayCheckpointRollbackError(
                    "live fact journal is shorter than the checkpointed prefix"
                )
            header, header_issue = _read_header(stream, start_stat.st_size)
            if header_issue is not None or header is None:
                raise WDLFactReplayCheckpointIntegrityError(
                    "live fact journal header is invalid"
                )
            if boundary < header.header_size:
                raise WDLFactReplayCheckpointIntegrityError(
                    "checkpoint boundary falls inside the live journal header"
                )
            prefix_hash = _hash_exact_prefix(stream, boundary)
            end_stat = os.fstat(stream.fileno())
            if (
                _stat_identity(start_stat) != _stat_identity(end_stat)
                or not os.path.samestat(os.stat(fact_path), end_stat)
            ):
                raise WDLFactReplayCheckpointIntegrityError(
                    "fact journal changed during checkpoint-prefix verification"
                )
    except WDLFactReplayCheckpointError:
        raise
    except OSError as exc:
        raise WDLFactReplayCheckpointIntegrityError(
            f"live fact journal is unavailable: {exc}"
        ) from exc
    if prefix_hash != checkpoint.journal_prefix_sha256:
        raise WDLFactReplayCheckpointIntegrityError(
            "live fact-journal prefix SHA-256 differs from the checkpoint"
        )
    return WDLFactReplayCheckpointPrefixVerification(
        checkpoint_path=sidecar_path,
        checkpoint=checkpoint,
        required_head=WDLFactReplayCheckpointHead.from_bytes(
            required_head.canonical_bytes()
        ),
        current_proof_dag_head=current_dag_head,
        live_fact_file_size=start_stat.st_size,
        verified_prefix_size=boundary,
        trailing_unverified_bytes=start_stat.st_size - boundary,
    )


__all__ = [
    "CHECKPOINT_BUILDER_PROFILE",
    "CHECKPOINT_FACT_SCHEMA",
    "CHECKPOINT_HEAD_SCHEMA",
    "CHECKPOINT_SCHEMA",
    "CheckpointFactSummary",
    "MAX_CHECKPOINT_BYTES",
    "MAX_CHECKPOINT_FACTS",
    "WDLFactReplayCheckpoint",
    "WDLFactReplayCheckpointBusyError",
    "WDLFactReplayCheckpointError",
    "WDLFactReplayCheckpointHead",
    "WDLFactReplayCheckpointIntegrityError",
    "WDLFactReplayCheckpointPrefixVerification",
    "WDLFactReplayCheckpointPublication",
    "WDLFactReplayCheckpointPublicationError",
    "WDLFactReplayCheckpointRollbackError",
    "publish_wdl_fact_replay_checkpoint",
    "verify_wdl_fact_replay_checkpoint_prefix",
]
