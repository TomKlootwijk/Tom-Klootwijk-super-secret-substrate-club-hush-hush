"""Bounded exactness tests for the tiny restartable proof-number DAG.

The exhaustive proof searches here are intentionally capped at 2x2.  They
exercise durable DAG invariants without implying production or 19x19 scale.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema.validators import validator_for

import ugts_go19.pndag as pndag_module
from ugts_go19.constants import PASS
from ugts_go19.cli import main as cli_main
from ugts_go19.digests import canonical_json_bytes, sha256_hex
from ugts_go19.engine import apply_move, play_sequence
from ugts_go19.pndag import ProofNumberDAG, UINT64_MAX
from ugts_go19.rules import Rules
from ugts_go19.state import State


def _rules(size: int) -> Rules:
    return Rules(
        size=size,
        komi2=1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id=f"test-{size}x{size}-area-psk-k0.5",
    )


def _read_checkpoint(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_rehashed_checkpoint(path: Path, payload: dict) -> None:
    unhashed = dict(payload)
    unhashed.pop("checkpoint_sha256", None)
    payload["checkpoint_sha256"] = sha256_hex(canonical_json_bytes(unhashed))
    path.write_bytes(canonical_json_bytes(payload) + b"\n")


@pytest.mark.parametrize(
    ("threshold2", "expected_status"),
    [(1, "PROVEN"), (3, "DISPROVEN")],
)
def test_2x2_interrupted_resume_matches_uninterrupted_exact_graph(
    tmp_path: Path, threshold2: int, expected_status: str
) -> None:
    """Deterministic bounded 2x2 corpus: resume adds work, never resets it."""

    rules = _rules(2)
    uninterrupted = ProofNumberDAG(rules, threshold2)
    complete = uninterrupted.advance(10_000)
    assert complete.status == expected_status
    if expected_status == "PROVEN":
        assert (complete.proof_number, complete.disproof_number) == (0, UINT64_MAX)
    else:
        assert (complete.proof_number, complete.disproof_number) == (UINT64_MAX, 0)

    interrupted = ProofNumberDAG(rules, threshold2)
    partial = interrupted.advance(7)
    assert partial.status == "UNKNOWN"
    assert partial.proof_number > 0
    assert partial.disproof_number > 0
    assert partial.expanded_this_call == 7
    checkpoint = tmp_path / f"threshold-{threshold2}.json"
    interrupted.save_checkpoint(checkpoint)

    resumed = ProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_root_state=State.initial(rules),
        expected_threshold2=threshold2,
    )
    first_increment = resumed.advance(3)
    assert first_increment.expanded_this_call == 3
    assert first_increment.committed_expansions == 10
    resumed_complete = resumed.advance(10_000)

    assert resumed_complete.status == complete.status
    assert resumed_complete.proof_number == complete.proof_number
    assert resumed_complete.disproof_number == complete.disproof_number
    assert resumed_complete.committed_expansions == complete.committed_expansions
    assert resumed_complete.node_count == complete.node_count
    assert resumed_complete.edge_count == complete.edge_count
    assert resumed_complete.graph_sha256 == complete.graph_sha256


def test_1x1_psk_threshold_truth_and_unknown_contract() -> None:
    """The 1x1 game has only pass edges with suicide disabled."""

    rules = _rules(1)
    proof = ProofNumberDAG(rules, threshold2=-1)
    untouched = proof.advance(0)
    assert untouched.status == "UNKNOWN"
    assert (untouched.proof_number, untouched.disproof_number) == (1, 1)
    assert proof.advance(10).status == "PROVEN"

    disproof = ProofNumberDAG(rules, threshold2=0).advance(10)
    assert disproof.status == "DISPROVEN"


def test_exact_semantic_bytes_merge_ply_but_distinguish_history_and_lineage() -> None:
    rules = _rules(2)
    root = State.initial(rules)
    dag = ProofNumberDAG(rules, threshold2=1, root_state=root)

    same_semantics_different_ply = State(
        board=root.board,
        to_play=root.to_play,
        passes=root.passes,
        seen=root.seen,
        previous_board=root.previous_board,
        ply=999,
    )
    assert dag.lookup_state_id(same_semantics_different_ply) == dag.root_id

    extra_history = State(
        board=root.board,
        to_play=root.to_play,
        passes=root.passes,
        seen=root.seen | frozenset((bytes((1, 0, 0, 0)),)),
        previous_board=root.previous_board,
        ply=0,
    )
    different_lineage = State(
        board=root.board,
        to_play=root.to_play,
        passes=root.passes,
        seen=root.seen,
        previous_board=root.board,
        ply=0,
    )
    assert dag.lookup_state_id(extra_history) is None
    assert dag.lookup_state_id(different_lineage) is None
    history_rooted = ProofNumberDAG(rules, threshold2=1, root_state=extra_history)
    assert history_rooted.lookup_state_id(different_lineage) is None


def test_real_transposition_has_two_incoming_paths_after_checkpoint(
    tmp_path: Path,
) -> None:
    rules = _rules(2)
    initial = State.initial(rules)
    first_moves = (0, 2, 3, PASS, 1, 2, PASS, 1, PASS)
    second_moves = (0, PASS, 3, PASS, 1, 2, 0, 1, PASS)
    first = play_sequence(initial, first_moves, rules)
    second = play_sequence(initial, second_moves, rules)
    assert first.exact_key() == second.exact_key()

    dag = ProofNumberDAG(rules, threshold2=1)

    def expand_path(moves: tuple[int, ...]) -> tuple[int, int]:
        state = initial
        node_id = dag.root_id
        parent_id = node_id
        for move in moves:
            if dag._nodes[node_id].expansion == "unexpanded":
                dag._expand_node(node_id)
            parent_id = node_id
            state = apply_move(state, move, rules)
            child_id = dag.lookup_state_id(state)
            assert child_id is not None
            node_id = child_id
        return parent_id, node_id

    first_parent, first_id = expand_path(first_moves)
    second_parent, second_id = expand_path(second_moves)
    assert first_id == second_id
    assert first_parent != second_parent
    assert {first_parent, second_parent}.issubset(dag.parent_ids_for(first_id))

    dag._recompute_all()
    checkpoint = tmp_path / "transposition.json"
    dag.save_checkpoint(checkpoint)
    restored = ProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_root_state=initial,
        expected_threshold2=1,
    )
    assert {first_parent, second_parent}.issubset(restored.parent_ids_for(first_id))


def test_constant_digest_retains_collisions_and_deduplicates_exact_bytes(
    tmp_path: Path,
) -> None:
    rules = _rules(2)

    def constant_digest(_data: bytes) -> bytes:
        return bytes(32)

    dag = ProofNumberDAG(
        rules,
        threshold2=1,
        digest_fn=constant_digest,
        digest_name="constant-test",
    )
    assert dag.advance(1).status == "UNKNOWN"
    assert dag.node_count == 6  # four placements plus pass, all distinct from root
    assert dag.collision_bucket_sizes() == (6,)

    root = State.initial(rules)
    pass_state = apply_move(root, PASS, rules)
    pass_id = dag.lookup_state_id(pass_state)
    assert dag.lookup_state_id(root) == dag.root_id
    assert pass_id is not None
    assert dag.lookup_state_id(pass_state) == pass_id
    assert dag.node_count == 6

    checkpoint = tmp_path / "constant-digest.json"
    roundtrip = tmp_path / "constant-digest-roundtrip.json"
    dag.save_checkpoint(checkpoint)
    loaded = ProofNumberDAG.load_checkpoint(
        checkpoint,
        digest_fn=constant_digest,
        digest_name="constant-test",
    )
    assert loaded.node_count == 6
    assert loaded.collision_bucket_sizes() == (6,)
    assert loaded.graph_sha256() == dag.graph_sha256()
    loaded.save_checkpoint(roundtrip)
    assert roundtrip.read_bytes() == checkpoint.read_bytes()


def test_checkpoint_rejects_content_corruption_and_rehashed_status_tamper(
    tmp_path: Path,
) -> None:
    rules = _rules(2)
    dag = ProofNumberDAG(rules, threshold2=1)
    assert dag.advance(5).status == "UNKNOWN"
    checkpoint = tmp_path / "checkpoint.json"
    dag.save_checkpoint(checkpoint)

    corrupted = tmp_path / "corrupted.json"
    raw = bytearray(checkpoint.read_bytes())
    marker = b'"checkpoint_sha256":"'
    digest_start = raw.index(marker) + len(marker)
    raw[digest_start] = ord("1") if raw[digest_start] != ord("1") else ord("2")
    corrupted.write_bytes(raw)
    with pytest.raises(ValueError, match="content hash mismatch"):
        ProofNumberDAG.load_checkpoint(corrupted)

    tampered = tmp_path / "tampered-status.json"
    payload = _read_checkpoint(checkpoint)
    payload["status"] = "PROVEN"
    _write_rehashed_checkpoint(tampered, payload)
    with pytest.raises(ValueError, match="status fails independent recomputation"):
        ProofNumberDAG.load_checkpoint(tampered)


def test_checkpoint_rejects_rehashed_missing_edge(tmp_path: Path) -> None:
    rules = _rules(2)
    dag = ProofNumberDAG(rules, threshold2=1)
    dag.advance(1)
    checkpoint = tmp_path / "complete-root-edges.json"
    tampered = tmp_path / "missing-edge.json"
    dag.save_checkpoint(checkpoint)

    payload = _read_checkpoint(checkpoint)
    root_record = payload["nodes"][payload["root_id"]]
    assert root_record["expansion"] == "expanded"
    assert len(root_record["children"]) == 5
    root_record["children"].pop()
    payload["edge_count"] -= 1
    _write_rehashed_checkpoint(tampered, payload)

    with pytest.raises(ValueError, match="complete legal edge set"):
        ProofNumberDAG.load_checkpoint(tampered)


def test_checkpoint_refuses_wrong_expected_run_envelope(tmp_path: Path) -> None:
    rules = _rules(2)
    checkpoint = tmp_path / "envelope.json"
    ProofNumberDAG(rules, threshold2=1).save_checkpoint(checkpoint)

    with pytest.raises(ValueError, match="threshold does not match"):
        ProofNumberDAG.load_checkpoint(checkpoint, expected_threshold2=3)

    differently_named_rules = Rules(
        size=2,
        komi2=1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id="different-run-envelope",
    )
    with pytest.raises(ValueError, match="rules do not match"):
        ProofNumberDAG.load_checkpoint(
            checkpoint, expected_rules=differently_named_rules
        )

    different_root = apply_move(State.initial(rules), PASS, rules)
    with pytest.raises(ValueError, match="root does not match"):
        ProofNumberDAG.load_checkpoint(
            checkpoint, expected_root_state=different_root
        )


def test_checkpoint_interchange_integers_are_portably_bounded(tmp_path: Path) -> None:
    rules = _rules(2)
    with pytest.raises(ValueError, match="threshold2 must fit signed 64-bit"):
        ProofNumberDAG(rules, threshold2=1 << 63)

    huge_komi_rules = Rules(
        size=2,
        komi2=1 << 63,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id="huge-komi-rejected-at-checkpoint-boundary",
    )
    with pytest.raises(ValueError, match="komi2 must fit signed 64-bit"):
        ProofNumberDAG(huge_komi_rules, threshold2=1)

    for edge_komi2 in (-(1 << 63), (1 << 63) - 1):
        overflow_score_rules = Rules(
            size=2,
            komi2=edge_komi2,
            superko="positional_superko",
            allow_suicide=False,
            scoring="area",
            passes_to_end=2,
            profile_id="terminal-score-overflow-rejected",
        )
        with pytest.raises(ValueError, match="possible score2 range"):
            ProofNumberDAG(overflow_score_rules, threshold2=1)

    checkpoint = tmp_path / "portable.json"
    ProofNumberDAG(rules, threshold2=1).save_checkpoint(checkpoint)
    payload = _read_checkpoint(checkpoint)
    payload["threshold2"] = 1 << 63
    _write_rehashed_checkpoint(checkpoint, payload)
    with pytest.raises(ValueError, match="threshold2 must be at most"):
        ProofNumberDAG.load_checkpoint(checkpoint)


def test_checkpoint_loads_and_recomputes_in_a_fresh_process(tmp_path: Path) -> None:
    rules = _rules(2)
    checkpoint = tmp_path / "fresh-process.json"
    dag = ProofNumberDAG(rules, threshold2=1)
    expected = dag.advance(11).as_dict()
    dag.save_checkpoint(checkpoint)

    script = (
        "import json,sys; "
        "from ugts_go19.pndag import ProofNumberDAG; "
        "result=ProofNumberDAG.load_checkpoint(sys.argv[1]).advance(0); "
        "print(json.dumps(result.as_dict(),sort_keys=True,separators=(',',':')))"
    )
    environment = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get(
        "PYTHONPATH", ""
    )
    process = subprocess.run(
        [sys.executable, "-c", script, str(checkpoint)],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    actual = json.loads(process.stdout)
    expected["expanded_this_call"] = 0
    assert actual == expected


@pytest.mark.parametrize(
    ("threshold2", "expected_status"),
    [(1, "PROVEN"), (3, "DISPROVEN")],
)
def test_solved_checkpoint_reopens_in_a_fresh_process(
    tmp_path: Path, threshold2: int, expected_status: str
) -> None:
    checkpoint = tmp_path / f"solved-{threshold2}.json"
    dag = ProofNumberDAG(_rules(2), threshold2=threshold2)
    assert dag.advance(10_000).status == expected_status
    dag.save_checkpoint(checkpoint)

    script = (
        "import json,sys; "
        "from ugts_go19.pndag import ProofNumberDAG; "
        "r=ProofNumberDAG.load_checkpoint(sys.argv[1]).advance(0); "
        "print(json.dumps({'status':r.status,'proof':r.proof_number,"
        "'disproof':r.disproof_number},sort_keys=True,separators=(',',':')))"
    )
    environment = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get(
        "PYTHONPATH", ""
    )
    process = subprocess.run(
        [sys.executable, "-c", script, str(checkpoint)],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
        timeout=30,
    )
    assert process.returncode == 0, process.stderr
    loaded = json.loads(process.stdout)
    assert loaded["status"] == expected_status
    assert (loaded["proof"], loaded["disproof"]) in {
        (0, UINT64_MAX),
        (UINT64_MAX, 0),
    }


def test_emitted_checkpoint_validates_against_repository_schema(
    tmp_path: Path,
) -> None:
    checkpoint = tmp_path / "schema-valid.json"
    dag = ProofNumberDAG(_rules(2), threshold2=1)
    dag.advance(5)
    dag.save_checkpoint(checkpoint)
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / (
        "pndag_checkpoint.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator_class = validator_for(schema)
    validator_class.check_schema(schema)
    validator_class(schema).validate(_read_checkpoint(checkpoint))


def test_failed_atomic_publication_preserves_previous_checkpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules = _rules(2)
    checkpoint = tmp_path / "atomic.json"
    dag = ProofNumberDAG(rules, threshold2=1)
    dag.advance(3)
    dag.save_checkpoint(checkpoint)
    previous = checkpoint.read_bytes()
    dag.advance(1)

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(pndag_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected publication failure"):
        dag.save_checkpoint(checkpoint)

    assert checkpoint.read_bytes() == previous
    assert not list(tmp_path.glob(".atomic.json.tmp-*"))
    restored = ProofNumberDAG.load_checkpoint(
        checkpoint,
        expected_rules=rules,
        expected_root_state=State.initial(rules),
        expected_threshold2=1,
    )
    assert restored.advance(0).committed_expansions == 3


def test_interrupted_expansion_rolls_back_all_unpublished_nodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rules = _rules(2)
    dag = ProofNumberDAG(rules, threshold2=1)
    pristine_hash = dag.graph_sha256()
    original_intern = dag._intern_state
    calls = 0

    def fail_after_partial_intern(state: State) -> int:
        nonlocal calls
        node_id = original_intern(state)
        calls += 1
        if calls == 3:
            raise MemoryError("injected mid-expansion interruption")
        return node_id

    monkeypatch.setattr(dag, "_intern_state", fail_after_partial_intern)
    with pytest.raises(MemoryError, match="injected mid-expansion interruption"):
        dag.advance(1)

    assert dag.node_count == 1
    assert dag.edge_count == 0
    assert dag.committed_expansions == 0
    assert dag.graph_sha256() == pristine_hash
    checkpoint = tmp_path / "rolled-back.json"
    dag.save_checkpoint(checkpoint)
    assert ProofNumberDAG.load_checkpoint(checkpoint).node_count == 1


def test_tiny_pndag_cli_rejects_output_checkpoint_alias(tmp_path: Path) -> None:
    aliased = tmp_path / "same.json"
    with pytest.raises(SystemExit, match="must not refer to the checkpoint"):
        cli_main(
            [
                "pndag-tiny",
                "--checkpoint",
                str(aliased),
                "--output",
                str(aliased),
            ]
        )
    assert not aliased.exists()


def test_tiny_pndag_status_gate_publishes_nothing_on_mismatch(
    tmp_path: Path,
) -> None:
    rules = Rules(
        size=2,
        komi2=1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id="UGTS-TINY-2x2-AREA-PSK-K1/2",
    )
    checkpoint = tmp_path / "preserved.json"
    dag = ProofNumberDAG(rules, threshold2=1)
    dag.advance(7)
    dag.save_checkpoint(checkpoint)
    before = checkpoint.read_bytes()
    output = tmp_path / "result.json"
    output.write_bytes(b"preserve-me\n")

    assert (
        cli_main(
            [
                "pndag-tiny",
                "--size",
                "2",
                "--komi2",
                "1",
                "--threshold2",
                "1",
                "--additional-expansions",
                "1",
                "--checkpoint",
                str(checkpoint),
                "--resume",
                "--expect-status",
                "PROVEN",
                "--output",
                str(output),
            ]
        )
        == 2
    )
    assert checkpoint.read_bytes() == before
    assert output.read_bytes() == b"preserve-me\n"


def test_tiny_pndag_cli_advances_then_resumes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    checkpoint = tmp_path / "cli.json"
    assert (
        cli_main(
            [
                "pndag-tiny",
                "--size",
                "2",
                "--komi2",
                "1",
                "--threshold2",
                "1",
                "--additional-expansions",
                "7",
                "--checkpoint",
                str(checkpoint),
                "--expect-status",
                "UNKNOWN",
            ]
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first["result"]["status"] == "UNKNOWN"
    assert first["result"]["committed_expansions"] == 7
    assert "not a standalone certificate" in first["claim_boundary"]

    assert (
        cli_main(
            [
                "pndag-tiny",
                "--size",
                "2",
                "--komi2",
                "1",
                "--threshold2",
                "1",
                "--additional-expansions",
                "3",
                "--checkpoint",
                str(checkpoint),
                "--resume",
                "--expect-status",
                "UNKNOWN",
            ]
        )
        == 0
    )
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["result"]["expanded_this_call"] == 3
    assert resumed["result"]["committed_expansions"] == 10
