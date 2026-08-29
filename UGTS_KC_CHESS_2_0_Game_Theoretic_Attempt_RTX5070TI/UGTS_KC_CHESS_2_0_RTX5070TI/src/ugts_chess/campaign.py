"""SQLite-backed, hash-chained proof campaign ledger.

The campaign database coordinates work; it is not itself the mathematical
proof.  Workers may lease an obligation and attach a candidate certificate,
but only an independently recorded checker result changes the obligation to
``verified``.  Unverified values aggregate as UNKNOWN.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .game_state import (
    RULE_PROFILE_ID,
    HistoryContext,
    automatic_status,
    current_claim_actions,
    game_state_sha256,
    intended_move_claims,
)
from .game_theory import ProofObligation, WDL, aggregate_root_wdl, root_obligations
from .hashing import canonical_json_bytes, state_sha256
from .position import Position, START_FEN
from .wdl import WDLVerificationError, verify_wdl_certificate

SCHEMA = "ugts-chess-campaign-2.0"
GENESIS_HASH = hashlib.sha256(b"UGTS-CHESS2-CAMPAIGN-GENESIS").hexdigest()
DEDICATION = {
    "to": "Anna Cramling",
    "opening": "The Cow Opening",
    "scope": (
        "Attribution only: this dedication does not alter or exempt any of the "
        "20 legal root-move proof obligations for the classical initial position."
    ),
}
COW_PRIORITY = 10
COW_PRIORITY_POLICY = {
    "schema": "ugts-chess-scheduler-priority-1.0",
    "moves_uci": ["d2d3", "e2e3"],
    "priority": COW_PRIORITY,
    "boundary": "Scheduling hint only; it changes no proof obligation or verifier rule.",
}
COW_PRIORITY_MOVES = frozenset(COW_PRIORITY_POLICY["moves_uci"])
CANONICAL_COMPONENT = "ugts.application.chess.game-theoretic-solver@2.0.0"
CLAIM_BOUNDARY = "Only independently verified certificate records may set a child WDL."
ROOT_IDENTITY_SCHEMA = "ugts-chess-campaign-root-identity-1.0"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_for_storage(db_path: str | Path, path: str | Path) -> str:
    """Store package-local paths relative to the campaign database.

    Absolute paths make a campaign checkpoint impossible to move to another
    workstation.  Paths outside the database directory remain absolute because
    there is no safe portable relative reference for them.
    """

    base = Path(db_path).resolve().parent
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(base).as_posix()
    except ValueError:
        return str(resolved)


def _path_from_storage(db_path: str | Path, stored: str | Path) -> Path:
    path = Path(stored)
    if path.is_absolute():
        return path
    return Path(db_path).resolve().parent / path


def _read_hashed_json(path: Path, *, label: str) -> tuple[dict[str, Any], str]:
    """Read one immutable view of a JSON artifact and hash those exact bytes."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"{label} cannot be read: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload, digest


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _history_from_record(record: object, *, label: str) -> HistoryContext:
    """Parse one canonical, non-coercive repetition-history record."""

    if not isinstance(record, list):
        raise ValueError(f"{label} must be a list")
    pairs: list[tuple[str, int]] = []
    for item in record:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError(f"{label} contains a malformed entry")
        key, count = item
        if not _is_sha256(key):
            raise ValueError(f"{label} contains an invalid repetition key")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
            raise ValueError(f"{label} occurrence counts must be integers in 1..5")
        pairs.append((key, count))
    if pairs != sorted(pairs) or len({key for key, _ in pairs}) != len(pairs):
        raise ValueError(f"{label} must be unique and sorted")
    return HistoryContext(tuple(pairs))


def _load_meta(conn: sqlite3.Connection, errors: list[str]) -> dict[str, Any]:
    """Load metadata without allowing malformed JSON to crash an audit."""

    metadata: dict[str, Any] = {}
    for row in conn.execute("SELECT key,value FROM meta"):
        try:
            metadata[row["key"]] = json.loads(row["value"])
        except (TypeError, json.JSONDecodeError) as exc:
            errors.append(f"meta {row['key']!r} is invalid JSON: {exc}")
    return metadata


def _root_identity_sha256(position: Position, history: HistoryContext) -> str:
    """Hash the exact campaign root, including FEN counters and history."""

    return hashlib.sha256(
        canonical_json_bytes(
            {
                "schema": ROOT_IDENTITY_SCHEMA,
                "rules_profile": RULE_PROFILE_ID,
                "fen": position.to_fen(),
                "history_counts": history.record(),
            }
        )
    ).hexdigest()


def _canonical_campaign_root(meta: dict[str, Any]) -> tuple[Position, HistoryContext]:
    """Reconstruct and validate the proof-critical campaign root metadata."""

    if meta.get("schema") != SCHEMA:
        raise ValueError("campaign schema mismatch")
    if meta.get("canonical_component") != CANONICAL_COMPONENT:
        raise ValueError("campaign canonical component mismatch")
    if meta.get("rules_profile") != RULE_PROFILE_ID:
        raise ValueError("campaign rules profile mismatch")
    if meta.get("root_wdl") != WDL.UNKNOWN.value:
        raise ValueError("campaign initial root WDL metadata mismatch")
    if meta.get("claim_boundary") != CLAIM_BOUNDARY:
        raise ValueError("campaign claim boundary mismatch")

    root_fen = meta.get("root_fen")
    if not isinstance(root_fen, str):
        raise ValueError("root FEN must be a string")
    root = Position.from_fen(root_fen, strict=True)
    if root.to_fen() != root_fen:
        raise ValueError("root FEN is not canonical")
    root_history = _history_from_record(meta.get("root_history_counts"), label="root history")
    if root_history != HistoryContext.initial(root):
        raise ValueError("root history is not the initial history for the campaign position")
    if state_sha256(root) != meta.get("root_position_sha256"):
        raise ValueError("root position hash mismatch")
    if game_state_sha256(root, root_history) != meta.get("root_game_state_sha256"):
        raise ValueError("root game-state hash mismatch")
    return root, root_history


