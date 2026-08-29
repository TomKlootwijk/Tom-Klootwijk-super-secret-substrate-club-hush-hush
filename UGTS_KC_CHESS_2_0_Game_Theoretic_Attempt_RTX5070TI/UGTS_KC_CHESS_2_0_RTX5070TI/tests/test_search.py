from __future__ import annotations

import unittest

from ugts_chess.position import Position
from ugts_chess.search import MATE_THRESHOLD, Searcher


class SearchTests(unittest.TestCase):
    MATE2 = "8/8/8/8/8/k7/8/1QK5 w - - 0 1"

    def test_01_finds_forced_mate_in_two(self) -> None:
        p = Position.from_fen(self.MATE2)
        result = Searcher().search(p, max_depth=4)
        self.assertEqual(result.best_move.uci() if result.best_move else None, "b1b5")
        self.assertGreaterEqual(result.score, MATE_THRESHOLD)
        self.assertEqual(result.score_text(), "mate +2")

    def test_02_search_is_deterministic(self) -> None:
        p = Position.from_fen(self.MATE2)
        a = Searcher().search(p, max_depth=4)
        b = Searcher().search(p, max_depth=4)
        self.assertEqual(a.score, b.score)
        self.assertEqual([m.uci() for m in a.principal_variation], [m.uci() for m in b.principal_variation])

    def test_03_terminal_checkmate_has_no_move(self) -> None:
        p = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        result = Searcher().search(p, max_depth=2)
        self.assertIsNone(result.best_move)
        self.assertLessEqual(result.score, -MATE_THRESHOLD)

    def test_04_time_limited_search_returns_record(self) -> None:
        result = Searcher().search(Position.initial(), max_depth=10, time_limit=0.02)
        self.assertGreaterEqual(result.depth, 0)
        self.assertGreater(result.elapsed_seconds, 0)

    def test_05_balanced_pawn_endgame_near_equal(self) -> None:
        p = Position.from_fen("6k1/5ppp/8/8/8/8/5PPP/6K1 w - - 0 1")
        result = Searcher().search(p, max_depth=3)
        self.assertLess(abs(result.score), 200)


if __name__ == "__main__":
    unittest.main()
