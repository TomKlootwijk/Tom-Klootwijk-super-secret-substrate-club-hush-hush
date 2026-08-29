#!/usr/bin/env python3
"""Generate or validate compact bounded persistent-PNDAG evidence.

The generated artifact exercises exact 2x2 legacy and compact checkpoint
restart, pinned lazy segment readback, and two-phase immutable generation
recovery.  It deliberately contains only deterministic hashes, counts, and
acceptance facts; temporary graph checkpoints are deleted.  This is neither a
19x19 search nor a proof certificate, and the canonical 19x19 root remains
UNKNOWN.
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
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import ugts_go19.persistent_pndag as persistent_pndag_module  # noqa: E402
from ugts_go19.digests import canonical_json_bytes  # noqa: E402
from ugts_go19.persistent_history import PersistentHistory  # noqa: E402
from ugts_go19.persistent_pndag import (  # noqa: E402
    UINT64_MAX,
    PersistentPNDAGResult,
    PersistentProofNumberDAG,
    canonical_persistent_state_bytes,
)
from ugts_go19.persistent_pndag_checkpoint_store import (  # noqa: E402
    CHECKPOINT_PREPARATION_FORMAT,
    PersistentPNDAGCheckpointPreparation,
    PersistentPNDAGCheckpointStore,
    PersistentPNDAGCheckpointStoreError,
)
from ugts_go19.persistent_pndag_compact_checkpoint import (  # noqa: E402
    COMPACT_CHECKPOINT_FORMAT,
    COMPACT_CODEC_ID,
    deserialize_compact_checkpoint,
    serialize_compact_checkpoint,
)
from ugts_go19.rules import Rules  # noqa: E402
from ugts_go19.segment_store import ImmutableSegmentStore  # noqa: E402


EVIDENCE_FORMAT = "UGTS-M2-PERSISTENT-PNDAG-EVIDENCE-v2"
GENERATOR = "deterministic-bounded-2x2-persistent-pndag-restart-v2"
ROOT_STATUS = "UNKNOWN"
SCOPE = "bounded exact persistent-PNDAG restart acceptance on 2x2 only"
ARTIFACT_ROLE = "acceptance evidence only; not a proof certificate"
PARTIAL_EXPANSIONS = 7
COMPLETION_BUDGET = 10_000
COLLISION_EXPANSIONS = 1
RULES_PAYLOAD = {
    "allow_suicide": False,
    "komi2": 1,
    "passes_to_end": 2,
    "profile_id": "persistent-pndag-gate-2x2-v1",
    "scoring": "area",
    "size": 2,
    "superko": "positional_superko",
}
LIMITATIONS = (
    "exercises a deterministic 2x2 fixture only, not the canonical 19x19 root",
    "the Python DAG and persistent histories remain resident in host RAM without a total-memory bound",
    "the compact codec removes repeated durable histories but fully materializes its JSON, forest, reconstructed histories, and a temporary legacy checkpoint",
    "the segment store treats each compact checkpoint as one opaque history-kind object; this adapter gate does not page the live DAG or prove campaign-scale NVMe behavior",
    "immutable generation recovery writes a full legacy checkpoint per generation and validates complete lineage under an externally enforced single-writer discipline",
    "the two-phase protocol requires the caller to durably retain the exact preparation outside the checkpoint store before committing CURRENT",
    "wall-clock runtime is machine-dependent and is not archived as deterministic evidence",
    "peak RSS is not measured or bounded by this gate",
    "SHA-256 self-hashes and external tips are cryptographic anti-substitution and anti-rollback assumptions, not collision-independent semantic identity",
    "exact bytes, exact root bytes, exact rules, and exact thresholds are supplied to strict loaders; hashes are indexes and verification aids",
    "the compact archive retains hashes and counts, not a graph, strategy, or independently verified certificate",
)
RESOURCE_ACCOUNTING = {
    "archived_checkpoint_files": 0,
    "checkpoint_generation_retention": "temporary full immutable lineage deleted before generation returns",
    "peak_rss": "not measured; host-RAM graph and history growth are unbounded",
    "runtime": "not archived; wall-clock duration is machine-dependent",
    "segment_store_payload_mode": "lazy mmap after forced spill; compact bytes still fully materialized for exact read and decode",
    "temporary_checkpoint_retention": "deleted before generation returns",
}

STATE_COLLISION_DIGEST_NAME = "constant-22-state-pndag-gate-v1"
STATE_COLLISION_DIGEST_HEX = "22" * 32
HISTORY_COLLISION_DIGEST_NAME = "constant-11-history-pndag-gate-v1"
HISTORY_COLLISION_DIGEST_HEX = "11" * 32
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

TOP_LEVEL_KEYS = frozenset(
    {
        "artifact_role",
        "cases",
        "collision_case",
        "evidence_format",
        "fixture_rules",
        "fork_rejection_case",
        "generator",
        "limitations",
        "resource_accounting",
        "root_19x19_status",
        "scope",
    }
)
CASE_KEYS = frozenset(
    {
        "checkpoint",
        "compact_checkpoint",
        "completed_after_restart",
        "expected_status",
        "generation_recovery",
        "partial",
        "threshold2",
        "uninterrupted_match",
    }
)
COMPACT_CHECKPOINT_KEYS = frozenset(
    {
        "codec",
        "compact_artifact_sha256",
        "compact_byte_count",
        "compact_file_sha256",
        "compact_format",
        "exact_load_match",
        "legacy_byte_count",
        "legacy_checkpoint_sha256",
        "legacy_file_sha256",
        "saved_byte_count",
        "segment_store",
    }
)
COMPACT_MATCH_KEYS = frozenset(
    {
        "checked_field_count",
        "committed_expansions",
        "edge_count",
        "fresh_dag_object",
        "fresh_history_object",
        "graph_sha256",
        "graph_and_counts_match",
        "node_count",
        "proof_numbers_match",
        "root_state_bytes_match",
        "status",
    }
)
SEGMENT_CHECKPOINT_KEYS = frozenset(
    {
        "digest_algorithm",
        "exact_read_byte_count",
        "exact_read_file_sha256",
        "final_generation",
        "forced_lazy_spill",
        "lazy_payloads",
        "manifest_sha256",
        "mapped_segment_count_after_restart",
        "object_count",
        "object_ref",
        "resident_payload_bytes_after_restart",
        "resident_payload_bytes_after_spill",
        "segment_sha256s",
        "staged_memory_limit_bytes",
        "supplied_exact_payload_pin",
        "supplied_manifest_sha256_pin",
    }
)
OBJECT_REF_KEYS = frozenset({"kind", "sha256"})
GENERATION_RECOVERY_KEYS = frozenset(
    {
        "after_current",
        "before_current",
        "current_pointer_file_sha256",
        "external_preparation_exact_file_roundtrip",
        "preparation_byte_count",
        "preparation_file_sha256",
        "preparation_format",
        "previous_tip_is_null",
        "retained_intended_tip",
    }
)
RECOVERY_FACT_KEYS = frozenset(
    {
        "committed_expansions",
        "current_condition_observed",
        "edge_count",
        "exact_graph_and_counts_match",
        "fresh_dag_object",
        "fresh_history_object",
        "fresh_store_object",
        "graph_sha256",
        "node_count",
        "proof_numbers_match",
        "root_state_bytes_match",
        "status",
    }
)
TIP_KEYS = frozenset(
    {
        "checkpoint_file_sha256",
        "checkpoint_sha256",
        "committed_expansions",
        "generation",
        "graph_sha256",
        "manifest_sha256",
        "run_sha256",
    }
)
FORK_REJECTION_KEYS = frozenset(
    {
        "baseline_committed_expansions",
        "baseline_status",
        "current_pointer_file_sha256",
        "current_pointer_preserved",
        "dropped_committed_expansion",
        "fork_committed_expansions",
        "fork_had_higher_counter",
        "fork_status",
        "publication_rejected",
        "published_tip_preserved",
        "rejection_category",
        "threshold2",
    }
)
RESULT_KEYS = frozenset(
    {
        "committed_expansions",
        "disproof_number",
        "edge_count",
        "expanded_this_call",
        "graph_sha256",
        "node_count",
        "proof_number",
        "status",
    }
)
CHECKPOINT_KEYS = frozenset(
    {
        "atomic_failed_replace_preserved_prior_file",
        "byte_count",
        "checkpoint_content_sha256",
        "checkpoint_file_sha256",
        "fresh_dag_object",
        "fresh_history_object",
        "root_state_byte_count",
        "root_state_sha256",
        "rules_sha256",
        "supplied_exact_root_bytes_pin",
        "supplied_exact_rules_pin",
        "supplied_exact_threshold_pin",
        "threshold2_pin",
    }
)
MATCH_KEYS = frozenset(
    {
        "checked_field_count",
        "counts_match",
        "graph_sha256_matches",
        "proof_numbers_match",
        "status_matches",
        "uninterrupted_expansions",
    }
)
COLLISION_KEYS = frozenset(
    {
        "checkpoint_byte_count",
        "checkpoint_content_sha256",
        "checkpoint_file_sha256",
        "distinct_exact_state_count",
        "edge_count",
        "fresh_dag_object",
        "fresh_history_object",
        "graph_sha256",
        "history_board_object_count",
        "history_digest_bucket_size",
        "history_digest_hex",
        "history_digest_name",
        "node_count",
        "partial_expansions",
        "root_state_byte_count",
        "root_state_sha256",
        "state_digest_bucket_size",
        "state_digest_hex",
        "state_digest_name",
        "status",
        "threshold2",
    }
)
RESOURCE_KEYS = frozenset(
    {
        "archived_checkpoint_files",
        "checkpoint_generation_retention",
        "peak_rss",
        "runtime",
        "segment_store_payload_mode",
        "temporary_checkpoint_retention",
    }
)

# These exact small-fixture counts are part of this evidence-format contract.
EXPECTED_RESULTS = {
    1: {
        "completed": ("PROVEN", 0, UINT64_MAX, 164, 171, 397, 396),
        "partial": ("UNKNOWN", 3, 4, 7, 7, 31, 30),
        "uninterrupted_expansions": 171,
    },
    3: {
        "completed": ("DISPROVEN", UINT64_MAX, 0, 191, 198, 483, 482),
        "partial": ("UNKNOWN", 3, 4, 7, 7, 31, 30),
        "uninterrupted_expansions": 198,
    },
}


def _rules() -> Rules:
    rules = Rules.from_dict(dict(RULES_PAYLOAD))
    if rules.as_dict() != RULES_PAYLOAD:
        raise AssertionError("runtime rules differ from the gate fixture")
    return rules


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _constant_state_digest(_data: bytes) -> bytes:
    return bytes.fromhex(STATE_COLLISION_DIGEST_HEX)


def _constant_history_digest(_data: bytes) -> bytes:
    return bytes.fromhex(HISTORY_COLLISION_DIGEST_HEX)


def _result_payload(result: PersistentPNDAGResult) -> dict[str, Any]:
    return {
        "committed_expansions": result.committed_expansions,
        "disproof_number": result.disproof_number,
        "edge_count": result.edge_count,
        "expanded_this_call": result.expanded_this_call,
        "graph_sha256": result.graph_sha256,
        "node_count": result.node_count,
        "proof_number": result.proof_number,
        "status": result.status,
    }


def _result_comparison_tuple(result: PersistentPNDAGResult) -> tuple[Any, ...]:
    return (
        result.status,
        result.proof_number,
        result.disproof_number,
        result.committed_expansions,
        result.node_count,
        result.edge_count,
        result.graph_sha256,
    )


def _checkpoint_hashes(path: Path) -> tuple[int, str, str]:
    raw = path.read_bytes()
    payload = _decode_canonical_json(raw, "temporary checkpoint")
    content_hash = payload.get("checkpoint_sha256")
    if type(content_hash) is not str or SHA256_RE.fullmatch(content_hash) is None:
        raise AssertionError("temporary checkpoint lacks its canonical content hash")
    return len(raw), _sha256(raw), content_hash


def _assert_exact_partial_load(
    loaded: PersistentProofNumberDAG,
    interrupted: PersistentProofNumberDAG,
    partial: PersistentPNDAGResult,
    label: str,
) -> PersistentPNDAGResult:
    if loaded is interrupted or loaded.history is interrupted.history:
        raise AssertionError(f"{label} reused interrupted in-memory objects")
    if loaded.root_state_bytes != interrupted.root_state_bytes:
        raise AssertionError(f"{label} changed exact pinned root bytes")
    loaded_result = loaded.advance(0)
    if _result_comparison_tuple(loaded_result) != _result_comparison_tuple(partial):
        raise AssertionError(f"{label} changed the exact partial graph")
    if loaded_result.status != "UNKNOWN":
        raise AssertionError(f"{label} converted a budget stop into an outcome")
    return loaded_result


def _exercise_segment_backed_compact_load(
    directory: Path,
    *,
    compact_raw: bytes,
    compact_artifact_sha256: str,
    interrupted: PersistentProofNumberDAG,
    partial: PersistentPNDAGResult,
) -> tuple[dict[str, Any], dict[str, Any]]:
    staged_limit = len(compact_raw)
    store = ImmutableSegmentStore(
        directory,
        lazy_payloads=True,
        staged_memory_limit_bytes=staged_limit,
    )
    try:
        object_ref = store.stage_history(compact_raw)
        snapshot = store.spill_staged()
        if store.resident_payload_bytes != 0:
            raise AssertionError("compact checkpoint remained resident after spill")
        resident_after_spill = store.resident_payload_bytes
    finally:
        store.close()

    restarted = ImmutableSegmentStore(
        directory,
        lazy_payloads=True,
        staged_memory_limit_bytes=staged_limit,
        expected_manifest_sha256=snapshot.manifest_sha256,
    )
    try:
        if restarted.snapshot != snapshot:
            raise AssertionError("pinned compact segment restart changed snapshot")
        exact_raw = restarted.read(object_ref, expected_payload=compact_raw)
        if exact_raw != compact_raw:
            raise AssertionError("pinned compact segment read changed exact bytes")
        loaded = deserialize_compact_checkpoint(
            exact_raw,
            expected_rules=interrupted.rules,
            expected_threshold2=interrupted.threshold2,
            expected_root_state_bytes=interrupted.root_state_bytes,
            expected_compact_artifact_sha256=compact_artifact_sha256,
        )
        loaded_result = _assert_exact_partial_load(
            loaded,
            interrupted,
            partial,
            "segment-backed compact checkpoint load",
        )
        if restarted.resident_payload_bytes != 0:
            raise AssertionError("compact segment restart retained full payload bytes")
        segment_payload = {
            "digest_algorithm": "sha256",
            "exact_read_byte_count": len(exact_raw),
            "exact_read_file_sha256": _sha256(exact_raw),
            "final_generation": snapshot.generation,
            "forced_lazy_spill": True,
            "lazy_payloads": True,
            "manifest_sha256": snapshot.manifest_sha256,
            "mapped_segment_count_after_restart": restarted.mapped_segment_count,
            "object_count": snapshot.object_count,
            "object_ref": object_ref.as_dict(),
            "resident_payload_bytes_after_restart": restarted.resident_payload_bytes,
            "resident_payload_bytes_after_spill": resident_after_spill,
            "segment_sha256s": list(snapshot.segment_sha256s),
            "staged_memory_limit_bytes": staged_limit,
            "supplied_exact_payload_pin": True,
            "supplied_manifest_sha256_pin": True,
        }
    finally:
        restarted.close()

    exact_load_match = {
        "checked_field_count": 7,
        "committed_expansions": loaded_result.committed_expansions,
        "edge_count": loaded_result.edge_count,
        "fresh_dag_object": True,
        "fresh_history_object": True,
        "graph_sha256": loaded_result.graph_sha256,
        "graph_and_counts_match": True,
        "node_count": loaded_result.node_count,
        "proof_numbers_match": True,
        "root_state_bytes_match": True,
        "status": loaded_result.status,
    }
    return segment_payload, exact_load_match


def _exercise_compact_checkpoint(
    directory: Path,
    *,
    interrupted: PersistentProofNumberDAG,
    partial: PersistentPNDAGResult,
    legacy_raw: bytes,
    legacy_checkpoint_sha256: str,
) -> dict[str, Any]:
    compact_raw = serialize_compact_checkpoint(interrupted)
    compact_payload = _decode_canonical_json(compact_raw, "compact checkpoint")
    compact_artifact_sha256 = compact_payload.get("compact_artifact_sha256")
    if (
        type(compact_artifact_sha256) is not str
        or SHA256_RE.fullmatch(compact_artifact_sha256) is None
    ):
        raise AssertionError("compact checkpoint lacks its canonical artifact hash")
    if len(compact_raw) >= len(legacy_raw):
        raise AssertionError("bounded compact checkpoint is not smaller than legacy")

    segment, exact_load_match = _exercise_segment_backed_compact_load(
        directory / "segment-store",
        compact_raw=compact_raw,
        compact_artifact_sha256=compact_artifact_sha256,
        interrupted=interrupted,
        partial=partial,
    )
    return {
        "codec": COMPACT_CODEC_ID,
        "compact_artifact_sha256": compact_artifact_sha256,
        "compact_byte_count": len(compact_raw),
        "compact_file_sha256": _sha256(compact_raw),
        "compact_format": COMPACT_CHECKPOINT_FORMAT,
        "exact_load_match": exact_load_match,
        "legacy_byte_count": len(legacy_raw),
        "legacy_checkpoint_sha256": legacy_checkpoint_sha256,
        "legacy_file_sha256": _sha256(legacy_raw),
        "saved_byte_count": len(legacy_raw) - len(compact_raw),
        "segment_store": segment,
    }


def _recovery_fact(
    loaded: PersistentProofNumberDAG,
    interrupted: PersistentProofNumberDAG,
    partial: PersistentPNDAGResult,
    *,
    current_condition: str,
) -> dict[str, Any]:
    result = _assert_exact_partial_load(
        loaded,
        interrupted,
        partial,
        "immutable generation recovery",
    )
    return {
        "committed_expansions": result.committed_expansions,
        "current_condition_observed": current_condition,
        "edge_count": result.edge_count,
        "exact_graph_and_counts_match": True,
        "fresh_dag_object": True,
        "fresh_history_object": True,
        "fresh_store_object": True,
        "graph_sha256": result.graph_sha256,
        "node_count": result.node_count,
        "proof_numbers_match": True,
        "root_state_bytes_match": True,
        "status": result.status,
    }


def _exercise_generation_recovery(
    directory: Path,
    *,
    interrupted: PersistentProofNumberDAG,
    partial: PersistentPNDAGResult,
) -> dict[str, Any]:
    store = PersistentPNDAGCheckpointStore.first_open(directory)
    preparation = store.prepare(interrupted)
    preparation_raw = canonical_json_bytes(preparation.as_dict()) + b"\n"
    external_preparation = directory.parent / "external-preparation.json"
    _write_atomic(external_preparation, preparation_raw)
    retained_raw = external_preparation.read_bytes()
    if retained_raw != preparation_raw:
        raise AssertionError("external preparation file changed exact retained bytes")
    retained_payload = _decode_canonical_json(
        retained_raw, "externally retained checkpoint preparation"
    )
    retained = PersistentPNDAGCheckpointPreparation.from_dict(retained_payload)
    if retained != preparation or retained.previous_tip is not None:
        raise AssertionError("external preparation roundtrip changed genesis intent")
    if (directory / "CURRENT").exists():
        raise AssertionError("prepare changed CURRENT before external recovery")

    recovered_before = PersistentPNDAGCheckpointStore.recover_prepared(
        directory,
        preparation=retained,
    )
    if recovered_before is store:
        raise AssertionError("before-CURRENT recovery reused the preparing store")
    loaded_before = recovered_before.load_dag(
        expected_rules=interrupted.rules,
        expected_threshold2=interrupted.threshold2,
        expected_root_state_bytes=interrupted.root_state_bytes,
    )
    before_fact = _recovery_fact(
        loaded_before,
        interrupted,
        partial,
        current_condition="CURRENT absent before recover_prepared",
    )
    if recovered_before.snapshot != retained.intended_tip:
        raise AssertionError("before-CURRENT recovery did not install intended tip")

    pointer_path = directory / "CURRENT"
    pointer_before = pointer_path.read_bytes()
    retained_again = PersistentPNDAGCheckpointPreparation.from_dict(
        _decode_canonical_json(preparation_raw, "retained preparation replay")
    )
    recovered_after = PersistentPNDAGCheckpointStore.recover_prepared(
        directory,
        preparation=retained_again,
    )
    if recovered_after is recovered_before:
        raise AssertionError("after-CURRENT recovery reused the prior store")
    loaded_after = recovered_after.load_dag(
        expected_rules=interrupted.rules,
        expected_threshold2=interrupted.threshold2,
        expected_root_state_bytes=interrupted.root_state_bytes,
    )
    after_fact = _recovery_fact(
        loaded_after,
        interrupted,
        partial,
        current_condition="intended CURRENT present before recover_prepared",
    )
    if recovered_after.snapshot != retained.intended_tip:
        raise AssertionError("after-CURRENT recovery did not preserve intended tip")
    pointer_after = pointer_path.read_bytes()
    if pointer_after != pointer_before:
        raise AssertionError("idempotent after-CURRENT recovery changed CURRENT bytes")

    return {
        "after_current": after_fact,
        "before_current": before_fact,
        "current_pointer_file_sha256": _sha256(pointer_after),
        "external_preparation_exact_file_roundtrip": True,
        "preparation_byte_count": len(preparation_raw),
        "preparation_file_sha256": _sha256(preparation_raw),
        "preparation_format": CHECKPOINT_PREPARATION_FORMAT,
        "previous_tip_is_null": True,
        "retained_intended_tip": retained.intended_tip.as_dict(),
    }


def _exercise_case(directory: Path, threshold2: int) -> dict[str, Any]:
    rules = _rules()
    history = PersistentHistory(2)
    interrupted = PersistentProofNumberDAG(rules, threshold2, history)
    root_state_bytes = interrupted.root_state_bytes

    # First publish a smaller checkpoint, then inject failure while replacing
    # it.  The previously published exact bytes must survive unchanged.
    checkpoint = directory / "checkpoint.json"
    interrupted.save_checkpoint(checkpoint)
    prior_bytes = checkpoint.read_bytes()
    partial = interrupted.advance(PARTIAL_EXPANSIONS)
    with mock.patch.object(
        persistent_pndag_module.os,
        "replace",
        side_effect=OSError("injected atomic replacement failure"),
    ):
        try:
            interrupted.save_checkpoint(checkpoint)
        except OSError as exc:
            if "injected atomic replacement failure" not in str(exc):
                raise
        else:
            raise AssertionError("injected checkpoint replacement did not fail")
    if checkpoint.read_bytes() != prior_bytes:
        raise AssertionError("failed checkpoint replacement changed prior bytes")
    if any(
        path.name.startswith(".checkpoint.json.tmp-") for path in directory.iterdir()
    ):
        raise AssertionError("failed checkpoint publication left a temporary file")

    interrupted.save_checkpoint(checkpoint)
    if partial.status != "UNKNOWN":
        raise AssertionError("bounded partial persistent PNDAG did not remain UNKNOWN")
    checkpoint_size, checkpoint_file_hash, checkpoint_content_hash = _checkpoint_hashes(
        checkpoint
    )
    legacy_raw = checkpoint.read_bytes()
    compact_checkpoint = _exercise_compact_checkpoint(
        directory / "compact-adapter",
        interrupted=interrupted,
        partial=partial,
        legacy_raw=legacy_raw,
        legacy_checkpoint_sha256=checkpoint_content_hash,
    )
    generation_recovery = _exercise_generation_recovery(
        directory / "checkpoint-generations",
        interrupted=interrupted,
        partial=partial,
    )

    loaded = PersistentProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_threshold2=threshold2,
        expected_root_state_bytes=root_state_bytes,
    )
    if loaded is interrupted or loaded.history is history:
        raise AssertionError("checkpoint load reused the interrupted in-memory objects")
    if loaded.root_state_bytes != root_state_bytes:
        raise AssertionError("fresh load changed the exact pinned root bytes")

    completed = loaded.advance(COMPLETION_BUDGET)
    uninterrupted = PersistentProofNumberDAG(rules, threshold2, PersistentHistory(2))
    uninterrupted_result = uninterrupted.advance(COMPLETION_BUDGET)
    if _result_comparison_tuple(completed) != _result_comparison_tuple(
        uninterrupted_result
    ):
        raise AssertionError("resumed graph/proof/counts differ from uninterrupted run")

    return {
        "checkpoint": {
            "atomic_failed_replace_preserved_prior_file": True,
            "byte_count": checkpoint_size,
            "checkpoint_content_sha256": checkpoint_content_hash,
            "checkpoint_file_sha256": checkpoint_file_hash,
            "fresh_dag_object": True,
            "fresh_history_object": True,
            "root_state_byte_count": len(root_state_bytes),
            "root_state_sha256": _sha256(root_state_bytes),
            "rules_sha256": _sha256(canonical_json_bytes(rules.as_dict())),
            "supplied_exact_root_bytes_pin": True,
            "supplied_exact_rules_pin": True,
            "supplied_exact_threshold_pin": True,
            "threshold2_pin": threshold2,
        },
        "compact_checkpoint": compact_checkpoint,
        "completed_after_restart": _result_payload(completed),
        "expected_status": "PROVEN" if threshold2 == 1 else "DISPROVEN",
        "generation_recovery": generation_recovery,
        "partial": _result_payload(partial),
        "threshold2": threshold2,
        "uninterrupted_match": {
            "checked_field_count": 7,
            "counts_match": True,
            "graph_sha256_matches": True,
            "proof_numbers_match": True,
            "status_matches": True,
            "uninterrupted_expansions": uninterrupted_result.expanded_this_call,
        },
    }


def _exercise_collision_case(directory: Path) -> dict[str, Any]:
    rules = _rules()
    history = PersistentHistory(
        2,
        digest_fn=_constant_history_digest,
        digest_name=HISTORY_COLLISION_DIGEST_NAME,
    )
    interrupted = PersistentProofNumberDAG(
        rules,
        1,
        history,
        digest_fn=_constant_state_digest,
        digest_name=STATE_COLLISION_DIGEST_NAME,
    )
    root_state_bytes = interrupted.root_state_bytes
    partial = interrupted.advance(COLLISION_EXPANSIONS)
    if partial.status != "UNKNOWN":
        raise AssertionError("collision fixture unexpectedly reached an outcome")
    checkpoint = directory / "collision-checkpoint.json"
    interrupted.save_checkpoint(checkpoint)
    checkpoint_size, checkpoint_file_hash, checkpoint_content_hash = _checkpoint_hashes(
        checkpoint
    )

    loaded = PersistentProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=root_state_bytes,
        digest_fn=_constant_state_digest,
        digest_name=STATE_COLLISION_DIGEST_NAME,
        history_digest_fn=_constant_history_digest,
        history_digest_name=HISTORY_COLLISION_DIGEST_NAME,
    )
    if loaded is interrupted or loaded.history is history:
        raise AssertionError("collision restart reused prior in-memory objects")
    restarted = loaded.advance(0)
    if _result_comparison_tuple(restarted) != _result_comparison_tuple(partial):
        raise AssertionError("collision restart changed the exact partial graph")

    exact_states = {
        canonical_persistent_state_bytes(
            loaded.state_for_id(node_id), rules, loaded.history
        )
        for node_id in range(loaded.node_count)
    }
    state_buckets = loaded.collision_bucket_sizes()
    history_buckets = loaded.history.digest_bucket_sizes()
    if len(exact_states) != loaded.node_count or state_buckets != (loaded.node_count,):
        raise AssertionError("state digest collision merged distinct exact states")
    if loaded.history.board_object_count <= 1 or history_buckets != (
        loaded.history.board_object_count,
    ):
        raise AssertionError("history digest collision merged distinct exact boards")

    return {
        "checkpoint_byte_count": checkpoint_size,
        "checkpoint_content_sha256": checkpoint_content_hash,
        "checkpoint_file_sha256": checkpoint_file_hash,
        "distinct_exact_state_count": len(exact_states),
        "edge_count": restarted.edge_count,
        "fresh_dag_object": True,
        "fresh_history_object": True,
        "graph_sha256": restarted.graph_sha256,
        "history_board_object_count": loaded.history.board_object_count,
        "history_digest_bucket_size": history_buckets[0],
        "history_digest_hex": HISTORY_COLLISION_DIGEST_HEX,
        "history_digest_name": HISTORY_COLLISION_DIGEST_NAME,
        "node_count": restarted.node_count,
        "partial_expansions": restarted.committed_expansions,
        "root_state_byte_count": len(root_state_bytes),
        "root_state_sha256": _sha256(root_state_bytes),
        "state_digest_bucket_size": state_buckets[0],
        "state_digest_hex": STATE_COLLISION_DIGEST_HEX,
        "state_digest_name": STATE_COLLISION_DIGEST_NAME,
        "status": restarted.status,
        "threshold2": 1,
    }


def _exercise_fork_rejection(directory: Path) -> dict[str, Any]:
    rules = _rules()
    baseline = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))
    baseline_result = baseline.advance(2)
    if baseline_result.status != "UNKNOWN":
        raise AssertionError("fork baseline unexpectedly reached an outcome")
    store = PersistentPNDAGCheckpointStore.first_open(directory)
    tip = store.publish(baseline)
    pointer_before = (directory / "CURRENT").read_bytes()

    fork = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))
    if fork.advance(1).status != "UNKNOWN":
        raise AssertionError("fork fixture unexpectedly reached an outcome")
    committed_second_leaf = fork._select_most_proving()
    for _ in range(2):
        alternate = next(
            node.node_id
            for node in fork._nodes
            if node.expansion == "unexpanded" and node.node_id != committed_second_leaf
        )
        fork._expand_node(alternate)
        fork._recompute_all()
    fork_result = fork.advance(0)
    if fork_result.status != "UNKNOWN":
        raise AssertionError("fork fixture unexpectedly reached an outcome")
    if fork.committed_expansions <= baseline.committed_expansions:
        raise AssertionError("fork fixture lacks a higher expansion counter")
    if baseline._nodes[committed_second_leaf].expansion != "expanded":
        raise AssertionError("baseline fixture did not commit its second leaf")
    if fork._nodes[committed_second_leaf].expansion != "unexpanded":
        raise AssertionError("fork fixture did not drop the committed expansion")

    rejection_category = "dropped or changed committed node expansion"
    try:
        store.publish(fork)
    except PersistentPNDAGCheckpointStoreError as exc:
        if rejection_category not in str(exc):
            raise
    else:
        raise AssertionError("immutable checkpoint lineage accepted a graph fork")
    pointer_after = (directory / "CURRENT").read_bytes()
    if pointer_after != pointer_before or store.snapshot != tip:
        raise AssertionError("rejected graph fork changed the published tip")

    return {
        "baseline_committed_expansions": baseline_result.committed_expansions,
        "baseline_status": baseline_result.status,
        "current_pointer_file_sha256": _sha256(pointer_after),
        "current_pointer_preserved": True,
        "dropped_committed_expansion": True,
        "fork_committed_expansions": fork_result.committed_expansions,
        "fork_had_higher_counter": True,
        "fork_status": fork_result.status,
        "publication_rejected": True,
        "published_tip_preserved": True,
        "rejection_category": rejection_category,
        "threshold2": 1,
    }


def generate_persistent_pndag_evidence(work_directory: str | Path) -> dict[str, Any]:
    """Run the bounded fixture and return compact deterministic evidence."""

    work = Path(work_directory)
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ugts-persistent-pndag-", dir=work) as run:
        run_path = Path(run)
        cases = []
        for threshold2 in (1, 3):
            with tempfile.TemporaryDirectory(
                prefix=f"threshold-{threshold2}-", dir=run_path
            ) as case_directory:
                cases.append(_exercise_case(Path(case_directory), threshold2))
        with tempfile.TemporaryDirectory(
            prefix="collision-", dir=run_path
        ) as collision:
            collision_case = _exercise_collision_case(Path(collision))
        with tempfile.TemporaryDirectory(prefix="fork-", dir=run_path) as fork:
            fork_rejection_case = _exercise_fork_rejection(Path(fork))

    result = {
        "artifact_role": ARTIFACT_ROLE,
        "cases": cases,
        "collision_case": collision_case,
        "evidence_format": EVIDENCE_FORMAT,
        "fixture_rules": dict(RULES_PAYLOAD),
        "fork_rejection_case": fork_rejection_case,
        "generator": GENERATOR,
        "limitations": list(LIMITATIONS),
        "resource_accounting": dict(RESOURCE_ACCOUNTING),
        "root_19x19_status": ROOT_STATUS,
        "scope": SCOPE,
    }
    validate_persistent_pndag_evidence(result)
    return result


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


def _require_int(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = UINT64_MAX,
) -> int:
    if type(value) is not int:
        raise ValueError(f"{label} must be an exact JSON integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} is outside its permitted integer range")
    return value


def _require_exact_int(value: Any, expected: int, label: str) -> None:
    actual = _require_int(value, label)
    if actual != expected:
        raise ValueError(f"{label} must be the deterministic integer {expected}")


def _require_sha256(value: Any, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be canonical lowercase SHA-256 text")
    return value


def _require_true(value: Any, label: str) -> None:
    if value is not True:
        raise ValueError(f"{label} must be boolean true")


def _validate_result(
    value: Any,
    expected: tuple[Any, ...],
    label: str,
) -> dict[str, Any]:
    result = _require_keys(value, RESULT_KEYS, label)
    (
        status,
        proof,
        disproof,
        expanded,
        committed,
        nodes,
        edges,
    ) = expected
    if result["status"] != status:
        raise ValueError(f"{label} has the wrong deterministic status")
    expected_ints = {
        "proof_number": proof,
        "disproof_number": disproof,
        "expanded_this_call": expanded,
        "committed_expansions": committed,
        "node_count": nodes,
        "edge_count": edges,
    }
    for field, expected_value in expected_ints.items():
        _require_exact_int(result[field], expected_value, f"{label} {field}")
    _require_sha256(result["graph_sha256"], f"{label} graph_sha256")
    return result


def _validate_compact_checkpoint(
    value: Any,
    *,
    checkpoint: dict[str, Any],
    partial: dict[str, Any],
    label: str,
) -> None:
    compact = _require_keys(value, COMPACT_CHECKPOINT_KEYS, label)
    if compact["codec"] != COMPACT_CODEC_ID:
        raise ValueError(f"{label} codec is not pinned")
    if compact["compact_format"] != COMPACT_CHECKPOINT_FORMAT:
        raise ValueError(f"{label} format is not pinned")
    for field in (
        "compact_artifact_sha256",
        "compact_file_sha256",
        "legacy_checkpoint_sha256",
        "legacy_file_sha256",
    ):
        _require_sha256(compact[field], f"{label} {field}")
    for field in (
        "compact_byte_count",
        "legacy_byte_count",
        "saved_byte_count",
    ):
        _require_int(compact[field], f"{label} {field}", minimum=1)
    if compact["legacy_byte_count"] != checkpoint["byte_count"]:
        raise ValueError(f"{label} legacy byte count differs from legacy checkpoint")
    if compact["legacy_checkpoint_sha256"] != checkpoint["checkpoint_content_sha256"]:
        raise ValueError(f"{label} legacy content hash differs from checkpoint")
    if compact["legacy_file_sha256"] != checkpoint["checkpoint_file_sha256"]:
        raise ValueError(f"{label} legacy file hash differs from checkpoint")
    if compact["compact_byte_count"] >= compact["legacy_byte_count"]:
        raise ValueError(f"{label} did not reduce bounded durable bytes")
    if compact["saved_byte_count"] != (
        compact["legacy_byte_count"] - compact["compact_byte_count"]
    ):
        raise ValueError(f"{label} saved byte count is inconsistent")

    match = _require_keys(
        compact["exact_load_match"], COMPACT_MATCH_KEYS, f"{label} exact load"
    )
    _require_exact_int(match["checked_field_count"], 7, f"{label} checked fields")
    expected_fields = {
        "committed_expansions": partial["committed_expansions"],
        "edge_count": partial["edge_count"],
        "node_count": partial["node_count"],
    }
    for field, expected in expected_fields.items():
        _require_exact_int(match[field], expected, f"{label} exact load {field}")
    if match["graph_sha256"] != partial["graph_sha256"]:
        raise ValueError(f"{label} exact load graph differs from partial")
    if match["status"] != "UNKNOWN":
        raise ValueError(f"{label} compact budget stop must remain UNKNOWN")
    for field in (
        "fresh_dag_object",
        "fresh_history_object",
        "graph_and_counts_match",
        "proof_numbers_match",
        "root_state_bytes_match",
    ):
        _require_true(match[field], f"{label} exact load {field}")

    segment = _require_keys(
        compact["segment_store"], SEGMENT_CHECKPOINT_KEYS, f"{label} segment store"
    )
    if segment["digest_algorithm"] != "sha256":
        raise ValueError(f"{label} segment digest algorithm is not pinned")
    for field in (
        "forced_lazy_spill",
        "lazy_payloads",
        "supplied_exact_payload_pin",
        "supplied_manifest_sha256_pin",
    ):
        _require_true(segment[field], f"{label} segment {field}")
    segment_exact_ints = {
        "exact_read_byte_count": compact["compact_byte_count"],
        "final_generation": 1,
        "mapped_segment_count_after_restart": 1,
        "object_count": 1,
        "resident_payload_bytes_after_restart": 0,
        "resident_payload_bytes_after_spill": 0,
        "staged_memory_limit_bytes": compact["compact_byte_count"],
    }
    for field, expected in segment_exact_ints.items():
        _require_exact_int(segment[field], expected, f"{label} segment {field}")
    for field in ("exact_read_file_sha256", "manifest_sha256"):
        _require_sha256(segment[field], f"{label} segment {field}")
    if segment["exact_read_file_sha256"] != compact["compact_file_sha256"]:
        raise ValueError(f"{label} exact segment read hash differs from compact bytes")
    segments = segment["segment_sha256s"]
    if type(segments) is not list or len(segments) != 1:
        raise ValueError(f"{label} must archive exactly one forced-spill segment")
    _require_sha256(segments[0], f"{label} segment file hash")
    object_ref = _require_keys(
        segment["object_ref"], OBJECT_REF_KEYS, f"{label} segment object ref"
    )
    if object_ref["kind"] != "history":
        raise ValueError(f"{label} compact adapter object kind must be history")
    _require_sha256(object_ref["sha256"], f"{label} object digest")


def _validate_recovery_fact(
    value: Any,
    *,
    partial: dict[str, Any],
    current_condition: str,
    label: str,
) -> None:
    fact = _require_keys(value, RECOVERY_FACT_KEYS, label)
    if fact["current_condition_observed"] != current_condition:
        raise ValueError(f"{label} CURRENT condition is not pinned")
    if fact["status"] != "UNKNOWN":
        raise ValueError(f"{label} budget stop must remain UNKNOWN")
    expected_ints = {
        "committed_expansions": partial["committed_expansions"],
        "edge_count": partial["edge_count"],
        "node_count": partial["node_count"],
    }
    for field, expected in expected_ints.items():
        _require_exact_int(fact[field], expected, f"{label} {field}")
    _require_sha256(fact["graph_sha256"], f"{label} graph hash")
    if fact["graph_sha256"] != partial["graph_sha256"]:
        raise ValueError(f"{label} graph differs from partial")
    for field in (
        "exact_graph_and_counts_match",
        "fresh_dag_object",
        "fresh_history_object",
        "fresh_store_object",
        "proof_numbers_match",
        "root_state_bytes_match",
    ):
        _require_true(fact[field], f"{label} {field}")


def _validate_generation_recovery(
    value: Any,
    *,
    checkpoint: dict[str, Any],
    partial: dict[str, Any],
    label: str,
) -> None:
    recovery = _require_keys(value, GENERATION_RECOVERY_KEYS, label)
    if recovery["preparation_format"] != CHECKPOINT_PREPARATION_FORMAT:
        raise ValueError(f"{label} preparation format is not pinned")
    _require_true(recovery["previous_tip_is_null"], f"{label} genesis previous tip")
    _require_true(
        recovery["external_preparation_exact_file_roundtrip"],
        f"{label} external preparation exact file roundtrip",
    )
    _require_int(
        recovery["preparation_byte_count"],
        f"{label} preparation byte count",
        minimum=1,
    )
    for field in ("current_pointer_file_sha256", "preparation_file_sha256"):
        _require_sha256(recovery[field], f"{label} {field}")
    tip = _require_keys(
        recovery["retained_intended_tip"], TIP_KEYS, f"{label} intended tip"
    )
    for field in (
        "manifest_sha256",
        "checkpoint_file_sha256",
        "checkpoint_sha256",
        "run_sha256",
        "graph_sha256",
    ):
        _require_sha256(tip[field], f"{label} intended tip {field}")
    _require_exact_int(tip["generation"], 1, f"{label} intended generation")
    _require_exact_int(
        tip["committed_expansions"],
        partial["committed_expansions"],
        f"{label} intended committed expansions",
    )
    if tip["checkpoint_file_sha256"] != checkpoint["checkpoint_file_sha256"]:
        raise ValueError(f"{label} intended checkpoint file differs from legacy")
    if tip["checkpoint_sha256"] != checkpoint["checkpoint_content_sha256"]:
        raise ValueError(f"{label} intended checkpoint content differs from legacy")
    if tip["graph_sha256"] != partial["graph_sha256"]:
        raise ValueError(f"{label} intended graph differs from partial")
    _validate_recovery_fact(
        recovery["before_current"],
        partial=partial,
        current_condition="CURRENT absent before recover_prepared",
        label=f"{label} before CURRENT",
    )
    _validate_recovery_fact(
        recovery["after_current"],
        partial=partial,
        current_condition="intended CURRENT present before recover_prepared",
        label=f"{label} after CURRENT",
    )


def validate_persistent_pndag_evidence(payload: Any) -> None:
    """Fail closed unless *payload* has the pinned bounded gate shape."""

    evidence = _require_keys(payload, TOP_LEVEL_KEYS, "evidence")
    literals = {
        "artifact_role": ARTIFACT_ROLE,
        "evidence_format": EVIDENCE_FORMAT,
        "generator": GENERATOR,
        "root_19x19_status": ROOT_STATUS,
        "scope": SCOPE,
    }
    for field, expected in literals.items():
        if evidence[field] != expected:
            raise ValueError(f"{field} is not the pinned gate value")
    try:
        fixture_rules = Rules.from_dict(evidence["fixture_rules"])
    except (TypeError, ValueError) as exc:
        raise ValueError("fixture rules are not valid exact rules") from exc
    if fixture_rules.as_dict() != RULES_PAYLOAD:
        raise ValueError("fixture rules are not the pinned exact 2x2 rules")
    if evidence["limitations"] != list(LIMITATIONS):
        raise ValueError("limitations are not the pinned bounded-scope statement")
    resources = _require_keys(
        evidence["resource_accounting"], RESOURCE_KEYS, "resource accounting"
    )
    _require_exact_int(
        resources["archived_checkpoint_files"],
        0,
        "archived checkpoint file count",
    )
    for field in (
        "checkpoint_generation_retention",
        "peak_rss",
        "runtime",
        "segment_store_payload_mode",
        "temporary_checkpoint_retention",
    ):
        if (
            type(resources[field]) is not str
            or resources[field] != RESOURCE_ACCOUNTING[field]
        ):
            raise ValueError(f"resource accounting {field} is not pinned")

    cases = evidence["cases"]
    if type(cases) is not list or len(cases) != 2:
        raise ValueError("cases must be the ordered threshold-1/threshold-3 pair")
    root_hashes: list[str] = []
    root_sizes: list[int] = []
    rules_hash = _sha256(canonical_json_bytes(RULES_PAYLOAD))
    for index, threshold2 in enumerate((1, 3)):
        case = _require_keys(cases[index], CASE_KEYS, f"case {threshold2}")
        _require_exact_int(case["threshold2"], threshold2, "case threshold2")
        expected_status = "PROVEN" if threshold2 == 1 else "DISPROVEN"
        if case["expected_status"] != expected_status:
            raise ValueError("case expected status does not match its threshold")

        expected = EXPECTED_RESULTS[threshold2]
        partial = _validate_result(
            case["partial"], expected["partial"], f"case {threshold2} partial"
        )
        completed = _validate_result(
            case["completed_after_restart"],
            expected["completed"],
            f"case {threshold2} completed",
        )
        if completed["status"] != case["expected_status"]:
            raise ValueError(
                "completed status differs from the expected fixture outcome"
            )
        if partial["status"] != "UNKNOWN":
            raise ValueError("budget-limited partial status must remain UNKNOWN")

        checkpoint = _require_keys(
            case["checkpoint"], CHECKPOINT_KEYS, f"case {threshold2} checkpoint"
        )
        for field in (
            "atomic_failed_replace_preserved_prior_file",
            "fresh_dag_object",
            "fresh_history_object",
            "supplied_exact_root_bytes_pin",
            "supplied_exact_rules_pin",
            "supplied_exact_threshold_pin",
        ):
            _require_true(checkpoint[field], f"case {threshold2} {field}")
        _require_int(
            checkpoint["byte_count"],
            f"case {threshold2} checkpoint byte_count",
            minimum=1,
        )
        _require_int(
            checkpoint["root_state_byte_count"],
            f"case {threshold2} root_state_byte_count",
            minimum=1,
        )
        _require_exact_int(
            checkpoint["threshold2_pin"],
            threshold2,
            f"case {threshold2} threshold2 pin",
        )
        for field in (
            "checkpoint_content_sha256",
            "checkpoint_file_sha256",
            "root_state_sha256",
            "rules_sha256",
        ):
            _require_sha256(checkpoint[field], f"case {threshold2} {field}")
        if checkpoint["rules_sha256"] != rules_hash:
            raise ValueError("checkpoint rules hash differs from exact fixture rules")
        root_hashes.append(checkpoint["root_state_sha256"])
        root_sizes.append(checkpoint["root_state_byte_count"])

        _validate_compact_checkpoint(
            case["compact_checkpoint"],
            checkpoint=checkpoint,
            partial=partial,
            label=f"case {threshold2} compact checkpoint",
        )
        _validate_generation_recovery(
            case["generation_recovery"],
            checkpoint=checkpoint,
            partial=partial,
            label=f"case {threshold2} generation recovery",
        )

        match = _require_keys(
            case["uninterrupted_match"], MATCH_KEYS, f"case {threshold2} match"
        )
        _require_exact_int(match["checked_field_count"], 7, "match field count")
        _require_exact_int(
            match["uninterrupted_expansions"],
            expected["uninterrupted_expansions"],
            "uninterrupted expansion count",
        )
        for field in (
            "counts_match",
            "graph_sha256_matches",
            "proof_numbers_match",
            "status_matches",
        ):
            _require_true(match[field], f"case {threshold2} {field}")

    if len(set(root_hashes)) != 1 or len(set(root_sizes)) != 1:
        raise ValueError("threshold cases do not pin the same exact root state bytes")

    collision = _require_keys(
        evidence["collision_case"], COLLISION_KEYS, "collision case"
    )
    collision_literals = {
        "history_digest_hex": HISTORY_COLLISION_DIGEST_HEX,
        "history_digest_name": HISTORY_COLLISION_DIGEST_NAME,
        "state_digest_hex": STATE_COLLISION_DIGEST_HEX,
        "state_digest_name": STATE_COLLISION_DIGEST_NAME,
        "status": "UNKNOWN",
    }
    for field, expected_value in collision_literals.items():
        if collision[field] != expected_value:
            raise ValueError(f"collision case {field} is not pinned")
    collision_ints = {
        "distinct_exact_state_count": 6,
        "edge_count": 5,
        "history_board_object_count": 5,
        "history_digest_bucket_size": 5,
        "node_count": 6,
        "partial_expansions": COLLISION_EXPANSIONS,
        "state_digest_bucket_size": 6,
        "threshold2": 1,
    }
    for field, expected_value in collision_ints.items():
        _require_exact_int(collision[field], expected_value, f"collision case {field}")
    for field in ("checkpoint_byte_count", "root_state_byte_count"):
        _require_int(collision[field], f"collision case {field}", minimum=1)
    for field in (
        "checkpoint_content_sha256",
        "checkpoint_file_sha256",
        "graph_sha256",
        "root_state_sha256",
    ):
        _require_sha256(collision[field], f"collision case {field}")
    for field in ("fresh_dag_object", "fresh_history_object"):
        _require_true(collision[field], f"collision case {field}")
    if collision["distinct_exact_state_count"] != collision["node_count"]:
        raise ValueError("forced state collision did not preserve exact identities")
    if collision["state_digest_bucket_size"] != collision["node_count"]:
        raise ValueError("forced state collision is not a single exact bucket")
    if (
        collision["history_digest_bucket_size"]
        != collision["history_board_object_count"]
    ):
        raise ValueError("forced history collision is not a single exact bucket")

    fork = _require_keys(
        evidence["fork_rejection_case"], FORK_REJECTION_KEYS, "fork rejection case"
    )
    if fork["baseline_status"] != "UNKNOWN" or fork["fork_status"] != "UNKNOWN":
        raise ValueError("fork rejection fixture budget stops must remain UNKNOWN")
    if fork["rejection_category"] != ("dropped or changed committed node expansion"):
        raise ValueError("fork rejection category is not pinned")
    fork_ints = {
        "baseline_committed_expansions": 2,
        "fork_committed_expansions": 3,
        "threshold2": 1,
    }
    for field, expected in fork_ints.items():
        _require_exact_int(fork[field], expected, f"fork rejection {field}")
    for field in (
        "current_pointer_preserved",
        "dropped_committed_expansion",
        "fork_had_higher_counter",
        "publication_rejected",
        "published_tip_preserved",
    ):
        _require_true(fork[field], f"fork rejection {field}")
    _require_sha256(fork["current_pointer_file_sha256"], "fork rejection CURRENT hash")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError(f"non-finite JSON constant {value}")


def _decode_canonical_json(raw: bytes, label: str) -> dict[str, Any]:
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise ValueError(f"{label} must end in exactly one newline")
    try:
        payload = json.loads(
            raw[:-1].decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError(f"{label} is not valid canonical JSON") from exc
    if type(payload) is not dict:
        raise ValueError(f"{label} must be a JSON object")
    try:
        canonical = canonical_json_bytes(payload) + b"\n"
    except (TypeError, UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError(f"{label} is not valid canonical JSON") from exc
    if raw != canonical:
        raise ValueError(f"{label} is not in canonical JSON form")
    return payload


def load_persistent_pndag_evidence(path: str | Path) -> dict[str, Any]:
    """Load one canonical evidence object, rejecting duplicate JSON keys."""

    return _decode_canonical_json(Path(path).read_bytes(), "evidence")


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
        description="Generate or validate bounded persistent-PNDAG evidence."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output", type=Path, help="write canonical compact evidence")
    mode.add_argument(
        "--validate",
        type=Path,
        metavar="EVIDENCE",
        help="strictly validate and reproduce archived evidence",
    )
    args = parser.parse_args()

    try:
        archived: dict[str, Any] | None = None
        if args.validate is not None:
            archived = load_persistent_pndag_evidence(args.validate)
            validate_persistent_pndag_evidence(archived)
        with tempfile.TemporaryDirectory(prefix="ugts-persistent-pndag-gate-") as run:
            generated = generate_persistent_pndag_evidence(Path(run))
        if archived is not None:
            if archived != generated:
                raise ValueError(
                    "archived evidence differs from deterministic fresh execution"
                )
            print(
                "persistent PNDAG gate: accepted compact bounded 2x2 evidence; "
                "19x19 root status remains UNKNOWN"
            )
            return 0

        raw = canonical_json_bytes(generated) + b"\n"
        if args.output is not None:
            _write_atomic(args.output, raw)
            print(
                f"persistent PNDAG gate: wrote {args.output}; "
                "19x19 root status remains UNKNOWN"
            )
        else:
            sys.stdout.buffer.write(raw)
        return 0
    except (OSError, UnicodeError, ValueError, AssertionError) as exc:
        raise SystemExit(f"persistent PNDAG gate: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
