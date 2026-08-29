"""Bounded proof-search tests for persistent positional-superko roots."""

from __future__ import annotations

import pytest

import ugts_go19.persistent_pns as persistent_pns_module
import ugts_go19.pns as flat_pns_module
from ugts_go19.constants import PASS
from ugts_go19.exact import ExactSolver
from ugts_go19.pndag import ProofNumberDAG
from ugts_go19.persistent_history import PersistentHistory
from ugts_go19.persistent_pns import (
    INF,
    PROOF_ARITHMETIC,
    PersistentProofNumberSearch,
    _sat_add,
)
from ugts_go19.pns import ProofNumberSearch
from ugts_go19.rules import Rules


def _rules(size: int) -> Rules:
    return Rules(
        size=size,
        komi2=1,
        superko="positional_superko",
        allow_suicide=False,
        scoring="area",
        passes_to_end=2,
        profile_id=f"persistent-pns-test-{size}x{size}",
    )


def test_complete_2x2_thresholds_match_exact_tree_pns_and_pndag() -> None:
    rules = _rules(2)
    exact_value = ExactSolver(rules, node_budget=50_000).solve().value2
    assert exact_value == 1

    for threshold2, expected in (
        (exact_value, ("PROVEN", 0, INF)),
        (exact_value + 2, ("DISPROVEN", INF, 0)),
    ):
        flat = ProofNumberSearch(
            rules, threshold2=threshold2, node_budget=1_000
        ).run()
        dag = ProofNumberDAG(rules, threshold2=threshold2).advance(10_000)
        history = PersistentHistory(2)
        persistent = PersistentProofNumberSearch(
            rules,
            threshold2=threshold2,
            history=history,
            node_budget=1_000,
        ).run()

        assert (
            persistent.status,
            persistent.proof_number,
            persistent.disproof_number,
        ) == expected
        assert (
            flat.status,
            flat.proof_number,
            flat.disproof_number,
        ) == expected
        assert (
            dag.status,
            dag.proof_number,
            dag.disproof_number,
        ) == expected
        # Both tree kernels consume identical ordered legal children.  This
        # checks more than the final label without requiring DAG node counts to
        # equal tree node counts.
        assert (
            persistent.expanded_nodes,
            persistent.generated_nodes,
            persistent.max_ply,
        ) == (flat.expanded_nodes, flat.generated_nodes, flat.max_ply)


@pytest.mark.parametrize(
    ("threshold2", "expected"),
    [(-1, ("PROVEN", 0, INF)), (0, ("DISPROVEN", INF, 0))],
)
def test_1x1_pass_only_truth_matches_existing_tree_pns(
    threshold2: int, expected: tuple[str, int, int]
) -> None:
    rules = _rules(1)
    history = PersistentHistory(1)
    persistent = PersistentProofNumberSearch(
        rules, threshold2, history, node_budget=10
    ).run()
    flat = ProofNumberSearch(rules, threshold2, node_budget=10).run()

    assert (
        persistent.status,
        persistent.proof_number,
        persistent.disproof_number,
    ) == expected
    assert (
        flat.status,
        flat.proof_number,
        flat.disproof_number,
    ) == expected


def test_search_never_materializes_members_and_retains_shared_old_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = _rules(2)
    history = PersistentHistory(2)

    def fail_if_materialized(
        _self: PersistentHistory, _root: object
    ) -> tuple[bytes, ...]:
        raise AssertionError("proof search materialized a flat history")

    monkeypatch.setattr(PersistentHistory, "members", fail_if_materialized)
    search = PersistentProofNumberSearch(
        rules, threshold2=1, history=history, node_budget=1_000
    )
    assert search.run().status == "PROVEN"

    root = search.last_root
    assert root is not None
    old_history_root = root.state.history_root
    point_children = [child for child in root.children if child.move != PASS]
    pass_child = next(child for child in root.children if child.move == PASS)
    assert point_children
    assert pass_child.state.history_root is old_history_root

    # A point insertion copies only its digest path.  The old root still
    # denotes just the empty board and shares its untouched immutable subtree
    # with each new version.
    for child in point_children:
        assert child.state.history_root is not old_history_root
        assert history.shared_node_count(
            old_history_root, child.state.history_root
        ) > 0
        assert not history.contains(old_history_root, child.state.board)
        assert history.contains(child.state.history_root, child.state.board)
    assert old_history_root.count == 1
    assert history.contains(old_history_root, root.state.board)