def _campaign_root_obligations(
    position: Position,
    history: HistoryContext,
) -> list[ProofObligation]:
    """Return move obligations only when the root is not automatically terminal."""

    if automatic_status(position, history).terminal:
        return []
    return root_obligations(position, history)


def _root_claim_action_ids(
    position: Position,
    history: HistoryContext,
    obligations: list[ProofObligation],
) -> tuple[str, ...]:
    """Return current and intended-move draw actions available at the root."""

    actions = [f"current:{code}" for code in current_claim_actions(position, history)]
    for obligation in obligations:
        child = Position.from_fen(obligation.child_fen, strict=True)
        child_history = HistoryContext(obligation.child_history_counts)
        for code in intended_move_claims(child, child_history):
            actions.append(f"move:{obligation.move_uci}:{code}")
    return tuple(actions)


def _aggregate_campaign_root_wdl(
    position: Position,
    history: HistoryContext,
    obligations: list[ProofObligation],
    child_outcomes: list[WDL],
) -> WDL:
    """Derive root WDL with automatic terminals and optional draw claims."""

    automatic = automatic_status(position, history)
    if automatic.terminal:
        return WDL.LOSS if automatic.code == "checkmate" else WDL.DRAW

    move_value = aggregate_root_wdl(child_outcomes)
    if move_value in (WDL.WIN, WDL.UNKNOWN):
        return move_value
    if _root_claim_action_ids(position, history, obligations):
        # With no winning move, an available claim prevents LOSS.  Unknown
        # children remain UNKNOWN above because one may still hide a win.
        return WDL.DRAW
    return move_value


def _canonical_obligation(
    meta: dict[str, Any],
    obligation_id: str,
) -> tuple[ProofObligation, str]:
    root, root_history = _canonical_campaign_root(meta)
    expected = next(
        (
            obligation
            for obligation in _campaign_root_obligations(root, root_history)
            if obligation.obligation_id == obligation_id
        ),
        None,
    )
    if expected is None:
        raise ValueError("obligation is not a canonical move from the campaign root")
    return expected, RULE_PROFILE_ID


def _require_canonical_obligation_row(row: sqlite3.Row, expected: ProofObligation) -> None:
    """Reject mutable job rows that no longer encode their canonical obligation."""

    checks: dict[str, object] = {
        "obligation_id": expected.obligation_id,
        "parent_game_state_sha256": expected.parent_game_state_sha256,
        "move_uci": expected.move_uci,
        "move_san": expected.move_san,
        "child_fen": expected.child_fen,
        "child_position_sha256": expected.child_position_sha256,
        "child_game_state_sha256": expected.child_game_state_sha256,
        "child_history_json": json.dumps(
            [[key, count] for key, count in expected.child_history_counts],
            separators=(",", ":"),
        ),
        "child_side_to_move": expected.child_side_to_move,
        "priority": COW_PRIORITY if expected.move_uci in COW_PRIORITY_MOVES else 0,
    }
    for field, wanted in checks.items():
        if row[field] != wanted:
            raise ValueError(
                f"{expected.obligation_id}: {field} does not match the canonical root obligation"
            )


