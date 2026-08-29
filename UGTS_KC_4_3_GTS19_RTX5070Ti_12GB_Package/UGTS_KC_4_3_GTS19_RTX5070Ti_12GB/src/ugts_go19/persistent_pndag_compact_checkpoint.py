"""Compact exact checkpoint codec for the bounded persistent-history PNDAG.

The legacy :mod:`ugts_go19.persistent_pndag` checkpoint embeds a complete
standalone history artifact in every state.  This codec replaces those repeated
artifacts with one exact multi-root ``PersistentHistory`` forest.  The ordered
forest roots correspond one-for-one with the ordered node records.

Loading does not introduce a second proof checker.  It strictly rehydrates the
forest, reconstructs canonical legacy state bytes, writes a private temporary
legacy checkpoint, and delegates all state, edge, proof-cache, status, and graph
validation to ``PersistentProofNumberDAG.load_checkpoint``.  It then exactly
reserializes the returned graph and requires byte equality with the reconstructed
checkpoint, closing the temporary-path reopen boundary.  Finally it builds a
new unpublished DAG over the already validated forest roots, repeats complete
graph/proof validation, and again requires exact legacy byte equality.  The
returned live graph therefore retains the forest's physical trie sharing.

This remains a bounded host-RAM codec for the 1x1/2x2 validation DAG.  It
materializes the compact JSON, forest, reconstructed per-root artifacts, a full
temporary legacy checkpoint, the independently validated legacy graph, and the
forest-backed clone during load.  It is a full snapshot rather than a delta/WAL,
and current forest construction traverses every input root.  Thus it reduces
durable and retained live-identity bytes but does not establish production-scale
peak memory or restart behavior.

The self-hash and optional external ``expected_compact_artifact_sha256`` are
cryptographic anti-substitution checks whose strength assumes SHA-256 collision
resistance.  They are not semantic identity.  Exact state/history records plus
the mandatory byte-for-byte root-state pin remain authoritative, including
when injected indexing digests collide.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .digests import canonical_json_bytes, sha256_hex
from .persistent_engine import PersistentState
from .persistent_history import HistoryRoot, PersistentHistory
from .persistent_pndag import (
    CHECKPOINT_FORMAT,
    PERSISTENT_STATE_FORMAT,
    DigestFunction,
    PersistentProofNumberDAG,
    canonical_persistent_state_bytes,
)
from .rules import Rules


COMPACT_CHECKPOINT_FORMAT = "UGTS-GO-PERSISTENT-PNDAG-COMPACT-CHECKPOINT-v1"
COMPACT_CODEC_ID = "exact-history-forest-to-strict-legacy-loader-v1"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")

_LEGACY_ENVELOPE_KEYS = {
    "algorithm",
    "committed_expansions",
    "digest_index",
    "edge_count",
    "format",
    "graph_sha256",
    "history_digest_index",
    "history_format",
    "move_order",
    "node_count",
    "proof_arithmetic",
    "root_disproof_number",
    "root_id",
    "root_proof_number",
    "root_state_object_id",
    "rules",
    "rules_sha256",
    "scope",
    "selection",
    "state_format",
    "status",
    "symmetry",
    "threshold2",
}
_COMPACT_NODE_KEYS = {
    "board_hex",
    "cached_disproof",
    "cached_proof",
    "children",
    "digest",
    "expansion",
    "id",
    "passes",
    "previous_board_hex",
    "rank",
    "to_play",
}


def _require_keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label} has a noncanonical shape")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError(f"{label} must be lowercase SHA-256 text")
    return value


def _decode_canonical_document(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise TypeError(f"{label} bytes must be immutable bytes")
    if not raw.endswith(b"\n"):
        raise ValueError(f"{label} is not in canonical form")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ValueError(f"non-finite JSON constant {value}")

    document = raw[:-1]
    try:
        payload = json.loads(
            document.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (
        UnicodeDecodeError,
        UnicodeEncodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ValueError(f"{label} is not valid canonical JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    try:
        canonical = canonical_json_bytes(payload)
    except (TypeError, UnicodeEncodeError, ValueError) as exc:
        raise ValueError(f"{label} is not valid canonical JSON") from exc
    if canonical != document:
        raise ValueError(f"{label} is not in canonical form")
    return payload


def _compact_payload_without_hash(
    dag: PersistentProofNumberDAG,
) -> dict[str, Any]:
    if not isinstance(dag, PersistentProofNumberDAG):
        raise TypeError("dag must be a PersistentProofNumberDAG")

    # The legacy producer performs the authoritative in-memory structure and
    # proof-cache validation before any compact representation is emitted.
    legacy = dag._checkpoint_payload_without_hash()
    legacy_nodes = legacy.pop("nodes")
    if set(legacy) != _LEGACY_ENVELOPE_KEYS:
        raise ValueError("legacy checkpoint envelope has an unexpected shape")
    if len(legacy_nodes) != len(dag._nodes):
        raise ValueError("legacy checkpoint node table changed during serialization")

    compact_nodes: list[dict[str, Any]] = []
    roots = []
    for record, node in zip(legacy_nodes, dag._nodes, strict=True):
        state_hex = record.pop("state_hex")
        if state_hex != canonical_persistent_state_bytes(
            node.state,
            dag.rules,
            dag.history,
        ).hex():
            raise ValueError("legacy state record differs from the exact DAG state")
        state = node.state
        compact_nodes.append(
            {
                **record,
                "board_hex": state.board.hex(),
                "passes": state.passes,
                "previous_board_hex": (
                    None
                    if state.previous_board is None
                    else state.previous_board.hex()
                ),
                "to_play": state.to_play,
            }
        )
        roots.append(state.history_root)

    forest_raw = dag.history.serialize_forest(roots)
    forest = _decode_canonical_document(forest_raw, "history forest")
    return {
        "codec": COMPACT_CODEC_ID,
        "format": COMPACT_CHECKPOINT_FORMAT,
        "history_forest": forest,
        "legacy_envelope": legacy,
        "nodes": compact_nodes,
    }


def serialize_compact_checkpoint(dag: PersistentProofNumberDAG) -> bytes:
    """Return deterministic canonical bytes for one compact exact snapshot."""

    payload = _compact_payload_without_hash(dag)
    payload["compact_artifact_sha256"] = sha256_hex(canonical_json_bytes(payload))
    return canonical_json_bytes(payload) + b"\n"


def _atomic_save_bytes(path: str | Path, raw: bytes) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.tmp-{os.getpid()}-",
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            written = handle.write(raw)
            if written != len(raw):
                raise OSError("short compact-checkpoint write")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
        if os.name == "posix":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(destination.parent, flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def save_compact_checkpoint(
    dag: PersistentProofNumberDAG, path: str | Path
) -> None:
    """Atomically publish a compact exact snapshot for a sequential writer."""

    _atomic_save_bytes(path, serialize_compact_checkpoint(dag))


def _canonical_hex_bytes(value: Any, label: str, expected_length: int) -> bytes:
    if type(value) is not str:
        raise ValueError(f"{label} must be hexadecimal text")
    try:
        raw = bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError(f"{label} is invalid hexadecimal text") from exc
    if value != raw.hex():
        raise ValueError(f"{label} must be canonical lowercase hexadecimal text")
    if len(raw) != expected_length:
        raise ValueError(f"{label} has the wrong board length")
    return raw


def _reconstruct_legacy_checkpoint(
    payload: dict[str, Any],
    *,
    expected_rules: Rules,
    history_digest_fn: DigestFunction | None,
    history_digest_name: str | None,
) -> tuple[bytes, PersistentHistory, tuple[HistoryRoot, ...]]:
    legacy = _require_keys(
        payload["legacy_envelope"],
        _LEGACY_ENVELOPE_KEYS,
        "legacy checkpoint envelope",
    )
    if legacy["format"] != CHECKPOINT_FORMAT:
        raise ValueError("unsupported embedded legacy checkpoint format")
    if legacy["state_format"] != PERSISTENT_STATE_FORMAT:
        raise ValueError("unsupported embedded persistent-state format")

    forest = payload["history_forest"]
    if not isinstance(forest, dict):
        raise ValueError("history_forest must be a JSON object")
    forest_raw = canonical_json_bytes(forest) + b"\n"
    configured_history_name = (
        "sha256"
        if history_digest_fn is None
        else ("injected" if history_digest_name is None else history_digest_name)
    )
    history = PersistentHistory(
        expected_rules.size,
        digest_fn=history_digest_fn,
        digest_name=configured_history_name,
    )
    roots = history.deserialize_forest(forest_raw)

    records = payload["nodes"]
    if not isinstance(records, list) or not records:
        raise ValueError("compact checkpoint nodes must be a nonempty array")
    if len(records) != len(roots):
        raise ValueError("compact node and ordered forest-root counts differ")

    legacy_nodes: list[dict[str, Any]] = []
    board_bytes = expected_rules.size * expected_rules.size
    for expected_id, (raw_record, root) in enumerate(
        zip(records, roots, strict=True)
    ):
        record = _require_keys(
            raw_record, _COMPACT_NODE_KEYS, "compact checkpoint node"
        )
        if record["id"] != expected_id:
            raise ValueError("compact node ids must be contiguous and ordered")
        board = _canonical_hex_bytes(record["board_hex"], "node board_hex", board_bytes)
        previous_hex = record["previous_board_hex"]
        previous = (
            None
            if previous_hex is None
            else _canonical_hex_bytes(
                previous_hex, "node previous_board_hex", board_bytes
            )
        )
        state = PersistentState(
            board=board,
            to_play=record["to_play"],
            passes=record["passes"],
            history_root=root,
            previous_board=previous,
            # Campaign depth is not proof-authoritative and is normalized by
            # the legacy codec as well.
            ply=0,
        )
        state_bytes = canonical_persistent_state_bytes(
            state, expected_rules, history
        )
        legacy_nodes.append(
            {
                "cached_disproof": record["cached_disproof"],
                "cached_proof": record["cached_proof"],
                "children": record["children"],
                "digest": record["digest"],
                "expansion": record["expansion"],
                "id": record["id"],
                "rank": record["rank"],
                "state_hex": state_bytes.hex(),
            }
        )

    legacy_payload = dict(legacy)
    legacy_payload["nodes"] = legacy_nodes
    legacy_payload["checkpoint_sha256"] = sha256_hex(
        canonical_json_bytes(legacy_payload)
    )
    return canonical_json_bytes(legacy_payload) + b"\n", history, roots


def _canonical_legacy_checkpoint_bytes(dag: PersistentProofNumberDAG) -> bytes:
    payload = dag._checkpoint_payload_without_hash()
    payload["checkpoint_sha256"] = sha256_hex(canonical_json_bytes(payload))
    return canonical_json_bytes(payload) + b"\n"


def deserialize_compact_checkpoint(
    raw: bytes,
    *,
    expected_rules: Rules,
    expected_threshold2: int,
    expected_root_state_bytes: bytes,
    expected_compact_artifact_sha256: str | None = None,
    digest_fn: DigestFunction | None = None,
    digest_name: str | None = None,
    history_digest_fn: DigestFunction | None = None,
    history_digest_name: str | None = None,
) -> PersistentProofNumberDAG:
    """Strictly load compact bytes through the legacy independent validator.

    ``expected_root_state_bytes`` is the mandatory exact target identity.
    ``expected_compact_artifact_sha256``, when supplied, is only a
    collision-resistance-based anti-substitution pin; it is not exact identity.
    """

    if not isinstance(expected_rules, Rules):
        raise TypeError("expected_rules must be a Rules instance")
    payload = _decode_canonical_document(raw, "compact checkpoint")
    payload = _require_keys(
        payload,
        {
            "codec",
            "compact_artifact_sha256",
            "format",
            "history_forest",
            "legacy_envelope",
            "nodes",
        },
        "compact checkpoint",
    )
    if payload["format"] != COMPACT_CHECKPOINT_FORMAT:
        raise ValueError("unsupported compact checkpoint format")
    if payload["codec"] != COMPACT_CODEC_ID:
        raise ValueError("unsupported compact checkpoint codec")
    stored_hash = _require_sha256(
        payload["compact_artifact_sha256"], "compact artifact hash"
    )
    unhashed = dict(payload)
    unhashed.pop("compact_artifact_sha256")
    calculated_hash = sha256_hex(canonical_json_bytes(unhashed))
    if stored_hash != calculated_hash:
        raise ValueError("compact checkpoint content hash mismatch")
    if expected_compact_artifact_sha256 is not None:
        expected_hash = _require_sha256(
            expected_compact_artifact_sha256,
            "expected compact artifact hash",
        )
        if stored_hash != expected_hash:
            raise ValueError("compact checkpoint does not match the expected artifact")

    legacy_raw, forest_history, forest_roots = _reconstruct_legacy_checkpoint(
        payload,
        expected_rules=expected_rules,
        history_digest_fn=history_digest_fn,
        history_digest_name=history_digest_name,
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"ugts-persistent-pndag-legacy-{os.getpid()}-",
        suffix=".json",
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            written = handle.write(legacy_raw)
            if written != len(legacy_raw):
                raise OSError("short reconstructed-checkpoint write")
            handle.flush()
        loaded = PersistentProofNumberDAG.load_checkpoint(
            temporary_name,
            expected_rules=expected_rules,
            expected_threshold2=expected_threshold2,
            expected_root_state_bytes=expected_root_state_bytes,
            digest_fn=digest_fn,
            digest_name=digest_name,
            history_digest_fn=history_digest_fn,
            history_digest_name=history_digest_name,
        )
        # The strict legacy loader must reopen a pathname.  Exact
        # reserialization binds its returned object back to the already
        # reconstructed bytes, so a valid same-target path swap cannot replace
        # the requested graph at that boundary.
        if _canonical_legacy_checkpoint_bytes(loaded) != legacy_raw:
            raise ValueError(
                "legacy loader returned a graph different from reconstructed bytes"
            )
        # The strict legacy loader deliberately reconstructs each standalone
        # history artifact independently.  Clone its fully validated graph onto
        # the already verified ordered forest roots so the returned live DAG
        # retains compact immutable-trie sharing.  The clone is unpublished
        # until every semantic/cache/graph check below succeeds.
        rebound = loaded._clone_with_validated_history_roots(
            forest_history,
            forest_roots,
        )
        if _canonical_legacy_checkpoint_bytes(rebound) != legacy_raw:
            raise ValueError(
                "forest-backed graph differs from reconstructed legacy bytes"
            )
        return rebound
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def load_compact_checkpoint(
    path: str | Path,
    *,
    expected_rules: Rules,
    expected_threshold2: int,
    expected_root_state_bytes: bytes,
    expected_compact_artifact_sha256: str | None = None,
    digest_fn: DigestFunction | None = None,
    digest_name: str | None = None,
    history_digest_fn: DigestFunction | None = None,
    history_digest_name: str | None = None,
) -> PersistentProofNumberDAG:
    """Read and strictly load one compact exact checkpoint from *path*."""

    return deserialize_compact_checkpoint(
        Path(path).read_bytes(),
        expected_rules=expected_rules,
        expected_threshold2=expected_threshold2,
        expected_root_state_bytes=expected_root_state_bytes,
        expected_compact_artifact_sha256=expected_compact_artifact_sha256,
        digest_fn=digest_fn,
        digest_name=digest_name,
        history_digest_fn=history_digest_fn,
        history_digest_name=history_digest_name,
    )


__all__ = [
    "COMPACT_CHECKPOINT_FORMAT",
    "COMPACT_CODEC_ID",
    "deserialize_compact_checkpoint",
    "load_compact_checkpoint",
    "save_compact_checkpoint",
    "serialize_compact_checkpoint",
]
