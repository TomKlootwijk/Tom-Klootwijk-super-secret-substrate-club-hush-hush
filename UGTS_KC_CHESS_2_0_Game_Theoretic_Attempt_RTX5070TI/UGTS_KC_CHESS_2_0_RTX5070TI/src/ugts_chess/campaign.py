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

from .game_state import RULE_PROFILE_ID, HistoryContext, game_state_sha256
from .game_theory import WDL, aggregate_root_wdl, root_obligations
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
    if bundle.get("root_state_hash") != row["child_game_state_sha256"]:
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
    if root_node.get("fen") != row["child_fen"]:
        raise ValueError("candidate certificate root FEN does not match the obligation child FEN")
    try:
        expected_history = json.loads(row["child_history_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("obligation child history is invalid JSON") from exc
    if root_node.get("history_counts") != expected_history:
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
    obligations = root_obligations(root, root_history)
    created_at = _utc_now()
    metadata = {
        "schema": SCHEMA,
        "created_at": created_at,
        "canonical_component": "ugts.application.chess.game-theoretic-solver@2.0.0",
        "root_fen": root.to_fen(),
        "root_position_sha256": state_sha256(root),
        "root_game_state_sha256": game_state_sha256(root, root_history),
        "root_history_counts": root_history.record(),
        "rules_profile": RULE_PROFILE_ID,
        "dedication": DEDICATION,
        "root_wdl": "unknown",
        "claim_boundary": "Only independently verified certificate records may set a child WDL.",
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
                    child_side_to_move,shard_path,shard_sha256,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
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
        profile_row = conn.execute("SELECT value FROM meta WHERE key='rules_profile'").fetchone()
        if profile_row is None:
            raise ValueError("campaign rules profile metadata is missing")
        try:
            rules_profile = json.loads(profile_row["value"])
        except json.JSONDecodeError as exc:
            raise ValueError("campaign rules profile metadata is invalid") from exc
        if not isinstance(rules_profile, str):
            raise ValueError("campaign rules profile metadata is invalid")
        _validate_checker_payload(checker_payload, row, obligation_id, verifier)
        proof = _verify_candidate_certificate(db_path, row, rules_profile=rules_profile)
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
                "child_game_state_sha256": row["child_game_state_sha256"],
            },
            obligation_id,
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM jobs WHERE obligation_id=?", (obligation_id,)).fetchone())


def reject_candidate(db_path: str | Path, obligation_id: str, *, verifier: str, reason: str) -> dict[str, Any]:
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
    with closing(_connect(db_path)) as conn:
        meta = {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT key,value FROM meta")}
        rows = list(conn.execute("SELECT obligation_id,status,wdl FROM jobs ORDER BY obligation_id"))
        counts: dict[str, int] = {}
        values: list[WDL] = []
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
            values.append(WDL(row["wdl"]) if row["status"] == "verified" else WDL.UNKNOWN)
        root_value = aggregate_root_wdl(values)
        last = conn.execute("SELECT sequence,event_hash FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        return {
            "schema": SCHEMA,
            "dedication": meta.get("dedication"),
            "root_fen": meta["root_fen"],
            "root_game_state_sha256": meta["root_game_state_sha256"],
            "root_wdl": root_value.value,
            "game_solved": root_value != WDL.UNKNOWN,
            "obligations": len(rows),
            "status_counts": counts,
            "verified_children": sum(1 for row in rows if row["status"] == "verified"),
            "last_event_sequence": 0 if last is None else last["sequence"],
            "last_event_hash": None if last is None else last["event_hash"],
            "evidence_boundary": "UNKNOWN remains UNKNOWN until proof certificates are independently verified.",
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


def verify_campaign(db_path: str | Path) -> dict[str, Any]:
    errors: list[str] = []
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    expected_obligations: dict[str, Any] = {}

    with closing(_connect(db_path)) as conn:
        meta = {row["key"]: json.loads(row["value"]) for row in conn.execute("SELECT key,value FROM meta")}
        if meta.get("schema") != SCHEMA:
            errors.append("meta schema mismatch")
        if meta.get("dedication") != DEDICATION:
            errors.append("campaign dedication metadata mismatch")
        if meta.get("rules_profile") != RULE_PROFILE_ID:
            errors.append("campaign rules profile mismatch")
        try:
            root = Position.from_fen(str(meta["root_fen"]))
            root_history = HistoryContext(tuple((str(k), int(v)) for k, v in meta["root_history_counts"]))
            if root_history != HistoryContext.initial(root):
                errors.append("root history is not the initial history for the campaign position")
            if state_sha256(root) != meta.get("root_position_sha256"):
                errors.append("root position hash mismatch")
            if game_state_sha256(root, root_history) != meta.get("root_game_state_sha256"):
                errors.append("root game-state hash mismatch")
            expected_obligations = {
                item.obligation_id: item for item in root_obligations(root, root_history)
            }
        except Exception as exc:
            errors.append(f"invalid root metadata: {exc}")

        prev_hash = GENESIS_HASH
        event_count = 0
        for row in conn.execute("SELECT * FROM events ORDER BY sequence"):
            event_count += 1
            payload = json.loads(row["payload_json"])
            record = {
                "action": row["action"],
                "job_id": row["job_id"],
                "payload": payload,
                "prev_hash": prev_hash,
                "timestamp": row["timestamp"],
            }
            expected = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
            if row["prev_hash"] != prev_hash:
                errors.append(f"event {row['sequence']} prev_hash mismatch")
            if row["event_hash"] != expected:
                errors.append(f"event {row['sequence']} event_hash mismatch")
            prev_hash = row["event_hash"]

        seen_jobs: set[str] = set()
        job_count = 0
        for row in conn.execute("SELECT * FROM jobs ORDER BY obligation_id"):
            job_count += 1
            obligation_id = row["obligation_id"]
            seen_jobs.add(obligation_id)
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
            }
            for field, wanted in checks.items():
                if row[field] != wanted:
                    errors.append(f"{obligation_id}: {field} mismatch")
            if json.loads(row["child_history_json"]) != [[k, c] for k, c in expected.child_history_counts]:
                errors.append(f"{obligation_id}: child history mismatch")
            shard_path = _path_from_storage(db_path, row["shard_path"])
            if not shard_path.is_file():
                errors.append(f"{obligation_id}: shard file missing")
            elif _file_sha256(shard_path) != row["shard_sha256"]:
                errors.append(f"{obligation_id}: shard hash mismatch")
            if row["certificate_path"] and row["status"] != "verified":
                certificate = _path_from_storage(db_path, row["certificate_path"])
                if not certificate.is_file():
                    errors.append(f"{obligation_id}: certificate file missing")
                elif _file_sha256(certificate) != row["certificate_sha256"]:
                    errors.append(f"{obligation_id}: certificate hash mismatch")
            if row["status"] == "verified":
                try:
                    _verify_candidate_certificate(
                        db_path,
                        row,
                        rules_profile=str(meta.get("rules_profile", "")),
                    )
                except ValueError as exc:
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
                    except ValueError as exc:
                        errors.append(f"{obligation_id}: checker record invalid: {exc}")
        missing = sorted(set(expected_obligations) - seen_jobs)
        if missing:
            errors.append(f"missing obligations: {missing}")

    status = campaign_status(db_path)
    return {
        "schema": SCHEMA,
        "valid": not errors,
        "job_count": job_count,
        "expected_job_count": len(expected_obligations),
        "event_count": event_count,
        "errors": errors,
        "final_event_hash": prev_hash,
        "root_wdl": status["root_wdl"],
        "game_solved": status["game_solved"],
    }