def _certificate_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept either a bare WDL bundle or the bounded-solver result wrapper."""

    bundle = payload.get("certificate_bundle", payload)
    if not isinstance(bundle, dict):
        raise ValueError("candidate certificate bundle must be a JSON object")
    return bundle


def _verify_candidate_certificate(
    db_path: str | Path,
    row: sqlite3.Row,
    *,
    rules_profile: str,
    expected_obligation: ProofObligation,
) -> dict[str, object]:
    """Replay and bind a candidate proof to its exact campaign obligation."""

    stored_path = row["certificate_path"]
    stored_hash = row["certificate_sha256"]
    if not stored_path or not stored_hash:
        raise ValueError("candidate certificate path or hash is missing")
    certificate_path = _path_from_storage(db_path, stored_path)
    if not certificate_path.is_file():
        raise ValueError("candidate certificate file is missing")
    payload, actual_hash = _read_hashed_json(certificate_path, label="candidate certificate")
    if actual_hash != stored_hash:
        raise ValueError("candidate certificate hash does not match the recorded bytes")
    bundle = _certificate_bundle(payload)
    if rules_profile != RULE_PROFILE_ID:
        raise ValueError("campaign does not declare the canonical claims-as-actions rules profile")
    if bundle.get("rules_profile") != rules_profile:
        raise ValueError("candidate certificate rules profile does not match the campaign")
    try:
        verified = verify_wdl_certificate(bundle, allow_unknown_root=False)
    except WDLVerificationError as exc:
        raise ValueError(f"candidate WDL proof is invalid: {exc}") from exc
    except Exception as exc:
        # Any malformed-proof failure is a rejection at this trust boundary;
        # a verifier crash must never leave a path to promotion.
        raise ValueError(f"candidate WDL proof could not be verified: {exc}") from exc

    # verify_wdl_certificate recomputes the root node's state hash before
    # accepting the bundle-level summary, so this comparison binds the proof
    # to the history-correct child state rather than trusting certificate JSON.
    if bundle.get("root_state_hash") != expected_obligation.child_game_state_sha256:
        raise ValueError("candidate certificate root does not match the obligation child game state")
    root_hash = verified.get("root_certificate_hash")
    root_node = next(
        (
            node
            for node in bundle.get("nodes", [])
            if isinstance(node, dict) and node.get("certificate_hash") == root_hash
        ),
        None,
    )
    if root_node is None:
        raise ValueError("verified candidate certificate root node is missing")
    if root_node.get("fen") != expected_obligation.child_fen:
        raise ValueError("candidate certificate root FEN does not match the obligation child FEN")
    expected_history = HistoryContext(expected_obligation.child_history_counts)
    if root_node.get("history_counts") != expected_history.record():
        raise ValueError("candidate certificate root history does not match the obligation child history")
    if verified.get("root_exact") is not True:
        raise ValueError("candidate certificate root is UNKNOWN")
    if row["wdl"] not in (WDL.WIN.value, WDL.DRAW.value, WDL.LOSS.value):
        raise ValueError("candidate declares UNKNOWN or an invalid WDL")
    if verified.get("root_value") != row["wdl"]:
        raise ValueError("candidate certificate root WDL does not match the declared WDL")
    return verified


def _validate_checker_payload(
    payload: dict[str, Any],
    row: sqlite3.Row,
    obligation_id: str,
    verifier: str,
) -> None:
    required_checker: dict[str, object] = {
        "schema": "ugts-chess-independent-check-2.0",
        "obligation_id": obligation_id,
        "wdl": row["wdl"],
        "certificate_sha256": row["certificate_sha256"],
        "child_game_state_sha256": row["child_game_state_sha256"],
        "checker": verifier,
    }
    if payload.get("valid") is not True:
        raise ValueError("checker record field 'valid' must be true")
    for key, expected in required_checker.items():
        if payload.get(key) != expected:
            raise ValueError(f"checker record field {key!r} does not match the candidate")


def _connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    return conn


def _append_event(conn: sqlite3.Connection, action: str, payload: dict[str, Any], job_id: str | None = None) -> str:
    row = conn.execute("SELECT event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
    prev_hash = row["event_hash"] if row else GENESIS_HASH
    timestamp = _utc_now()
    record = {
        "action": action,
        "job_id": job_id,
        "payload": payload,
        "prev_hash": prev_hash,
        "timestamp": timestamp,
    }
    event_hash = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    conn.execute(
        "INSERT INTO events(timestamp,job_id,action,payload_json,prev_hash,event_hash) VALUES(?,?,?,?,?,?)",
        (timestamp, job_id, action, json.dumps(payload, sort_keys=True, separators=(",", ":")), prev_hash, event_hash),
    )
    return event_hash


def init_campaign(
    db_path: str | Path,
    shard_dir: str | Path,
    *,
    root_fen: str = START_FEN,
    force: bool = False,
) -> dict[str, Any]:
    db_path = Path(db_path)
    shard_dir = Path(shard_dir)
    if db_path.exists() and not force:
        raise FileExistsError(f"campaign database already exists: {db_path}")
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    shard_dir.mkdir(parents=True, exist_ok=True)
    for old in shard_dir.glob("root-*.json"):
        old.unlink()

    root = Position.from_fen(root_fen)
    root_history = HistoryContext.initial(root)
    obligations = _campaign_root_obligations(root, root_history)
    created_at = _utc_now()
    metadata = {
        "schema": SCHEMA,
        "created_at": created_at,
        "canonical_component": CANONICAL_COMPONENT,
        "root_fen": root.to_fen(),
        "root_position_sha256": state_sha256(root),
        "root_game_state_sha256": game_state_sha256(root, root_history),
        "root_history_counts": root_history.record(),
        "rules_profile": RULE_PROFILE_ID,
        "dedication": DEDICATION,
        "cow_opening_priority": COW_PRIORITY_POLICY,
        "root_wdl": "unknown",
        "claim_boundary": CLAIM_BOUNDARY,
    }

    with closing(_connect(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE jobs(
                obligation_id TEXT PRIMARY KEY,
                parent_game_state_sha256 TEXT NOT NULL,
                move_uci TEXT NOT NULL,
                move_san TEXT NOT NULL,
                child_fen TEXT NOT NULL,
                child_position_sha256 TEXT NOT NULL,
                child_game_state_sha256 TEXT NOT NULL,
                child_history_json TEXT NOT NULL,
                child_side_to_move TEXT NOT NULL,
                wdl TEXT NOT NULL DEFAULT 'unknown' CHECK(wdl IN ('win','draw','loss','unknown')),
                status TEXT NOT NULL DEFAULT 'unresolved' CHECK(status IN ('unresolved','leased','candidate','verified','rejected')),
                verification TEXT NOT NULL DEFAULT 'unverified',
                priority INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0,
                lease_owner TEXT,
                lease_expires TEXT,
                certificate_path TEXT,
                certificate_sha256 TEXT,
                checker_path TEXT,
                checker_sha256 TEXT,
                shard_path TEXT NOT NULL,
                shard_sha256 TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                job_id TEXT,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE
            );
            """
        )
        conn.executemany("INSERT INTO meta(key,value) VALUES(?,?)", [(key, json.dumps(value)) for key, value in metadata.items()])
        for obligation in obligations:
            record = obligation.to_dict()
            shard_path = shard_dir / f"{obligation.obligation_id}.json"
            shard_path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            shard_hash = _file_sha256(shard_path)
            conn.execute(
                """INSERT INTO jobs(
                    obligation_id,parent_game_state_sha256,move_uci,move_san,child_fen,
                    child_position_sha256,child_game_state_sha256,child_history_json,
                    child_side_to_move,priority,shard_path,shard_sha256,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    obligation.obligation_id,
                    obligation.parent_game_state_sha256,
                    obligation.move_uci,
                    obligation.move_san,
                    obligation.child_fen,
                    obligation.child_position_sha256,
                    obligation.child_game_state_sha256,
                    json.dumps([[key, count] for key, count in obligation.child_history_counts], separators=(",", ":")),
                    obligation.child_side_to_move,
                    COW_PRIORITY if obligation.move_uci in COW_PRIORITY_MOVES else 0,
                    _path_for_storage(db_path, shard_path),
                    shard_hash,
                    created_at,
                ),
            )
        _append_event(
            conn,
            "campaign_initialized",
            {
                "root_game_state_sha256": metadata["root_game_state_sha256"],
                "obligations": len(obligations),
                "root_wdl": "unknown",
            },
        )
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return {
        **metadata,
        "database": str(db_path),
        "shard_dir": str(shard_dir),
        "obligation_count": len(obligations),
    }


def lease_next(db_path: str | Path, worker: str, *, seconds: int = 900) -> dict[str, Any] | None:
    if not worker.strip():
        raise ValueError("worker name must be non-empty")
    now = datetime.now(UTC)
    expiry = (now + timedelta(seconds=max(1, seconds))).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    now_text = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT * FROM jobs
               WHERE status='unresolved' OR (status='leased' AND lease_expires < ?)
               ORDER BY priority DESC, attempts ASC, obligation_id ASC LIMIT 1""",
            (now_text,),
        ).fetchone()
        if row is None:
            conn.rollback()
            return None
        conn.execute(
            """UPDATE jobs SET status='leased',lease_owner=?,lease_expires=?,
               attempts=attempts+1,updated_at=? WHERE obligation_id=?""",
            (worker, expiry, now_text, row["obligation_id"]),
        )
        _append_event(conn, "job_leased", {"worker": worker, "lease_expires": expiry}, row["obligation_id"])
        conn.commit()
        return dict(conn.execute("SELECT * FROM jobs WHERE obligation_id=?", (row["obligation_id"],)).fetchone())


