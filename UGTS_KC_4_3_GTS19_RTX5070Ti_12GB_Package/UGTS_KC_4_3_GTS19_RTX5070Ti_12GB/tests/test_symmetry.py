from __future__ import annotations

import unittest

from ugts_go19.engine import apply_move
from ugts_go19.rules import Rules
from ugts_go19.state import State
from ugts_go19.symmetry import (
    canonical_state_key,
    transform_board,
    transform_move,
)


class SymmetryTests(unittest.TestCase):
    def test_four_rotations_restore_board(self) -> None:
        board = bytes(range(9))
        transformed = board
        for _ in range(4):
            transformed = transform_board(transformed, 3, 1)
        self.assertEqual(transformed, board)

    def test_move_transform_stays_on_board(self) -> None:
        for symmetry in range(8):
            for move in range(25):
                self.assertIn(transform_move(move, 5, symmetry), range(25))

    def test_canonical_key_transforms_full_history(self) -> None:
        rules = Rules(size=3, komi2=1, profile_id="symmetry-test")
        state = State.initial(rules)
        state = apply_move(state, 0, rules)
        state = apply_move(state, 4, rules)
        rotated_board = transform_board(state.board, 3, 1)
        rotated_seen = frozenset(transform_board(token, 3, 1) for token in state.seen)
        rotated_previous = transform_board(state.previous_board, 3, 1)
        rotated = State(
            board=rotated_board,
            to_play=state.to_play,
            passes=state.passes,
            seen=rotated_seen,
            previous_board=rotated_previous,
            ply=state.ply,
        )
        self.assertEqual(canonical_state_key(state, rules), canonical_state_key(rotated, rules))


if __name__ == "__main__":
    unittest.main()
