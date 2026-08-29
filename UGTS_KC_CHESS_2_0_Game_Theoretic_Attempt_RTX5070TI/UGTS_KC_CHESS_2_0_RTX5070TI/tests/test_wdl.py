from __future__ import annotations

import copy
import unittest

from ugts_chess.game_theory import WDL
from ugts_chess.position import Position
from ugts_chess.wdl import BoundedWDLSolver, WDLVerificationError, verify_wdl_certificate


class WDLTests(unittest.TestCase):
    def test_01_checkmate_is_exact_loss(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        result = BoundedWDLSolver().solve(position, max_plies=0)
        self.assertTrue(result.root.exact)
        self.assertEqual(result.root.value, WDL.LOSS)
        verified = verify_wdl_certificate(result.certificate_bundle())
        self.assertTrue(verified["root_exact"])

    def test_02_stalemate_is_exact_draw(self) -> None:
        position = Position.from_fen("k7/2Q5/2K5/8/8/8/8/8 b - - 0 1")
        result = BoundedWDLSolver().solve(position, max_plies=0)
        self.assertEqual(result.root.value, WDL.DRAW)
        self.assertTrue(result.root.exact)

    def test_03_mate_in_two_closes_as_win(self) -> None:
        position = Position.from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1")
        result = BoundedWDLSolver(node_budget=200_000).solve(position, max_plies=3)
        self.assertEqual(result.root.value, WDL.WIN)
        self.assertTrue(result.root.exact)
        verified = verify_wdl_certificate(result.certificate_bundle())
        self.assertEqual(verified["root_value"], "win")

    def test_04_draw_claim_at_horizon_is_not_an_exact_draw(self) -> None:
        position = Position.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 100 1")
        result = BoundedWDLSolver().solve(position, max_plies=0)
        self.assertEqual(result.root.value, WDL.UNKNOWN)
        self.assertFalse(result.root.exact)
        verified = verify_wdl_certificate(result.certificate_bundle(), allow_unknown_root=True)
        self.assertFalse(verified["root_exact"])

    def test_05_tampered_certificate_hash_is_rejected(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        bundle = BoundedWDLSolver().solve(position, max_plies=0).certificate_bundle()
        tampered = copy.deepcopy(bundle)
        tampered["nodes"][0]["value"] = "win"
        with self.assertRaises(WDLVerificationError):
            verify_wdl_certificate(tampered)

    def test_06_wrong_rules_profile_is_rejected(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        bundle = BoundedWDLSolver().solve(position, max_plies=0).certificate_bundle()
        bundle["rules_profile"] = "different-chess-rules"

        with self.assertRaises(WDLVerificationError):
            verify_wdl_certificate(bundle)


if __name__ == "__main__":
    unittest.main()
