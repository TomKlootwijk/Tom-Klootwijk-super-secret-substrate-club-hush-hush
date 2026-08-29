"""Focused tests for the bounded persistent-history proof-number DAG."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema.validators import validator_for

from ugts_go19.constants import BLACK, PASS
from ugts_go19.digests import canonical_json_bytes, sha256_hex
from ugts_go19.exact import ExactSolver
from ugts_go19.pndag import ProofNumberDAG
from ugts_go19.persistent_engine import PersistentState, initial_state
from ugts_go19.persistent_history import PersistentHistory
from ugts_go19.persistent_pndag import (
    PROOF_ARITHMETIC,
    SCOPE,
    UINT64_MAX,
    PersistentProofNumberDAG,
    _sat_add,
    canonical_persistent_state_bytes,
)
from ugts_go19.rules import Rules


def _rules(size: int) -> Rules:
    return Rules(
        size=size,
        komi2=1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id=f"persistent-pndag-test-{size}x{size}",
    )


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_rehashed(path: Path, payload: dict) -> None:
    unhashed = dict(payload)
    unhashed.pop("checkpoint_sha256", None)
    payload["checkpoint_sha256"] = sha256_hex(canonical_json_bytes(unhashed))
    path.write_bytes(canonical_json_bytes(payload) + b"\n")


@pytest.mark.parametrize(
    ("threshold2", "expected"),
    [
        (1, ("PROVEN", 0, UINT64_MAX)),
        (3, ("DISPROVEN", UINT64_MAX, 0)),
    ],
)
def test_complete_2x2_thresholds_match_exact_solver_and_existing_pndag(
    threshold2: int, expected: tuple[str, int, int]
) -> None:
    rules = _rules(2)
    assert ExactSolver(rules, node_budget=50_000).solve().value2 == 1
    flat_dag = ProofNumberDAG(rules, threshold2).advance(10_000)
    history = PersistentHistory(2)
    persistent = PersistentProofNumberDAG(rules, threshold2, history).advance(10_000)

    assert (
        persistent.status,
        persistent.proof_number,
        persistent.disproof_number,
    ) == expected
    assert (
        flat_dag.status,
        flat_dag.proof_number,
        flat_dag.disproof_number,
    ) == expected


def test_budget_stop_is_unknown_and_result_declares_bounded_scope() -> None:
    rules = _rules(2)
    dag = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))

    untouched = dag.advance(0)
    partial = dag.advance(1)

    assert untouched.status == "UNKNOWN"
    assert untouched.expanded_this_call == 0
    assert partial.status == "UNKNOWN"
    assert partial.expanded_this_call == 1
    assert partial.proof_number > 0
    assert partial.disproof_number > 0
    assert partial.as_dict()["scope"] == SCOPE


def test_live_nodes_retain_zero_serialized_state_or_history_artifacts() -> None:
    rules = _rules(2)
    dag = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))
    assert dag.advance(20).status == "UNKNOWN"

    transient_total = sum(
        len(canonical_persistent_state_bytes(node.state, rules, dag.history))
        for node in dag._nodes
    )
    assert transient_total > 1_000_000
    assert dag.retained_state_artifact_bytes == 0
    assert all(not hasattr(node, "state_bytes") for node in dag._nodes)


def test_transitions_never_flatten_history_and_keep_shared_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = _rules(2)
    history = PersistentHistory(2)

    def fail_if_materialized(
        _self: PersistentHistory, _root: object
    ) -> tuple[bytes, ...]:
        raise AssertionError("persistent PNDAG materialized flat history")

    monkeypatch.setattr(PersistentHistory, "members", fail_if_materialized)
    dag = PersistentProofNumberDAG(rules, 1, history)
    old_root = dag.state_for_id(0).history_root
    assert dag.advance(1).status == "UNKNOWN"

    point_roots = []
    pass_root = None
    for move, child_id in dag.child_edges_for(0):
        child_root = dag.state_for_id(child_id).history_root
        if move == PASS:
            pass_root = child_root
        else:
            point_roots.append(child_root)
    assert pass_root is old_root
    assert point_roots
    for child_root in point_roots:
        assert child_root is not old_root
        assert history.shared_node_count(old_root, child_root) > 0
    assert old_root.count == 1


def test_exact_state_identity_includes_history_artifact_but_excludes_ply() -> None:
    def constant_history_digest(_board: bytes) -> bytes:
        return bytes(32)

    def constant_state_digest(_state: bytes) -> bytes:
        return b"\x55" * 32

    rules = _rules(2)
    history = PersistentHistory(
        2,
        digest_fn=constant_history_digest,
        digest_name="constant-history-identity-test",
    )
    root_state = initial_state(rules, history)
    dag = PersistentProofNumberDAG(
        rules,
        1,
        history,
        root_state,
        digest_fn=constant_state_digest,
        digest_name="constant-state-identity-test",
    )
    extra_board = bytes((BLACK, 0, 0, 0))
    poisoned_root = history.insert(root_state.history_root, extra_board)
    different_history = PersistentState(
        board=root_state.board,
        to_play=root_state.to_play,
        passes=root_state.passes,
        history_root=poisoned_root,
        previous_board=root_state.previous_board,
        ply=root_state.ply,
    )
    different_ply = PersistentState(
        board=root_state.board,
        to_play=root_state.to_play,
        passes=root_state.passes,
        history_root=root_state.history_root,
        previous_board=root_state.previous_board,
        ply=1,
    )

    root_bytes = canonical_persistent_state_bytes(root_state, rules, history)
    assert (
        canonical_persistent_state_bytes(different_history, rules, history)
        != root_bytes
    )
    assert canonical_persistent_state_bytes(different_ply, rules, history) == root_bytes
    assert dag.lookup_state_id(different_history) is None
    assert dag.lookup_state_id(different_ply) == 0
    different_history_id = dag._intern_state(different_history)
    assert different_history_id != 0
    assert dag.lookup_state_id(different_history) == different_history_id
    assert dag.lookup_state_id(different_ply) == 0
    assert dag.collision_bucket_sizes() == (2,)


@pytest.mark.parametrize("collide", (False, True))
def test_failed_expansion_rolls_back_dag_and_history_cache(
    monkeypatch: pytest.MonkeyPatch, collide: bool
) -> None:
    rules = _rules(2)
    history = (
        PersistentHistory(
            2,
            digest_fn=lambda _board: bytes(32),
            digest_name="rollback-constant-digest-test",
        )
        if collide
        else PersistentHistory(2)
    )
    dag = PersistentProofNumberDAG(rules, 1, history)
    initial_board_count = history.board_object_count
    real_intern = dag._intern_state
    calls = 0

    def fail_mid_expansion(state: PersistentState) -> int:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise MemoryError("injected speculative history failure")
        return real_intern(state)

    monkeypatch.setattr(dag, "_intern_state", fail_mid_expansion)
    with pytest.raises(MemoryError, match="injected speculative"):
        dag.advance(1)

    assert dag.node_count == 1
    assert dag.edge_count == 0
    assert dag.committed_expansions == 0
    assert history.board_object_count == initial_board_count
    assert history.digest_bucket_sizes() == (1,)

    monkeypatch.setattr(dag, "_intern_state", real_intern)
    actual = dag.advance(1)
    fresh_history = (
        PersistentHistory(
            2,
            digest_fn=lambda _board: bytes(32),
            digest_name="rollback-constant-digest-test",
        )
        if collide
        else PersistentHistory(2)
    )
    fresh = PersistentProofNumberDAG(rules, 1, fresh_history)
    expected = fresh.advance(1)
    assert actual == expected
    assert history.board_object_count == fresh_history.board_object_count
    assert history.digest_bucket_sizes() == fresh_history.digest_bucket_sizes()
    assert dag.collision_bucket_sizes() == fresh.collision_bucket_sizes()


def test_reverse_parent_publication_failure_rolls_back_existing_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class MutateThenFailSet(set[int]):
        def add(self, value: int) -> None:
            super().add(value)
            raise MemoryError("injected reverse-parent publication failure")

    rules = _rules(2)
    history = PersistentHistory(2)
    dag = PersistentProofNumberDAG(rules, 1, history)
    first_child_state = dag._canonical_children(dag.state_for_id(0))[0][1]
    existing_child_id = dag._intern_state(first_child_state)
    original_node_count = dag.node_count
    dag._nodes[existing_child_id].parents = MutateThenFailSet()

    with pytest.raises(MemoryError, match="reverse-parent publication"):
        dag.advance(1)

    assert dag.node_count == original_node_count
    assert dag.edge_count == 0
    assert dag.committed_expansions == 0
    assert dag.parent_ids_for(existing_child_id) == ()


def test_campaign_ply_does_not_block_semantically_identical_root() -> None:
    rules = _rules(2)
    history = PersistentHistory(2)
    root = initial_state(rules, history)
    huge_ply = PersistentState(
        root.board,
        root.to_play,
        root.passes,
        root.history_root,
        root.previous_board,
        UINT64_MAX,
    )
    normal = PersistentProofNumberDAG(rules, 1, history, root)
    huge = PersistentProofNumberDAG(rules, 1, history, huge_ply)

    assert huge.root_state_bytes == normal.root_state_bytes
    assert huge.advance(1).status == normal.advance(1).status == "UNKNOWN"
    assert huge.graph_sha256() == normal.graph_sha256()


def test_partial_checkpoint_resume_in_fresh_object_matches_uninterrupted_graph(
    tmp_path: Path,
) -> None:
    rules = _rules(2)
    uninterrupted = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))
    expected = uninterrupted.advance(10_000)
    assert expected.status == "PROVEN"

    interrupted = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))
    assert interrupted.advance(7).status == "UNKNOWN"
    pin = interrupted.root_state_bytes
    checkpoint = tmp_path / "persistent-pndag.json"
    interrupted.save_checkpoint(checkpoint)

    resumed = PersistentProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=pin,
    )
    actual = resumed.advance(10_000)

    assert actual.status == expected.status
    assert actual.proof_number == expected.proof_number
    assert actual.disproof_number == expected.disproof_number
    assert actual.committed_expansions == expected.committed_expansions
    assert actual.node_count == expected.node_count
    assert actual.edge_count == expected.edge_count
    assert actual.graph_sha256 == expected.graph_sha256


def test_checkpoint_recomputes_in_a_fresh_consumer_process(tmp_path: Path) -> None:
    rules = _rules(2)
    dag = PersistentProofNumberDAG(rules, 1, PersistentHistory(2))
    expected = dag.advance(7)
    checkpoint = tmp_path / "producer-checkpoint.json"
    root_pin = tmp_path / "exact-root-state.bin"
    dag.save_checkpoint(checkpoint)
    root_pin.write_bytes(dag.root_state_bytes)

    script = (
        "import json,sys; "
        "from ugts_go19.persistent_pndag import PersistentProofNumberDAG; "
        "from ugts_go19.rules import Rules; "
        "from pathlib import Path; "
        "rules=Rules.from_dict(json.loads(sys.argv[2])); "
        "dag=PersistentProofNumberDAG.load_checkpoint(sys.argv[1],"
        "expected_rules=rules,expected_threshold2=int(sys.argv[3]),"
        "expected_root_state_bytes=Path(sys.argv[4]).read_bytes()); "
        "r=dag.advance(0); "
        "print(json.dumps(r.as_dict(),sort_keys=True,separators=(',',':')))"
    )
    environment = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get(
        "PYTHONPATH", ""
    )
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(checkpoint),
            json.dumps(rules.as_dict()),
            "1",
            str(root_pin),
        ],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    actual = json.loads(process.stdout)
    expected_payload = expected.as_dict()
    expected_payload["expanded_this_call"] = 0
    assert actual == expected_payload


def test_checkpoint_v2_validates_against_repository_schema(tmp_path: Path) -> None:
    checkpoint = tmp_path / "schema-valid.json"
    dag = PersistentProofNumberDAG(_rules(2), 1, PersistentHistory(2))
    dag.advance(5)
    dag.save_checkpoint(checkpoint)
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / (
        "persistent_pndag_checkpoint.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(schema).validate(_read(checkpoint))


def test_forced_history_and_state_digest_collisions_survive_restart(
    tmp_path: Path,
) -> None:
    def constant_history_digest(_board: bytes) -> bytes:
        return bytes(32)

    def constant_state_digest(_state: bytes) -> bytes:
        return b"\xaa" * 32

    rules = _rules(2)
    history_name = "constant-history-restart-test"
    state_name = "constant-state-restart-test"
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
    checkpoint = tmp_path / "colliding.json"
    dag.save_checkpoint(checkpoint)

    loaded = PersistentProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_threshold2=1,
        expected_root_state_bytes=dag.root_state_bytes,
        digest_fn=constant_state_digest,
        digest_name=state_name,
        history_digest_fn=constant_history_digest,
        history_digest_name=history_name,
    )
    result = loaded.advance(10_000)

    assert (result.status, result.proof_number, result.disproof_number) == (
        "PROVEN",
        0,
        UINT64_MAX,
    )
    assert loaded.collision_bucket_sizes() == (loaded.node_count,)
    assert loaded.history.digest_bucket_sizes() == (loaded.history.board_object_count,)


def test_checkpoint_rejects_wrong_root_pin_and_rehashed_cache_tamper(
    tmp_path: Path,
) -> None:
    rules = _rules(1)
    dag = PersistentProofNumberDAG(rules, -1, PersistentHistory(1))
    assert dag.advance(1).status == "UNKNOWN"
    checkpoint = tmp_path / "checkpoint.json"
    dag.save_checkpoint(checkpoint)

    with pytest.raises(ValueError, match="exact expected target"):
        PersistentProofNumberDAG.load_checkpoint(
            checkpoint,
            expected_rules=rules,
            expected_threshold2=-1,
            expected_root_state_bytes=dag.root_state_bytes + b"x",
        )

    payload = _read(checkpoint)
    payload["status"] = "PROVEN"
    _write_rehashed(checkpoint, payload)
    with pytest.raises(ValueError, match="status fails independent recomputation"):
        PersistentProofNumberDAG.load_checkpoint(
            checkpoint,
            expected_rules=rules,
            expected_threshold2=-1,
            expected_root_state_bytes=dag.root_state_bytes,
        )


def test_solved_checkpoint_reload_performs_zero_more_expansions(
    tmp_path: Path,
) -> None:
    rules = _rules(1)
    dag = PersistentProofNumberDAG(rules, -1, PersistentHistory(1))
    solved = dag.advance(100)
    assert solved.status == "PROVEN"
    checkpoint = tmp_path / "solved.json"
    dag.save_checkpoint(checkpoint)

    loaded = PersistentProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_threshold2=-1,
        expected_root_state_bytes=dag.root_state_bytes,
    )
    reloaded = loaded.advance(0)

    assert reloaded.status == "PROVEN"
    assert reloaded.expanded_this_call == 0
    assert reloaded.committed_expansions == solved.committed_expansions
    assert reloaded.graph_sha256 == solved.graph_sha256


def test_failed_atomic_replace_preserves_previous_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules = _rules(1)
    dag = PersistentProofNumberDAG(rules, -1, PersistentHistory(1))
    checkpoint = tmp_path / "atomic.json"
    dag.save_checkpoint(checkpoint)
    previous = checkpoint.read_bytes()
    dag.advance(1)

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr("ugts_go19.persistent_pndag.os.replace", fail_replace)
    with pytest.raises(OSError, match="injected publication failure"):
        dag.save_checkpoint(checkpoint)

    assert checkpoint.read_bytes() == previous
    restored = PersistentProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_threshold2=-1,
        expected_root_state_bytes=dag.root_state_bytes,
    )
    assert restored.advance(0).committed_expansions == 0


def test_uint64_saturation_and_unsupported_campaign_scope() -> None:
    assert UINT64_MAX == (1 << 64) - 1
    assert _sat_add((UINT64_MAX - 1, 1)) == UINT64_MAX
    assert _sat_add((UINT64_MAX - 1, 2)) == UINT64_MAX
    assert PROOF_ARITHMETIC["kind"] == "saturating_uint64"
    with pytest.raises(ValueError, match="outside uint64"):
        _sat_add((-1,))
    with pytest.raises(ValueError, match="outside uint64"):
        _sat_add((UINT64_MAX + 1,))
    with pytest.raises(ValueError, match="outside uint64"):
        _sat_add((UINT64_MAX - 1, 2, -1))

    for edge_komi2 in (-(1 << 63), (1 << 63) - 1):
        rules = Rules(
            size=2,
            komi2=edge_komi2,
            superko="positional_superko",
            allow_suicide=False,
            scoring="area",
            passes_to_end=2,
            profile_id="persistent-pndag-score-overflow-rejected",
        )
        with pytest.raises(ValueError, match="possible score2 range"):
            PersistentProofNumberDAG(rules, 1, PersistentHistory(2))

    rules = Rules.canonical_19x19()
    with pytest.raises(ValueError, match="bounded to 1x1 and 2x2"):
        PersistentProofNumberDAG(rules, 1, PersistentHistory(19))
