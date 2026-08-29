from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from ugts_chess.constants import WHITE
from ugts_chess.game_state import HistoryContext, game_state_sha256
from ugts_chess.hashing import repetition_key
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
        self.assertIsNone(result.certificate["tree"])

        schema_path = Path(__file__).resolve().parents[1] / "spec" / "ugts_kc_chess_proof.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        validator.validate(result.certificate)
        validator.validate(MateProver().prove(Position.from_fen(self.FEN), max_plies=3).certificate)

        forged_negative = copy.deepcopy(result.certificate)
        forged_negative["tree"] = {"role": "terminal"}
        self.assertTrue(list(validator.iter_errors(forged_negative)))

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
        for field in ("root_hash", "root_game_state_sha256"):
            with self.subTest(field=field):
                tampered = copy.deepcopy(cert)
                tampered[field] = "f" * 64
                with self.assertRaises(ValueError):
                    verify_mate_certificate(tampered)

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

    def test_10_profile_and_schema_are_part_of_the_trust_boundary(self) -> None:
        certificate = MateProver().prove(Position.from_fen(self.FEN), max_plies=3).certificate
        mutations = (
            ("$schema", "legacy-or-unrelated-proof"),
            ("schema_version", "1.0.0"),
            ("rules_profile", "different-chess-rules"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                tampered = copy.deepcopy(certificate)
                tampered[field] = value
                with self.assertRaises(ValueError):
                    verify_mate_certificate(tampered)

    def test_11_root_history_is_explicit_unique_and_non_coercive(self) -> None:
        certificate = MateProver().prove(Position.from_fen(self.FEN), max_plies=3).certificate

        missing = copy.deepcopy(certificate)
        del missing["root_history_counts"]
        with self.assertRaisesRegex(ValueError, "explicit list"):
            verify_mate_certificate(missing)

        for non_integer in (True, "1", 1.0):
            with self.subTest(non_integer=non_integer):
                tampered = copy.deepcopy(certificate)
                tampered["root_history_counts"][0][1] = non_integer
                with self.assertRaisesRegex(ValueError, "integers in 1..5"):
                    verify_mate_certificate(tampered)

        duplicate = copy.deepcopy(certificate)
        duplicate["root_history_counts"].append(copy.deepcopy(duplicate["root_history_counts"][0]))
        with self.assertRaisesRegex(ValueError, "unique and sorted"):
            verify_mate_certificate(duplicate)

    def test_12_mate_identity_and_defender_claim_are_history_bound(self) -> None:
        position = Position.from_fen("8/8/8/1Q6/8/k7/8/2K5 b - - 1 1")
        current_key = repetition_key(position)
        once = HistoryContext(((current_key, 1),))
        threefold = HistoryContext(((current_key, 3),))

        proved = MateProver().prove(
            position,
            max_plies=2,
            attacker=WHITE,
            history=once,
        )
        claimable = MateProver().prove(
            position,
            max_plies=2,
            attacker=WHITE,
            history=threefold,
        )
        self.assertEqual(proved.status, "proved")
        self.assertEqual(claimable.status, "not_forced_within_horizon")
        self.assertEqual(
            proved.certificate["root_hash"],
            claimable.certificate["root_hash"],
        )
        self.assertNotEqual(
            proved.certificate["root_game_state_sha256"],
            claimable.certificate["root_game_state_sha256"],
        )
        self.assertTrue(verify_mate_certificate(proved.certificate)["valid"])

        forged = copy.deepcopy(proved.certificate)
        forged["root_history_counts"] = threefold.record()
        forged["root_game_state_sha256"] = game_state_sha256(position, threefold)
        with self.assertRaisesRegex(ValueError, "defender has an available draw claim"):
            verify_mate_certificate(forged)

    def test_13_noncurrent_fivefold_history_is_unreachable(self) -> None:
        position = Position.from_fen(self.FEN)
        current_key = repetition_key(position)
        ended_key = "0" * 64
        self.assertNotEqual(ended_key, current_key)
        forged_history = HistoryContext(
            tuple(sorted(((current_key, 1), (ended_key, 5))))
        )

        with self.assertRaisesRegex(ValueError, "already ended automatically"):
            MateProver().prove(
                position,
                max_plies=3,
                history=forged_history,
            )

        certificate = copy.deepcopy(
            MateProver().prove(position, max_plies=3).certificate
        )
        certificate["root_history_counts"] = forged_history.record()
        certificate["root_game_state_sha256"] = game_state_sha256(
            position,
            forged_history,
        )
        with self.assertRaisesRegex(ValueError, "non-current position at five occurrences"):
            verify_mate_certificate(certificate)

    def test_14_current_fivefold_is_terminal_with_checkmate_precedence(self) -> None:
        ongoing = Position.from_fen(self.FEN)
        ongoing_history = HistoryContext(((repetition_key(ongoing), 5),))
        result = MateProver().prove(
            ongoing,
            max_plies=3,
            history=ongoing_history,
        )
        self.assertEqual(result.status, "not_forced_within_horizon")

        checkmate = Position.from_fen("kQ6/2K5/8/8/8/8/8/8 b - - 0 1")
        mate_history = HistoryContext(((repetition_key(checkmate), 5),))
        certificate = MateProver().prove(
            checkmate,
            max_plies=1,
            attacker=WHITE,
            history=mate_history,
        ).certificate
        self.assertEqual(certificate["status"], "proved")
        self.assertTrue(verify_mate_certificate(certificate)["valid"])


if __name__ == "__main__":
    unittest.main()
