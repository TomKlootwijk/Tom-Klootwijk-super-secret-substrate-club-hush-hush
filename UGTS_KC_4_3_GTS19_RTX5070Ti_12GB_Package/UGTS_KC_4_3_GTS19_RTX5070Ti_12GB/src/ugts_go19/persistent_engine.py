"""Bounded exact Go transitions backed by immutable PSK history roots.

This module is a host-RAM validation adapter, not a 19x19 proof search.  It
supports positional superko only.  Board digests in :mod:`persistent_history`
select lookup buckets; exact board bytes decide repetition membership.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import BLACK, EMPTY, PASS, WHITE, other
from .engine import IllegalMove, group_and_liberties, neighbor_table
from .persistent_history import HistoryRoot, PersistentHistory
from .rules import Rules


def _require_psk_store(rules: Rules, history: PersistentHistory) -> None:
    if not isinstance(rules, Rules):
        raise TypeError("rules must be a Rules instance")
    if rules.superko != "positional_superko":
        raise ValueError("persistent transition adapter requires positional superko")
    if not isinstance(history, PersistentHistory):
        raise TypeError("history must be a PersistentHistory")
    if history.board_size != rules.size:
        raise ValueError("history board size does not match rules")


@dataclass(frozen=True, slots=True)
class PersistentState:
    """Exact Go state whose repetition context is a persistent set root."""

    board: bytes
    to_play: int
    passes: int
    history_root: HistoryRoot
    previous_board: bytes | None
    ply: int = 0

    @classmethod
    def initial(
        cls, rules: Rules, history: PersistentHistory
    ) -> "PersistentState":
        _require_psk_store(rules, history)
        board = bytes(rules.size * rules.size)
        root = history.insert(history.empty_root, board)
        return cls(
            board=board,
            to_play=BLACK,
            passes=0,
            history_root=root,
            previous_board=None,
            ply=0,
        )

    def is_terminal(self, rules: Rules) -> bool:
        return self.passes >= rules.passes_to_end

    def validate(self, rules: Rules, history: PersistentHistory) -> None:
        _require_psk_store(rules, history)
        expected = rules.size * rules.size
        if type(self.board) is not bytes:
            raise TypeError("board must be immutable bytes")
        if len(self.board) != expected:
            raise ValueError(f"board has {len(self.board)} points, expected {expected}")
        if type(self.to_play) is not int:
            raise TypeError("to_play must be an integer")
        if self.to_play not in (BLACK, WHITE):
            raise ValueError("to_play must be 1 (black) or 2 (white)")
        if type(self.passes) is not int:
            raise TypeError("passes must be an integer")
        if not 0 <= self.passes <= rules.passes_to_end:
            raise ValueError(
                f"passes must be in 0..{rules.passes_to_end} for a reachable state"
            )
        if type(self.ply) is not int:
            raise TypeError("ply must be an integer")
        if self.ply < 0:
            raise ValueError("ply cannot be negative")
        if any(point not in (EMPTY, BLACK, WHITE) for point in self.board):
            raise ValueError("board contains an invalid point value")
        if self.previous_board is not None:
            if type(self.previous_board) is not bytes:
                raise TypeError("previous_board must be immutable bytes or None")
            if len(self.previous_board) != expected:
                raise ValueError("previous_board length does not match board size")
            if any(
                point not in (EMPTY, BLACK, WHITE)
                for point in self.previous_board
            ):
                raise ValueError("previous_board contains an invalid point value")

        # ``contains`` also verifies that the root belongs to this exact store.
        # Exact raw bytes, not a digest or root hash, determine membership.
        if not history.contains(self.history_root, self.board):
            raise ValueError("superko history must contain current board")
        if self.previous_board is not None and not history.contains(
            self.history_root, self.previous_board
        ):
            raise ValueError("superko history must contain the previous board")


@dataclass(frozen=True, slots=True)
class PersistentMoveResult:
    state: PersistentState
    captured: int
    self_captured: int


def initial_state(rules: Rules, history: PersistentHistory) -> PersistentState:
    """Create the empty-board state and insert it into an empty history root."""

    return PersistentState.initial(rules, history)


def apply_move_detailed(
    state: PersistentState,
    move: int,
    rules: Rules,
    history: PersistentHistory,
) -> PersistentMoveResult:
    """Apply one exact move without materializing a flat repetition set."""

    if type(move) is not int:
        raise TypeError("move must be an integer")
    if not isinstance(state, PersistentState):
        raise TypeError("state must be a PersistentState")
    state.validate(rules, history)
    if state.is_terminal(rules):
        raise IllegalMove("game is already terminal")

    next_player = other(state.to_play)
    if move == PASS:
        # Positional superko does not forbid pass.  Passing preserves both the
        # exact board set and its immutable root.
        return PersistentMoveResult(
            state=PersistentState(
                board=state.board,
                to_play=next_player,
                passes=state.passes + 1,
                history_root=state.history_root,
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
    if history.contains(state.history_root, new_board):
        raise IllegalMove("positional_superko")
    new_root = history.insert(state.history_root, new_board)

    return PersistentMoveResult(
        state=PersistentState(
            board=new_board,
            to_play=next_player,
            passes=0,
            history_root=new_root,
            previous_board=state.board,
            ply=state.ply + 1,
        ),
        captured=captured,
        self_captured=self_captured,
    )


def apply_move(
    state: PersistentState,
    move: int,
    rules: Rules,
    history: PersistentHistory,
) -> PersistentState:
    return apply_move_detailed(state, move, rules, history).state


def is_legal(
    state: PersistentState,
    move: int,
    rules: Rules,
    history: PersistentHistory,
) -> bool:
    try:
        apply_move(state, move, rules, history)
        return True
    except IllegalMove:
        return False


def legal_moves(
    state: PersistentState,
    rules: Rules,
    history: PersistentHistory,
    include_pass: bool = True,
) -> list[int]:
    if not isinstance(state, PersistentState):
        raise TypeError("state must be a PersistentState")
    state.validate(rules, history)
    if state.is_terminal(rules):
        return []
    moves: list[int] = []
    for point, value in enumerate(state.board):
        if value != EMPTY:
            continue
        try:
            apply_move(state, point, rules, history)
            moves.append(point)
        except IllegalMove:
            pass
    if include_pass:
        moves.append(PASS)
    return moves


def ordered_children(
    state: PersistentState,
    rules: Rules,
    history: PersistentHistory,
) -> list[tuple[int, PersistentState, int]]:
    """Return exact children in the reference engine's deterministic order."""

    center = (rules.size - 1) / 2.0
    children: list[tuple[int, PersistentState, int]] = []
    for point, value in enumerate(state.board):
        if value != EMPTY:
            continue
        try:
            result = apply_move_detailed(state, point, rules, history)
        except IllegalMove:
            continue
        x, y = point % rules.size, point // rules.size
        distance2 = int((x - center) ** 2 + (y - center) ** 2)
        priority = -result.captured * 10_000 + distance2
        children.append((point, result.state, priority))
    children.sort(key=lambda item: (item[2], item[0]))
    pass_state = apply_move(state, PASS, rules, history)
    children.append((PASS, pass_state, 10**9))
    return children


__all__ = [
    "PersistentMoveResult",
    "PersistentState",
    "apply_move",
    "apply_move_detailed",
    "initial_state",
    "is_legal",
    "legal_moves",
    "ordered_children",
]
