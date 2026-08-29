from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from ugts_chess.campaign import (
    campaign_status,
    export_campaign,
    init_campaign,
    mark_verified,
    record_candidate,
    verify_campaign,
)
from ugts_chess.game_state import RULE_PROFILE_ID, HistoryContext, game_state_sha256
from ugts_chess.game_theory import ProofObligation, root_obligations
from ugts_chess.position import Position
from ugts_chess.wdl import BoundedWDLSolver, WDL


MATE_PARENT_FEN = "k7/8/2K5/1Q6/8/8/8/8 w - - 0 1"
MATE_MOVE = "b5b7"
CLAIM_PARENT_FEN = "8/8/8/8/8/8/R3k3/K7 w - - 99 1"
CLAIM_MOVE = "a2a3"
VERIFIER = "independent-test-oracle"


class CampaignTests(unittest.TestCase):
    @staticmethod
    def _obligation(root_fen: str, move_uci: str) -> ProofObligation:
        position = Position.from_fen(root_fen)
        history = HistoryContext.initial(position)
        return next(item for item in root_obligations(position, history) if item.move_uci == move_uci)

    @staticmethod
    def _write_certificate(
        path: Path,
        obligation: ProofObligation,
        *,
        max_plies: int = 0,
    ) -> dict[str, object]:
        child = Position.from_fen(obligation.child_fen)
        history = HistoryContext(obligation.child_history_counts)
        result = BoundedWDLSolver().solve(child, max_plies=max_plies, history=history)
        payload = result.record()
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return payload

    @staticmethod
    def _write_checker(
        path: Path,
        *,
        obligation: ProofObligation,
        certificate: Path,
        wdl: str,
        checker: str = VERIFIER,
    ) -> None:
        payload = {
            "schema": "ugts-chess-independent-check-2.0",
            "valid": True,
            "obligation_id": obligation.obligation_id,
            "wdl": wdl,
            "certificate_sha256": hashlib.sha256(certificate.read_bytes()).hexdigest(),
            "child_game_state_sha256": obligation.child_game_state_sha256,
            "checker": checker,
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_01_initial_campaign_is_complete_and_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            meta = init_campaign(db, root / "shards")
            self.assertEqual(meta["obligation_count"], 20)
            self.assertEqual(meta["dedication"]["to"], "Anna Cramling")
            self.assertEqual(meta["dedication"]["opening"], "The Cow Opening")
            self.assertIn("20 legal root-move proof obligations", meta["dedication"]["scope"])
            status = campaign_status(db)
            self.assertEqual(status["root_wdl"], "unknown")
            self.assertFalse(status["game_solved"])
            audit = verify_campaign(db)
            self.assertTrue(audit["valid"], audit["errors"])

    def test_02_exact_bound_certificate_can_be_promoted_and_reaudited(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=MATE_PARENT_FEN)
            obligation = self._obligation(MATE_PARENT_FEN, MATE_MOVE)
            certificate = root / "candidate.json"
            payload = self._write_certificate(certificate, obligation)
            self.assertTrue(payload["completed"])
            self.assertEqual(payload["root"]["value"], WDL.LOSS.value)

            record_candidate(db, obligation.obligation_id, WDL.LOSS, certificate, worker="worker-a")
            checker = root / "checker.json"
            self._write_checker(
                checker,
                obligation=obligation,
                certificate=certificate,
                wdl=WDL.LOSS.value,
            )
            promoted = mark_verified(
                db,
                obligation.obligation_id,
                verifier=VERIFIER,
                checker_record=checker,
            )
            self.assertEqual(promoted["status"], "verified")
            self.assertEqual(campaign_status(db)["root_wdl"], WDL.WIN.value)

            audit = verify_campaign(db)
            self.assertTrue(audit["valid"], audit["errors"])
            self.assertEqual(audit["expected_job_count"], 26)
            exported = export_campaign(db, root / "checkpoint.json")
            self.assertEqual(exported["jobs"], 26)
            checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
            self.assertEqual(checkpoint["metadata"]["dedication"]["to"], "Anna Cramling")

    def test_03_self_authored_checker_cannot_promote_fabricated_certificate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=MATE_PARENT_FEN)
            obligation = self._obligation(MATE_PARENT_FEN, MATE_MOVE)
            certificate = root / "fabricated.json"
            certificate.write_text(
                json.dumps({"candidate": True, "rules_profile": RULE_PROFILE_ID}) + "\n",
                encoding="utf-8",
            )
            record_candidate(db, obligation.obligation_id, WDL.LOSS, certificate, worker="worker-a")
            checker = root / "checker.json"
            self._write_checker(
                checker,
                obligation=obligation,
                certificate=certificate,
                wdl=WDL.LOSS.value,
            )

            with self.assertRaisesRegex(ValueError, "candidate WDL proof is invalid"):
                mark_verified(
                    db,
                    obligation.obligation_id,
                    verifier=VERIFIER,
                    checker_record=checker,
                )
            status = campaign_status(db)
            self.assertEqual(status["root_wdl"], WDL.UNKNOWN.value)
            self.assertEqual(status["status_counts"].get("candidate"), 1)

    def test_04_valid_certificate_for_another_state_or_wdl_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            obligation = self._obligation(MATE_PARENT_FEN, MATE_MOVE)

            wrong_state_db = root / "wrong-state.sqlite3"
            init_campaign(wrong_state_db, root / "wrong-state-shards", root_fen=MATE_PARENT_FEN)
            wrong_state_certificate = root / "wrong-state.json"
            stalemate = Position.from_fen("k7/2Q5/2K5/8/8/8/8/8 b - - 0 1")
            wrong_state_payload = BoundedWDLSolver().solve(stalemate, max_plies=0).record()
            wrong_state_certificate.write_text(
                json.dumps(wrong_state_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            record_candidate(
                wrong_state_db,
                obligation.obligation_id,
                WDL.DRAW,
                wrong_state_certificate,
                worker="worker-a",
            )
            wrong_state_checker = root / "wrong-state-checker.json"
            self._write_checker(
                wrong_state_checker,
                obligation=obligation,
                certificate=wrong_state_certificate,
                wdl=WDL.DRAW.value,
            )
            with self.assertRaisesRegex(ValueError, "root does not match the obligation child game state"):
                mark_verified(
                    wrong_state_db,
                    obligation.obligation_id,
                    verifier=VERIFIER,
                    checker_record=wrong_state_checker,
                )

            wrong_wdl_db = root / "wrong-wdl.sqlite3"
            init_campaign(wrong_wdl_db, root / "wrong-wdl-shards", root_fen=MATE_PARENT_FEN)
            exact_certificate = root / "exact-loss.json"
            self._write_certificate(exact_certificate, obligation)
            record_candidate(
                wrong_wdl_db,
                obligation.obligation_id,
                WDL.WIN,
                exact_certificate,
                worker="worker-a",
            )
            wrong_wdl_checker = root / "wrong-wdl-checker.json"
            self._write_checker(
                wrong_wdl_checker,
                obligation=obligation,
                certificate=exact_certificate,
                wdl=WDL.WIN.value,
            )
            with self.assertRaisesRegex(ValueError, "root WDL does not match the declared WDL"):
                mark_verified(
                    wrong_wdl_db,
                    obligation.obligation_id,
                    verifier=VERIFIER,
                    checker_record=wrong_wdl_checker,
                )

    def test_05_same_state_hash_with_different_fen_lineage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=MATE_PARENT_FEN)
            obligation = self._obligation(MATE_PARENT_FEN, MATE_MOVE)
            expected_child = Position.from_fen(obligation.child_fen)
            different_fullmove = Position.from_fen(
                obligation.child_fen.rsplit(" ", 1)[0] + " 42"
            )
            history = HistoryContext(obligation.child_history_counts)
            self.assertEqual(
                game_state_sha256(expected_child, history),
                game_state_sha256(different_fullmove, history),
            )
            certificate = root / "wrong-lineage.json"
            payload = BoundedWDLSolver().solve(
                different_fullmove,
                max_plies=0,
                history=history,
            ).record()
            certificate.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            record_candidate(db, obligation.obligation_id, WDL.LOSS, certificate, worker="worker-a")
            checker = root / "checker.json"
            self._write_checker(
                checker,
                obligation=obligation,
                certificate=certificate,
                wdl=WDL.LOSS.value,
            )
            with self.assertRaisesRegex(ValueError, "root FEN does not match"):
                mark_verified(
                    db,
                    obligation.obligation_id,
                    verifier=VERIFIER,
                    checker_record=checker,
                )

    def test_06_wrong_rules_profile_cannot_be_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=MATE_PARENT_FEN)
            obligation = self._obligation(MATE_PARENT_FEN, MATE_MOVE)
            certificate = root / "wrong-profile.json"
            payload = self._write_certificate(certificate, obligation)
            payload["certificate_bundle"]["rules_profile"] = "fabricated-rules-profile"
            certificate.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            record_candidate(db, obligation.obligation_id, WDL.LOSS, certificate, worker="worker-a")
            checker = root / "checker.json"
            self._write_checker(
                checker,
                obligation=obligation,
                certificate=certificate,
                wdl=WDL.LOSS.value,
            )
            with self.assertRaisesRegex(ValueError, "rules profile does not match the campaign"):
                mark_verified(
                    db,
                    obligation.obligation_id,
                    verifier=VERIFIER,
                    checker_record=checker,
                )

    def test_07_claim_action_at_horizon_remains_unknown_and_cannot_be_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=CLAIM_PARENT_FEN)
            obligation = self._obligation(CLAIM_PARENT_FEN, CLAIM_MOVE)
            certificate = root / "unknown-claim.json"
            payload = self._write_certificate(certificate, obligation)
            self.assertFalse(payload["completed"])
            self.assertEqual(payload["root"]["value"], WDL.UNKNOWN.value)
            self.assertIn("claim_fifty_move_current", payload["root"]["current_claim_actions"])

            record_candidate(db, obligation.obligation_id, WDL.DRAW, certificate, worker="worker-a")
            checker = root / "checker.json"
            self._write_checker(
                checker,
                obligation=obligation,
                certificate=certificate,
                wdl=WDL.DRAW.value,
            )
            with self.assertRaisesRegex(ValueError, "root is UNKNOWN"):
                mark_verified(
                    db,
                    obligation.obligation_id,
                    verifier=VERIFIER,
                    checker_record=checker,
                )
            self.assertEqual(campaign_status(db)["root_wdl"], WDL.UNKNOWN.value)

    def test_08_audit_replays_proof_and_rejects_legacy_forged_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=MATE_PARENT_FEN)
            obligation = self._obligation(MATE_PARENT_FEN, MATE_MOVE)
            certificate = root / "fabricated.json"
            certificate.write_text(
                json.dumps({"candidate": True, "rules_profile": RULE_PROFILE_ID}) + "\n",
                encoding="utf-8",
            )
            record_candidate(db, obligation.obligation_id, WDL.LOSS, certificate, worker="worker-a")
            checker = root / "checker.json"
            self._write_checker(
                checker,
                obligation=obligation,
                certificate=certificate,
                wdl=WDL.LOSS.value,
            )
            checker_hash = hashlib.sha256(checker.read_bytes()).hexdigest()

            # Model a row promoted by the former field-only implementation.
            with closing(sqlite3.connect(db)) as conn:
                conn.execute(
                    """UPDATE jobs SET status='verified',verification=?,checker_path=?,checker_sha256=?
                       WHERE obligation_id=?""",
                    (
                        f"independent-check:{VERIFIER}",
                        checker.name,
                        checker_hash,
                        obligation.obligation_id,
                    ),
                )
                conn.commit()

            audit = verify_campaign(db)
            self.assertFalse(audit["valid"])
            self.assertTrue(
                any("verified certificate invalid" in error for error in audit["errors"]),
                audit["errors"],
            )


if __name__ == "__main__":
    unittest.main()
