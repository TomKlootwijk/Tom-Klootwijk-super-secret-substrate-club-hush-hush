from __future__ import annotations

import hashlib
import json
import unittest
from importlib import resources

from ugts_chess.position import Position
from ugts_chess.tablebase import (
    DRAW,
    INVALID,
    LOSS,
    WIN,
    KXKTablebase,
    _successors,
)


def load_tb(piece: str) -> KXKTablebase:
    name = "kqk.tb.gz" if piece == "Q" else "krk.tb.gz"
    ref = resources.files("ugts_chess.resources").joinpath(name)
    with resources.as_file(ref) as path:
        return KXKTablebase.load(path)


class TablebaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.kqk = load_tb("Q")
        cls.krk = load_tb("R")

    def test_01_kqk_checkmate_loss_dtm_zero(self) -> None:
        p = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        probe = self.kqk.probe(p)
        self.assertEqual((probe.outcome, probe.dtm_plies), ("loss", 0))

    def test_02_kqk_mate_in_two_dtm_three(self) -> None:
        p = Position.from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1")
        probe = self.kqk.probe(p)
        self.assertEqual((probe.outcome, probe.dtm_plies), ("win", 3))

    def test_03_kqk_best_move(self) -> None:
        p = Position.from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1")
        self.assertEqual([item["move"] for item in self.kqk.best_moves(p)], ["b1b5"])

    def test_04_krk_checkmate(self) -> None:
        p = Position.from_fen("8/8/8/8/8/R7/8/k1K5 b - - 0 1")
        probe = self.krk.probe(p)
        self.assertEqual((probe.outcome, probe.dtm_plies), ("loss", 0))

    def test_05_black_strong_side_normalizes(self) -> None:
        p = Position.from_fen("8/8/8/8/8/K7/8/1qk5 b - - 0 1")
        probe = self.kqk.probe(p)
        self.assertEqual(probe.strong_side, "black")
        self.assertEqual((probe.outcome, probe.dtm_plies), ("win", 3))

    def test_06_non_tablebase_material_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.kqk.probe(Position.initial())

    def test_07_metadata_metrics(self) -> None:
        self.assertEqual(self.kqk.metadata["max_dtm_plies"], 20)
        self.assertEqual(self.krk.metadata["max_dtm_plies"], 32)
        self.assertEqual(self.kqk.metadata["address_bits"], 19)

    def test_08_transport_hash_matches_metadata(self) -> None:
        ref = resources.files("ugts_chess.resources").joinpath("kqk.tb.gz")
        with resources.as_file(ref) as path:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(digest, self.kqk.metadata["sha256"])

    def test_09_sampled_retrograde_invariants(self) -> None:
        checked = 0
        for index in range(0, len(self.kqk.outcomes), 257):
            outcome = self.kqk.outcomes[index]
            if outcome in (INVALID,):
                continue
            successors = _successors(index, "Q")
            child_outcomes = [DRAW if child == -1 else self.kqk.outcomes[child] for child in successors]
            child_dtm = [0 if child == -1 else self.kqk.dtm[child] for child in successors]
            if outcome == WIN:
                losing = [child_dtm[i] for i, code in enumerate(child_outcomes) if code == LOSS]
                self.assertTrue(losing)
                self.assertEqual(self.kqk.dtm[index], min(losing) + 1)
            elif outcome == LOSS:
                if not child_outcomes:
                    self.assertEqual(self.kqk.dtm[index], 0)
                else:
                    self.assertTrue(all(code == WIN for code in child_outcomes))
                    self.assertEqual(self.kqk.dtm[index], max(child_dtm) + 1)
            elif outcome == DRAW and successors:
                self.assertNotIn(LOSS, child_outcomes)
                self.assertIn(DRAW, child_outcomes)
            checked += 1
        self.assertGreater(checked, 1000)

    def test_10_outcome_counts_sum_to_address_space(self) -> None:
        counts = self.kqk.metadata["outcome_counts"]
        self.assertEqual(sum(counts.values()), 524288)


if __name__ == "__main__":
    unittest.main()
