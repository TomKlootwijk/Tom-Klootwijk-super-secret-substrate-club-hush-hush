"""Differential tests for persistent-root positional-superko transitions."""

from __future__ import annotations

import random

import pytest

from ugts_go19.constants import BLACK, PASS, WHITE
from ugts_go19.engine import (
    IllegalMove,
    apply_move as flat_apply_move,
    apply_move_detailed as flat_apply_move_detailed,
    legal_moves as flat_legal_moves,
    ordered_children as flat_ordered_children,
)
from ugts_go19.persistent_engine import (
    PersistentState,
    apply_move,
    apply_move_detailed,
    initial_state,
    legal_moves,
    ordered_children,
)
from ugts_go19.persistent_history import PersistentHistory
from ugts_go19.rules import Rules
from ugts_go19.state import State


def _rules(size: int, *, allow_suicide: bool = False) -> Rules:
    return Rules(
        size=size,
        komi2=1,
        allow_suicide=allow_suicide,
        profile_id=f"persistent-engine-test-{size}-{int(allow_suicide)}",
    )


def _flat(state: PersistentState, history: PersistentHistory) -> State:
    # Full materialization is deliberately confined to the differential test
    # oracle.  The persistent transition implementation never does this.
    return State(
        board=state.board,
        to_play=state.to_play,
        passes=state.passes,
        seen=frozenset(history.members(state.history_root)),
        previous_board=state.previous_board,
        ply=state.ply,
    )


def _assert_state(
    persistent: PersistentState,
    flat: State,
    rules: Rules,
    history: PersistentHistory,
) -> None:
    assert persistent.board == flat.board
    assert persistent.to_play == flat.to_play
    assert persistent.passes == flat.passes
    assert persistent.previous_board == flat.previous_board
    assert persistent.ply == flat.ply
    assert history.members(persistent.history_root) == tuple(sorted(flat.seen))
    persistent.validate(rules, history)
    flat.validate(rules)


@pytest.mark.parametrize("size,seed", [(2, 0xC0FFEE), (3, 0xBADC0DE)])
def test_deterministic_randomized_traces_match_flat_oracle(
    size: int, seed: int
) -> None:
    rules = _rules(size)
    randomizer = random.Random(seed)

    for game in range(24):
        history = PersistentHistory(size)
        persistent = initial_state(rules, history)
        flat = State.initial(rules)
        _assert_state(persistent, flat, rules, history)

        for ply in range(size * size * 3 + 4):
            persistent_moves = legal_moves(
                persistent, rules, history, include_pass=True
            )
            flat_moves = flat_legal_moves(flat, rules, include_pass=True)
            assert persistent_moves == flat_moves
            if not persistent_moves:
                break

            # Mostly choose points so each trace exercises more than pass logic,
            # while still forcing deterministic pass/termination coverage.
            points = [move for move in persistent_moves if move != PASS]
            choose_pass = (game + ply) % 11 == 0 or not points
            move = PASS if choose_pass else randomizer.choice(points)
            persistent_result = apply_move_detailed(
                persistent, move, rules, history
            )
            flat_result = flat_apply_move_detailed(flat, move, rules)
            assert persistent_result.captured == flat_result.captured
            assert persistent_result.self_captured == flat_result.self_captured
            persistent = persistent_result.state
            flat = flat_result.state
            _assert_state(persistent, flat, rules, history)


def test_capture_suicide_and_poisoned_psk_history_match_flat_oracle() -> None:
    rules = _rules(3)
    history = PersistentHistory(3)
    board = bytes(
        (
            0,
            0,
            0,
            WHITE,
            BLACK,
            WHITE,
            0,
            WHITE,
            0,
        )
    )
    root = history.insert(history.empty_root, bytes(9))
    root = history.insert(root, board)
    persistent = PersistentState(board, WHITE, 0, root, None, 8)
    flat = _flat(persistent, history)
    persistent_result = apply_move_detailed(persistent, 1, rules, history)
    flat_result = flat_apply_move_detailed(flat, 1, rules)
    assert persistent_result.captured == flat_result.captured == 1
    _assert_state(persistent_result.state, flat_result.state, rules, history)

    suicide_board = bytes(
        (
            0,
            WHITE,
            0,
            WHITE,
            0,
            WHITE,
            0,
            WHITE,
            0,
        )
    )
    suicide_root = history.insert(history.empty_root, suicide_board)
    suicide = PersistentState(suicide_board, BLACK, 0, suicide_root, None, 0)
    with pytest.raises(IllegalMove, match="suicide"):
        apply_move(suicide, 4, rules, history)
    with pytest.raises(IllegalMove, match="suicide"):
        flat_apply_move(_flat(suicide, history), 4, rules)
    suicide_allowed = _rules(3, allow_suicide=True)
    # Removing one's own just-played stone recreates the current board, so PSK
    # still rejects it even under a rule profile that permits self-capture.
    with pytest.raises(IllegalMove, match="positional_superko"):
        apply_move(suicide, 4, suicide_allowed, history)
    with pytest.raises(IllegalMove, match="positional_superko"):
        flat_apply_move(_flat(suicide, history), 4, suicide_allowed)

    empty = bytes(9)
    forbidden = bytes((BLACK,)) + bytes(8)
    poisoned_root = history.insert(history.empty_root, empty)
    poisoned_root = history.insert(poisoned_root, forbidden)
    poisoned = PersistentState(empty, BLACK, 0, poisoned_root, None, 0)
    assert poisoned.validate(rules, history) is None
    with pytest.raises(IllegalMove, match="positional_superko"):
        apply_move(poisoned, 0, rules, history)
    with pytest.raises(IllegalMove, match="positional_superko"):
        flat_apply_move(_flat(poisoned, history), 0, rules)


