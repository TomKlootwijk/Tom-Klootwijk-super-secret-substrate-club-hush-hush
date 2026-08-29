from __future__ import annotations

import copy
import unittest

from ugts_chess.constants import WHITE
from ugts_chess.position import Position
from ugts_chess.proof import MateProver, verify_mate_certificate


class MateProofTests(unittest.TestCase):
    FEN = "8/8/8/8/8/k7/8/1QK5 w - - 0 1"

    def test_01_proves_mate_within_three_plies(self) -> None:
        result = MateProver().prove(Position.from_fen(self.FEN), max_plies=3)
        self.assertEqual(result.status, "proved")
        self.assertEqual(result.certificate["tree"]["move"], "b1b5")

    def test_02_independent_verifier_accepts(self) -> None:
        cert = MateProver().prove(Position.from_fen(self.FEN), max_plies=3).certificate
        verified = verify_mate_certificate(cert)
        self.assertTrue(verified["valid"])
        self.assertGreaterEqual(verified["verified_nodes"], 4)

    def test_03_short_horizon_is_not_proved(self) -> None:
        result = MateProver().prove(Position.from_fen(self.FEN), max_plies=1)
        self.assertEqual(result.status, "not_forced_within_horizon")

    def test_04_tampered_move_fails(self) -> None:
        cert = MateProver().prove(Position.from_fen(self.FEN), max_plies=3).certificate
        tampered = copy.deepcopy(cert)
        tampered["tree"]["move"] = "b1b2"
        with self.assertRaises(ValueError):
            verify_mate_certificate(tampered)

    def test_05_missing_defender_reply_fails(self) -> None:
        # Use a position whose first defender node has one reply, then remove it.
        cert = MateProver().prove(Position.from_fen(self.FEN), max_plies=3).certificate
        tampered = copy.deepcopy(cert)
        tampered["tree"]["child"]["replies"] = []
        with self.assertRaises(ValueError):
            verify_mate_certificate(tampered)

    def test_06_root_hash_tamper_fails(self) -> None:
        cert = MateProver().prove(Position.from_fen(self.FEN), max_plies=3).certificate
        cert = copy.deepcopy(cert)
        cert["root_hash"] = "f" * 64
        with self.assertRaises(ValueError):
            verify_mate_certificate(cert)

    def test_07_attacker_draw_claim_move_does_not_hide_later_mate(self) -> None:
        position = Position.from_fen("kr6/2K5/1Q6/8/8/8/8/8 w - - 99 1")
        prover = MateProver()
        # Exercise an ordering in which Qb7+ reaches the 50-move threshold
        # before the capture Qxb8# is considered.
        priorities = {"b6b7": 0, "b6b8": 1}
        prover._order = lambda current, moves: sorted(  # type: ignore[method-assign]
            moves, key=lambda move: priorities.get(move.uci(), 2)
        )

        result = prover.prove(position, max_plies=2)

        self.assertEqual(result.status, "proved")
        self.assertEqual(result.certificate["tree"]["move"], "b6b8")
        self.assertTrue(verify_mate_certificate(result.certificate)["valid"])

    def test_08_verifier_accepts_checkmate_at_75_move_threshold(self) -> None:
        checkmate = Position.from_fen("kQ6/2K5/8/8/8/8/8/8 b - - 150 1")
        cert = MateProver().prove(checkmate, max_plies=1, attacker=WHITE).certificate

        self.assertEqual(cert["status"], "proved")
        self.assertTrue(verify_mate_certificate(cert)["valid"])

    def test_09_quiet_checkmate_precedes_50_move_claim(self) -> None:
        position = Position.from_fen("k7/2K5/1Q6/8/8/8/8/8 w - - 99 1")

        result = MateProver().prove(position, max_plies=1)

        self.assertEqual(result.status, "proved")
        self.assertEqual(result.certificate["tree"]["move"], "b6b8")
        self.assertTrue(verify_mate_certificate(result.certificate)["valid"])


if __name__ == "__main__":
    unittest.main()