def record_candidate(
    db_path: str | Path,
    obligation_id: str,
    wdl: WDL | str,
    certificate_path: str | Path,
    *,
    worker: str,
) -> dict[str, Any]:
    if not worker.strip():
        raise ValueError("worker name must be non-empty")
    value = wdl if isinstance(wdl, WDL) else WDL(wdl)
    if value == WDL.UNKNOWN:
        raise ValueError("candidate WDL must be win, draw, or loss")
    certificate_path = Path(certificate_path).resolve()
    if not certificate_path.is_file():
        raise FileNotFoundError(certificate_path)
    certificate_hash = _file_sha256(certificate_path)
    now = _utc_now()
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM jobs WHERE obligation_id=?", (obligation_id,)).fetchone()
        if row is None:
            raise KeyError(obligation_id)
        if row["status"] == "verified":
            raise ValueError("verified job cannot be overwritten")
        if row["lease_owner"] not in (None, worker):
            raise PermissionError("job is leased to a different worker")
        conn.execute(
            """UPDATE jobs SET status='candidate',wdl=?,verification='pending-independent-check',
               certificate_path=?,certificate_sha256=?,checker_path=NULL,checker_sha256=NULL,
               lease_owner=NULL,lease_expires=NULL,updated_at=? WHERE obligation_id=?""",
            (value.value, _path_for_storage(db_path, certificate_path), certificate_hash, now, obligation_id),
        )
        _append_event(
            conn,
            "candidate_recorded",
            {"worker": worker, "wdl": value.value, "certificate_sha256": certificate_hash},
            obligation_id,
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM jobs WHERE obligation_id=?", (obligation_id,)).fetchone())


def mark_verified(
    db_path: str | Path,
    obligation_id: str,
    *,
    verifier: str,
    checker_record: str | Path,
) -> dict[str, Any]:
    if not verifier.strip():
        raise ValueError("verifier name must be non-empty")
    checker_record = Path(checker_record).resolve()
    if not checker_record.is_file():
        raise FileNotFoundError(checker_record)
    checker_payload, checker_hash = _read_hashed_json(checker_record, label="checker record")
    now = _utc_now()
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM jobs WHERE obligation_id=?", (obligation_id,)).fetchone()
        if row is None:
            raise KeyError(obligation_id)
        if row["status"] != "candidate" or not row["certificate_sha256"]:
            raise ValueError("only a complete candidate can be marked verified")
        metadata_errors: list[str] = []
        meta = _load_meta(conn, metadata_errors)
        if metadata_errors:
            raise ValueError(f"campaign metadata is invalid: {'; '.join(metadata_errors)}")
        try:
            expected, rules_profile = _canonical_obligation(meta, obligation_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"campaign root metadata is invalid: {exc}") from exc
        _require_canonical_obligation_row(row, expected)
        _validate_checker_payload(checker_payload, row, obligation_id, verifier)
        proof = _verify_candidate_certificate(
            db_path,
            row,
            rules_profile=rules_profile,
            expected_obligation=expected,
        )
        conn.execute(
            """UPDATE jobs SET status='verified',verification=?,checker_path=?,checker_sha256=?,
               updated_at=? WHERE obligation_id=?""",
            (f"independent-check:{verifier}", _path_for_storage(db_path, checker_record), checker_hash, now, obligation_id),
        )
        _append_event(
            conn,
            "candidate_verified",
            {
                "verifier": verifier,
                "checker_sha256": checker_hash,
                "wdl": row["wdl"],
                "root_certificate_hash": proof["root_certificate_hash"],
                "child_game_state_sha256": expected.child_game_state_sha256,
            },
            obligation_id,
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM jobs WHERE obligation_id=?", (obligation_id,)).fetchone())


def reject_candidate(db_path: str | Path, obligation_id: str, *, verifier: str, reason: str) -> dict[str, Any]:
    if not verifier.strip():
        raise ValueError("verifier name must be non-empty")
    if not reason.strip():
        raise ValueError("rejection reason must be non-empty")
    now = _utc_now()
    with closing(_connect(db_path)) as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM jobs WHERE obligation_id=?", (obligation_id,)).fetchone()
        if row is None:
            raise KeyError(obligation_id)
        if row["status"] not in ("candidate", "leased"):
            raise ValueError("only a candidate or leased job can be rejected")
        conn.execute(
            """UPDATE jobs SET status='rejected',verification=?,lease_owner=NULL,lease_expires=NULL,
               updated_at=? WHERE obligation_id=?""",
            (f"rejected:{verifier}:{reason}", now, obligation_id),
        )
        _append_event(conn, "candidate_rejected", {"verifier": verifier, "reason": reason}, obligation_id)
        conn.commit()
        return dict(conn.execute("SELECT * FROM jobs WHERE obligation_id=?", (obligation_id,)).fetchone())


def campaign_status(db_path: str | Path) -> dict[str, Any]:
    """Return operational counts with fail-closed, audit-derived solve status.

    The jobs table is a scheduler projection, not proof authority.  In
    particular, a row whose ``status``/``wdl`` fields were edited directly
    must never make this public status endpoint report a solved game.  Replay
    the complete campaign audit (including certificate verification) and use
    only its result for root WDL and verified-child claims.  ``game_solved``
    always refers to the declared campaign root; ``classical_initial_solved``
    is the narrower orthodox-chess claim.
    """

    audit = verify_campaign(db_path)
    audit_valid = audit.get("valid") is True
    try:
        audited_root = WDL(str(audit.get("root_wdl"))) if audit_valid else WDL.UNKNOWN
    except ValueError:
        # This should be unreachable for verify_campaign's own output, but the
        # public evidence boundary remains fail-closed if that contract ever
        # regresses.
        audit_valid = False
        audited_root = WDL.UNKNOWN

    with closing(_connect(db_path)) as conn:
        metadata_errors: list[str] = []
        meta = _load_meta(conn, metadata_errors)
        rows = list(conn.execute("SELECT obligation_id,status,wdl FROM jobs ORDER BY obligation_id"))
        counts: dict[str, int] = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        last = conn.execute("SELECT sequence,event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        audit_errors = list(audit.get("errors", []))
        audit_errors.extend(metadata_errors)
        public_audit_valid = audit_valid and not metadata_errors
        return {
            "schema": SCHEMA,
            "dedication": meta.get("dedication"),
            "cow_opening_priority": meta.get("cow_opening_priority"),
            "root_fen": audit.get("root_fen"),
            "root_position_sha256": audit.get("root_position_sha256"),
            "root_game_state_sha256": audit.get("root_game_state_sha256"),
            "root_identity_sha256": audit.get("root_identity_sha256"),
            "root_identity_schema": audit.get("root_identity_schema"),
            "root_automatic_code": audit.get("root_automatic_code"),
            "root_claim_actions": audit.get("root_claim_actions", []),
            "is_classical_initial_root": bool(audit.get("is_classical_initial_root")),
            "root_wdl": audited_root.value if public_audit_valid else WDL.UNKNOWN.value,
            "game_solved": public_audit_valid and audited_root != WDL.UNKNOWN,
            "game_solved_scope": "declared_campaign_root_only",
            "classical_initial_solved": (
                public_audit_valid and audit.get("classical_initial_solved") is True
            ),
            "obligations": len(rows),
            "status_counts": counts,
            "verified_children": int(audit.get("verified_children", 0)) if public_audit_valid else 0,
            "last_event_sequence": 0 if last is None else last["sequence"],
            "last_event_hash": None if last is None else last["event_hash"],
            "audit_valid": public_audit_valid,
            "audit_errors": audit_errors,
            "evidence_boundary": (
                "The declared root remains UNKNOWN unless audit proves an automatic terminal "
                "result or replays sufficient exact child certificates."
            ),
        }


def campaign_snapshot(db_path: str | Path) -> dict[str, Any]:
    status = campaign_status(db_path)
    with closing(_connect(db_path)) as conn:
        metadata = {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT key,value FROM meta")}
        jobs = []
        for row in conn.execute("SELECT * FROM jobs ORDER BY obligation_id"):
            item = dict(row)
            item["child_history_counts"] = json.loads(item.pop("child_history_json"))
            jobs.append(item)
        events = []
        for row in conn.execute("SELECT * FROM events ORDER BY sequence"):
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json"))
            events.append(item)
    return {"schema": SCHEMA, "metadata": metadata, "status": status, "jobs": jobs, "events": events}


def export_campaign(db_path: str | Path, output: str | Path) -> dict[str, Any]:
    output = Path(output)
    payload = campaign_snapshot(db_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(output), "sha256": _file_sha256(output), "jobs": len(payload["jobs"]), "events": len(payload["events"])}


def _audit_event_semantics(
    events: list[dict[str, Any]],
    rows: dict[str, sqlite3.Row],
    expected_obligations: dict[str, Any],
    verified_proofs: dict[str, dict[str, object]],
    root_game_state_sha256: object,
    errors: list[str],
) -> None:
    """Replay the append-only lifecycle instead of checking hashes alone."""

    if not events:
        errors.append("campaign has no initialization event")
        return

    first = events[0]
    expected_init_payload = {
        "root_game_state_sha256": root_game_state_sha256,
        "obligations": len(expected_obligations),
        "root_wdl": WDL.UNKNOWN.value,
    }
    if (
        first.get("sequence") != 1
        or first.get("action") != "campaign_initialized"
        or first.get("job_id") is not None
        or first.get("payload") != expected_init_payload
    ):
        errors.append("event 1 is not the canonical campaign initialization")

    replay: dict[str, dict[str, Any]] = {
        obligation_id: {
            "status": "unresolved",
            "wdl": WDL.UNKNOWN.value,
            "certificate_sha256": None,
            "checker_sha256": None,
            "verifier": None,
            "root_certificate_hash": None,
            "lease_owner": None,
            "lease_expires": None,
            "attempts": 0,
        }
        for obligation_id in expected_obligations
    }

    required_payload_keys = {
        "job_leased": {"worker", "lease_expires"},
        "candidate_recorded": {"worker", "wdl", "certificate_sha256"},
        "candidate_verified": {
            "verifier",
            "checker_sha256",
            "wdl",
            "root_certificate_hash",
            "child_game_state_sha256",
        },
        "candidate_rejected": {"verifier", "reason"},
    }

    for event in events[1:]:
        sequence = event.get("sequence")
        action = event.get("action")
        job_id = event.get("job_id")
        payload = event.get("payload")
        if action == "campaign_initialized":
            errors.append(f"event {sequence} repeats campaign initialization")
            continue
        if action not in required_payload_keys:
            errors.append(f"event {sequence} has unsupported action {action!r}")
            continue
        if job_id not in replay:
            errors.append(f"event {sequence} references an unknown obligation")
            continue
        if not isinstance(payload, dict) or set(payload) != required_payload_keys[action]:
            errors.append(f"event {sequence} has a malformed {action} payload")
            continue

        state = replay[job_id]
        if action == "job_leased":
            worker = payload.get("worker")
            expiry = payload.get("lease_expires")
            if state["status"] not in ("unresolved", "leased"):
                errors.append(f"event {sequence} leases a job from state {state['status']}")
            if not isinstance(worker, str) or not worker.strip() or not isinstance(expiry, str) or not expiry:
                errors.append(f"event {sequence} has invalid lease identity or expiry")
            state.update(
                status="leased",
                lease_owner=worker,
                lease_expires=expiry,
                attempts=state["attempts"] + 1,
            )
            continue

        if action == "candidate_recorded":
            worker = payload.get("worker")
            wdl = payload.get("wdl")
            certificate_hash = payload.get("certificate_sha256")
            if state["status"] == "verified":
                errors.append(f"event {sequence} overwrites a verified job")
            if state["status"] == "leased" and worker != state["lease_owner"]:
                errors.append(f"event {sequence} candidate worker does not own the lease")
            if not isinstance(worker, str) or not worker.strip():
                errors.append(f"event {sequence} has an empty candidate worker")
            if wdl not in (WDL.WIN.value, WDL.DRAW.value, WDL.LOSS.value):
                errors.append(f"event {sequence} has an invalid candidate WDL")
            if not _is_sha256(certificate_hash):
                errors.append(f"event {sequence} has an invalid candidate certificate hash")
            state.update(
                status="candidate",
                wdl=wdl,
                certificate_sha256=certificate_hash,
                checker_sha256=None,
                verifier=None,
                root_certificate_hash=None,
                lease_owner=None,
                lease_expires=None,
            )
            continue

        if action == "candidate_verified":
            if state["status"] != "candidate":
                errors.append(f"event {sequence} verifies a job from state {state['status']}")
            verifier = payload.get("verifier")
            checker_hash = payload.get("checker_sha256")
            root_certificate_hash = payload.get("root_certificate_hash")
            if not isinstance(verifier, str) or not verifier.strip():
                errors.append(f"event {sequence} has an empty verifier")
            if not _is_sha256(checker_hash):
                errors.append(f"event {sequence} has an invalid checker hash")
            if not _is_sha256(root_certificate_hash):
                errors.append(f"event {sequence} has an invalid root certificate hash")
            if payload.get("wdl") != state["wdl"]:
                errors.append(f"event {sequence} verified WDL does not match the active candidate")
            expected = expected_obligations[job_id]
            if payload.get("child_game_state_sha256") != expected.child_game_state_sha256:
                errors.append(f"event {sequence} verified child game-state hash mismatch")
            state.update(
                status="verified",
                checker_sha256=checker_hash,
                verifier=verifier,
                root_certificate_hash=root_certificate_hash,
                lease_owner=None,
                lease_expires=None,
            )
            continue

        if state["status"] not in ("candidate", "leased"):
            errors.append(f"event {sequence} rejects a job from state {state['status']}")
        if not isinstance(payload.get("verifier"), str) or not payload["verifier"].strip():
            errors.append(f"event {sequence} has an empty rejecting verifier")
        if not isinstance(payload.get("reason"), str) or not payload["reason"].strip():
            errors.append(f"event {sequence} has an empty rejection reason")
        state.update(status="rejected", lease_owner=None, lease_expires=None)

    for obligation_id, row in rows.items():
        state = replay.get(obligation_id)
        if state is None:
            continue
        if row["status"] != state["status"]:
            errors.append(
                f"{obligation_id}: row status {row['status']!r} does not match event-replayed status {state['status']!r}"
            )
        if row["attempts"] != state["attempts"]:
            errors.append(f"{obligation_id}: attempt count does not match lease events")
        if row["lease_owner"] != state["lease_owner"] or row["lease_expires"] != state["lease_expires"]:
            errors.append(f"{obligation_id}: lease fields do not match event replay")
        if state["status"] in ("candidate", "verified", "rejected") and state["certificate_sha256"] is not None:
            if row["certificate_sha256"] != state["certificate_sha256"] or row["wdl"] != state["wdl"]:
                errors.append(f"{obligation_id}: candidate fields do not match event replay")
        if state["status"] == "verified":
            verifier = state["verifier"]
            if row["verification"] != f"independent-check:{verifier}":
                errors.append(f"{obligation_id}: verifier identity does not match the verification event")
            if row["checker_sha256"] != state["checker_sha256"]:
                errors.append(f"{obligation_id}: checker hash does not match the verification event")
            proof = verified_proofs.get(obligation_id)
            if proof is not None and proof.get("root_certificate_hash") != state["root_certificate_hash"]:
                errors.append(f"{obligation_id}: root certificate hash does not match the verification event")


def verify_campaign(db_path: str | Path) -> dict[str, Any]:
    errors: list[str] = []
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    expected_obligations: dict[str, Any] = {}
    event_count = 0
    job_count = 0
    prev_hash = GENESIS_HASH
    verified_proofs: dict[str, dict[str, object]] = {}
    rows_by_id: dict[str, sqlite3.Row] = {}
    root: Position | None = None
    root_history: HistoryContext | None = None
    audited_root_fen: str | None = None
    audited_root_position_sha256: str | None = None
    audited_root_game_state_sha256: str | None = None
    audited_root_identity_sha256: str | None = None
    root_automatic_code: str | None = None
    root_claim_actions: tuple[str, ...] = ()
    is_classical_initial_root = False

    with closing(_connect(db_path)) as conn:
        meta = _load_meta(conn, errors)
        if meta.get("schema") != SCHEMA:
            errors.append("meta schema mismatch")
        if meta.get("dedication") != DEDICATION:
            errors.append("campaign dedication metadata mismatch")
        if meta.get("cow_opening_priority") != COW_PRIORITY_POLICY:
            errors.append("campaign Cow Opening scheduler-priority metadata mismatch")
        if meta.get("rules_profile") != RULE_PROFILE_ID:
            errors.append("campaign rules profile mismatch")
        if meta.get("canonical_component") != CANONICAL_COMPONENT:
            errors.append("campaign canonical component mismatch")
        if meta.get("claim_boundary") != CLAIM_BOUNDARY:
            errors.append("campaign claim boundary mismatch")
        if meta.get("root_wdl") != WDL.UNKNOWN.value:
            errors.append("campaign initial root WDL metadata mismatch")
        if not isinstance(meta.get("created_at"), str) or not meta["created_at"]:
            errors.append("campaign creation timestamp is missing or invalid")
        try:
            root, root_history = _canonical_campaign_root(meta)
            obligations = _campaign_root_obligations(root, root_history)
            expected_obligations = {item.obligation_id: item for item in obligations}
            root_status = automatic_status(root, root_history)
            root_automatic_code = root_status.code
            if not root_status.terminal:
                root_claim_actions = _root_claim_action_ids(root, root_history, obligations)
            audited_root_fen = root.to_fen()
            audited_root_position_sha256 = state_sha256(root)
            audited_root_game_state_sha256 = game_state_sha256(root, root_history)
            audited_root_identity_sha256 = _root_identity_sha256(root, root_history)
            is_classical_initial_root = audited_root_fen == START_FEN
        except Exception as exc:
            errors.append(f"invalid root metadata: {exc}")

        events: list[dict[str, Any]] = []
        next_sequence = 1
        for row in conn.execute("SELECT * FROM events ORDER BY sequence"):
            event_count += 1
            if row["sequence"] != next_sequence:
                errors.append(f"event sequence gap: expected {next_sequence}, got {row['sequence']}")
            next_sequence = row["sequence"] + 1
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                errors.append(f"event {row['sequence']} payload is invalid JSON: {exc}")
                payload = None
            if row["prev_hash"] != prev_hash:
                errors.append(f"event {row['sequence']} prev_hash mismatch")
            if payload is not None:
                record = {
                    "action": row["action"],
                    "job_id": row["job_id"],
                    "payload": payload,
                    "prev_hash": prev_hash,
                    "timestamp": row["timestamp"],
                }
                expected_hash = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
                if row["event_hash"] != expected_hash:
                    errors.append(f"event {row['sequence']} event_hash mismatch")
            events.append(
                {
                    "sequence": row["sequence"],
                    "timestamp": row["timestamp"],
                    "job_id": row["job_id"],
                    "action": row["action"],
                    "payload": payload,
                }
            )
            prev_hash = row["event_hash"]

        seen_jobs: set[str] = set()
        for row in conn.execute("SELECT * FROM jobs ORDER BY obligation_id"):
            job_count += 1
            obligation_id = row["obligation_id"]
            seen_jobs.add(obligation_id)
            rows_by_id[obligation_id] = row
            expected = expected_obligations.get(obligation_id)
            if expected is None:
                errors.append(f"unexpected obligation {obligation_id}")
                continue
            checks = {
                "parent_game_state_sha256": expected.parent_game_state_sha256,
                "move_uci": expected.move_uci,
                "move_san": expected.move_san,
                "child_fen": expected.child_fen,
                "child_position_sha256": expected.child_position_sha256,
                "child_game_state_sha256": expected.child_game_state_sha256,
                "child_side_to_move": expected.child_side_to_move,
                "priority": COW_PRIORITY if expected.move_uci in COW_PRIORITY_MOVES else 0,
            }
            for field, wanted in checks.items():
                if row[field] != wanted:
                    errors.append(f"{obligation_id}: {field} mismatch")
            try:
                child_history_record = json.loads(row["child_history_json"])
                child_history = _history_from_record(child_history_record, label="child history")
                if child_history.counts != expected.child_history_counts:
                    errors.append(f"{obligation_id}: child history mismatch")
            except (TypeError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{obligation_id}: child history invalid: {exc}")
            try:
                shard_path = _path_from_storage(db_path, row["shard_path"])
                if not shard_path.is_file():
                    errors.append(f"{obligation_id}: shard file missing")
                else:
                    shard_payload, shard_hash = _read_hashed_json(shard_path, label="obligation shard")
                    if shard_hash != row["shard_sha256"]:
                        errors.append(f"{obligation_id}: shard hash mismatch")
                    if shard_payload != expected.to_dict():
                        errors.append(f"{obligation_id}: shard content does not match the canonical obligation")
            except (TypeError, ValueError, OSError) as exc:
                errors.append(f"{obligation_id}: shard invalid: {exc}")
            if bool(row["certificate_path"]) != bool(row["certificate_sha256"]):
                errors.append(f"{obligation_id}: certificate path/hash completeness mismatch")
            elif row["certificate_path"] and row["status"] != "verified":
                try:
                    certificate = _path_from_storage(db_path, row["certificate_path"])
                    if not certificate.is_file():
                        errors.append(f"{obligation_id}: certificate file missing")
                    elif _file_sha256(certificate) != row["certificate_sha256"]:
                        errors.append(f"{obligation_id}: certificate hash mismatch")
                except (TypeError, OSError, ValueError) as exc:
                    errors.append(f"{obligation_id}: certificate artifact invalid: {exc}")
            if row["status"] == "verified":
                try:
                    proof = _verify_candidate_certificate(
                        db_path,
                        row,
                        rules_profile=str(meta.get("rules_profile", "")),
                        expected_obligation=expected,
                    )
                    verified_proofs[obligation_id] = proof
                except Exception as exc:
                    errors.append(f"{obligation_id}: verified certificate invalid: {exc}")
                if not row["checker_path"] or not row["checker_sha256"]:
                    errors.append(f"{obligation_id}: verified job lacks checker record")
                else:
                    checker = _path_from_storage(db_path, row["checker_path"])
                    try:
                        if not checker.is_file():
                            raise ValueError("checker record file is missing")
                        checker_payload, checker_hash = _read_hashed_json(checker, label="checker record")
                        if checker_hash != row["checker_sha256"]:
                            raise ValueError("checker record hash does not match the recorded bytes")
                        prefix = "independent-check:"
                        verification = row["verification"]
                        if not isinstance(verification, str) or not verification.startswith(prefix):
                            raise ValueError("verified job has no independent-check verifier identity")
                        verifier = verification[len(prefix):]
                        if not verifier:
                            raise ValueError("verified job has an empty verifier identity")
                        _validate_checker_payload(checker_payload, row, obligation_id, verifier)
                    except Exception as exc:
                        errors.append(f"{obligation_id}: checker record invalid: {exc}")
        missing = sorted(set(expected_obligations) - seen_jobs)
        if missing:
            errors.append(f"missing obligations: {missing}")
        _audit_event_semantics(
            events,
            rows_by_id,
            expected_obligations,
            verified_proofs,
            meta.get("root_game_state_sha256"),
            errors,
        )

    verified_values: list[WDL] = []
    for obligation_id in sorted(expected_obligations):
        row = rows_by_id.get(obligation_id)
        try:
            verified_values.append(WDL(row["wdl"]) if row is not None and row["status"] == "verified" else WDL.UNKNOWN)
        except ValueError:
            errors.append(f"{obligation_id}: invalid WDL value")
            verified_values.append(WDL.UNKNOWN)
    valid = not errors
    derived_root = (
        _aggregate_campaign_root_wdl(
            root,
            root_history,
            list(expected_obligations.values()),
            verified_values,
        )
        if valid and root is not None and root_history is not None
        else WDL.UNKNOWN
    )
    game_solved = valid and derived_root != WDL.UNKNOWN
    return {
        "schema": SCHEMA,
        "valid": valid,
        "job_count": job_count,
        "expected_job_count": len(expected_obligations),
        "event_count": event_count,
        "errors": errors,
        "final_event_hash": prev_hash,
        "verified_children": len(verified_proofs) if valid else 0,
        "root_fen": audited_root_fen,
        "root_position_sha256": audited_root_position_sha256,
        "root_game_state_sha256": audited_root_game_state_sha256,
        "root_identity_sha256": audited_root_identity_sha256,
        "root_identity_schema": ROOT_IDENTITY_SCHEMA,
        "root_automatic_code": root_automatic_code,
        "root_claim_actions": list(root_claim_actions),
        "is_classical_initial_root": is_classical_initial_root,
        "root_wdl": derived_root.value,
        "game_solved": game_solved,
        "game_solved_scope": "declared_campaign_root_only",
        "classical_initial_solved": game_solved and is_classical_initial_root,
    }
