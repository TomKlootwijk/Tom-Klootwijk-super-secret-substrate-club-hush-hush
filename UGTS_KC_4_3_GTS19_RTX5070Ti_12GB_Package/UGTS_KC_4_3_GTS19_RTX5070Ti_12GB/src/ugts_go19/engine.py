"""Deterministic transition engine for Go."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable

from .constants import BLACK, EMPTY, PASS, WHITE, other
from .rules import Rules
from .state import State, repetition_token


class IllegalMove(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MoveResult:
    state: State
    captured: int
    self_captured: int


@lru_cache(maxsize=32)
def neighbor_table(size: int) -> tuple[tuple[int, ...], ...]:
    table: list[tuple[int, ...]] = []
    for y in range(size):
        for x in range(size):
            ns: list[int] = []
            if x > 0:
                ns.append(y * size + x - 1)
            if x + 1 < size:
                ns.append(y * size + x + 1)
            if y > 0:
                ns.append((y - 1) * size + x)
            if y + 1 < size:
                ns.append((y + 1) * size + x)
            table.append(tuple(ns))
    return tuple(table)


def group_and_liberties(
    board: bytes | bytearray, start: int, size: int
) -> tuple[set[int], set[int]]:
    color = board[start]
    if color == EMPTY:
        return set(), {start}
    neighbors = neighbor_table(size)
    stones = {start}
    liberties: set[int] = set()
    stack = [start]
    while stack:
        point = stack.pop()
        for adjacent in neighbors[point]:
            value = board[adjacent]
            if value == EMPTY:
                liberties.add(adjacent)
            elif value == color and adjacent not in stones:
                stones.add(adjacent)
                stack.append(adjacent)
    return stones, liberties


def _check_repetition(state: State, new_board: bytes, next_to_play: int, rules: Rules) -> None:
    if rules.superko == "none":
        return
    if rules.superko == "simple_ko":
        if state.previous_board is not None and new_board == state.previous_board:
            raise IllegalMove("simple ko repetition")
        return
    token = repetition_token(new_board, next_to_play, rules)
    if token in state.seen:
        raise IllegalMove(rules.superko)


def apply_move_detailed(state: State, move: int, rules: Rules) -> MoveResult:
    if type(move) is not int:
        raise TypeError("move must be an integer")
    state.validate(rules)
    if state.is_terminal(rules):
        raise IllegalMove("game is already terminal")

    next_player = other(state.to_play)
    if move == PASS:
        # Pass is explicitly permitted even though it preserves the board.
        new_seen = state.seen
        if rules.superko == "situational_superko":
            # The repetition check is waived for pass, but the newly reached
            # player/board situation still participates in later SSK checks.
            new_seen = state.seen | frozenset(
                (repetition_token(state.board, next_player, rules),)
            )
        return MoveResult(
            state=State(
                board=state.board,
                to_play=next_player,
                passes=state.passes + 1,
                seen=new_seen,
                previous_board=state.board,
                ply=state.ply + 1,
            ),
            captured=0,
            self_captured=0,
        )

    points = rules.size * rules.size
    if not 0 <= move < points:
        raise IllegalMove(f"point {move} outside board")
    if state.board[move] != EMPTY:
        raise IllegalMove("occupied point")

    board = bytearray(state.board)
    board[move] = state.to_play
    opponent = next_player
    neighbors = neighbor_table(rules.size)
    captured = 0
    checked: set[int] = set()

    # Capture adjacent opponent groups before checking own liberties.
    for adjacent in neighbors[move]:
        if board[adjacent] != opponent or adjacent in checked:
            continue
        stones, liberties = group_and_liberties(board, adjacent, rules.size)
        checked.update(stones)
        if not liberties:
            captured += len(stones)
            for stone in stones:
                board[stone] = EMPTY

    own_stones, own_liberties = group_and_liberties(board, move, rules.size)
    self_captured = 0
    if not own_liberties:
        if not rules.allow_suicide:
            raise IllegalMove("suicide")
        self_captured = len(own_stones)
        for stone in own_stones:
            board[stone] = EMPTY

    new_board = bytes(board)
    _check_repetition(state, new_board, next_player, rules)
    token = repetition_token(new_board, next_player, rules)
    new_seen = state.seen
    if rules.superko in {"positional_superko", "situational_superko"}:
        new_seen = state.seen | frozenset((token,))

    return MoveResult(
        state=State(
            board=new_board,
            to_play=next_player,
            passes=0,
            seen=new_seen,
            previous_board=state.board,
            ply=state.ply + 1,
        ),
        captured=captured,
        self_captured=self_captured,
    )


def apply_move(state: State, move: int, rules: Rules) -> State:
    return apply_move_detailed(state, move, rules).state


def is_legal(state: State, move: int, rules: Rules) -> bool:
    try:
        apply_move(state, move, rules)
        return True
    except IllegalMove:
        return False


def legal_moves(state: State, rules: Rules, include_pass: bool = True) -> list[int]:
    if state.is_terminal(rules):
        return []
    moves: list[int] = []
    for point, value in enumerate(state.board):
        if value != EMPTY:
            continue
        try:
            apply_move(state, point, rules)
            moves.append(point)
        except IllegalMove:
            pass
    if include_pass:
        moves.append(PASS)
    return moves


def ordered_children(state: State, rules: Rules) -> list[tuple[int, State, int]]:
    """Return legal children ordered deterministically for alpha-beta/PNS.

    Captures first, then points nearer the center, then lexical point order;
    pass is last. The ordering changes speed, never the proof semantics.
    """
    center = (rules.size - 1) / 2.0
    children: list[tuple[int, State, int]] = []
    for point, value in enumerate(state.board):
        if value != EMPTY:
            continue
        try:
            result = apply_move_detailed(state, point, rules)
        except IllegalMove:
            continue
        x, y = point % rules.size, point // rules.size
        distance2 = int((x - center) ** 2 + (y - center) ** 2)
        priority = -result.captured * 10_000 + distance2
        children.append((point, result.state, priority))
    children.sort(key=lambda item: (item[2], item[0]))
    pass_state = apply_move(state, PASS, rules)
    children.append((PASS, pass_state, 10**9))
    return children


def play_sequence(state: State, moves: Iterable[int], rules: Rules) -> State:
    current = state
    for move in moves:
        current = apply_move(current, move, rules)
    return current
