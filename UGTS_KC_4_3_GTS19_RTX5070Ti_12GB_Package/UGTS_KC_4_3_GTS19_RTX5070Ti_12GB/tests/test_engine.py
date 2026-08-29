from __future__ import annotations

import unittest

from ugts_go19.constants import BLACK, PASS, WHITE, coord_to_move, move_to_coord
from ugts_go19.engine import (
    IllegalMove,
    apply_move,
    apply_move_detailed,
    legal_moves,
    play_sequence,
)
from ugts_go19.rules import Rules
from ugts_go19.score import area_score, area_score2
from ugts_go19.state import State


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = Rules(size=3, komi2=1, profile_id="test-3")

    def test_coordinate_round_trip(self) -> None:
        for move in range(9):
            self.assertEqual(coord_to_move(move_to_coord(move, 3), 3), move)
        self.assertEqual(coord_to_move("pass", 3), PASS)

    def test_capture_single_stone(self) -> None:
        # B at B2; W surrounds on A2, B1, C2; final W at B3 captures.
        board = bytes([
            0, 0, 0,
            WHITE, BLACK, WHITE,
            0, WHITE, 0,
        ])
        state = State(
            board=board,
            to_play=WHITE,
            passes=0,
            seen=frozenset((bytes(9), board)),
            previous_board=None,
        )
        result = apply_move_detailed(state, 1, self.rules)
        self.assertEqual(result.captured, 1)
        self.assertEqual(result.state.board[4], 0)

    def test_suicide_is_illegal(self) -> None:
        board = bytes([
            0, WHITE, 0,
            WHITE, 0, WHITE,
            0, WHITE, 0,
        ])
        state = State(
            board=board,
            to_play=BLACK,
            passes=0,
            seen=frozenset((board,)),
            previous_board=None,
        )
        with self.assertRaises(IllegalMove):
            apply_move(state, 4, self.rules)

    def test_two_passes_terminate(self) -> None:
        state = State.initial(self.rules)
        state = apply_move(state, PASS, self.rules)
        self.assertFalse(state.is_terminal(self.rules))
        state = apply_move(state, PASS, self.rules)
        self.assertTrue(state.is_terminal(self.rules))
        with self.assertRaises(IllegalMove):
            apply_move(state, PASS, self.rules)

    def test_situational_superko_records_pass_created_situation(self) -> None:
        rules = Rules(
            size=3,
            komi2=1,
            superko="situational_superko",
            profile_id="situational-pass-history",
        )
        state = play_sequence(State.initial(rules), [1, 0, 5, 4, PASS, 2], rules)
        with self.assertRaises(IllegalMove):
            apply_move(state, 1, rules)

    def test_positional_superko_rejects_seen_board(self) -> None:
        initial = State.initial(self.rules)
        # Any legal move's result can be made forbidden by inserting it into seen.
        move = legal_moves(initial, self.rules, include_pass=False)[0]
        candidate = apply_move(initial, move, self.rules)
        poisoned = State(
            board=initial.board,
            to_play=initial.to_play,
            passes=0,
            seen=initial.seen | frozenset((candidate.board,)),
            previous_board=None,
        )
        with self.assertRaises(IllegalMove):
            apply_move(poisoned, move, self.rules)

    def test_empty_area_is_neutral(self) -> None:
        score = area_score(bytes(9), self.rules)
        self.assertEqual(score.neutral, 9)
        self.assertEqual(score.black_area, 0)
        self.assertEqual(score.white_area, 0)
        self.assertEqual(area_score2(bytes(9), self.rules), -1)


if __name__ == "__main__":
    unittest.main()
