"""Externally retainable commitments to exact audited ProofDAG prefixes.

The frontier journal remains authority.  A :class:`ProofDAGHead` is only a
compact rollback/rewrite witness produced by a stable full replay of that
authority.  Its ordered manifest deliberately matches the manifest algorithm
used by :mod:`ugts_chess.wdl_expansion`: every exact edge occurrence commits
its ordinal, content address, parent occurrence, parent node, and child node.

An expected older head is accepted only when it is reconstructed exactly as a
prefix of the current audited journal.  In particular, prefix node counts are
recomputed from the distinct child identities in that prefix; current SQLite
metadata is never used as authority for an earlier boundary.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Final

from .game_state import RULE_PROFILE_ID
from .hashing import canonical_json_bytes
from .proof_dag import DAGEdge, ProofDAG, ProofDAGError, ProofDAGIntegrityError


PROOF_DAG_HEAD_SCHEMA: Final = "ugts-chess-proof-dag-head-1.0"
# Keep this value and the hashing algorithm byte-for-byte compatible with the
# current expansion/worklist manifest so those callers can later share it.
PROOF_DAG_MANIFEST_SCHEMA: Final = "ugts-chess-dag-expansion-manifest-1.0"
_MAX_STABLE_AUDIT_ATTEMPTS: Final = 8
_SHA256_BYTES: Final = hashlib.sha256().digest_size
_HEAD_KEYS: Final = frozenset(
    {
        "schema",
        "rule_profile_id",
        "frontier_record_count",
        "sqlite_edge_count",
        "sqlite_node_count",
        "frontier_size",
        "last_frontier_content_sha256",
        "frontier_manifest_sha256",
    }
)


class ProofDAGCommitmentError(ProofDAGError):
    """Base class for ProofDAG head capture and comparison failures."""


class ProofDAGConcurrentMutationError(ProofDAGCommitmentError):
    """Raised when no stable complete ProofDAG audit can be captured."""


class ProofDAGHeadMismatchError(ProofDAGCommitmentError):
    """Raised when an external head is not the exact current DAG prefix."""

    def __init__(
        self,
        message: str,
        *,
        expected: "ProofDAGHead",
        current: "ProofDAGHead",
    ) -> None:
        self.expected = expected
        self.current = current
        super().__init__(message)


class ProofDAGRollbackError(ProofDAGHeadMismatchError):
    """Raised when the live DAG is shorter than an externally retained head."""


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


def _require_count(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ProofDAGHead:
    """Canonical commitment to one fully audited ProofDAG prefix."""

    rule_profile_id: str
    frontier_record_count: int
    sqlite_edge_count: int
    sqlite_node_count: int
    frontier_size: int
    last_frontier_content_sha256: str | None
    frontier_manifest_sha256: str

    def __post_init__(self) -> None:
        if self.rule_profile_id != RULE_PROFILE_ID:
            raise ValueError("ProofDAG head rule profile is not canonical")
        records = _require_count(
            self.frontier_record_count,
            label="frontier_record_count",
        )
        edges = _require_count(self.sqlite_edge_count, label="sqlite_edge_count")
        nodes = _require_count(self.sqlite_node_count, label="sqlite_node_count")
        size = _require_count(self.frontier_size, label="frontier_size")
        if records != edges:
            raise ValueError("ProofDAG head frontier and edge counts differ")
        if nodes > edges:
            raise ValueError("ProofDAG head has more nodes than edge occurrences")
        if size == 0:
            raise ValueError("ProofDAG head size must include the frontier header")
        if records == 0:
            if nodes != 0:
                raise ValueError("empty ProofDAG head may not contain nodes")
            if self.last_frontier_content_sha256 is not None:
                raise ValueError("empty ProofDAG head may not name a last record")
        else:
            _require_sha256(
                self.last_frontier_content_sha256,
                label="last frontier content hash",
            )
        _require_sha256(
            self.frontier_manifest_sha256,
            label="frontier manifest hash",
        )

    def record(self) -> dict[str, object]:
        return {
            "schema": PROOF_DAG_HEAD_SCHEMA,
            "rule_profile_id": self.rule_profile_id,
            "frontier_record_count": self.frontier_record_count,
            "sqlite_edge_count": self.sqlite_edge_count,
            "sqlite_node_count": self.sqlite_node_count,
            "frontier_size": self.frontier_size,
            "last_frontier_content_sha256": self.last_frontier_content_sha256,
            "frontier_manifest_sha256": self.frontier_manifest_sha256,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.record())

    @classmethod
    def from_bytes(
        cls,
        value: bytes | bytearray | memoryview,
    ) -> "ProofDAGHead":
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise TypeError("ProofDAG head must be bytes-like")
        snapshot = bytes(value)
        try:
            raw = json.loads(snapshot)
            reconstructed_bytes = canonical_json_bytes(raw)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise ValueError(f"ProofDAG head is not canonical UTF-8 JSON: {exc}") from exc
        if not isinstance(raw, dict) or reconstructed_bytes != snapshot:
            raise ValueError("ProofDAG head is not a canonical JSON object")
        if set(raw) != _HEAD_KEYS:
            raise ValueError("ProofDAG head has missing or unexpected fields")
        if raw.get("schema") != PROOF_DAG_HEAD_SCHEMA:
            raise ValueError("ProofDAG head schema mismatch")
        result = cls(
            rule_profile_id=raw.get("rule_profile_id"),  # type: ignore[arg-type]
            frontier_record_count=raw.get("frontier_record_count"),  # type: ignore[arg-type]
            sqlite_edge_count=raw.get("sqlite_edge_count"),  # type: ignore[arg-type]
            sqlite_node_count=raw.get("sqlite_node_count"),  # type: ignore[arg-type]
            frontier_size=raw.get("frontier_size"),  # type: ignore[arg-type]
            last_frontier_content_sha256=raw.get(  # type: ignore[arg-type]
                "last_frontier_content_sha256"
            ),
            frontier_manifest_sha256=raw.get(  # type: ignore[arg-type]
                "frontier_manifest_sha256"
            ),
        )
        if result.canonical_bytes() != snapshot:
            raise ValueError("ProofDAG head differs from exact reconstruction")
        return result


@dataclass(frozen=True, slots=True)
class _StableCapture:
    current: ProofDAGHead
    prefix: ProofDAGHead | None


def _manifest_seed() -> bytes:
    return hashlib.sha256(
        PROOF_DAG_MANIFEST_SCHEMA.encode("ascii") + b"\x00seed\x00"
    ).digest()


def _manifest_record(edge: DAGEdge) -> bytes:
    if isinstance(edge.frontier_record_index, bool) or not isinstance(
        edge.frontier_record_index,
        int,
    ):
        raise ProofDAGIntegrityError("frontier edge ordinal is not an integer")
    if edge.frontier_record_index < 0:
        raise ProofDAGIntegrityError("frontier edge ordinal is negative")
    _require_sha256(
        edge.frontier_content_sha256,
        label="frontier edge content hash",
    )
    _require_sha256(edge.child_node_sha256, label="frontier child node hash")
    parent_occurrence = edge.parent_frontier_content_sha256
    parent_node = edge.parent_node_sha256
    if (parent_occurrence is None) != (parent_node is None):
        raise ProofDAGIntegrityError(
            "frontier edge parent occurrence/node presence differs"
        )
    if parent_occurrence is not None:
        _require_sha256(parent_occurrence, label="frontier parent occurrence hash")
        _require_sha256(parent_node, label="frontier parent node hash")
    return canonical_json_bytes(
        {
            "frontier_record_index": edge.frontier_record_index,
            "frontier_content_sha256": edge.frontier_content_sha256,
            "parent_frontier_content_sha256": parent_occurrence,
            "parent_node_sha256": parent_node,
            "child_node_sha256": edge.child_node_sha256,
        }
    )


def _advance_manifest(previous: bytes, record: bytes) -> bytes:
    if len(previous) != _SHA256_BYTES:
        raise ValueError("ordered manifest predecessor must be one SHA-256 digest")
    digest = hashlib.sha256()
    digest.update(PROOF_DAG_MANIFEST_SCHEMA.encode("ascii") + b"\x00step\x00")
    digest.update(previous)
    digest.update(len(record).to_bytes(8, "big"))
    digest.update(record)
    return digest.digest()


def _head(
    *,
    record_count: int,
    node_count: int,
    frontier_size: int,
    last_content_sha256: str | None,
    manifest: bytes,
) -> ProofDAGHead:
    return ProofDAGHead(
        rule_profile_id=RULE_PROFILE_ID,
        frontier_record_count=record_count,
        sqlite_edge_count=record_count,
        sqlite_node_count=node_count,
        frontier_size=frontier_size,
        last_frontier_content_sha256=last_content_sha256,
        frontier_manifest_sha256=manifest.hex(),
    )


def _stable_capture(
    dag: ProofDAG,
    *,
    prefix_record_count: int | None = None,
) -> _StableCapture:
    if not isinstance(dag, ProofDAG) or dag.closed:
        raise TypeError("dag must be an open ProofDAG")
    if dag.rule_profile_id != RULE_PROFILE_ID:
        raise ValueError("ProofDAG commitment supports only the canonical rule profile")
    if prefix_record_count is not None:
        _require_count(prefix_record_count, label="prefix_record_count")

    for _ in range(_MAX_STABLE_AUDIT_ATTEMPTS):
        before = dag.audit().require_valid()
        manifest = _manifest_seed()
        seen_nodes: set[str] = set()
        count = 0
        first_frame_offset: int | None = None
        last_content_sha256: str | None = None
        last_frame_end = 0
        prefix_node_count: int | None = None
        prefix_size: int | None = None
        prefix_last_sha256: str | None = None
        prefix_manifest: bytes | None = None

        for edge in dag.iter_edges():
            if edge.frontier_record_index != count:
                raise ProofDAGIntegrityError(
                    "frontier edge ordinals are not contiguous from zero"
                )
            if first_frame_offset is None:
                first_frame_offset = edge.frame_offset
                if first_frame_offset <= 0:
                    raise ProofDAGIntegrityError(
                        "first frontier frame does not follow a positive-size header"
                    )
            if edge.frame_end_offset <= edge.frame_offset:
                raise ProofDAGIntegrityError("frontier edge frame boundary is invalid")
            if count and edge.frame_offset != last_frame_end:
                raise ProofDAGIntegrityError("frontier edge frames are not contiguous")
            manifest = _advance_manifest(manifest, _manifest_record(edge))
            seen_nodes.add(edge.child_node_sha256)
            count += 1
            last_content_sha256 = edge.frontier_content_sha256
            last_frame_end = edge.frame_end_offset
            if prefix_record_count is not None and count == prefix_record_count:
                prefix_node_count = len(seen_nodes)
                prefix_size = last_frame_end
                prefix_last_sha256 = last_content_sha256
                prefix_manifest = manifest

        after = dag.audit().require_valid()
        if before != after or count != after.frontier_record_count:
            continue
        if after.sqlite_edge_count != count:
            raise ProofDAGIntegrityError(
                "audited SQLite edge count differs from ordered frontier replay"
            )
        if after.sqlite_node_count != len(seen_nodes):
            raise ProofDAGIntegrityError(
                "audited SQLite node count differs from ordered frontier identities"
            )
        if count:
            if last_frame_end != after.frontier_size:
                raise ProofDAGIntegrityError(
                    "last frontier frame does not end at the audited byte boundary"
                )
            assert first_frame_offset is not None
            header_size = first_frame_offset
        else:
            header_size = after.frontier_size

        current = _head(
            record_count=count,
            node_count=len(seen_nodes),
            frontier_size=after.frontier_size,
            last_content_sha256=last_content_sha256,
            manifest=manifest,
        )
        prefix: ProofDAGHead | None = None
        if prefix_record_count is not None:
            if prefix_record_count == 0:
                prefix = _head(
                    record_count=0,
                    node_count=0,
                    frontier_size=header_size,
                    last_content_sha256=None,
                    manifest=_manifest_seed(),
                )
            elif prefix_record_count <= count:
                assert prefix_node_count is not None
                assert prefix_size is not None
                assert prefix_last_sha256 is not None
                assert prefix_manifest is not None
                prefix = _head(
                    record_count=prefix_record_count,
                    node_count=prefix_node_count,
                    frontier_size=prefix_size,
                    last_content_sha256=prefix_last_sha256,
                    manifest=prefix_manifest,
                )
        return _StableCapture(current=current, prefix=prefix)

    raise ProofDAGConcurrentMutationError(
        "proof DAG changed repeatedly during full commitment audit"
    )


def audit_proof_dag_head(dag: ProofDAG) -> ProofDAGHead:
    """Return a stable full commitment to an open, fully audited ProofDAG."""

    return _stable_capture(dag).current


def require_external_dag_head(
    dag: ProofDAG,
    expected: ProofDAGHead,
) -> ProofDAGHead:
    """Require ``expected`` to occur as the exact current ProofDAG prefix.

    The returned value is the current full head, which may extend the retained
    head.  A shorter current journal is a rollback; an equal-or-longer journal
    with different committed prefix bytes is a mismatch/rewrite.
    """

    if not isinstance(expected, ProofDAGHead):
        raise TypeError("expected must be a ProofDAGHead")
    canonical_expected = ProofDAGHead.from_bytes(expected.canonical_bytes())
    capture = _stable_capture(
        dag,
        prefix_record_count=canonical_expected.frontier_record_count,
    )
    current = capture.current
    if canonical_expected.frontier_record_count > current.frontier_record_count:
        raise ProofDAGRollbackError(
            "live ProofDAG is shorter than the externally retained head",
            expected=canonical_expected,
            current=current,
        )
    prefix = capture.prefix
    if prefix is None or prefix != canonical_expected:
        raise ProofDAGHeadMismatchError(
            "external ProofDAG head is not the exact live journal prefix",
            expected=canonical_expected,
            current=current,
        )
    return current


__all__ = [
    "PROOF_DAG_HEAD_SCHEMA",
    "PROOF_DAG_MANIFEST_SCHEMA",
    "ProofDAGCommitmentError",
    "ProofDAGConcurrentMutationError",
    "ProofDAGHead",
    "ProofDAGHeadMismatchError",
    "ProofDAGRollbackError",
    "audit_proof_dag_head",
    "require_external_dag_head",
]
