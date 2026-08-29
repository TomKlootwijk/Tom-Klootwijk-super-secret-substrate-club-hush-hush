"""Focused tests for the exact compact persistent-PNDAG checkpoint codec."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from jsonschema.exceptions import ValidationError
from jsonschema.validators import validator_for

from ugts_go19.digests import canonical_json_bytes, sha256_hex
from ugts_go19.persistent_history import PersistentHistory
from ugts_go19.persistent_pndag import PersistentProofNumberDAG
from ugts_go19.persistent_pndag_compact_checkpoint import (
    deserialize_compact_checkpoint,
    load_compact_checkpoint,
    save_compact_checkpoint,
    serialize_compact_checkpoint,
)
from ugts_go19.rules import Rules


def _rules() -> Rules:
    return Rules(
        size=2,
        komi2=1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id="persistent-pndag-compact-checkpoint-test-2x2",
    )


def _partial_dag(expansions: int = 7) -> PersistentProofNumberDAG:
    rules = _rules()
    dag = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))
    assert dag.advance(expansions).status == "UNKNOWN"
    return dag


def _payload(raw: bytes) -> dict:
    return json.loads(raw.decode("utf-8"))


def _rehashed(payload: dict) -> bytes:
    unhashed = dict(payload)
    unhashed.pop("compact_artifact_sha256", None)
    payload["compact_artifact_sha256"] = sha256_hex(
        canonical_json_bytes(unhashed)
    )
    return canonical_json_bytes(payload) + b"\n"


def _rehash_forest(forest: dict) -> None:
    unhashed = dict(forest)
    unhashed.pop("artifact_sha256", None)
    forest["artifact_sha256"] = sha256_hex(canonical_json_bytes(unhashed))


def _load(raw: bytes, dag: PersistentProofNumberDAG) -> PersistentProofNumberDAG:
    return deserialize_compact_checkpoint(
        raw,
        expected_rules=dag.rules,
        expected_threshold2=dag.threshold2,
        expected_root_state_bytes=dag.root_state_bytes,
    )


def _schema_validator():
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / (
        "persistent_pndag_compact_checkpoint.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    return validator_class(schema)


def test_canonical_bytes_are_deterministic_and_load_via_strict_legacy_path() -> None:
    first = _partial_dag()
    second = _partial_dag()

    first_raw = serialize_compact_checkpoint(first)
    second_raw = serialize_compact_checkpoint(second)
    assert first_raw == second_raw

    loaded = _load(first_raw, first)
    result = loaded.advance(0)
    assert result.status == "UNKNOWN"
    assert result.committed_expansions == first.committed_expansions
    assert loaded.root_state_bytes == first.root_state_bytes
    assert loaded.graph_sha256() == first.graph_sha256()


def test_compact_load_returns_the_validated_shared_forest_roots() -> None:
    dag = _partial_dag(20)
    raw = serialize_compact_checkpoint(dag)
    compact = _payload(raw)
    loaded = _load(raw, dag)

    union_node_ids: set[int] = set()
    summed_node_count = 0
    for proof_node in loaded._nodes:
        root_node = proof_node.state.history_root._node
        local_node_ids: set[int] = set()
        stack = [] if root_node is None else [root_node]
        while stack:
            node = stack.pop()
            if id(node) in local_node_ids:
                continue
            local_node_ids.add(id(node))
            union_node_ids.add(id(node))
            stack.extend(
                child for _slot, child in getattr(node, "children", ())
            )
        summed_node_count += len(local_node_ids)

    forest = compact["history_forest"]
    assert len(union_node_ids) == forest["node_record_count"]
    assert summed_node_count > len(union_node_ids)
    assert loaded.history.board_object_count == forest["board_record_count"]
    assert loaded.retained_state_artifact_bytes == 0
    assert all(not hasattr(node, "state_bytes") for node in loaded._nodes)

    root = loaded.state_for_id(0).history_root
    placement_child = next(
        loaded.state_for_id(child_id).history_root
        for move, child_id in loaded.child_edges_for(0)
        if move >= 0
    )
    assert loaded.history.shared_node_count(root, placement_child) > 0


def test_compact_rebind_allocation_failure_never_mutates_source_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ugts_go19 import persistent_pndag as pndag_module

    dag = _partial_dag()
    raw = serialize_compact_checkpoint(dag)
    source_graph = dag.graph_sha256()
    source_compact = raw
    real_proof_node = pndag_module._ProofNode
    calls = 0

    def fail_during_rebound(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        # The strict legacy loader constructs one complete node table first.
        # Fail only after the unpublished forest-backed clone has begun.
        if calls == dag.node_count + 2:
            raise MemoryError("injected forest-backed clone allocation failure")
        return real_proof_node(*args, **kwargs)

    monkeypatch.setattr(pndag_module, "_ProofNode", fail_during_rebound)
    with pytest.raises(MemoryError, match="forest-backed clone allocation"):
        _load(raw, dag)

    monkeypatch.setattr(pndag_module, "_ProofNode", real_proof_node)
    assert calls == dag.node_count + 2
    assert dag.graph_sha256() == source_graph
    assert serialize_compact_checkpoint(dag) == source_compact


def test_compact_checkpoint_validates_against_repository_schema() -> None:
    payload = _payload(serialize_compact_checkpoint(_partial_dag()))
    _schema_validator().validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.__setitem__("unexpected", True),
        lambda payload: payload["legacy_envelope"].__setitem__(
            "unexpected", True
        ),
        lambda payload: payload["history_forest"].__setitem__(
            "unexpected", True
        ),
        lambda payload: payload["history_forest"]["boards"][0].__setitem__(
            "unexpected", True
        ),
        lambda payload: payload["history_forest"]["nodes"][0].__setitem__(
            "unexpected", True
        ),
        lambda payload: payload["nodes"][0].__setitem__("passes", "0"),
        lambda payload: payload["legacy_envelope"].__setitem__(
            "committed_expansions", False
        ),
        lambda payload: payload["history_forest"]["roots"][0].__setitem__(
            "root_sha256", 0
        ),
    ],
    ids=(
        "top-level-extra",
        "legacy-envelope-extra",
        "forest-envelope-extra",
        "forest-board-extra",
        "forest-node-extra",
        "compact-node-wrong-type",
        "legacy-counter-wrong-type",
        "forest-root-wrong-type",
    ),
)
def test_compact_checkpoint_schema_rejects_closed_shapes_and_wrong_types(
    mutation: object,
) -> None:
    payload = _payload(serialize_compact_checkpoint(_partial_dag()))
    mutation(payload)  # type: ignore[operator]

    with pytest.raises(ValidationError):
        _schema_validator().validate(payload)


def test_resume_matches_uninterrupted_exact_result() -> None:
    rules = _rules()
    expected = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))
    expected_result = expected.advance(10_000)
    assert expected_result.status == "PROVEN"

    partial = _partial_dag()
    resumed = _load(serialize_compact_checkpoint(partial), partial)
    actual = resumed.advance(10_000)

    assert actual.status == expected_result.status
    assert actual.proof_number == expected_result.proof_number
    assert actual.disproof_number == expected_result.disproof_number
    assert actual.committed_expansions == expected_result.committed_expansions
    assert actual.node_count == expected_result.node_count
    assert actual.edge_count == expected_result.edge_count
    assert actual.graph_sha256 == expected_result.graph_sha256


def test_file_save_load_and_collision_resistance_based_artifact_pin(
    tmp_path: Path,
) -> None:
    dag = _partial_dag()
    path = tmp_path / "compact.json"
    save_compact_checkpoint(dag, path)
    payload = _payload(path.read_bytes())
    pin = payload["compact_artifact_sha256"]

    loaded = load_compact_checkpoint(
        path,
        expected_rules=dag.rules,
        expected_threshold2=dag.threshold2,
        expected_root_state_bytes=dag.root_state_bytes,
        expected_compact_artifact_sha256=pin,
    )
    assert loaded.graph_sha256() == dag.graph_sha256()

    wrong_pin = "0" * 64 if pin != "0" * 64 else "1" * 64
    with pytest.raises(ValueError, match="expected artifact"):
        load_compact_checkpoint(
            path,
            expected_rules=dag.rules,
            expected_threshold2=dag.threshold2,
            expected_root_state_bytes=dag.root_state_bytes,
            expected_compact_artifact_sha256=wrong_pin,
        )


def test_compact_forest_removes_most_repeated_history_bytes(tmp_path: Path) -> None:
    dag = _partial_dag(20)
    legacy = tmp_path / "legacy.json"
    dag.save_checkpoint(legacy)
    compact = serialize_compact_checkpoint(dag)

    # This bounded fixture currently removes over 90% of durable bytes.  Keep a
    # deliberately looser gate so harmless JSON metadata changes do not make
    # the exact-codec test brittle.
    assert len(compact) < legacy.stat().st_size // 5
    loaded = _load(compact, dag)
    assert loaded.graph_sha256() == dag.graph_sha256()


def test_forced_history_and_state_digest_collisions_preserve_exact_identity() -> None:
    def constant_history_digest(_board: bytes) -> bytes:
        return bytes(32)

    def constant_state_digest(_state: bytes) -> bytes:
        return b"\xaa" * 32

    rules = _rules()
    history_name = "compact-constant-history-test"
    state_name = "compact-constant-state-test"
    history = PersistentHistory(
        2,
        digest_fn=constant_history_digest,
        digest_name=history_name,
    )
    dag = PersistentProofNumberDAG(
        rules,
        1,
        history,
        digest_fn=constant_state_digest,
        digest_name=state_name,
    )
    assert dag.advance(7).status == "UNKNOWN"
    raw = serialize_compact_checkpoint(dag)

    loaded = deserialize_compact_checkpoint(
        raw,
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=dag.root_state_bytes,
        digest_fn=constant_state_digest,
        digest_name=state_name,
        history_digest_fn=constant_history_digest,
        history_digest_name=history_name,
    )

    assert loaded.graph_sha256() == dag.graph_sha256()
    assert loaded.collision_bucket_sizes() == (loaded.node_count,)
    assert loaded.history.digest_bucket_sizes() == (
        loaded.history.board_object_count,
    )
    assert loaded.retained_state_artifact_bytes == 0
    root = loaded.state_for_id(0).history_root
    pass_child = next(
        loaded.state_for_id(child_id).history_root
        for move, child_id in loaded.child_edges_for(0)
        if move < 0
    )
    # A constant board-index digest gives the trie only one path, so inserting
    # another colliding board path-copies that complete path.  Passing still
    # preserves the exact forest node handle rather than duplicating it.
    assert pass_child._node is root._node


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["legacy_envelope"].__setitem__(
            "status", "PROVEN"
        ),
        lambda payload: payload["nodes"][0].__setitem__("cached_proof", 0),
        lambda payload: payload["nodes"][0].__setitem__("board_hex", "01" * 4),
    ],
    ids=("false-solved-status", "proof-cache", "state-board"),
)
def test_rehashed_semantic_tamper_is_rejected_by_exact_legacy_validation(
    mutation: object,
) -> None:
    dag = _partial_dag()
    payload = _payload(serialize_compact_checkpoint(dag))
    mutation(payload)  # type: ignore[operator]

    with pytest.raises(ValueError):
        _load(_rehashed(payload), dag)


def test_rehashed_forest_or_positional_mapping_tamper_is_rejected() -> None:
    dag = _partial_dag()
    payload = _payload(serialize_compact_checkpoint(dag))
    roots = payload["history_forest"]["roots"]
    second_index = next(
        index
        for index, root in enumerate(roots[1:], start=1)
        if root["root_sha256"] != roots[0]["root_sha256"]
    )
    first = {key: value for key, value in roots[0].items() if key != "id"}
    second = {
        key: value for key, value in roots[second_index].items() if key != "id"
    }
    roots[0].update(second)
    roots[second_index].update(first)
    _rehash_forest(payload["history_forest"])

    # Repair both integrity hashes so rejection reaches the positional
    # state-to-history mapping and strict legacy semantic validation.
    with pytest.raises(ValueError):
        _load(_rehashed(payload), dag)


def test_wrong_exact_root_pin_and_node_root_cardinality_are_rejected() -> None:
    dag = _partial_dag()
    raw = serialize_compact_checkpoint(dag)
    with pytest.raises(ValueError, match="exact expected target"):
        deserialize_compact_checkpoint(
            raw,
            expected_rules=dag.rules,
            expected_threshold2=dag.threshold2,
            expected_root_state_bytes=dag.root_state_bytes + b"x",
        )

    payload = _payload(raw)
    payload["nodes"].pop()
    with pytest.raises(ValueError, match="counts differ"):
        _load(_rehashed(payload), dag)


def test_noncanonical_and_hostile_envelopes_are_rejected() -> None:
    dag = _partial_dag()
    raw = serialize_compact_checkpoint(dag)

    with pytest.raises(ValueError, match="canonical form"):
        _load(raw[:-1], dag)

    duplicate = raw.replace(
        b'{"codec":', b'{"codec":"duplicate","codec":', 1
    )
    with pytest.raises(ValueError, match="canonical JSON"):
        _load(duplicate, dag)

    payload = _payload(raw)
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="noncanonical shape"):
        _load(_rehashed(payload), dag)


def test_failed_atomic_replace_preserves_previous_compact_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dag = _partial_dag()
    path = tmp_path / "compact.json"
    save_compact_checkpoint(dag, path)
    previous = path.read_bytes()
    dag.advance(1)

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("injected compact publication failure")

    monkeypatch.setattr(
        "ugts_go19.persistent_pndag_compact_checkpoint.os.replace", fail_replace
    )
    with pytest.raises(OSError, match="compact publication"):
        save_compact_checkpoint(dag, path)

    assert path.read_bytes() == previous
    assert _load(previous, _partial_dag()).advance(0).status == "UNKNOWN"


def test_valid_legacy_temp_path_swap_cannot_replace_compact_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requested = _partial_dag(7)
    replacement = _partial_dag(8)
    replacement_path = tmp_path / "replacement-legacy.json"
    replacement.save_checkpoint(replacement_path)
    replacement_raw = replacement_path.read_bytes()
    original = PersistentProofNumberDAG.load_checkpoint.__func__

    def swap_before_open(
        cls: type[PersistentProofNumberDAG], path: str | Path, **kwargs: object
    ) -> PersistentProofNumberDAG:
        Path(path).write_bytes(replacement_raw)
        return original(cls, path, **kwargs)

    monkeypatch.setattr(
        PersistentProofNumberDAG,
        "load_checkpoint",
        classmethod(swap_before_open),
    )
    with pytest.raises(ValueError, match="different from reconstructed bytes"):
        _load(serialize_compact_checkpoint(requested), requested)


def test_compact_save_closes_descriptor_and_unlinks_temp_on_fdopen_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ugts_go19 import persistent_pndag_compact_checkpoint as compact_module

    captured: dict[str, object] = {}
    real_mkstemp = compact_module.tempfile.mkstemp

    def capture_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        descriptor, name = real_mkstemp(*args, **kwargs)
        captured.update(descriptor=descriptor, name=name)
        return descriptor, name

    def fail_fdopen(_descriptor: int, _mode: str) -> object:
        raise MemoryError("injected compact fdopen failure")

    monkeypatch.setattr(compact_module.tempfile, "mkstemp", capture_mkstemp)
    monkeypatch.setattr(compact_module.os, "fdopen", fail_fdopen)
    with pytest.raises(MemoryError, match="injected compact fdopen failure"):
        save_compact_checkpoint(_partial_dag(), tmp_path / "compact.json")

    assert not Path(captured["name"]).exists()
    with pytest.raises(OSError):
        os.fstat(captured["descriptor"])  # type: ignore[arg-type]


def test_compact_load_closes_descriptor_and_unlinks_temp_on_fdopen_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ugts_go19 import persistent_pndag_compact_checkpoint as compact_module

    dag = _partial_dag()
    raw = serialize_compact_checkpoint(dag)
    captured: dict[str, object] = {}
    real_mkstemp = compact_module.tempfile.mkstemp

    def capture_mkstemp(*args: object, **kwargs: object) -> tuple[int, str]:
        descriptor, name = real_mkstemp(*args, **kwargs)
        captured.update(descriptor=descriptor, name=name)
        return descriptor, name

    def fail_fdopen(_descriptor: int, _mode: str) -> object:
        raise MemoryError("injected reconstructed fdopen failure")

    monkeypatch.setattr(compact_module.tempfile, "mkstemp", capture_mkstemp)
    monkeypatch.setattr(compact_module.os, "fdopen", fail_fdopen)
    with pytest.raises(MemoryError, match="injected reconstructed fdopen failure"):
        _load(raw, dag)

    assert not Path(captured["name"]).exists()
    with pytest.raises(OSError):
        os.fstat(captured["descriptor"])  # type: ignore[arg-type]
