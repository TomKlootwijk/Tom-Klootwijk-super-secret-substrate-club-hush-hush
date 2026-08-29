from __future__ import annotations

import unittest

from ugts_chess.game_theory import WDL, aggregate_root_wdl, root_obligations
from ugts_chess.hashing import repetition_key, state_sha256
from ugts_chess.game_state import HistoryContext, game_state_sha256
from ugts_chess.position import Position


class GameTheoryTests(unittest.TestCase):
    def test_01_initial_root_has_twenty_exact_obligations(self) -> None:
        obligations = root_obligations()
        self.assertEqual(len(obligations), 20)
        self.assertEqual(len({item.obligation_id for item in obligations}), 20)
        self.assertTrue(all(item.wdl == WDL.UNKNOWN for item in obligations))
        self.assertTrue(all(len(item.child_game_state_sha256) == 64 for item in obligations))

    def test_02_root_aggregation_orientation(self) -> None:
        self.assertEqual(aggregate_root_wdl([WDL.LOSS, WDL.UNKNOWN]), WDL.WIN)
        self.assertEqual(aggregate_root_wdl([WDL.WIN, WDL.WIN]), WDL.LOSS)
        self.assertEqual(aggregate_root_wdl([WDL.WIN, WDL.DRAW]), WDL.DRAW)
        self.assertEqual(aggregate_root_wdl([WDL.WIN, WDL.UNKNOWN]), WDL.UNKNOWN)

    def test_03_illegal_en_passant_does_not_split_repetition_identity(self) -> None:
        pinned = Position.from_fen("k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        no_ep = Position.from_fen("k3r3/8/8/3pP3/8/8/8/4K3 w - - 0 1")
        self.assertEqual(repetition_key(pinned), repetition_key(no_ep))

    def test_04_legal_en_passant_changes_repetition_identity(self) -> None:
        legal = Position.from_fen("k7/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        no_ep = Position.from_fen("k7/8/8/3pP3/8/8/8/4K3 w - - 0 1")
        self.assertNotEqual(repetition_key(legal), repetition_key(no_ep))

    def test_05_fullmove_counter_is_lineage_not_game_value_identity(self) -> None:
        a = Position.from_fen("8/8/8/8/8/8/R3k3/K7 w - - 0 1")
        b = Position.from_fen("8/8/8/8/8/8/R3k3/K7 w - - 0 87")
        self.assertNotEqual(state_sha256(a), state_sha256(b))
        history_a = HistoryContext.initial(a)
        history_b = HistoryContext.initial(b)
        self.assertEqual(game_state_sha256(a, history_a), game_state_sha256(b, history_b))


if __name__ == "__main__":
    unittest.main()