def test_constant_digest_collision_does_not_create_false_repetition() -> None:
    rules = _rules(2)

    def constant_digest(_board: bytes) -> bytes:
        return bytes(32)

    history = PersistentHistory(
        2, digest_fn=constant_digest, digest_name="constant-transition-test"
    )
    initial = initial_state(rules, history)
    old_root = initial.history_root
    old_members = history.members(old_root)
    child = apply_move(initial, 0, rules, history)

    assert child.board != initial.board
    assert history.digest_bucket_sizes() == (2,)
    assert history.members(old_root) == old_members
    assert not history.contains(old_root, child.board)
    assert history.contains(child.history_root, child.board)
    assert child.history_root.count == 2
    _assert_state(
        child,
        flat_apply_move(State.initial(rules), 0, rules),
        rules,
        history,
    )


def test_transition_does_not_materialize_history_members(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rules = _rules(3)
    history = PersistentHistory(3)
    state = initial_state(rules, history)

    def fail_if_materialized(
        _self: PersistentHistory, _root: object
    ) -> tuple[bytes, ...]:
        raise AssertionError("transition materialized the complete history")

    monkeypatch.setattr(PersistentHistory, "members", fail_if_materialized)
    child = apply_move(state, 4, rules, history)
    assert child.board[4] == BLACK
    assert child.history_root.count == 2


def test_pass_reuses_root_and_two_passes_terminate_exactly() -> None:
    rules = _rules(2)
    history = PersistentHistory(2)
    persistent = initial_state(rules, history)
    flat = State.initial(rules)
    original_root = persistent.history_root

    for _ in range(2):
        persistent = apply_move(persistent, PASS, rules, history)
        flat = flat_apply_move(flat, PASS, rules)
        assert persistent.history_root is original_root
        _assert_state(persistent, flat, rules, history)
    assert persistent.is_terminal(rules)
    assert legal_moves(persistent, rules, history) == []
    with pytest.raises(IllegalMove, match="terminal"):
        apply_move(persistent, PASS, rules, history)


def test_ordered_children_match_flat_moves_priorities_and_exact_states() -> None:
    rules = _rules(3)
    history = PersistentHistory(3)
    persistent = initial_state(rules, history)
    flat = State.initial(rules)
    for move in (0, 1, 4, 8):
        persistent = apply_move(persistent, move, rules, history)
        flat = flat_apply_move(flat, move, rules)

    persistent_children = ordered_children(persistent, rules, history)
    flat_children = flat_ordered_children(flat, rules)
    assert [(move, priority) for move, _state, priority in persistent_children] == [
        (move, priority) for move, _state, priority in flat_children
    ]
    for (_move, persistent_child, _priority), (
        _flat_move,
        flat_child,
        _flat_priority,
    ) in zip(persistent_children, flat_children, strict=True):
        _assert_state(persistent_child, flat_child, rules, history)


def test_validation_rejects_wrong_profile_foreign_or_incomplete_roots() -> None:
    rules = _rules(2)
    history = PersistentHistory(2)
    state = initial_state(rules, history)

    non_psk = Rules(
        size=2,
        komi2=1,
        superko="simple_ko",
        profile_id="persistent-engine-wrong-ko",
    )
    with pytest.raises(ValueError, match="requires positional superko"):
        state.validate(non_psk, history)

    wrong_size = PersistentHistory(3)
    with pytest.raises(ValueError, match="board size"):
        state.validate(rules, wrong_size)

    foreign = PersistentHistory(2)
    foreign_state = PersistentState(
        state.board, BLACK, 0, foreign.insert(foreign.empty_root, state.board), None
    )
    with pytest.raises(ValueError, match="different store"):
        foreign_state.validate(rules, history)

    missing = PersistentState(
        bytes((BLACK, 0, 0, 0)), BLACK, 0, state.history_root, None
    )
    with pytest.raises(ValueError, match="current board"):
        missing.validate(rules, history)

    previous = bytes((BLACK, 0, 0, 0))
    missing_previous = PersistentState(
        state.board, BLACK, 0, state.history_root, previous, 1
    )
    with pytest.raises(ValueError, match="previous board"):
        missing_previous.validate(rules, history)


def test_19x19_initial_and_one_move_keep_exact_history() -> None:
    rules = Rules.canonical_19x19()
    history = PersistentHistory(19)
    state = initial_state(rules, history)
    old_root = state.history_root
    center = 9 * 19 + 9
    child = apply_move(state, center, rules, history)

    assert len(child.board) == 361
    assert child.board[center] == BLACK
    assert child.to_play == WHITE
    assert child.previous_board == state.board
    assert child.ply == 1
    assert old_root.count == 1
    assert child.history_root.count == 2
    assert history.members(old_root) == (state.board,)
    _assert_state(
        child,
        flat_apply_move(State.initial(rules), center, rules),
        rules,
        history,
    )


def test_persistent_and_flat_moves_require_exact_integer_type() -> None:
    rules = _rules(2)
    history = PersistentHistory(2)
    persistent = initial_state(rules, history)
    flat = State.initial(rules)

    for move in (True, False, -1.0, 0.0, "0"):
        with pytest.raises(TypeError, match="move must be an integer"):
            apply_move(persistent, move, rules, history)  # type: ignore[arg-type]
        with pytest.raises(TypeError, match="move must be an integer"):
            flat_apply_move(flat, move, rules)  # type: ignore[arg-type]
