#!/usr/bin/env python3
"""Generate or strictly validate deterministic bounded M2 storage evidence.

This gate exercises exact storage mechanics around one canonical 19x19 move.
It is not a search, result certificate, or evidence that the 19x19 root is
solved.  Hashes select and verify records; exact bytes remain authoritative.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_go19.constants import WHITE
from ugts_go19.digests import canonical_json_bytes
from ugts_go19.engine import apply_move_detailed as flat_apply_move_detailed
from ugts_go19.persistent_engine import (
    apply_move_detailed as persistent_apply_move_detailed,
    initial_state as persistent_initial_state,
)
from ugts_go19.persistent_history import (
    HistoryRoot,
    PersistentHistory,
    roots_exactly_equal,
)
from ugts_go19.rules import Rules
from ugts_go19.segment_store import DigestCollisionError, ImmutableSegmentStore
from ugts_go19.state import State


EVIDENCE_FORMAT = "UGTS-M2-STORAGE-EVIDENCE-v2"
GENERATOR = "deterministic-19x19-one-move-storage-restart-v2"
ROOT_STATUS = "UNKNOWN"
SCOPE = "bounded exact storage and one-transition acceptance only"
LIMITATIONS = (
    "exercises only the empty canonical 19x19 state and one center move",
    "uses the host Python persistent history and local immutable segment store",
    "hashes are indexes and verification aids; exact bytes establish identity",
    "resident_payload_bytes is a post-spill store counter, not peak RSS or a total-memory bound",
    "streaming seal avoids a second full segment, but mmap handles, metadata, and restart indexes are not bounded",
    "the compact forest is one bounded full JSON artifact, not an incremental campaign graph or checkpoint",
    "the segment store treats forest bytes as opaque; exact semantic validation happens after readback",
    "campaign-scale NVMe behavior, first-publication recovery, and external tip management are out of scope",
    "does not search, prove, disprove, or estimate the canonical 19x19 root",
)
CANONICAL_RULES = {
    "allow_suicide": False,
    "komi2": 15,
    "passes_to_end": 2,
    "profile_id": "UGTS-GO19-AREA-PSK-K7.5-v1",
    "scoring": "area",
    "size": 19,
    "superko": "positional_superko",
}
BOARD_SIZE = 19
BOARD_BYTES = BOARD_SIZE * BOARD_SIZE
CENTER_MOVE = 9 * BOARD_SIZE + 9
PRIMARY_STAGED_MEMORY_LIMIT_BYTES = 21_000
COLLISION_STAGED_MEMORY_LIMIT_BYTES = 400
COLLISION_DIGEST_NAME = "constant-a5-storage-gate-v1"
COLLISION_DIGEST_HEX = "a5" * 32
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

TOP_LEVEL_KEYS = frozenset(
    {
        "case",
        "collision_case",
        "evidence_format",
        "generator",
        "limitations",
        "root_19x19_status",
        "rules",
        "scope",
    }
)
CASE_KEYS = frozenset(
    {
        "move",
        "persistent_engine_parity",
        "persistent_history",
        "persistent_history_forest",
        "segment_store",
    }
)
HISTORY_KEYS = frozenset(
    {
        "board_bytes",
        "board_record_count",
        "board_size",
        "canonical_across_fresh_stores",
        "initial_member_count",
        "initial_root_sha256",
        "node_record_count",
        "one_move_member_count",
        "one_move_root_sha256",
        "serialized_artifact_sha256",
        "serialized_byte_count",
        "serialized_file_sha256",
        "trusted_root_pin_verifications",
    }
)
FOREST_KEYS = frozenset(
    {
        "artifact_sha256",
        "board_record_count",
        "canonical_across_fresh_stores",
        "deduplicated_board_record_count",
        "deduplicated_node_record_count",
        "exact_root_roundtrips",
        "node_record_count",
        "ordered_member_counts",
        "ordered_root_sha256s",
        "root_count",
        "separate_root_board_record_count",
        "separate_root_node_record_count",
        "separate_root_serialized_byte_count",
        "serialized_byte_count",
        "serialized_byte_savings",
        "serialized_file_sha256",
        "shared_node_identity_count",
        "trusted_pin_verifications",
    }
)
PARITY_KEYS = frozenset(
    {
        "captured",
        "exact_history_members_equal",
        "matched_exact_field_count",
        "persistent_board_sha256",
        "self_captured",
    }
)
STORE_KEYS = frozenset(
    {
        "auto_spill_generation",
        "board_object_count",
        "digest_algorithm",
        "exact_reads_after_restart",
        "final_generation",
        "history_object_count",
        "lazy_payloads",
        "manifest_sha256",
        "mapped_segment_count_after_restart",
        "object_count",
        "object_refs",
        "pinned_forest_artifact_sha256",
        "pinned_forest_rehydrate_member_counts",
        "pinned_forest_rehydrate_root_sha256s",
        "pinned_forest_shared_node_identity_count",
        "resident_payload_bytes_after_restart",
        "resident_payload_bytes_after_spill",
        "segment_sha256s",
        "staged_memory_limit_bytes",
    }
)
OBJECT_REF_KEYS = frozenset({"empty_board", "history_forest", "one_move_board"})
COLLISION_KEYS = frozenset(
    {
        "ambiguous_digest_only_read_rejected",
        "collision_bucket_size_after_restart",
        "digest_name",
        "exact_reads_after_restart",
        "final_generation",
        "index_digest",
        "lazy_payloads",
        "manifest_sha256",
        "object_count",
        "payload_sha256s",
        "resident_payload_bytes_after_restart",
        "resident_payload_bytes_after_spill",
        "segment_sha256s",
        "staged_memory_limit_bytes",
    }
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _constant_a5_digest(_preimage: bytes) -> bytes:
    return bytes.fromhex(COLLISION_DIGEST_HEX)


def _require_keys(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} keys are noncanonical: "
            f"missing={sorted(expected - actual)}, extra={sorted(actual - expected)}"
        )
    return value


def _require_exact_int(value: Any, expected: int, label: str) -> None:
    if type(value) is not int or value != expected:
        raise ValueError(f"{label} must be the integer {expected}")


def _require_sha256(value: Any, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be canonical lowercase SHA-256 text")
    return value


def _require_sha256_list(value: Any, expected_length: int, label: str) -> list[str]:
    if type(value) is not list or len(value) != expected_length:
        raise ValueError(f"{label} must contain exactly {expected_length} hashes")
    result = [_require_sha256(item, f"{label} item") for item in value]
    if len(set(result)) != len(result):
        raise ValueError(f"{label} must contain distinct hashes")
    return result


def _require_exact_int_list(
    value: Any, expected: list[int], label: str
) -> list[int]:
    if type(value) is not list or len(value) != len(expected):
        raise ValueError(f"{label} must contain exactly {len(expected)} integers")
    for index, (actual, pinned) in enumerate(zip(value, expected, strict=True)):
        _require_exact_int(actual, pinned, f"{label}[{index}]")
    return value


def _require_true(value: Any, label: str) -> None:
    if value is not True:
        raise ValueError(f"{label} must be boolean true")


def _assert_runtime_rules() -> Rules:
    rules = Rules.canonical_19x19()
    if rules.as_dict() != CANONICAL_RULES:
        raise AssertionError("runtime canonical rules differ from the storage gate")
    return rules


def _root_node_identity_set(root: HistoryRoot) -> frozenset[int]:
    """Return exact in-process node identities reachable from one root."""

    pending = [] if root._node is None else [root._node]
    identities: set[int] = set()
    while pending:
        node = pending.pop()
        identity = id(node)
        if identity in identities:
            continue
        identities.add(identity)
        pending.extend(child for _slot, child in getattr(node, "children", ()))
    return frozenset(identities)


def _shared_node_identity_count(first: HistoryRoot, second: HistoryRoot) -> int:
    return len(_root_node_identity_set(first) & _root_node_identity_set(second))


def _exercise_primary_store(
    directory: Path,
    *,
    empty_board: bytes,
    one_move_board: bytes,
    serialized_forest: bytes,
    trusted_artifact_sha256: str,
    trusted_root_sha256s: tuple[str, str],
    expected_root_members: tuple[tuple[bytes, ...], tuple[bytes, ...]],
) -> dict[str, Any]:
    store = ImmutableSegmentStore(
        directory,
        lazy_payloads=True,
        staged_memory_limit_bytes=PRIMARY_STAGED_MEMORY_LIMIT_BYTES,
    )
    empty_ref = store.stage_board(empty_board)
    one_move_ref = store.stage_board(one_move_board)
    forest_ref = store.stage_history(serialized_forest)

    # The forest object fits the explicit bound by itself, but staging it
    # forces the two boards to an immutable first segment.
    auto_snapshot = store.snapshot
    if auto_snapshot is None or auto_snapshot.generation != 1:
        raise AssertionError("staged-memory threshold did not force the first spill")
    final_snapshot = store.spill_staged()
    if store.resident_payload_bytes != 0:
        raise AssertionError("published payload bytes remain resident")
    resident_after_spill = store.resident_payload_bytes
    store.close()

    restarted = ImmutableSegmentStore(
        directory,
        lazy_payloads=True,
        staged_memory_limit_bytes=PRIMARY_STAGED_MEMORY_LIMIT_BYTES,
        expected_manifest_sha256=final_snapshot.manifest_sha256,
    )
    try:
        if restarted.snapshot != final_snapshot:
            raise AssertionError("fresh restart did not recover the pinned snapshot")
        exact_payloads = (
            restarted.read(empty_ref, expected_payload=empty_board),
            restarted.read(one_move_ref, expected_payload=one_move_board),
            restarted.read(forest_ref, expected_payload=serialized_forest),
        )
        if exact_payloads != (empty_board, one_move_board, serialized_forest):
            raise AssertionError("fresh restart changed exact object bytes")
        rehydrated_history = PersistentHistory(BOARD_SIZE)
        rehydrated_roots = rehydrated_history.deserialize_forest(
            exact_payloads[2],
            expected_artifact_sha256=trusted_artifact_sha256,
            expected_root_sha256s=trusted_root_sha256s,
        )
        rehydrated_members = tuple(
            rehydrated_history.members(root) for root in rehydrated_roots
        )
        if rehydrated_members != expected_root_members:
            raise AssertionError("pinned forest rehydrate changed exact members")
        shared_node_count = _shared_node_identity_count(*rehydrated_roots)
        if shared_node_count <= 0:
            raise AssertionError("pinned forest rehydrate lost immutable sharing")
        if restarted.resident_payload_bytes != 0:
            raise AssertionError("restart retained full payload bytes in host objects")
        result = {
            "auto_spill_generation": auto_snapshot.generation,
            "board_object_count": 2,
            "digest_algorithm": "sha256",
            "exact_reads_after_restart": 3,
            "final_generation": final_snapshot.generation,
            "history_object_count": 1,
            "lazy_payloads": True,
            "manifest_sha256": final_snapshot.manifest_sha256,
            "mapped_segment_count_after_restart": restarted.mapped_segment_count,
            "object_count": final_snapshot.object_count,
            "object_refs": {
                "empty_board": empty_ref.as_dict(),
                "history_forest": forest_ref.as_dict(),
                "one_move_board": one_move_ref.as_dict(),
            },
            "pinned_forest_artifact_sha256": trusted_artifact_sha256,
            "pinned_forest_rehydrate_member_counts": [
                root.count for root in rehydrated_roots
            ],
            "pinned_forest_rehydrate_root_sha256s": [
                root.root_sha256 for root in rehydrated_roots
            ],
            "pinned_forest_shared_node_identity_count": shared_node_count,
            "resident_payload_bytes_after_restart": restarted.resident_payload_bytes,
            "resident_payload_bytes_after_spill": resident_after_spill,
            "segment_sha256s": list(final_snapshot.segment_sha256s),
            "staged_memory_limit_bytes": PRIMARY_STAGED_MEMORY_LIMIT_BYTES,
        }
    finally:
        restarted.close()
    return result


def _exercise_collision_store(directory: Path) -> dict[str, Any]:
    first_payload = bytes(BOARD_BYTES)
    second_payload = bytes((WHITE,)) + bytes(BOARD_BYTES - 1)
    store = ImmutableSegmentStore(
        directory,
        lazy_payloads=True,
        staged_memory_limit_bytes=COLLISION_STAGED_MEMORY_LIMIT_BYTES,
        digest_fn=_constant_a5_digest,
        digest_name=COLLISION_DIGEST_NAME,
    )
    first_ref = store.stage_board(first_payload)
    second_ref = store.stage_board(second_payload)
    if first_ref != second_ref:
        raise AssertionError("injected digest did not create the intended collision")
    final_snapshot = store.spill_staged()
    if store.resident_payload_bytes != 0:
        raise AssertionError("colliding published payloads remain resident")
    resident_after_spill = store.resident_payload_bytes
    store.close()

    restarted = ImmutableSegmentStore(
        directory,
        lazy_payloads=True,
        staged_memory_limit_bytes=COLLISION_STAGED_MEMORY_LIMIT_BYTES,
        digest_fn=_constant_a5_digest,
        digest_name=COLLISION_DIGEST_NAME,
        expected_manifest_sha256=final_snapshot.manifest_sha256,
    )
    ambiguous_rejected = False
    try:
        try:
            restarted.read(first_ref)
        except DigestCollisionError:
            ambiguous_rejected = True
        if not ambiguous_rejected:
            raise AssertionError("digest-only collision lookup was not rejected")
        if restarted.read(first_ref, expected_payload=first_payload) != first_payload:
            raise AssertionError("first exact colliding payload changed after restart")
        if restarted.read(first_ref, expected_payload=second_payload) != second_payload:
            raise AssertionError("second exact colliding payload changed after restart")
        if restarted.resident_payload_bytes != 0:
            raise AssertionError("colliding restart retained full payload bytes")
        result = {
            "ambiguous_digest_only_read_rejected": ambiguous_rejected,
            "collision_bucket_size_after_restart": max(
                restarted.collision_bucket_sizes(include_staged=False)
            ),
            "digest_name": COLLISION_DIGEST_NAME,
            "exact_reads_after_restart": 2,
            "final_generation": final_snapshot.generation,
            "index_digest": first_ref.sha256,
            "lazy_payloads": True,
            "manifest_sha256": final_snapshot.manifest_sha256,
            "object_count": final_snapshot.object_count,
            "payload_sha256s": sorted((_sha256(first_payload), _sha256(second_payload))),
            "resident_payload_bytes_after_restart": restarted.resident_payload_bytes,
            "resident_payload_bytes_after_spill": resident_after_spill,
            "segment_sha256s": list(final_snapshot.segment_sha256s),
            "staged_memory_limit_bytes": COLLISION_STAGED_MEMORY_LIMIT_BYTES,
        }
    finally:
        restarted.close()
    return result


def generate_storage_evidence(work_directory: str | Path) -> dict[str, Any]:
    """Run the deterministic bounded exercise and return canonical evidence."""

    work = Path(work_directory)
    work.mkdir(parents=True, exist_ok=True)
    rules = _assert_runtime_rules()
    history = PersistentHistory(BOARD_SIZE)
    persistent_initial = persistent_initial_state(rules, history)
    persistent_result = persistent_apply_move_detailed(
        persistent_initial, CENTER_MOVE, rules, history
    )
    persistent_child = persistent_result.state

    flat_initial = State.initial(rules)
    flat_result = flat_apply_move_detailed(flat_initial, CENTER_MOVE, rules)
    flat_child = flat_result.state
    exact_fields = (
        persistent_child.board == flat_child.board,
        persistent_child.to_play == flat_child.to_play,
        persistent_child.passes == flat_child.passes,
        history.members(persistent_child.history_root) == tuple(sorted(flat_child.seen)),
        persistent_child.previous_board == flat_child.previous_board,
        persistent_child.ply == flat_child.ply,
        persistent_result.captured == flat_result.captured,
        persistent_result.self_captured == flat_result.self_captured,
    )
    if not all(exact_fields):
        raise AssertionError("persistent transition differs from the flat exact oracle")

    initial_serialized = history.serialize_root(persistent_initial.history_root)
    serialized = history.serialize_root(persistent_child.history_root)
    pinned = PersistentHistory(BOARD_SIZE)
    pinned_root = pinned.deserialize_root(
        serialized,
        expected_root_sha256=persistent_child.history_root.root_sha256,
    )
    if not roots_exactly_equal(
        history, persistent_child.history_root, pinned, pinned_root
    ):
        raise AssertionError("trusted-pin roundtrip changed exact history members")

    forest_roots = (
        persistent_initial.history_root,
        persistent_child.history_root,
    )
    serialized_forest = history.serialize_forest(forest_roots)
    forest_payload = json.loads(serialized_forest.decode("utf-8"))
    trusted_forest = PersistentHistory(BOARD_SIZE)
    trusted_forest_roots = trusted_forest.deserialize_forest(
        serialized_forest,
        expected_artifact_sha256=forest_payload["artifact_sha256"],
        expected_root_sha256s=tuple(root.root_sha256 for root in forest_roots),
    )
    if not all(
        roots_exactly_equal(history, source, trusted_forest, loaded)
        for source, loaded in zip(forest_roots, trusted_forest_roots, strict=True)
    ):
        raise AssertionError("trusted forest roundtrip changed exact root members")
    source_shared_node_count = _shared_node_identity_count(*forest_roots)
    if (
        source_shared_node_count <= 0
        or _shared_node_identity_count(*trusted_forest_roots)
        != source_shared_node_count
    ):
        raise AssertionError("trusted forest roundtrip changed immutable sharing")

    reverse_history = PersistentHistory(BOARD_SIZE)
    reverse_root = reverse_history.empty_root
    reverse_root = reverse_history.insert(reverse_root, persistent_child.board)
    reverse_root = reverse_history.insert(reverse_root, persistent_initial.board)
    fresh_initial_history = PersistentHistory(BOARD_SIZE)
    fresh_initial_root = fresh_initial_history.insert(
        fresh_initial_history.empty_root, persistent_initial.board
    )
    canonical_across_fresh_stores = (
        fresh_initial_root.root_sha256 == persistent_initial.history_root.root_sha256
        and fresh_initial_history.serialize_root(fresh_initial_root)
        == history.serialize_root(persistent_initial.history_root)
        and roots_exactly_equal(
            history,
            persistent_initial.history_root,
            fresh_initial_history,
            fresh_initial_root,
        )
        and reverse_root.root_sha256
        == persistent_child.history_root.root_sha256
        and reverse_history.serialize_root(reverse_root) == serialized
        and roots_exactly_equal(
            history,
            persistent_child.history_root,
            reverse_history,
            reverse_root,
        )
    )
    if not canonical_across_fresh_stores:
        raise AssertionError("history root depends on allocation or insertion order")

    fresh_forest_history = PersistentHistory(BOARD_SIZE)
    fresh_forest_initial = fresh_forest_history.insert(
        fresh_forest_history.empty_root, persistent_initial.board
    )
    fresh_forest_child = fresh_forest_history.insert(
        fresh_forest_history.empty_root, persistent_child.board
    )
    fresh_forest_child = fresh_forest_history.insert(
        fresh_forest_child, persistent_initial.board
    )
    forest_canonical_across_fresh_stores = (
        fresh_forest_history.serialize_forest(
            (fresh_forest_initial, fresh_forest_child)
        )
        == serialized_forest
    )
    if not forest_canonical_across_fresh_stores:
        raise AssertionError("history forest depends on allocation or insertion order")

    history_payload = json.loads(serialized.decode("utf-8"))
    initial_history_payload = json.loads(initial_serialized.decode("utf-8"))
    separate_board_record_count = (
        initial_history_payload["board_record_count"]
        + history_payload["board_record_count"]
    )
    separate_node_record_count = (
        initial_history_payload["node_record_count"]
        + history_payload["node_record_count"]
    )
    separate_serialized_byte_count = len(initial_serialized) + len(serialized)
    deduplicated_board_record_count = (
        separate_board_record_count - forest_payload["board_record_count"]
    )
    deduplicated_node_record_count = (
        separate_node_record_count - forest_payload["node_record_count"]
    )
    serialized_byte_savings = (
        separate_serialized_byte_count - len(serialized_forest)
    )
    if (
        deduplicated_board_record_count <= 0
        or deduplicated_node_record_count != source_shared_node_count
        or serialized_byte_savings <= 0
    ):
        raise AssertionError("bounded forest did not preserve expected compact sharing")

    expected_root_members = tuple(history.members(root) for root in forest_roots)
    segment_store_result = _exercise_primary_store(
        work / "primary",
        empty_board=persistent_initial.board,
        one_move_board=persistent_child.board,
        serialized_forest=serialized_forest,
        trusted_artifact_sha256=forest_payload["artifact_sha256"],
        trusted_root_sha256s=tuple(root.root_sha256 for root in forest_roots),
        expected_root_members=expected_root_members,
    )
    if (
        segment_store_result["pinned_forest_shared_node_identity_count"]
        != source_shared_node_count
    ):
        raise AssertionError("segment restart changed compact forest sharing")

    result = {
        "case": {
            "move": CENTER_MOVE,
            "persistent_engine_parity": {
                "captured": persistent_result.captured,
                "exact_history_members_equal": True,
                "matched_exact_field_count": len(exact_fields),
                "persistent_board_sha256": _sha256(persistent_child.board),
                "self_captured": persistent_result.self_captured,
            },
            "persistent_history": {
                "board_bytes": BOARD_BYTES,
                "board_record_count": history_payload["board_record_count"],
                "board_size": BOARD_SIZE,
                "canonical_across_fresh_stores": canonical_across_fresh_stores,
                "initial_member_count": persistent_initial.history_root.count,
                "initial_root_sha256": persistent_initial.history_root.root_sha256,
                "node_record_count": history_payload["node_record_count"],
                "one_move_member_count": persistent_child.history_root.count,
                "one_move_root_sha256": persistent_child.history_root.root_sha256,
                "serialized_artifact_sha256": history_payload["artifact_sha256"],
                "serialized_byte_count": len(serialized),
                "serialized_file_sha256": _sha256(serialized),
                "trusted_root_pin_verifications": 2,
            },
            "persistent_history_forest": {
                "artifact_sha256": forest_payload["artifact_sha256"],
                "board_record_count": forest_payload["board_record_count"],
                "canonical_across_fresh_stores": (
                    forest_canonical_across_fresh_stores
                ),
                "deduplicated_board_record_count": (
                    deduplicated_board_record_count
                ),
                "deduplicated_node_record_count": deduplicated_node_record_count,
                "exact_root_roundtrips": 4,
                "node_record_count": forest_payload["node_record_count"],
                "ordered_member_counts": [root.count for root in forest_roots],
                "ordered_root_sha256s": [
                    root.root_sha256 for root in forest_roots
                ],
                "root_count": forest_payload["root_count"],
                "separate_root_board_record_count": separate_board_record_count,
                "separate_root_node_record_count": separate_node_record_count,
                "separate_root_serialized_byte_count": (
                    separate_serialized_byte_count
                ),
                "serialized_byte_count": len(serialized_forest),
                "serialized_byte_savings": serialized_byte_savings,
                "serialized_file_sha256": _sha256(serialized_forest),
                "shared_node_identity_count": source_shared_node_count,
                "trusted_pin_verifications": 2,
            },
            "segment_store": segment_store_result,
        },
        "collision_case": _exercise_collision_store(work / "collision"),
        "evidence_format": EVIDENCE_FORMAT,
        "generator": GENERATOR,
        "limitations": list(LIMITATIONS),
        "root_19x19_status": ROOT_STATUS,
        "rules": rules.as_dict(),
        "scope": SCOPE,
    }
    validate_storage_evidence(result)
    return result


def _validate_object_ref(value: Any, expected_kind: str, label: str) -> str:
    ref = _require_keys(value, frozenset({"kind", "sha256"}), label)
    if ref["kind"] != expected_kind:
        raise ValueError(f"{label} kind must be {expected_kind!r}")
    return _require_sha256(ref["sha256"], f"{label} digest")


def validate_storage_evidence(payload: Any) -> None:
    """Fail closed unless *payload* has the complete pinned M2 gate shape."""

    evidence = _require_keys(payload, TOP_LEVEL_KEYS, "evidence")
    pinned = {
        "evidence_format": EVIDENCE_FORMAT,
        "generator": GENERATOR,
        "root_19x19_status": ROOT_STATUS,
        "scope": SCOPE,
    }
    for field, expected in pinned.items():
        if evidence[field] != expected:
            raise ValueError(f"{field} is not the pinned storage-gate value")
    if evidence["limitations"] != list(LIMITATIONS):
        raise ValueError("limitations are not the pinned bounded-scope statement")
    if evidence["rules"] != CANONICAL_RULES:
        raise ValueError("rules do not match the canonical 19x19 profile")

    case = _require_keys(evidence["case"], CASE_KEYS, "case")
    _require_exact_int(case["move"], CENTER_MOVE, "case move")

    history = _require_keys(
        case["persistent_history"], HISTORY_KEYS, "persistent_history"
    )
    exact_history_counts = {
        "board_bytes": BOARD_BYTES,
        "board_record_count": 2,
        "board_size": BOARD_SIZE,
        "initial_member_count": 1,
        "node_record_count": 65,
        "one_move_member_count": 2,
        "serialized_byte_count": 20_405,
        "trusted_root_pin_verifications": 2,
    }
    for field, expected in exact_history_counts.items():
        _require_exact_int(history[field], expected, f"persistent_history.{field}")
    _require_true(
        history["canonical_across_fresh_stores"],
        "persistent_history.canonical_across_fresh_stores",
    )
    history_hashes = {
        field: _require_sha256(history[field], f"persistent_history.{field}")
        for field in (
            "initial_root_sha256",
            "one_move_root_sha256",
            "serialized_artifact_sha256",
            "serialized_file_sha256",
        )
    }
    if history_hashes["initial_root_sha256"] == history_hashes["one_move_root_sha256"]:
        raise ValueError("initial and one-move history roots must differ")

    forest = _require_keys(
        case["persistent_history_forest"],
        FOREST_KEYS,
        "persistent_history_forest",
    )
    exact_forest_counts = {
        "board_record_count": 2,
        "deduplicated_board_record_count": 1,
        "deduplicated_node_record_count": 32,
        "exact_root_roundtrips": 4,
        "node_record_count": 66,
        "root_count": 2,
        "separate_root_board_record_count": 3,
        "separate_root_node_record_count": 98,
        "separate_root_serialized_byte_count": 30_918,
        "serialized_byte_count": 20_915,
        "serialized_byte_savings": 10_003,
        "shared_node_identity_count": 32,
        "trusted_pin_verifications": 2,
    }
    for field, expected in exact_forest_counts.items():
        _require_exact_int(
            forest[field], expected, f"persistent_history_forest.{field}"
        )
    _require_true(
        forest["canonical_across_fresh_stores"],
        "persistent_history_forest.canonical_across_fresh_stores",
    )
    _require_exact_int_list(
        forest["ordered_member_counts"],
        [1, 2],
        "persistent_history_forest.ordered_member_counts",
    )
    forest_root_hashes = _require_sha256_list(
        forest["ordered_root_sha256s"],
        2,
        "persistent_history_forest.ordered_root_sha256s",
    )
    if forest_root_hashes != [
        history_hashes["initial_root_sha256"],
        history_hashes["one_move_root_sha256"],
    ]:
        raise ValueError("forest ordered roots do not match the exact root pins")
    forest_artifact_sha256 = _require_sha256(
        forest["artifact_sha256"],
        "persistent_history_forest.artifact_sha256",
    )
    _require_sha256(
        forest["serialized_file_sha256"],
        "persistent_history_forest.serialized_file_sha256",
    )
    if (
        forest["node_record_count"] + forest["deduplicated_node_record_count"]
        != forest["separate_root_node_record_count"]
        or forest["board_record_count"]
        + forest["deduplicated_board_record_count"]
        != forest["separate_root_board_record_count"]
        or forest["serialized_byte_count"] + forest["serialized_byte_savings"]
        != forest["separate_root_serialized_byte_count"]
        or forest["shared_node_identity_count"]
        != forest["deduplicated_node_record_count"]
    ):
        raise ValueError("forest compactness and sharing counts are inconsistent")

    parity = _require_keys(
        case["persistent_engine_parity"], PARITY_KEYS, "persistent_engine_parity"
    )
    for field, expected in {
        "captured": 0,
        "matched_exact_field_count": 8,
        "self_captured": 0,
    }.items():
        _require_exact_int(parity[field], expected, f"persistent_engine_parity.{field}")
    _require_true(
        parity["exact_history_members_equal"],
        "persistent_engine_parity.exact_history_members_equal",
    )
    _require_sha256(
        parity["persistent_board_sha256"],
        "persistent_engine_parity.persistent_board_sha256",
    )

    store = _require_keys(case["segment_store"], STORE_KEYS, "segment_store")
    if store["digest_algorithm"] != "sha256":
        raise ValueError("segment_store.digest_algorithm must be sha256")
    _require_true(store["lazy_payloads"], "segment_store.lazy_payloads")
    store_counts = {
        "auto_spill_generation": 1,
        "board_object_count": 2,
        "exact_reads_after_restart": 3,
        "final_generation": 2,
        "history_object_count": 1,
        "mapped_segment_count_after_restart": 2,
        "object_count": 3,
        "pinned_forest_shared_node_identity_count": 32,
        "resident_payload_bytes_after_restart": 0,
        "resident_payload_bytes_after_spill": 0,
        "staged_memory_limit_bytes": PRIMARY_STAGED_MEMORY_LIMIT_BYTES,
    }
    for field, expected in store_counts.items():
        _require_exact_int(store[field], expected, f"segment_store.{field}")
    _require_sha256(store["manifest_sha256"], "segment_store.manifest_sha256")
    _require_sha256_list(store["segment_sha256s"], 2, "segment_store.segment_sha256s")
    _require_exact_int_list(
        store["pinned_forest_rehydrate_member_counts"],
        [1, 2],
        "segment_store.pinned_forest_rehydrate_member_counts",
    )
    restarted_root_hashes = _require_sha256_list(
        store["pinned_forest_rehydrate_root_sha256s"],
        2,
        "segment_store.pinned_forest_rehydrate_root_sha256s",
    )
    if restarted_root_hashes != forest_root_hashes:
        raise ValueError("segment forest rehydrate does not match ordered root pins")
    if store["pinned_forest_artifact_sha256"] != forest_artifact_sha256:
        raise ValueError("segment forest rehydrate does not match the artifact pin")
    if (
        store["pinned_forest_shared_node_identity_count"]
        != forest["shared_node_identity_count"]
    ):
        raise ValueError("segment forest rehydrate changed immutable sharing")

    refs = _require_keys(store["object_refs"], OBJECT_REF_KEYS, "object_refs")
    ref_hashes = {
        "empty_board": _validate_object_ref(
            refs["empty_board"], "board", "object_refs.empty_board"
        ),
        "history_forest": _validate_object_ref(
            refs["history_forest"], "history", "object_refs.history_forest"
        ),
        "one_move_board": _validate_object_ref(
            refs["one_move_board"], "board", "object_refs.one_move_board"
        ),
    }
    if len(set(ref_hashes.values())) != 3:
        raise ValueError("production object references must be distinct")

    collision = _require_keys(
        evidence["collision_case"], COLLISION_KEYS, "collision_case"
    )
    if collision["digest_name"] != COLLISION_DIGEST_NAME:
        raise ValueError("collision digest name is not pinned")
    if collision["index_digest"] != COLLISION_DIGEST_HEX:
        raise ValueError("collision index digest is not the injected constant")
    _require_true(collision["lazy_payloads"], "collision_case.lazy_payloads")
    _require_true(
        collision["ambiguous_digest_only_read_rejected"],
        "collision_case.ambiguous_digest_only_read_rejected",
    )
    collision_counts = {
        "collision_bucket_size_after_restart": 2,
        "exact_reads_after_restart": 2,
        "final_generation": 2,
        "object_count": 2,
        "resident_payload_bytes_after_restart": 0,
        "resident_payload_bytes_after_spill": 0,
        "staged_memory_limit_bytes": COLLISION_STAGED_MEMORY_LIMIT_BYTES,
    }
    for field, expected in collision_counts.items():
        _require_exact_int(collision[field], expected, f"collision_case.{field}")
    _require_sha256(collision["manifest_sha256"], "collision_case.manifest_sha256")
    _require_sha256_list(
        collision["segment_sha256s"], 2, "collision_case.segment_sha256s"
    )
    payload_hashes = _require_sha256_list(
        collision["payload_sha256s"], 2, "collision_case.payload_sha256s"
    )
    if payload_hashes != sorted(payload_hashes):
        raise ValueError("collision payload hashes must be canonically sorted")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant: {value}")


def load_storage_evidence(path: str | Path) -> dict[str, Any]:
    raw = Path(path).read_bytes()
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise ValueError("evidence must end in exactly one newline")
    try:
        payload = json.loads(
            raw[:-1].decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("evidence is not valid canonical JSON") from exc
    if type(payload) is not dict:
        raise ValueError("evidence must be a JSON object")
    try:
        canonical = canonical_json_bytes(payload) + b"\n"
    except (TypeError, UnicodeError, ValueError) as exc:
        raise ValueError("evidence is not valid canonical JSON") from exc
    if raw != canonical:
        raise ValueError("evidence is not in canonical JSON form")
    return payload


def _write_atomic(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.tmp-"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or strictly validate deterministic bounded M2 storage evidence."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output", type=Path, help="write generated canonical evidence")
    mode.add_argument(
        "--validate",
        type=Path,
        metavar="EVIDENCE",
        help="strictly validate and deterministically reproduce archived evidence",
    )
    args = parser.parse_args()

    try:
        with tempfile.TemporaryDirectory(prefix="ugts-m2-storage-gate-") as temporary:
            generated = generate_storage_evidence(Path(temporary))
        if args.validate is not None:
            archived = load_storage_evidence(args.validate)
            validate_storage_evidence(archived)
            if archived != generated:
                raise ValueError(
                    "archived evidence differs from deterministic fresh execution"
                )
            print(
                "storage gate: accepted deterministic bounded M2 storage evidence; "
                "19x19 root status remains UNKNOWN"
            )
            return 0

        raw = canonical_json_bytes(generated) + b"\n"
        if args.output is not None:
            _write_atomic(args.output, raw)
            print(
                f"storage gate: wrote {args.output}; "
                "19x19 root status remains UNKNOWN"
            )
        else:
            sys.stdout.buffer.write(raw)
        return 0
    except (OSError, UnicodeError, ValueError, AssertionError) as exc:
        raise SystemExit(f"storage gate: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