@pytest.mark.parametrize(
    ("threshold2", "expected"),
    [(1, ("PROVEN", 0, INF)), (3, ("DISPROVEN", INF, 0))],
)
def test_constant_index_digest_collisions_do_not_change_proof_truth(
    threshold2: int, expected: tuple[str, int, int]
) -> None:
    def constant_digest(_board: bytes) -> bytes:
        return bytes(32)

    rules = _rules(2)
    history = PersistentHistory(
        2,
        digest_fn=constant_digest,
        digest_name="persistent-pns-constant-test",
    )
    result = PersistentProofNumberSearch(
        rules, threshold2, history, node_budget=1_000
    ).run()

    assert (result.status, result.proof_number, result.disproof_number) == expected
    assert history.digest_bucket_sizes() == (history.board_object_count,)
    assert history.board_object_count > 1


def test_budget_stop_is_explicit_unknown_with_live_proof_numbers() -> None:
    rules = _rules(2)
    history = PersistentHistory(2)
    result = PersistentProofNumberSearch(
        rules, threshold2=1, history=history, node_budget=1
    ).run()

    assert result.status == "UNKNOWN"
    assert result.expanded_nodes == 1
    assert result.proof_number > 0
    assert result.disproof_number > 0
    assert result.as_dict()["scope"] == "bounded-host-ram-psk-1x1-2x2"


def test_uint64_proof_sums_saturate_instead_of_wrapping() -> None:
    assert INF == (1 << 64) - 1
    assert _sat_add((INF - 1, 1)) == INF
    assert _sat_add((INF - 1, 2)) == INF
    assert PROOF_ARITHMETIC == {
        "bits": 64,
        "endianness": "little",
        "infinity": "18446744073709551615",
        "kind": "saturating_uint64",
    }
    with pytest.raises(ValueError, match="outside uint64"):
        _sat_add((-1,))
    with pytest.raises(ValueError, match="outside uint64"):
        _sat_add((INF + 1,))


@pytest.mark.parametrize(
    ("threshold2", "expected_status"),
    [(1, "PROVEN"), (3, "DISPROVEN")],
)
def test_saturated_scheduler_never_reselects_solved_children(
    threshold2: int,
    expected_status: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A deliberately tiny infinity reaches the same tie that only a very
    # large production search could reach with real uint64 arithmetic.
    monkeypatch.setattr(persistent_pns_module, "INF", 4)
    monkeypatch.setattr(flat_pns_module, "INF", 4)
    rules = _rules(2)
    persistent = PersistentProofNumberSearch(
        rules,
        threshold2,
        PersistentHistory(2),
        node_budget=1_000,
    ).run()
    flat = ProofNumberSearch(
        rules, threshold2=threshold2, node_budget=1_000
    ).run()

    assert persistent.status == expected_status
    assert flat.status == expected_status
    assert persistent.expanded_nodes < 1_000
    assert flat.expanded_nodes < 1_000


def test_constructor_rejects_profiles_outside_the_bounded_psk_slice() -> None:
    non_psk = Rules(
        size=2,
        komi2=1,
        superko="situational_superko",
        profile_id="persistent-pns-ssk-rejected",
    )
    with pytest.raises(ValueError, match="requires positional superko"):
        PersistentProofNumberSearch(non_psk, 1, PersistentHistory(2))

    rules_3x3 = _rules(3)
    with pytest.raises(ValueError, match="only 1x1 and 2x2"):
        PersistentProofNumberSearch(rules_3x3, 1, PersistentHistory(3))

    with pytest.raises(ValueError, match="board size"):
        PersistentProofNumberSearch(_rules(2), 1, PersistentHistory(1))
