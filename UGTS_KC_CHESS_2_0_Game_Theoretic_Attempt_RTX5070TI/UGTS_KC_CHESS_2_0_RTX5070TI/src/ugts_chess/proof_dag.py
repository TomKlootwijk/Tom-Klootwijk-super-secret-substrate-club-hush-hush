"""Disk-backed, content-addressed storage for unresolved proof states.

The append-only :mod:`ugts_chess.frontier` journal is the authority.  SQLite
is a crash-recoverable index over that journal, never a source of chess truth.
Every node identity covers the exact canonical FEN, the complete repetition
history, and the one supported FIDE rule profile.  Compact 64-bit keys are
non-unique lookup hints and are always checked against the full node record.

This module deliberately stores only ``UNKNOWN``.  It does not expose an API
that can mutate a state to WIN/DRAW/LOSS.  The append-only
:mod:`ugts_chess.verified_overlay` binds independently verified certificates
to exact nodes and exposes effective values without changing this schema.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator

from .frontier import (
    FrontierEntry,
    FrontierError,
    FrontierReader,
    FrontierRecord,
    FrontierWriter,
    MAX_RECORD_PAYLOAD_BYTES,
    RECORD_CRC32_SIZE,
    RECORD_PREFIX_SIZE,
    RECORD_SHA256_SIZE,
)
from .game_state import HistoryContext, RULE_PROFILE_ID, automatic_status
from .game_theory import WDL
from .hashing import canonical_json_bytes, compact_key64
from .position import Position
from .rules import apply_move, parse_uci_move


DAG_INDEX_SCHEMA = "ugts-chess-proof-dag-index-1.0"
DAG_NODE_SCHEMA = "ugts-chess-proof-dag-node-1.0"
SQLITE_USER_VERSION = 1
MAX_MOVE_APPEND_BATCH = 4096
MAX_MOVE_APPEND_BATCH_BYTES = (
    MAX_RECORD_PAYLOAD_BYTES
    + RECORD_PREFIX_SIZE
    + RECORD_SHA256_SIZE
    + RECORD_CRC32_SIZE
)

_META_KEYS = frozenset(
    {
        "schema",
        "rule_profile_id",
        "indexed_record_count",
        "indexed_frontier_size",
    }
)


class ProofDAGError(Exception):
    """Base class for proof-DAG persistence errors."""


class ProofDAGIntegrityError(ProofDAGError):
    """Raised when SQLite is not an exact index of the verified journal."""


class ProofDAGCommitError(ProofDAGError):
    """Raised after an append/index transaction could not finish cleanly.

    The journal may contain one or more complete records that SQLite has not
    indexed yet, or a torn final batch frame when physical writing itself
    failed.  Close and reopen the DAG; deterministic suffix replay recovers a
    fully valid suffix when the existing SQLite rows are still a valid prefix.
    A torn frame remains fail-closed and needs explicit preserved-tail recovery.
    """


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


def _canonical_json_text(value: object) -> str:
    return canonical_json_bytes(value).decode("ascii")


def _index_key_blob(value: int) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < 2**64:
        raise ValueError("compact index key must be an unsigned 64-bit integer")
    return value.to_bytes(8, "big", signed=False)


def _index_key_int(value: object) -> int:
    if not isinstance(value, bytes) or len(value) != 8:
        raise ProofDAGIntegrityError("stored compact index key is not exactly 64 bits")
    return int.from_bytes(value, "big", signed=False)


def _history_json(history: HistoryContext) -> str:
    return _canonical_json_text(history.record())


def _history_from_json(value: object) -> HistoryContext:
    if not isinstance(value, str):
        raise ProofDAGIntegrityError("stored history is not canonical JSON text")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ProofDAGIntegrityError(f"stored history is invalid JSON: {exc}") from exc
    if _canonical_json_text(decoded) != value or not isinstance(decoded, list):
        raise ProofDAGIntegrityError("stored history is not a canonical array")
    pairs: list[tuple[str, int]] = []
    for item in decoded:
        if not isinstance(item, list) or len(item) != 2:
            raise ProofDAGIntegrityError("stored history entry is not a two-item array")
        key, count = item
        if not _is_sha256_hex(key) or isinstance(count, bool) or not isinstance(count, int):
            raise ProofDAGIntegrityError("stored history entry has invalid key or count")
        pairs.append((key, count))
    return HistoryContext(tuple(pairs))


def _node_identity_record(record: FrontierRecord) -> dict[str, object]:
    return {
        "schema": DAG_NODE_SCHEMA,
        "rule_profile_id": record.rule_profile_id,
        "fen": record.fen,
        "history_counts": record.history.record(),
    }


def node_identity_sha256(
    position: Position,
    history: HistoryContext,
    *,
    rule_profile_id: str = RULE_PROFILE_ID,
) -> str:
    """Return the full content address used by :class:`ProofDAG` nodes.

    This is deliberately stronger than the semantic game-state hash: the
    canonical FEN (including its fullmove counter), complete repetition
    history, and exact rules profile are all covered.  Callers that replay a
    DAG edge can therefore compare the independently derived child identity
    without relying on SQLite's compact lookup key.
    """

    record = FrontierRecord(
        position,
        history,
        rule_profile_id=rule_profile_id,
    )
    return hashlib.sha256(canonical_json_bytes(_node_identity_record(record))).hexdigest()


def _node_sha256(record: FrontierRecord) -> str:
    return node_identity_sha256(
        record.position,
        record.history,
        rule_profile_id=record.rule_profile_id,
    )


def _move_uci_from_action(action: object) -> str:
    """Return the sole canonical move token accepted on a state edge."""

    if not isinstance(action, dict) or set(action) != {"kind", "uci"}:
        raise ValueError(
            "non-root state action must be exactly "
            "{'kind': 'move', 'uci': <canonical-uci>}"
        )
    if action["kind"] != "move" or not isinstance(action["uci"], str):
        raise ValueError(
            "non-root state action must be exactly "
            "{'kind': 'move', 'uci': <canonical-uci>}"
        )
    return action["uci"]


@dataclass(frozen=True, slots=True)
class DAGNode:
    """An exact rule state reconstructed and checked from the SQLite index."""

    node_sha256: str
    position: Position
    history: HistoryContext
    rule_profile_id: str
    position_sha256: str
    game_state_sha256: str
    index_key64: int
    first_frontier_record_index: int
    wdl: WDL = WDL.UNKNOWN

    @property
    def fen(self) -> str:
        return self.position.to_fen()


@dataclass(frozen=True, slots=True)
class DAGEdge:
    """One append-only frontier occurrence connecting parent and child nodes."""

    frontier_content_sha256: str
    frontier_record_index: int
    frame_offset: int
    frame_end_offset: int
    frontier_crc32: int
    parent_frontier_content_sha256: str | None
    parent_node_sha256: str | None
    child_node_sha256: str
    action: Any
    lineage: Any


@dataclass(frozen=True, slots=True)
class DAGAppendResult:
    node: DAGNode
    edge: DAGEdge
    appended: bool


@dataclass(frozen=True, slots=True)
class DAGMoveAppendRequest:
    """One caller-supplied exact move transition for batch validation.

    The parent occurrence must already exist in the durable DAG prefix.  Batch
    requests cannot name an edge created by an earlier item in the same batch.
    Child position and history are comparison data; :class:`ProofDAG` derives
    both independently from the exact parent and canonical UCI token.
    """

    child_position: Position
    child_history: HistoryContext
    parent_frontier_content_sha256: str
    uci: str
    lineage: Any = None


@dataclass(frozen=True, slots=True)
class DAGMoveBatchAppendResult:
    """Ordered batch outcomes and exact authoritative prefix boundaries."""

    results: tuple[DAGAppendResult, ...]
    frontier_record_count_before: int
    frontier_record_count_after: int
    frontier_size_before: int
    frontier_size_after: int

    @property
    def request_count(self) -> int:
        return len(self.results)

    @property
    def appended_count(self) -> int:
        return sum(result.appended for result in self.results)

    @property
    def appended_record_indexes(self) -> tuple[int, ...]:
        return tuple(
            result.edge.frontier_record_index
            for result in self.results
            if result.appended
        )


@dataclass(frozen=True, slots=True)
class _PreparedMoveAppend:
    request: DAGMoveAppendRequest
    record: FrontierRecord
    payload_bytes: bytes
    content_sha256: str


@dataclass(frozen=True, slots=True)
class DAGAuditReport:
    valid: bool
    frontier_record_count: int
    sqlite_edge_count: int
    sqlite_node_count: int
    frontier_size: int
    issues: tuple[str, ...] = ()

    def require_valid(self) -> "DAGAuditReport":
        if not self.valid:
            detail = "; ".join(self.issues) if self.issues else "unknown divergence"
            raise ProofDAGIntegrityError(f"proof DAG audit failed: {detail}")
        return self


@dataclass(frozen=True, slots=True)
class _ExpectedNode:
    node_sha256: str
    fen: str
    history_json: str
    rule_profile_id: str
    position_sha256: str
    game_state_sha256: str
    index_key64: bytes
    first_frontier_record_index: int


@dataclass(frozen=True, slots=True)
class _ExpectedEdge:
    frontier_content_sha256: str
    frontier_record_index: int
    frame_offset: int
    frame_end_offset: int
    frontier_crc32: int
    parent_frontier_content_sha256: str | None
    parent_node_sha256: str | None
    child_node_sha256: str
    action_json: str
    lineage_json: str


def _expected_node(entry: FrontierEntry) -> _ExpectedNode:
    if entry.record_index is None:
        raise ProofDAGIntegrityError("sequential frontier entry has no record index")
    record = entry.record
    return _ExpectedNode(
        node_sha256=_node_sha256(record),
        fen=record.fen,
        history_json=_history_json(record.history),
        rule_profile_id=record.rule_profile_id,
        position_sha256=record.position_sha256,
        game_state_sha256=record.game_state_sha256,
        index_key64=_index_key_blob(compact_key64(record.position)),
        first_frontier_record_index=entry.record_index,
    )


def _expected_edge(
    entry: FrontierEntry,
    node: _ExpectedNode,
    parent_node_sha256: str | None,
) -> _ExpectedEdge:
    if entry.record_index is None:
        raise ProofDAGIntegrityError("sequential frontier entry has no record index")
    payload = entry.record.payload_record()
    return _ExpectedEdge(
        frontier_content_sha256=entry.content_sha256,
        frontier_record_index=entry.record_index,
        frame_offset=entry.frame_offset,
        frame_end_offset=entry.frame_end_offset,
        frontier_crc32=entry.crc32,
        parent_frontier_content_sha256=entry.record.parent_content_sha256,
        parent_node_sha256=parent_node_sha256,
        child_node_sha256=node.node_sha256,
        action_json=_canonical_json_text(payload["action"]),
        lineage_json=_canonical_json_text(payload["lineage"]),
    )


class ProofDAG:
    """Exclusive append handle plus a verified SQLite DAG index.

    Opening performs a complete deterministic audit.  A frontier suffix with
    no corresponding SQLite rows is the one recoverable crash state and is
    indexed transactionally.  SQLite rows that are extra, reordered, spoofed,
    or different from any existing frontier frame are rejected.  The audited
    SQLite index remains exclusively locked for this handle's lifetime, so
    other SQLite readers/writers must wait until :meth:`close`; this is what
    makes live random-access getters sound without rescanning the journal.
    """

    def __init__(
        self,
        database_path: str | os.PathLike[str],
        frontier_path: str | os.PathLike[str],
        *,
        rule_profile_id: str = RULE_PROFILE_ID,
    ) -> None:
        if rule_profile_id != RULE_PROFILE_ID:
            raise ValueError(
                f"proof DAG supports only canonical rule profile {RULE_PROFILE_ID!r}"
            )
        self.database_path = Path(database_path)
        self.frontier_path = Path(frontier_path)
        if self.database_path.resolve(strict=False) == self.frontier_path.resolve(strict=False):
            raise ValueError("SQLite database and frontier journal must be different files")
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.frontier_path.parent.mkdir(parents=True, exist_ok=True)
        self.rule_profile_id = rule_profile_id
        self._connection: sqlite3.Connection | None = None
        self._writer: FrontierWriter | None = None
        self._failed_append = False
        try:
            self._writer = FrontierWriter(
                self.frontier_path,
                rule_profile_id=self.rule_profile_id,
                fsync_on_append=True,
            )
            self._connection = sqlite3.connect(
                self.database_path,
                isolation_level=None,
                timeout=30.0,
            )
            self._connection.row_factory = sqlite3.Row
            self._configure_connection()
            self._initialize_or_validate_schema()
            self._reconcile_valid_frontier_suffix()
            self._audit_or_raise()
        except sqlite3.DatabaseError as exc:
            self.close()
            raise ProofDAGIntegrityError(f"SQLite proof-DAG database error: {exc}") from exc
        except BaseException:
            self.close()
            raise

    @property
    def closed(self) -> bool:
        return self._connection is None

    @property
    def _db(self) -> sqlite3.Connection:
        if self._connection is None:
            raise ProofDAGError("proof DAG is closed")
        return self._connection

    @property
    def _frontier_writer(self) -> FrontierWriter:
        if self._writer is None or self._writer.closed:
            raise ProofDAGError("proof DAG frontier writer is closed")
        return self._writer

    def _configure_connection(self) -> None:
        db = self._db
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA busy_timeout = 30000")
        mode = db.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if str(mode).lower() != "wal":
            raise ProofDAGIntegrityError(f"SQLite WAL mode unavailable (got {mode!r})")
        # A live getter can prove a random-access frontier frame's offset and
        # content address, but the v1 journal does not embed its ordinal.  The
        # ordinal lives in SQLite, so allowing another SQLite writer after the
        # opening full audit would make coordinated row deletion/redirection a
        # live integrity gap.  EXCLUSIVE locking makes that audited index
        # immutable for this append handle without an O(n) scan or RAM mirror.
        locking = db.execute("PRAGMA locking_mode = EXCLUSIVE").fetchone()[0]
        if str(locking).lower() != "exclusive":
            raise ProofDAGIntegrityError(
                f"SQLite exclusive locking unavailable (got {locking!r})"
            )
        db.execute("PRAGMA synchronous = FULL")
        # Materialize and retain the exclusive SQLite file lock immediately,
        # including when opening an existing database for read-only getters.
        db.execute("BEGIN IMMEDIATE")
        db.execute("COMMIT")

    def _initialize_or_validate_schema(self) -> None:
        db = self._db
        tables = {
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if not tables:
            header = self._frontier_writer.header
            assert header is not None
            try:
                db.executescript(
                    """
                    BEGIN IMMEDIATE;

                    CREATE TABLE metadata (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL
                    ) WITHOUT ROWID;

                    CREATE TABLE nodes (
                        node_sha256 TEXT PRIMARY KEY,
                        index_key64 BLOB NOT NULL CHECK(length(index_key64) = 8),
                        rule_profile_id TEXT NOT NULL,
                        fen TEXT NOT NULL,
                        history_json TEXT NOT NULL,
                        position_sha256 TEXT NOT NULL,
                        game_state_sha256 TEXT NOT NULL,
                        first_frontier_record_index INTEGER NOT NULL
                            CHECK(first_frontier_record_index >= 0),
                        wdl TEXT NOT NULL DEFAULT 'unknown' CHECK(wdl = 'unknown')
                    ) WITHOUT ROWID;

                    CREATE INDEX nodes_index_key64 ON nodes(index_key64);
                    CREATE INDEX nodes_game_state_sha256 ON nodes(game_state_sha256);

                    CREATE TABLE edges (
                        frontier_content_sha256 TEXT PRIMARY KEY,
                        frontier_record_index INTEGER NOT NULL UNIQUE
                            CHECK(frontier_record_index >= 0),
                        frame_offset INTEGER NOT NULL UNIQUE CHECK(frame_offset >= 0),
                        frame_end_offset INTEGER NOT NULL CHECK(frame_end_offset > frame_offset),
                        frontier_crc32 INTEGER NOT NULL
                            CHECK(frontier_crc32 >= 0 AND frontier_crc32 <= 4294967295),
                        parent_frontier_content_sha256 TEXT,
                        parent_node_sha256 TEXT,
                        child_node_sha256 TEXT NOT NULL,
                        action_json TEXT NOT NULL,
                        lineage_json TEXT NOT NULL,
                        CHECK(
                            (parent_frontier_content_sha256 IS NULL AND parent_node_sha256 IS NULL)
                            OR
                            (parent_frontier_content_sha256 IS NOT NULL AND parent_node_sha256 IS NOT NULL)
                        ),
                        FOREIGN KEY(parent_frontier_content_sha256)
                            REFERENCES edges(frontier_content_sha256),
                        FOREIGN KEY(parent_node_sha256) REFERENCES nodes(node_sha256),
                        FOREIGN KEY(child_node_sha256) REFERENCES nodes(node_sha256)
                    ) WITHOUT ROWID;

                    CREATE INDEX edges_parent_node ON edges(parent_node_sha256);
                    CREATE INDEX edges_child_node ON edges(child_node_sha256);
                    """
                )
                metadata = {
                    "schema": DAG_INDEX_SCHEMA,
                    "rule_profile_id": self.rule_profile_id,
                    "indexed_record_count": "0",
                    "indexed_frontier_size": str(header.header_size),
                }
                db.executemany(
                    "INSERT INTO metadata(key, value) VALUES(?, ?)",
                    sorted(metadata.items()),
                )
                db.execute(f"PRAGMA user_version = {SQLITE_USER_VERSION}")
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                raise
            return
        if tables != {"metadata", "nodes", "edges"}:
            raise ProofDAGIntegrityError(
                f"unexpected SQLite table set: {sorted(tables)}"
            )
        executable_objects = self._db.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE type IN ('trigger', 'view') ORDER BY type, name"
        ).fetchall()
        if executable_objects:
            rendered = [f"{row['type']}:{row['name']}" for row in executable_objects]
            raise ProofDAGIntegrityError(
                f"unexpected executable SQLite schema objects: {rendered}"
            )
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != SQLITE_USER_VERSION:
            raise ProofDAGIntegrityError(
                f"unsupported SQLite proof-DAG schema version {version}"
            )
        self._validated_metadata()

    def _validated_metadata(self) -> dict[str, str]:
        rows = self._db.execute("SELECT key, value FROM metadata ORDER BY key").fetchall()
        metadata = {row["key"]: row["value"] for row in rows}
        if set(metadata) != _META_KEYS:
            raise ProofDAGIntegrityError(
                "SQLite metadata keys differ from the proof-DAG schema"
            )
        if metadata["schema"] != DAG_INDEX_SCHEMA:
            raise ProofDAGIntegrityError("SQLite proof-DAG schema identifier mismatch")
        if metadata["rule_profile_id"] != self.rule_profile_id:
            raise ProofDAGIntegrityError("SQLite rule profile does not match the frontier")
        for key in ("indexed_record_count", "indexed_frontier_size"):
            try:
                parsed = int(metadata[key])
            except (TypeError, ValueError) as exc:
                raise ProofDAGIntegrityError(f"SQLite metadata {key} is not an integer") from exc
            if parsed < 0 or str(parsed) != metadata[key]:
                raise ProofDAGIntegrityError(f"SQLite metadata {key} is not canonical")
        return metadata

    def _node_row(self, node_sha256: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM nodes WHERE node_sha256 = ?",
            (node_sha256,),
        ).fetchone()

    def _edge_row(self, content_sha256: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM edges WHERE frontier_content_sha256 = ?",
            (content_sha256,),
        ).fetchone()

    @staticmethod
    def _node_columns(expected: _ExpectedNode) -> tuple[object, ...]:
        return (
            expected.node_sha256,
            expected.index_key64,
            expected.rule_profile_id,
            expected.fen,
            expected.history_json,
            expected.position_sha256,
            expected.game_state_sha256,
            expected.first_frontier_record_index,
            WDL.UNKNOWN.value,
        )

    @staticmethod
    def _edge_columns(expected: _ExpectedEdge) -> tuple[object, ...]:
        return (
            expected.frontier_content_sha256,
            expected.frontier_record_index,
            expected.frame_offset,
            expected.frame_end_offset,
            expected.frontier_crc32,
            expected.parent_frontier_content_sha256,
            expected.parent_node_sha256,
            expected.child_node_sha256,
            expected.action_json,
            expected.lineage_json,
        )

    @staticmethod
    def _actual_node_columns(row: sqlite3.Row) -> tuple[object, ...]:
        return tuple(
            row[name]
            for name in (
                "node_sha256",
                "index_key64",
                "rule_profile_id",
                "fen",
                "history_json",
                "position_sha256",
                "game_state_sha256",
                "first_frontier_record_index",
                "wdl",
            )
        )

    @staticmethod
    def _actual_edge_columns(row: sqlite3.Row) -> tuple[object, ...]:
        return tuple(
            row[name]
            for name in (
                "frontier_content_sha256",
                "frontier_record_index",
                "frame_offset",
                "frame_end_offset",
                "frontier_crc32",
                "parent_frontier_content_sha256",
                "parent_node_sha256",
                "child_node_sha256",
                "action_json",
                "lineage_json",
            )
        )

    def _checked_parent_node_for_entry(self, entry: FrontierEntry) -> DAGNode | None:
        """Reconstruct the exact prior node named by an edge occurrence."""

        parent = entry.record.parent_content_sha256
        if parent is None:
            return None
        row = self._edge_row(parent)
        if row is None:
            raise ProofDAGIntegrityError(
                f"frontier record {entry.content_sha256} references missing/forward parent {parent}"
            )
        if entry.record_index is None or row["frontier_record_index"] >= entry.record_index:
            raise ProofDAGIntegrityError("frontier parent must precede its child record")
        node_row = self._node_row(row["child_node_sha256"])
        if node_row is None:
            raise ProofDAGIntegrityError("frontier parent edge references an absent exact node")
        parent_node = self._checked_node_from_row(node_row)
        if parent_node.node_sha256 != row["child_node_sha256"]:
            raise ProofDAGIntegrityError("frontier parent node reconstruction changed its identity")
        return parent_node

    @staticmethod
    def _derive_move_child(
        parent: DAGNode,
        uci: str,
    ) -> tuple[Position, HistoryContext]:
        """Derive one exact child under the canonical classical rule profile."""

        if not isinstance(uci, str):
            raise ValueError("state edge UCI must be a string")
        if automatic_status(parent.position, parent.history).terminal:
            raise ValueError("a terminal parent state cannot have a move child")
        try:
            move = parse_uci_move(parent.position, uci)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"state edge UCI is not a legal move: {exc}") from exc
        if uci != move.uci():
            raise ValueError(
                f"state edge UCI must be canonical {move.uci()!r}, got {uci!r}"
            )
        child = apply_move(parent.position, move)
        return child, parent.history.push(child)

    def _validate_transition(self, entry: FrontierEntry) -> str | None:
        """Validate root/move semantics independently of caller metadata."""

        action = entry.record.payload_record()["action"]
        parent = self._checked_parent_node_for_entry(entry)
        if parent is None:
            if action is not None:
                raise ProofDAGIntegrityError("root frontier records must not carry an action")
            return None
        try:
            uci = _move_uci_from_action(action)
            expected_position, expected_history = self._derive_move_child(parent, uci)
        except ValueError as exc:
            raise ProofDAGIntegrityError(f"invalid non-root state edge: {exc}") from exc

        record = entry.record
        if record.fen != expected_position.to_fen() or record.position != expected_position:
            raise ProofDAGIntegrityError(
                "non-root state edge child differs from exact legal move result"
            )
        if record.history != expected_history:
            raise ProofDAGIntegrityError(
                "non-root state edge history differs from parent HistoryContext.push(child)"
            )
        expected_record = FrontierRecord(
            expected_position,
            expected_history,
            rule_profile_id=self.rule_profile_id,
        )
        if (
            record.position_sha256 != expected_record.position_sha256
            or record.game_state_sha256 != expected_record.game_state_sha256
        ):
            raise ProofDAGIntegrityError(
                "non-root state edge fails exact position/game-state identity reconstruction"
            )
        return parent.node_sha256

    def _ensure_node(self, expected: _ExpectedNode) -> None:
        row = self._node_row(expected.node_sha256)
        if row is None:
            self._db.execute(
                """
                INSERT INTO nodes(
                    node_sha256,index_key64,rule_profile_id,fen,history_json,
                    position_sha256,game_state_sha256,first_frontier_record_index,wdl
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                self._node_columns(expected),
            )
            return
        actual = self._actual_node_columns(row)
        wanted = list(self._node_columns(expected))
        # A repeated state keeps the earliest occurrence as provenance.
        wanted[7] = actual[7]
        if actual != tuple(wanted):
            raise ProofDAGIntegrityError(
                f"node content-address collision or SQLite divergence for {expected.node_sha256}"
            )
        if row["first_frontier_record_index"] > expected.first_frontier_record_index:
            raise ProofDAGIntegrityError("node first-occurrence index is after a known occurrence")

    def _insert_entry(self, entry: FrontierEntry) -> None:
        parent_node = self._validate_transition(entry)
        expected_node = _expected_node(entry)
        self._ensure_node(expected_node)
        expected_edge = _expected_edge(entry, expected_node, parent_node)
        existing = self._edge_row(expected_edge.frontier_content_sha256)
        if existing is not None:
            raise ProofDAGIntegrityError(
                f"duplicate frontier content address at record {entry.record_index}"
            )
        self._db.execute(
            """
            INSERT INTO edges(
                frontier_content_sha256,frontier_record_index,frame_offset,
                frame_end_offset,frontier_crc32,parent_frontier_content_sha256,
                parent_node_sha256,child_node_sha256,action_json,lineage_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            self._edge_columns(expected_edge),
        )

    def _validate_indexed_entry(self, entry: FrontierEntry, row: sqlite3.Row) -> None:
        expected_node = _expected_node(entry)
        node_row = self._node_row(expected_node.node_sha256)
        if node_row is None:
            raise ProofDAGIntegrityError(
                f"SQLite edge {entry.record_index} references an absent exact node"
            )
        wanted_node = list(self._node_columns(expected_node))
        wanted_node[7] = node_row["first_frontier_record_index"]
        if self._actual_node_columns(node_row) != tuple(wanted_node):
            raise ProofDAGIntegrityError(
                f"SQLite node differs from frontier state at record {entry.record_index}"
            )
        parent_node = self._validate_transition(entry)
        expected_edge = _expected_edge(entry, expected_node, parent_node)
        if self._actual_edge_columns(row) != self._edge_columns(expected_edge):
            raise ProofDAGIntegrityError(
                f"SQLite edge differs from frontier record {entry.record_index}"
            )

    def _reconcile_valid_frontier_suffix(self) -> None:
        metadata = self._validated_metadata()
        db_count = self._db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        if int(metadata["indexed_record_count"]) != db_count:
            raise ProofDAGIntegrityError("SQLite indexed count metadata diverges from edge rows")
        if db_count:
            boundary = self._db.execute(
                """
                SELECT MIN(frontier_record_index), MAX(frontier_record_index),
                       MAX(frame_end_offset)
                FROM edges
                """
            ).fetchone()
            if boundary[0] != 0 or boundary[1] != db_count - 1:
                raise ProofDAGIntegrityError("SQLite frontier record indexes are not contiguous")
            indexed_size = boundary[2]
        else:
            header = self._frontier_writer.header
            assert header is not None
            indexed_size = header.header_size
        if int(metadata["indexed_frontier_size"]) != indexed_size:
            raise ProofDAGIntegrityError("SQLite frontier-size metadata diverges from its prefix")
        # Reject every non-prefix inconsistency before adding a recoverable
        # frontier suffix.  Recovery may extend a sound derived index; it must
        # never mutate an index that is already internally divergent.
        self._validate_index_graph_invariants()

        cursor = self._db.execute(
            "SELECT * FROM edges WHERE frontier_record_index < ? "
            "ORDER BY frontier_record_index",
            (db_count,),
        )
        suffix_started = False
        count = 0
        last_end = indexed_size
        try:
            for entry in FrontierReader(self.frontier_path).iter_entries():
                count += 1
                last_end = entry.frame_end_offset
                if entry.record_index is not None and entry.record_index < db_count:
                    row = cursor.fetchone()
                    if row is None:
                        raise ProofDAGIntegrityError("SQLite index ended before its declared count")
                    self._validate_indexed_entry(entry, row)
                    continue
                if not suffix_started:
                    self._db.execute("BEGIN IMMEDIATE")
                    suffix_started = True
                self._insert_entry(entry)
            if count < db_count or cursor.fetchone() is not None:
                raise ProofDAGIntegrityError("SQLite has records beyond the frontier journal")
            if suffix_started:
                self._db.execute(
                    "UPDATE metadata SET value = ? WHERE key = 'indexed_record_count'",
                    (str(count),),
                )
                self._db.execute(
                    "UPDATE metadata SET value = ? WHERE key = 'indexed_frontier_size'",
                    (str(last_end),),
                )
                self._db.execute("COMMIT")
            elif int(metadata["indexed_frontier_size"]) != self.frontier_path.stat().st_size:
                raise ProofDAGIntegrityError("SQLite prefix boundary differs from frontier size")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise

    def _audit_or_raise(self) -> DAGAuditReport:
        quick_check = self._db.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise ProofDAGIntegrityError(f"SQLite quick_check failed: {quick_check}")
        metadata = self._validated_metadata()
        edge_cursor = self._db.execute(
            "SELECT * FROM edges ORDER BY frontier_record_index"
        )
        frontier_count = 0
        frontier_size = 0
        for entry in FrontierReader(self.frontier_path).iter_entries():
            frontier_count += 1
            frontier_size = entry.frame_end_offset
            row = edge_cursor.fetchone()
            if row is None:
                raise ProofDAGIntegrityError("frontier has an unindexed record")
            self._validate_indexed_entry(entry, row)
        if edge_cursor.fetchone() is not None:
            raise ProofDAGIntegrityError("SQLite has an edge absent from the frontier")
        if frontier_count == 0:
            header = self._frontier_writer.header
            assert header is not None
            frontier_size = header.header_size
        edge_count = self._db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        node_count = self._db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        self._validate_index_graph_invariants()
        if int(metadata["indexed_record_count"]) != frontier_count:
            raise ProofDAGIntegrityError("SQLite count metadata differs from frontier replay")
        if int(metadata["indexed_frontier_size"]) != frontier_size:
            raise ProofDAGIntegrityError("SQLite size metadata differs from frontier replay")
        return DAGAuditReport(
            True,
            frontier_count,
            edge_count,
            node_count,
            frontier_size,
        )

    def _validate_index_graph_invariants(self) -> None:
        orphan = self._db.execute(
            """
            SELECT node_sha256 FROM nodes
            WHERE NOT EXISTS (
                SELECT 1 FROM edges WHERE edges.child_node_sha256 = nodes.node_sha256
            ) LIMIT 1
            """
        ).fetchone()
        if orphan is not None:
            raise ProofDAGIntegrityError(f"SQLite contains orphan node {orphan[0]}")
        bad_first = self._db.execute(
            """
            SELECT nodes.node_sha256
            FROM nodes
            JOIN (
                SELECT child_node_sha256, MIN(frontier_record_index) AS first_index
                FROM edges GROUP BY child_node_sha256
            ) AS occurrences
              ON occurrences.child_node_sha256 = nodes.node_sha256
            WHERE nodes.first_frontier_record_index != occurrences.first_index
            LIMIT 1
            """
        ).fetchone()
        if bad_first is not None:
            raise ProofDAGIntegrityError(
                f"SQLite node has spoofed first occurrence: {bad_first[0]}"
            )

    def audit(self) -> DAGAuditReport:
        """Replay the complete frontier and compare every SQLite field."""

        edge_count = 0
        node_count = 0
        try:
            edge_count = self._db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            node_count = self._db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            return self._audit_or_raise()
        except (FrontierError, ProofDAGError, sqlite3.DatabaseError, OSError, ValueError) as exc:
            try:
                frontier_size = self.frontier_path.stat().st_size
            except OSError:
                frontier_size = 0
            return DAGAuditReport(
                False,
                0,
                edge_count,
                node_count,
                frontier_size,
                (str(exc),),
            )

    def _checked_node_from_row(self, row: sqlite3.Row) -> DAGNode:
        if row["rule_profile_id"] != self.rule_profile_id or row["wdl"] != WDL.UNKNOWN.value:
            raise ProofDAGIntegrityError("node rule profile or WDL is not authoritative UNKNOWN")
        try:
            position = Position.from_fen(row["fen"], strict=True)
        except (TypeError, ValueError) as exc:
            raise ProofDAGIntegrityError(f"stored node FEN is invalid: {exc}") from exc
        if position.to_fen() != row["fen"]:
            raise ProofDAGIntegrityError("stored node FEN is not canonical")
        history = _history_from_json(row["history_json"])
        try:
            reconstructed = FrontierRecord(
                position,
                history,
                rule_profile_id=self.rule_profile_id,
            )
        except (TypeError, ValueError) as exc:
            raise ProofDAGIntegrityError(f"stored node state is invalid: {exc}") from exc
        expected = _ExpectedNode(
            node_sha256=_node_sha256(reconstructed),
            fen=reconstructed.fen,
            history_json=_history_json(reconstructed.history),
            rule_profile_id=reconstructed.rule_profile_id,
            position_sha256=reconstructed.position_sha256,
            game_state_sha256=reconstructed.game_state_sha256,
            index_key64=_index_key_blob(compact_key64(reconstructed.position)),
            first_frontier_record_index=row["first_frontier_record_index"],
        )
        if self._actual_node_columns(row) != self._node_columns(expected):
            raise ProofDAGIntegrityError("SQLite node fails exact-state reconstruction")
        minimum = self._db.execute(
            "SELECT MIN(frontier_record_index) FROM edges WHERE child_node_sha256 = ?",
            (expected.node_sha256,),
        ).fetchone()[0]
        if minimum is None or minimum != expected.first_frontier_record_index:
            raise ProofDAGIntegrityError("SQLite node first occurrence is not backed by an edge")
        return DAGNode(
            node_sha256=expected.node_sha256,
            position=position,
            history=history,
            rule_profile_id=expected.rule_profile_id,
            position_sha256=expected.position_sha256,
            game_state_sha256=expected.game_state_sha256,
            index_key64=_index_key_int(expected.index_key64),
            first_frontier_record_index=expected.first_frontier_record_index,
        )

    def get_node(self, node_sha256: str) -> DAGNode | None:
        node_sha256 = _require_sha256(node_sha256, label="node content address")
        row = self._node_row(node_sha256)
        return None if row is None else self._checked_node_from_row(row)

    def find_nodes_by_index_key(self, index_key64: int) -> tuple[DAGNode, ...]:
        """Return every exact node under a non-unique 64-bit lookup hint."""

        key = _index_key_blob(index_key64)
        rows = self._db.execute(
            "SELECT * FROM nodes WHERE index_key64 = ? ORDER BY node_sha256",
            (key,),
        ).fetchall()
        # Reconstruction is mandatory: a spoofed key never redirects lookup.
        return tuple(self._checked_node_from_row(row) for row in rows)

    def _checked_edge_from_row(self, row: sqlite3.Row) -> DAGEdge:
        content_sha256 = _require_sha256(
            row["frontier_content_sha256"],
            label="frontier content address",
        )
        entry = FrontierReader(self.frontier_path).read_entry_at(
            row["frame_offset"],
            expected_content_sha256=content_sha256,
        )
        entry = FrontierEntry(
            record_index=row["frontier_record_index"],
            frame_offset=entry.frame_offset,
            frame_end_offset=entry.frame_end_offset,
            payload_offset=entry.payload_offset,
            payload_length=entry.payload_length,
            sha256_offset=entry.sha256_offset,
            crc32_offset=entry.crc32_offset,
            content_sha256=entry.content_sha256,
            crc32=entry.crc32,
            record=entry.record,
        )
        self._validate_indexed_entry(entry, row)
        try:
            action = json.loads(row["action_json"])
            lineage = json.loads(row["lineage_json"])
        except json.JSONDecodeError as exc:
            raise ProofDAGIntegrityError("edge metadata is not valid JSON") from exc
        return DAGEdge(
            frontier_content_sha256=content_sha256,
            frontier_record_index=row["frontier_record_index"],
            frame_offset=row["frame_offset"],
            frame_end_offset=row["frame_end_offset"],
            frontier_crc32=row["frontier_crc32"],
            parent_frontier_content_sha256=row["parent_frontier_content_sha256"],
            parent_node_sha256=row["parent_node_sha256"],
            child_node_sha256=row["child_node_sha256"],
            action=action,
            lineage=lineage,
        )

    def get_edge(self, frontier_content_sha256: str) -> DAGEdge | None:
        frontier_content_sha256 = _require_sha256(
            frontier_content_sha256,
            label="frontier content address",
        )
        row = self._edge_row(frontier_content_sha256)
        return None if row is None else self._checked_edge_from_row(row)

    def incoming_edges(self, node_sha256: str) -> tuple[DAGEdge, ...]:
        node_sha256 = _require_sha256(node_sha256, label="node content address")
        rows = self._db.execute(
            "SELECT * FROM edges WHERE child_node_sha256 = ? ORDER BY frontier_record_index",
            (node_sha256,),
        ).fetchall()
        return tuple(self._checked_edge_from_row(row) for row in rows)

    def outgoing_edges(self, node_sha256: str) -> tuple[DAGEdge, ...]:
        node_sha256 = _require_sha256(node_sha256, label="node content address")
        rows = self._db.execute(
            "SELECT * FROM edges WHERE parent_node_sha256 = ? ORDER BY frontier_record_index",
            (node_sha256,),
        ).fetchall()
        return tuple(self._checked_edge_from_row(row) for row in rows)

    def iter_nodes(self) -> Iterator[DAGNode]:
        for row in self._db.execute("SELECT * FROM nodes ORDER BY node_sha256"):
            yield self._checked_node_from_row(row)

    def iter_edges(self) -> Iterator[DAGEdge]:
        for row in self._db.execute("SELECT * FROM edges ORDER BY frontier_record_index"):
            yield self._checked_edge_from_row(row)

    def _append_record(
        self,
        position: Position,
        history: HistoryContext,
        *,
        parent_frontier_content_sha256: str | None = None,
        action: Any = None,
        lineage: Any = None,
    ) -> DAGAppendResult:
        """Append an already validated root or move record."""

        if self._failed_append:
            raise ProofDAGCommitError("reopen the proof DAG after the failed append")
        if parent_frontier_content_sha256 is not None:
            parent_frontier_content_sha256 = _require_sha256(
                parent_frontier_content_sha256,
                label="parent frontier content address",
            )
            if self.get_edge(parent_frontier_content_sha256) is None:
                raise ValueError("parent frontier content address is not indexed")
        record = FrontierRecord(
            position=position,
            history=history,
            parent_content_sha256=parent_frontier_content_sha256,
            action=action,
            lineage=lineage,
            rule_profile_id=self.rule_profile_id,
        )
        existing_row = self._edge_row(record.content_sha256)
        if existing_row is not None:
            edge = self._checked_edge_from_row(existing_row)
            node = self.get_node(edge.child_node_sha256)
            assert node is not None
            return DAGAppendResult(node, edge, False)

        appended = False
        self._db.execute("BEGIN IMMEDIATE")
        try:
            metadata = self._validated_metadata()
            edge_count = self._db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            frontier_size = self.frontier_path.stat().st_size
            if int(metadata["indexed_record_count"]) != edge_count:
                raise ProofDAGIntegrityError("SQLite count changed before append")
            if int(metadata["indexed_frontier_size"]) != frontier_size:
                raise ProofDAGIntegrityError("frontier/SQLite boundary changed before append")
            entry = self._frontier_writer.append(record, fsync=True)
            appended = True
            if entry.record_index != edge_count or entry.frame_offset != frontier_size:
                raise ProofDAGIntegrityError("frontier writer returned a noncontiguous append")
            self._insert_entry(entry)
            self._db.execute(
                "UPDATE metadata SET value = ? WHERE key = 'indexed_record_count'",
                (str(edge_count + 1),),
            )
            self._db.execute(
                "UPDATE metadata SET value = ? WHERE key = 'indexed_frontier_size'",
                (str(entry.frame_end_offset),),
            )
            self._db.execute("COMMIT")
        except BaseException as exc:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            if appended:
                self._failed_append = True
                if self._writer is not None:
                    self._writer.close()
                raise ProofDAGCommitError(
                    "frontier append is durable but SQLite commit failed; reopen to replay suffix"
                ) from exc
            raise
        edge = self.get_edge(record.content_sha256)
        assert edge is not None
        node = self.get_node(edge.child_node_sha256)
        assert node is not None
        return DAGAppendResult(node, edge, True)

    def _exact_parent_for_move(
        self,
        parent_frontier_content_sha256: str,
    ) -> tuple[str, DAGNode]:
        parent_frontier_content_sha256 = _require_sha256(
            parent_frontier_content_sha256,
            label="parent frontier content address",
        )
        parent_edge = self.get_edge(parent_frontier_content_sha256)
        if parent_edge is None:
            raise ValueError("parent frontier content address is not indexed")
        parent = self.get_node(parent_edge.child_node_sha256)
        if parent is None:
            raise ProofDAGIntegrityError("indexed parent edge has no exact parent node")
        return parent_frontier_content_sha256, parent

    def _validated_move_record_for_parent(
        self,
        child_position: Position,
        child_history: HistoryContext,
        *,
        parent_frontier_content_sha256: str,
        parent: DAGNode,
        uci: str,
        lineage: Any = None,
    ) -> FrontierRecord:
        expected_position, expected_history = self._derive_move_child(parent, uci)
        if not isinstance(child_position, Position):
            raise TypeError("child_position must be a Position")
        if (
            child_position.to_fen() != expected_position.to_fen()
            or child_position != expected_position
        ):
            raise ValueError("supplied child position differs from exact legal move result")
        try:
            supplied = FrontierRecord(
                child_position,
                child_history,
                rule_profile_id=self.rule_profile_id,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"supplied child state is invalid: {exc}") from exc
        expected = FrontierRecord(
            expected_position,
            expected_history,
            parent_content_sha256=parent_frontier_content_sha256,
            action={"kind": "move", "uci": uci},
            lineage=lineage,
            rule_profile_id=self.rule_profile_id,
        )
        if supplied.history != expected_history:
            raise ValueError(
                "supplied child history differs from parent HistoryContext.push(child)"
            )
        if (
            supplied.position_sha256 != expected.position_sha256
            or supplied.game_state_sha256 != expected.game_state_sha256
        ):
            raise ValueError("supplied child fails exact position/game-state identity match")
        payload = expected.payload_bytes()
        if len(payload) > MAX_RECORD_PAYLOAD_BYTES:
            raise ValueError(
                f"frontier record payload is {len(payload)} bytes; maximum is "
                f"{MAX_RECORD_PAYLOAD_BYTES}"
            )
        return expected

    def _validated_move_record(
        self,
        child_position: Position,
        child_history: HistoryContext,
        *,
        parent_frontier_content_sha256: str,
        uci: str,
        lineage: Any = None,
    ) -> FrontierRecord:
        """Prevalidate one exact move request without writing either authority."""

        parent_frontier_content_sha256, parent = self._exact_parent_for_move(
            parent_frontier_content_sha256
        )
        return self._validated_move_record_for_parent(
            child_position,
            child_history,
            parent_frontier_content_sha256=parent_frontier_content_sha256,
            parent=parent,
            uci=uci,
            lineage=lineage,
        )

    @staticmethod
    def _bounded_move_batch(
        requests: Iterable[DAGMoveAppendRequest],
    ) -> tuple[DAGMoveAppendRequest, ...]:
        try:
            iterator = iter(requests)
        except TypeError as exc:
            raise TypeError("requests must be an iterable of DAGMoveAppendRequest") from exc
        items: list[DAGMoveAppendRequest] = []
        for item in iterator:
            if len(items) >= MAX_MOVE_APPEND_BATCH:
                raise ValueError(
                    f"move append batch exceeds maximum {MAX_MOVE_APPEND_BATCH} requests"
                )
            if not isinstance(item, DAGMoveAppendRequest):
                raise TypeError("every batch item must be a DAGMoveAppendRequest")
            items.append(item)
        return tuple(items)

    def _existing_result_for_record(
        self,
        payload_bytes: bytes,
        content_sha256: str,
    ) -> DAGAppendResult | None:
        row = self._edge_row(content_sha256)
        if row is None:
            return None
        edge = self._checked_edge_from_row(row)
        entry = FrontierReader(self.frontier_path).read_entry_at(
            edge.frame_offset,
            expected_content_sha256=content_sha256,
        )
        if entry.record.payload_bytes() != payload_bytes:
            raise ProofDAGIntegrityError(
                "frontier SHA-256 collision between distinct canonical records"
            )
        node = self.get_node(edge.child_node_sha256)
        if node is None:
            raise ProofDAGIntegrityError("existing batch edge has no exact child node")
        return DAGAppendResult(node, edge, False)

    def append_moves_batch(
        self,
        requests: Iterable[DAGMoveAppendRequest],
    ) -> DAGMoveBatchAppendResult:
        """Append a deterministic bounded move batch with one frontier fsync.

        Every request and its complete canonical frontier payload is validated
        before the SQLite transaction begins or any frontier byte is written.
        Exact pre-existing records and later identical requests are returned in
        request order with ``appended=False`` and create no duplicate bytes.
        Distinct lineages remain distinct occurrences, matching
        :meth:`append_move` semantics.

        All parent occurrences must belong to the prefix present before the
        batch.  The method writes unique-new frames contiguously without fsync,
        performs one frontier sync, indexes every frame in one SQLite
        transaction, updates the boundary once, and commits once.  A failure
        after the first write attempt poisons the handle.  Fully written frames
        form the same replayable suffix used by ordinary append recovery; a
        physically torn final frame still requires explicit frontier recovery.
        The aggregate encoded-frame budget is bounded before mutation.  The
        underlying writer retains its per-frame lock; callers must not treat a
        single ``ProofDAG`` handle as a concurrently thread-safe batch object.
        """

        if self._failed_append:
            raise ProofDAGCommitError("reopen the proof DAG after the failed append")
        batch = self._bounded_move_batch(requests)

        prepared: list[_PreparedMoveAppend] = []
        payload_by_sha256: dict[str, bytes] = {}
        first_request_index: dict[str, int] = {}
        parent_cache: dict[str, tuple[str, DAGNode]] = {}
        aggregate_encoded_bytes = 0
        for index, request in enumerate(batch):
            cached_parent = parent_cache.get(request.parent_frontier_content_sha256)
            if cached_parent is None:
                cached_parent = self._exact_parent_for_move(
                    request.parent_frontier_content_sha256
                )
                parent_cache[cached_parent[0]] = cached_parent
            canonical_parent_sha256, parent = cached_parent
            record = self._validated_move_record_for_parent(
                request.child_position,
                request.child_history,
                parent_frontier_content_sha256=canonical_parent_sha256,
                parent=parent,
                uci=request.uci,
                lineage=request.lineage,
            )
            payload = record.payload_bytes()
            content_sha256 = hashlib.sha256(payload).hexdigest()
            aggregate_encoded_bytes += (
                RECORD_PREFIX_SIZE
                + len(payload)
                + RECORD_SHA256_SIZE
                + RECORD_CRC32_SIZE
            )
            if aggregate_encoded_bytes > MAX_MOVE_APPEND_BATCH_BYTES:
                raise ValueError(
                    "move append batch encoded bytes exceed maximum "
                    f"{MAX_MOVE_APPEND_BATCH_BYTES}"
                )
            prior_payload = payload_by_sha256.get(content_sha256)
            if prior_payload is not None and prior_payload != payload:
                raise ProofDAGIntegrityError(
                    "frontier SHA-256 collision inside move append batch"
                )
            payload_by_sha256.setdefault(content_sha256, payload)
            first_request_index.setdefault(content_sha256, index)
            prepared.append(
                _PreparedMoveAppend(request, record, payload, content_sha256)
            )

        metadata = self._validated_metadata()
        boundary_count = self._db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        boundary_size = self.frontier_path.stat().st_size
        if int(metadata["indexed_record_count"]) != boundary_count:
            raise ProofDAGIntegrityError("SQLite count changed before batch append")
        if int(metadata["indexed_frontier_size"]) != boundary_size:
            raise ProofDAGIntegrityError("frontier/SQLite boundary changed before batch append")

        resolved: dict[str, DAGAppendResult] = {}
        unique_new: list[_PreparedMoveAppend] = []
        seen_new: set[str] = set()
        for item in prepared:
            content_sha256 = item.content_sha256
            if content_sha256 in resolved or content_sha256 in seen_new:
                continue
            existing = self._existing_result_for_record(
                item.payload_bytes,
                content_sha256,
            )
            if existing is not None:
                resolved[content_sha256] = existing
            else:
                seen_new.add(content_sha256)
                unique_new.append(item)

        if not unique_new:
            ordered = tuple(resolved[item.content_sha256] for item in prepared)
            return DAGMoveBatchAppendResult(
                results=ordered,
                frontier_record_count_before=boundary_count,
                frontier_record_count_after=boundary_count,
                frontier_size_before=boundary_size,
                frontier_size_after=boundary_size,
            )

        write_attempted = False
        frontier_synced = False
        entries: list[FrontierEntry] = []
        writer = self._frontier_writer
        try:
            self._db.execute("BEGIN IMMEDIATE")
            metadata = self._validated_metadata()
            edge_count = self._db.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            frontier_size = self.frontier_path.stat().st_size
            if edge_count != boundary_count or frontier_size != boundary_size:
                raise ProofDAGIntegrityError(
                    "proof DAG boundary moved after batch prevalidation"
                )
            if int(metadata["indexed_record_count"]) != edge_count:
                raise ProofDAGIntegrityError("SQLite count changed before batch write")
            if int(metadata["indexed_frontier_size"]) != frontier_size:
                raise ProofDAGIntegrityError(
                    "frontier/SQLite boundary changed before batch write"
                )

            next_offset = frontier_size
            for ordinal, item in enumerate(unique_new, start=edge_count):
                write_attempted = True
                entry = writer.append(item.record, fsync=False)
                if (
                    entry.record_index != ordinal
                    or entry.frame_offset != next_offset
                    or entry.content_sha256 != item.content_sha256
                ):
                    raise ProofDAGIntegrityError(
                        "frontier writer returned a noncontiguous batch append"
                    )
                entries.append(entry)
                next_offset = entry.frame_end_offset

            writer.sync()
            frontier_synced = True
            for entry in entries:
                self._insert_entry(entry)
            self._db.execute(
                "UPDATE metadata SET value = ? WHERE key = 'indexed_record_count'",
                (str(edge_count + len(entries)),),
            )
            self._db.execute(
                "UPDATE metadata SET value = ? WHERE key = 'indexed_frontier_size'",
                (str(next_offset),),
            )
            self._db.execute("COMMIT")

            if self.frontier_path.stat().st_size != next_offset:
                raise ProofDAGIntegrityError(
                    "frontier size changed after committed batch append"
                )
            for item in unique_new:
                edge = self.get_edge(item.content_sha256)
                if edge is None:
                    raise ProofDAGIntegrityError(
                        "committed batch edge is absent from the exact index"
                    )
                node = self.get_node(edge.child_node_sha256)
                if node is None:
                    raise ProofDAGIntegrityError(
                        "committed batch edge has no exact child node"
                    )
                resolved[item.content_sha256] = DAGAppendResult(
                    node,
                    edge,
                    True,
                )

            ordered_results: list[DAGAppendResult] = []
            new_hashes = {item.content_sha256 for item in unique_new}
            for index, item in enumerate(prepared):
                base = resolved[item.content_sha256]
                appended = (
                    item.content_sha256 in new_hashes
                    and first_request_index[item.content_sha256] == index
                )
                ordered_results.append(DAGAppendResult(base.node, base.edge, appended))
            return DAGMoveBatchAppendResult(
                results=tuple(ordered_results),
                frontier_record_count_before=edge_count,
                frontier_record_count_after=edge_count + len(entries),
                frontier_size_before=frontier_size,
                frontier_size_after=next_offset,
            )
        except BaseException as exc:
            rollback_failure: BaseException | None = None
            if self._db.in_transaction:
                try:
                    self._db.execute("ROLLBACK")
                except BaseException as rollback_exc:
                    rollback_failure = rollback_exc
            if write_attempted or rollback_failure is not None:
                self._failed_append = True
                try:
                    self.close()
                except BaseException:
                    pass
                if write_attempted:
                    durability = (
                        "the complete frontier batch was synced"
                        if frontier_synced
                        else "the frontier may contain a complete or torn batch prefix"
                    )
                else:
                    durability = "the SQLite batch transaction could not be rolled back"
                rollback_detail = (
                    "; SQLite rollback also failed"
                    if rollback_failure is not None
                    else ""
                )
                raise ProofDAGCommitError(
                    f"{durability}{rollback_detail}; reopen to replay a valid suffix or explicitly "
                    "recover a torn final frame"
                ) from exc
            raise

    def append_move(
        self,
        child_position: Position,
        child_history: HistoryContext,
        *,
        parent_frontier_content_sha256: str,
        uci: str,
        lineage: Any = None,
    ) -> DAGAppendResult:
        """Append one exact legal-move child of a prior frontier occurrence.

        The parent is reconstructed from its content-addressed frontier edge
        and exact SQLite node.  ``uci`` must already be the canonical lowercase
        legal token.  The implementation recomputes both ``apply_move`` and
        ``HistoryContext.push``; caller-supplied child state is comparison data,
        never authority.  Draw claims are actions without a child and therefore
        are deliberately outside this state-edge API.
        """

        expected = self._validated_move_record(
            child_position,
            child_history,
            parent_frontier_content_sha256=parent_frontier_content_sha256,
            uci=uci,
            lineage=lineage,
        )
        return self._append_record(
            expected.position,
            expected.history,
            parent_frontier_content_sha256=expected.parent_content_sha256,
            action=expected.action,
            lineage=expected.lineage,
        )

    def append_state(
        self,
        position: Position,
        history: HistoryContext,
        *,
        parent_frontier_content_sha256: str | None = None,
        action: Any = None,
        lineage: Any = None,
    ) -> DAGAppendResult:
        """Compatibility path that accepts only a canonical move state edge.

        New callers should use :meth:`append_move`.  Root creation is explicit
        through :meth:`append_root`; arbitrary dependency/claim metadata cannot
        create a child state.
        """

        if parent_frontier_content_sha256 is None:
            raise ValueError("append_state cannot create roots; use append_root")
        uci = _move_uci_from_action(action)
        return self.append_move(
            position,
            history,
            parent_frontier_content_sha256=parent_frontier_content_sha256,
            uci=uci,
            lineage=lineage,
        )

    def append_root(
        self,
        position: Position,
        history: HistoryContext,
        *,
        lineage: Any = None,
    ) -> DAGAppendResult:
        return self._append_record(position, history, lineage=lineage)

    def close(self) -> None:
        writer = self._writer
        connection = self._connection
        self._writer = None
        self._connection = None
        try:
            if writer is not None:
                writer.close()
        finally:
            if connection is not None:
                connection.close()

    def __enter__(self) -> "ProofDAG":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


__all__ = [
    "DAG_INDEX_SCHEMA",
    "DAG_NODE_SCHEMA",
    "DAGAppendResult",
    "DAGAuditReport",
    "DAGEdge",
    "DAGMoveAppendRequest",
    "DAGMoveBatchAppendResult",
    "DAGNode",
    "MAX_MOVE_APPEND_BATCH",
    "MAX_MOVE_APPEND_BATCH_BYTES",
    "ProofDAG",
    "ProofDAGCommitError",
    "ProofDAGError",
    "ProofDAGIntegrityError",
    "node_identity_sha256",
]
