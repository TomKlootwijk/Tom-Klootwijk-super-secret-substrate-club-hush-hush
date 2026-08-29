"""Tests for immutable persistent-PNDAG checkpoint generations."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ugts_go19.digests import canonical_json_bytes, sha256_hex
from ugts_go19.persistent_history import PersistentHistory
from ugts_go19.persistent_pndag import PersistentProofNumberDAG
from ugts_go19.persistent_pndag_checkpoint_store import (
    PersistentPNDAGCheckpointCommitUncertain,
    PersistentPNDAGCheckpointPreparation,
    PersistentPNDAGCheckpointStore,
    PersistentPNDAGCheckpointStoreError,
    PersistentPNDAGCheckpointTip,
)
from ugts_go19.rules import Rules


def _rules(size: int = 2) -> Rules:
    return Rules(
        size=size,
        komi2=1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id=f"checkpoint-generation-test-{size}x{size}",
    )


def _dag(rules: Rules, threshold2: int = 1) -> PersistentProofNumberDAG:
    return PersistentProofNumberDAG(
        rules,
        threshold2,
        PersistentHistory(rules.size),
    )


def _manifest(root: Path, tip: PersistentPNDAGCheckpointTip) -> dict:
    return json.loads(
        (root / "manifests" / f"{tip.manifest_sha256}.json").read_text(encoding="utf-8")
    )


def test_two_immutable_generations_resume_and_load_exact_graph(
    tmp_path: Path,
) -> None:
    root = tmp_path / "checkpoint-store"
    rules = _rules()
    dag = _dag(rules)
    expected_root = dag.root_state_bytes
    assert dag.advance(2).status == "UNKNOWN"

    store = PersistentPNDAGCheckpointStore.first_open(root)
    first = store.publish(dag)
    first_pointer = (root / "CURRENT").read_bytes()
    first_checkpoint = (
        root / "checkpoints" / f"{first.checkpoint_file_sha256}.json"
    ).read_bytes()

    assert dag.advance(3).status == "UNKNOWN"
    second = store.publish(dag)
    second_manifest = _manifest(root, second)

    assert second.generation == first.generation + 1 == 2
    assert second.committed_expansions > first.committed_expansions
    assert second_manifest["previous_manifest_sha256"] == first.manifest_sha256
    assert (root / "CURRENT").read_bytes() != first_pointer
    assert (
        root / "checkpoints" / f"{first.checkpoint_file_sha256}.json"
    ).read_bytes() == first_checkpoint
    assert len(list((root / "checkpoints").glob("*.json"))) == 2
    assert len(list((root / "manifests").glob("*.json"))) == 2

    pinned = PersistentPNDAGCheckpointTip.from_dict(second.as_dict())
    resumed_store = PersistentPNDAGCheckpointStore.resume(root, expected_tip=pinned)
    resumed = resumed_store.load_dag(
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=expected_root,
    )
    result = resumed.advance(0)

    assert result.status == "UNKNOWN"
    assert result.committed_expansions == second.committed_expansions
    assert result.graph_sha256 == second.graph_sha256


def test_two_phase_genesis_is_recoverable_before_or_after_current(
    tmp_path: Path,
) -> None:
    root = tmp_path / "prepared-genesis"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(2)
    expected_root = dag.root_state_bytes
    store = PersistentPNDAGCheckpointStore.first_open(root)

    prepared = store.prepare(dag)
    retained = PersistentPNDAGCheckpointPreparation.from_dict(prepared.as_dict())
    assert retained == prepared
    assert retained.previous_tip is None
    assert retained.intended_tip.generation == 1
    assert not (root / "CURRENT").exists()

    # A fresh process can finish a genesis commit using only the externally
    # retained preparation; it never infers an uncommitted orphan from disk.
    recovered = PersistentPNDAGCheckpointStore.recover_prepared(
        root,
        preparation=retained,
    )
    assert recovered.snapshot == retained.intended_tip
    loaded = recovered.load_dag(
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=expected_root,
    )
    assert loaded.committed_expansions == dag.committed_expansions

    # Recovery is idempotent when the intended CURRENT was already installed
    # but the caller crashed before marking its external journal committed.
    again = PersistentPNDAGCheckpointStore.recover_prepared(
        root,
        preparation=retained,
    )
    assert again.snapshot == retained.intended_tip


def test_two_phase_successor_recovers_old_or_new_current(tmp_path: Path) -> None:
    root = tmp_path / "prepared-successor"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    first = store.publish(dag)
    first_current = (root / "CURRENT").read_bytes()

    dag.advance(1)
    second_preparation = store.prepare(dag)
    assert second_preparation.previous_tip == first
    assert (root / "CURRENT").read_bytes() == first_current
    recovered = PersistentPNDAGCheckpointStore.recover_prepared(
        root,
        preparation=second_preparation,
    )
    second = second_preparation.intended_tip
    assert recovered.snapshot == second

    dag.advance(1)
    third_preparation = recovered.prepare(dag)
    third = recovered.commit_prepared(third_preparation)
    assert third == third_preparation.intended_tip
    assert recovered.commit_prepared(third_preparation) == third
    after_return_crash = PersistentPNDAGCheckpointStore.recover_prepared(
        root,
        preparation=third_preparation,
    )
    assert after_return_crash.snapshot == third


def test_idempotent_commit_rejects_forged_predecessor_tip(tmp_path: Path) -> None:
    root = tmp_path / "prepared-idempotent-forged-predecessor"
    dag = _dag(_rules())
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    store.publish(dag)

    dag.advance(1)
    preparation = store.prepare(dag)
    store.commit_prepared(preparation)
    assert preparation.previous_tip is not None
    forged_previous = replace(
        preparation.previous_tip,
        graph_sha256="00" * 32,
    )
    forged = PersistentPNDAGCheckpointPreparation(
        previous_tip=forged_previous,
        intended_tip=preparation.intended_tip,
    )

    with pytest.raises(
        PersistentPNDAGCheckpointStoreError,
        match="prepared predecessor tip disagrees with its manifest",
    ):
        store.commit_prepared(forged)


def test_prepared_genesis_recovers_after_failed_current_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ugts_go19 import persistent_pndag_checkpoint_store as store_module

    root = tmp_path / "prepared-genesis-replace-failure"
    dag = _dag(_rules())
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    preparation = store.prepare(dag)
    real_replace = store_module._atomic_replace_bytes

    def fail_replace(_path: Path, _data: bytes) -> None:
        raise OSError("injected prepared CURRENT failure")

    monkeypatch.setattr(store_module, "_atomic_replace_bytes", fail_replace)
    with pytest.raises(OSError, match="injected prepared CURRENT failure"):
        store.commit_prepared(preparation)
    assert not (root / "CURRENT").exists()

    monkeypatch.setattr(store_module, "_atomic_replace_bytes", real_replace)
    recovered = PersistentPNDAGCheckpointStore.recover_prepared(
        root,
        preparation=preparation,
    )
    assert recovered.snapshot == preparation.intended_tip


def test_post_replace_validation_failure_exposes_recoverable_preparation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "prepared-post-replace-failure"
    dag = _dag(_rules())
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    store.publish(dag)
    dag.advance(1)
    preparation = store.prepare(dag)
    real_load_current = store._load_current
    calls = 0

    def fail_post_replace(*, expected_tip: PersistentPNDAGCheckpointTip) -> None:
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise MemoryError("injected post-replace validation failure")
        real_load_current(expected_tip=expected_tip)

    monkeypatch.setattr(store, "_load_current", fail_post_replace)
    with pytest.raises(PersistentPNDAGCheckpointCommitUncertain) as raised:
        store.commit_prepared(preparation)
    assert raised.value.preparation == preparation

    # CURRENT moved even though this live object never completed its normal
    # post-replace update.  Retrying the same exact preparation directly is
    # nevertheless idempotent; callers are not forced through a different API.
    monkeypatch.setattr(store, "_load_current", real_load_current)
    assert store.snapshot != preparation.intended_tip
    assert store.commit_prepared(preparation) == preparation.intended_tip
    assert store.snapshot == preparation.intended_tip

    recovered = PersistentPNDAGCheckpointStore.recover_prepared(
        root,
        preparation=raised.value.preparation,
    )
    assert recovered.snapshot == preparation.intended_tip


def test_resume_requires_pin_and_detects_silent_current_rollback(
    tmp_path: Path,
) -> None:
    root = tmp_path / "rollback"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    first = store.publish(dag)
    first_pointer = (root / "CURRENT").read_bytes()

    dag.advance(1)
    second = store.publish(dag)
    with pytest.raises(TypeError, match="requires a PersistentPNDAGCheckpointTip"):
        PersistentPNDAGCheckpointStore.resume(root, expected_tip=None)  # type: ignore[arg-type]
    with pytest.raises(PersistentPNDAGCheckpointStoreError, match="already exists"):
        PersistentPNDAGCheckpointStore.first_open(root)

    # Simulate storage rollback to a complete, internally valid old pointer.
    (root / "CURRENT").write_bytes(first_pointer)
    with pytest.raises(
        PersistentPNDAGCheckpointStoreError, match="externally expected"
    ):
        PersistentPNDAGCheckpointStore.resume(root, expected_tip=second)

    # Downgrade is possible only when the caller explicitly supplies the old
    # externally retained pin, never as an automatic fallback.
    old_store = PersistentPNDAGCheckpointStore.resume(root, expected_tip=first)
    old_dag = old_store.load_dag(
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=dag.root_state_bytes,
    )
    assert old_dag.committed_expansions == first.committed_expansions


def test_first_open_refuses_existing_artifacts_when_current_is_lost(
    tmp_path: Path,
) -> None:
    root = tmp_path / "lost-current"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(1)
    tip = PersistentPNDAGCheckpointStore.first_open(root).publish(dag)
    (root / "CURRENT").unlink()

    with pytest.raises(
        PersistentPNDAGCheckpointStoreError, match="existing checkpoint artifacts"
    ):
        PersistentPNDAGCheckpointStore.first_open(root)
    with pytest.raises(PersistentPNDAGCheckpointStoreError, match="CURRENT is missing"):
        PersistentPNDAGCheckpointStore.resume(root, expected_tip=tip)

    missing = tmp_path / "never-created"
    with pytest.raises(PersistentPNDAGCheckpointStoreError, match="root is missing"):
        PersistentPNDAGCheckpointStore.resume(missing, expected_tip=tip)
    assert not missing.exists()


def test_publish_rejects_lost_work_or_changed_run_envelope(tmp_path: Path) -> None:
    root = tmp_path / "lost-work"
    rules = _rules()
    advanced = _dag(rules)
    advanced.advance(2)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    tip = store.publish(advanced)
    current = (root / "CURRENT").read_bytes()

    with pytest.raises(PersistentPNDAGCheckpointStoreError, match="strictly increase"):
        store.publish(_dag(rules))
    assert (root / "CURRENT").read_bytes() == current
    assert store.snapshot == tip

    with pytest.raises(
        PersistentPNDAGCheckpointStoreError, match="different root, rules, threshold"
    ):
        store.publish(_dag(rules, threshold2=3))
    assert (root / "CURRENT").read_bytes() == current


def test_publish_rejects_a_higher_counter_from_a_forked_graph(tmp_path: Path) -> None:
    root = tmp_path / "forked-lineage"
    rules = _rules()
    committed = _dag(rules)
    committed.advance(2)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    tip = store.publish(committed)
    current = (root / "CURRENT").read_bytes()

    fork = _dag(rules)
    fork.advance(1)
    committed_second_leaf = fork._select_most_proving()
    for _ in range(2):
        alternate = next(
            node.node_id
            for node in fork._nodes
            if node.expansion == "unexpanded" and node.node_id != committed_second_leaf
        )
        fork._expand_node(alternate)
        fork._recompute_all()
    assert fork.committed_expansions > committed.committed_expansions
    assert committed._nodes[committed_second_leaf].expansion == "expanded"
    assert fork._nodes[committed_second_leaf].expansion == "unexpanded"

    with pytest.raises(
        PersistentPNDAGCheckpointStoreError,
        match="dropped or changed committed node expansion",
    ):
        store.publish(fork)
    assert (root / "CURRENT").read_bytes() == current
    assert store.snapshot == tip


def test_solved_checkpoint_is_a_final_generation(tmp_path: Path) -> None:
    root = tmp_path / "solved-final-generation"
    dag = _dag(_rules())
    solved = dag.advance(10_000)
    assert solved.status == "PROVEN"
    store = PersistentPNDAGCheckpointStore.first_open(root)
    tip = store.publish(dag)
    current = (root / "CURRENT").read_bytes()

    # A hostile caller can expand an irrelevant open node after the root is
    # already solved.  It remains a valid exact graph, but it is not a legal
    # continuation of this deterministic search lineage.
    open_node = next(
        node.node_id for node in dag._nodes if node.expansion == "unexpanded"
    )
    dag._expand_node(open_node)
    dag._recompute_all()
    assert dag.advance(0).status == "PROVEN"
    assert dag.committed_expansions > tip.committed_expansions

    with pytest.raises(
        PersistentPNDAGCheckpointStoreError,
        match="solved checkpoint is a final generation",
    ):
        store.publish(dag)
    assert (root / "CURRENT").read_bytes() == current
    assert store.snapshot == tip


def test_run_envelope_comparison_rejects_boolean_integer_alias(
    tmp_path: Path,
) -> None:
    root = tmp_path / "type-exact-run"
    dag = _dag(_rules())
    dag.advance(1)
    tip = PersistentPNDAGCheckpointStore.first_open(root).publish(dag)
    manifest = _manifest(root, tip)

    # JSON true and 1 compare equal as Python values.  Rehash a hostile but
    # canonical manifest so only type-exact canonical-byte comparison catches
    # the changed run envelope.
    manifest["run"]["digest_index"]["collision_checked"] = 1
    manifest["run_sha256"] = sha256_hex(canonical_json_bytes(manifest["run"]))
    manifest.pop("manifest_sha256")
    new_manifest_sha = sha256_hex(canonical_json_bytes(manifest))
    manifest["manifest_sha256"] = new_manifest_sha
    (root / "manifests" / f"{new_manifest_sha}.json").write_bytes(
        canonical_json_bytes(manifest) + b"\n"
    )

    pointer = json.loads((root / "CURRENT").read_bytes())
    pointer["manifest_file"] = f"{new_manifest_sha}.json"
    pointer["manifest_sha256"] = new_manifest_sha
    pointer.pop("pointer_sha256")
    pointer["pointer_sha256"] = sha256_hex(canonical_json_bytes(pointer))
    (root / "CURRENT").write_bytes(canonical_json_bytes(pointer) + b"\n")
    hostile_tip = replace(
        tip,
        manifest_sha256=new_manifest_sha,
        run_sha256=manifest["run_sha256"],
    )

    with pytest.raises(
        PersistentPNDAGCheckpointStoreError,
        match="collision-checked indexing",
    ):
        PersistentPNDAGCheckpointStore.resume(root, expected_tip=hostile_tip)


def test_failed_current_replace_preserves_prior_tip_and_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "replace-failure"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    first = store.publish(dag)
    current = (root / "CURRENT").read_bytes()
    immutable = (
        root / "checkpoints" / f"{first.checkpoint_file_sha256}.json"
    ).read_bytes()
    dag.advance(1)

    def fail_replace(_path: Path, _data: bytes) -> None:
        raise OSError("injected CURRENT replacement failure")

    monkeypatch.setattr(
        "ugts_go19.persistent_pndag_checkpoint_store._atomic_replace_bytes",
        fail_replace,
    )
    with pytest.raises(OSError, match="injected CURRENT replacement failure"):
        store.publish(dag)

    assert (root / "CURRENT").read_bytes() == current
    assert (
        root / "checkpoints" / f"{first.checkpoint_file_sha256}.json"
    ).read_bytes() == immutable
    restored = PersistentPNDAGCheckpointStore.resume(root, expected_tip=first)
    loaded = restored.load_dag(
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=dag.root_state_bytes,
    )
    assert loaded.committed_expansions == first.committed_expansions


def test_post_replace_error_is_reconciled_only_for_exact_intended_tip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "replace-then-error"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    first = store.publish(dag)
    dag.advance(1)
    from ugts_go19 import persistent_pndag_checkpoint_store as store_module

    real_replace = store_module._atomic_replace_bytes

    def replace_then_error(path: Path, data: bytes) -> None:
        real_replace(path, data)
        raise OSError("injected error after CURRENT replacement")

    monkeypatch.setattr(store_module, "_atomic_replace_bytes", replace_then_error)
    second = store.publish(dag)

    assert second.generation == first.generation + 1
    assert store.snapshot == second
    resumed = PersistentPNDAGCheckpointStore.resume(root, expected_tip=second)
    assert resumed.snapshot == second


def test_replace_then_error_and_failed_retry_barrier_is_commit_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "replace-then-error-retry-barrier"
    dag = _dag(_rules())
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    store.publish(dag)
    dag.advance(1)
    preparation = store.prepare(dag)
    from ugts_go19 import persistent_pndag_checkpoint_store as store_module

    real_replace = store_module._atomic_replace_bytes

    def replace_then_error(path: Path, data: bytes) -> None:
        real_replace(path, data)
        raise OSError("injected error after CURRENT replacement")

    def fail_retry_barrier(_path: Path) -> None:
        raise OSError("injected retry durability-barrier failure")

    monkeypatch.setattr(store_module, "_atomic_replace_bytes", replace_then_error)
    monkeypatch.setattr(store_module, "_fsync_file", fail_retry_barrier)
    with pytest.raises(PersistentPNDAGCheckpointCommitUncertain) as raised:
        store.commit_prepared(preparation)

    assert raised.value.preparation == preparation
    assert store.snapshot == preparation.intended_tip
    resumed = PersistentPNDAGCheckpointStore.resume(
        root,
        expected_tip=preparation.intended_tip,
    )
    assert resumed.snapshot == preparation.intended_tip


def test_replace_then_error_and_unverifiable_current_is_commit_uncertain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "replace-then-error-unverifiable-current"
    dag = _dag(_rules())
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    store.publish(dag)
    dag.advance(1)
    preparation = store.prepare(dag)
    from ugts_go19 import persistent_pndag_checkpoint_store as store_module

    real_replace = store_module._atomic_replace_bytes
    real_load_current = store._load_current
    load_calls = 0

    def replace_then_error(path: Path, data: bytes) -> None:
        real_replace(path, data)
        raise OSError("injected error after CURRENT replacement")

    def fail_post_replace_validation(
        *, expected_tip: PersistentPNDAGCheckpointTip
    ) -> None:
        nonlocal load_calls
        load_calls += 1
        if load_calls >= 2:
            raise MemoryError("injected inability to classify CURRENT")
        real_load_current(expected_tip=expected_tip)

    monkeypatch.setattr(store_module, "_atomic_replace_bytes", replace_then_error)
    monkeypatch.setattr(store, "_load_current", fail_post_replace_validation)
    with pytest.raises(PersistentPNDAGCheckpointCommitUncertain) as raised:
        store.commit_prepared(preparation)

    assert raised.value.preparation == preparation
    assert store.snapshot == preparation.previous_tip
    monkeypatch.setattr(store, "_load_current", real_load_current)
    assert store.commit_prepared(preparation) == preparation.intended_tip


def test_checkpoint_tamper_and_noncanonical_manifest_are_rejected(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tamper"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    tip = store.publish(dag)
    checkpoint_path = root / "checkpoints" / f"{tip.checkpoint_file_sha256}.json"
    checkpoint_raw = checkpoint_path.read_bytes()

    tampered = checkpoint_raw.replace(b'"status":"UNKNOWN"', b'"status":"PROVEN "', 1)
    assert len(tampered) == len(checkpoint_raw) and tampered != checkpoint_raw
    checkpoint_path.write_bytes(tampered)
    with pytest.raises(
        PersistentPNDAGCheckpointStoreError, match="file hash disagrees"
    ):
        PersistentPNDAGCheckpointStore.resume(root, expected_tip=tip)

    checkpoint_path.write_bytes(checkpoint_raw)
    manifest_path = root / "manifests" / f"{tip.manifest_sha256}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(
        PersistentPNDAGCheckpointStoreError, match="not in canonical form"
    ):
        PersistentPNDAGCheckpointStore.resume(root, expected_tip=tip)


def test_exact_verified_checkpoint_bytes_reach_semantic_loader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "exact-loader-bytes"
    rules = _rules(1)
    dag = _dag(rules, threshold2=-1)
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    tip = store.publish(dag)
    expected_raw = (
        root / "checkpoints" / f"{tip.checkpoint_file_sha256}.json"
    ).read_bytes()
    original = PersistentProofNumberDAG.load_checkpoint.__func__
    observed: dict[str, bytes] = {}

    def capture(
        cls: type[PersistentProofNumberDAG], path: str | Path, **kwargs: object
    ) -> PersistentProofNumberDAG:
        observed["raw"] = Path(path).read_bytes()
        return original(cls, path, **kwargs)

    monkeypatch.setattr(
        PersistentProofNumberDAG,
        "load_checkpoint",
        classmethod(capture),
    )
    loaded = store.load_dag(
        expected_rules=rules,
        expected_threshold2=-1,
        expected_root_state_bytes=dag.root_state_bytes,
    )

    assert observed["raw"] == expected_raw
    assert loaded.committed_expansions == tip.committed_expansions


def test_semantic_loader_path_swap_cannot_return_an_older_valid_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "loader-path-swap"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    first = store.publish(dag)
    first_raw = (
        root / "checkpoints" / f"{first.checkpoint_file_sha256}.json"
    ).read_bytes()
    dag.advance(1)
    second = store.publish(dag)
    original = PersistentProofNumberDAG.load_checkpoint.__func__

    def swap_before_open(
        cls: type[PersistentProofNumberDAG], path: str | Path, **kwargs: object
    ) -> PersistentProofNumberDAG:
        Path(path).write_bytes(first_raw)
        return original(cls, path, **kwargs)

    monkeypatch.setattr(
        PersistentProofNumberDAG,
        "load_checkpoint",
        classmethod(swap_before_open),
    )
    with pytest.raises(
        PersistentPNDAGCheckpointStoreError,
        match="different from verified bytes",
    ):
        store.load_dag(
            expected_rules=rules,
            expected_threshold2=1,
            expected_root_state_bytes=dag.root_state_bytes,
        )
    assert store.snapshot == second


def test_injected_collision_indexes_round_trip_through_generation_store(
    tmp_path: Path,
) -> None:
    def state_digest(_data: bytes) -> bytes:
        return b"\xaa" * 32

    def history_digest(_data: bytes) -> bytes:
        return bytes(32)

    root = tmp_path / "collision-indexes"
    rules = _rules()
    history = PersistentHistory(
        2,
        digest_fn=history_digest,
        digest_name="checkpoint-store-constant-history",
    )
    dag = PersistentProofNumberDAG(
        rules,
        1,
        history,
        digest_fn=state_digest,
        digest_name="checkpoint-store-constant-state",
    )
    dag.advance(3)
    expected_root = dag.root_state_bytes
    tip = PersistentPNDAGCheckpointStore.first_open(root).publish(dag)

    resumed_store = PersistentPNDAGCheckpointStore.resume(root, expected_tip=tip)
    resumed = resumed_store.load_dag(
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=expected_root,
        digest_fn=state_digest,
        digest_name="checkpoint-store-constant-state",
        history_digest_fn=history_digest,
        history_digest_name="checkpoint-store-constant-history",
    )

    assert resumed.advance(0).graph_sha256 == tip.graph_sha256
    assert resumed.collision_bucket_sizes() == (resumed.node_count,)


def test_wrong_exact_target_pins_are_rejected_before_semantic_load(
    tmp_path: Path,
) -> None:
    root = tmp_path / "target-pins"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(1)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    store.publish(dag)

    with pytest.raises(
        PersistentPNDAGCheckpointStoreError, match="exact expected target"
    ):
        store.load_dag(
            expected_rules=rules,
            expected_threshold2=1,
            expected_root_state_bytes=dag.root_state_bytes + b"x",
        )
    with pytest.raises(PersistentPNDAGCheckpointStoreError, match="expected threshold"):
        store.load_dag(
            expected_rules=rules,
            expected_threshold2=3,
            expected_root_state_bytes=dag.root_state_bytes,
        )
    different_rules = replace(rules, profile_id="different-profile")
    with pytest.raises(
        PersistentPNDAGCheckpointStoreError, match="exact expected rules"
    ):
        store.load_dag(
            expected_rules=different_rules,
            expected_threshold2=1,
            expected_root_state_bytes=dag.root_state_bytes,
        )


def test_pinned_subprocess_restart_uses_published_generation(tmp_path: Path) -> None:
    root = tmp_path / "subprocess"
    rules = _rules()
    dag = _dag(rules)
    dag.advance(3)
    store = PersistentPNDAGCheckpointStore.first_open(root)
    tip = store.publish(dag)
    script = (
        "import json,sys; "
        "from ugts_go19.persistent_pndag_checkpoint_store import "
        "PersistentPNDAGCheckpointStore as Store, "
        "PersistentPNDAGCheckpointTip as Tip; "
        "from ugts_go19.rules import Rules; "
        "request=json.load(sys.stdin); "
        "tip=Tip.from_dict(request['tip']); "
        "rules=Rules.from_dict(request['rules']); "
        "store=Store.resume(sys.argv[1],expected_tip=tip); "
        "dag=store.load_dag(expected_rules=rules,expected_threshold2=1,"
        "expected_root_state_bytes=bytes.fromhex(request['root_state_hex'])); "
        "result=dag.advance(0); "
        "print(json.dumps({'generation':store.snapshot.generation,"
        "'committed_expansions':result.committed_expansions,"
        "'graph_sha256':result.graph_sha256},sort_keys=True))"
    )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(root),
        ],
        check=False,
        capture_output=True,
        input=json.dumps(
            {
                "root_state_hex": dag.root_state_bytes.hex(),
                "rules": rules.as_dict(),
                "tip": tip.as_dict(),
            },
            sort_keys=True,
        ),
        text=True,
    )

    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {
        "committed_expansions": tip.committed_expansions,
        "generation": tip.generation,
        "graph_sha256": tip.graph_sha256,
    }


def test_tip_shape_and_hashes_are_strict() -> None:
    valid = {
        "generation": 1,
        "manifest_sha256": "0" * 64,
        "checkpoint_file_sha256": "1" * 64,
        "checkpoint_sha256": "2" * 64,
        "run_sha256": "3" * 64,
        "graph_sha256": "4" * 64,
        "committed_expansions": 0,
    }
    assert PersistentPNDAGCheckpointTip.from_dict(valid).as_dict() == valid
    with pytest.raises(PersistentPNDAGCheckpointStoreError, match="shape"):
        PersistentPNDAGCheckpointTip.from_dict({**valid, "extra": True})
    with pytest.raises(PersistentPNDAGCheckpointStoreError, match="lowercase"):
        PersistentPNDAGCheckpointTip.from_dict({**valid, "manifest_sha256": "A" * 64})
    with pytest.raises(PersistentPNDAGCheckpointStoreError, match="integer"):
        PersistentPNDAGCheckpointTip.from_dict({**valid, "generation": True})


def test_manifest_and_pointer_are_canonical_json(tmp_path: Path) -> None:
    root = tmp_path / "canonical"
    dag = _dag(_rules())
    dag.advance(1)
    tip = PersistentPNDAGCheckpointStore.first_open(root).publish(dag)

    for path in (
        root / "CURRENT",
        root / "manifests" / f"{tip.manifest_sha256}.json",
    ):
        raw = path.read_bytes()
        assert raw == canonical_json_bytes(json.loads(raw)) + b"\n"
