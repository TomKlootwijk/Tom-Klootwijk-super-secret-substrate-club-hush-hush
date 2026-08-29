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
from ugts_chess.hashing import state_sha256
from ugts_chess.position import START_FEN, Position
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
            self.assertEqual(meta["cow_opening_priority"]["moves_uci"], ["d2d3", "e2e3"])
            with closing(sqlite3.connect(db)) as conn:
                priorities = dict(conn.execute("SELECT move_uci,priority FROM jobs"))
            cow_moves = {"d2d3", "e2e3"}
            self.assertEqual({move for move, value in priorities.items() if value > 0}, cow_moves)
            self.assertEqual({priorities[move] for move in cow_moves}, {10})
            self.assertTrue(all(value == 0 for move, value in priorities.items() if move not in cow_moves))
            status = campaign_status(db)
            self.assertEqual(status["root_wdl"], "unknown")
            self.assertFalse(status["game_solved"])
            self.assertTrue(status["is_classical_initial_root"])
            self.assertFalse(status["classical_initial_solved"])
            self.assertEqual(status["game_solved_scope"], "declared_campaign_root_only")
            self.assertEqual(len(status["root_identity_sha256"]), 64)
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
            status = campaign_status(db)
            self.assertEqual(status["root_wdl"], WDL.WIN.value)
            self.assertTrue(status["game_solved"])
            self.assertFalse(status["is_classical_initial_root"])
            self.assertFalse(status["classical_initial_solved"])

            audit = verify_campaign(db)
            self.assertTrue(audit["valid"], audit["errors"])
            self.assertEqual(audit["expected_job_count"], 26)
            self.assertEqual(audit["root_fen"], MATE_PARENT_FEN)
            self.assertEqual(
                audit["root_position_sha256"],
                state_sha256(Position.from_fen(MATE_PARENT_FEN)),
            )
            self.assertEqual(len(audit["root_identity_sha256"]), 64)
            self.assertTrue(audit["game_solved"])
            self.assertFalse(audit["classical_initial_solved"])
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
            self.assertEqual(audit["root_wdl"], WDL.UNKNOWN.value)
            self.assertFalse(audit["game_solved"])

    def test_09_verified_row_requires_a_matching_lifecycle_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=MATE_PARENT_FEN)
            obligation = self._obligation(MATE_PARENT_FEN, MATE_MOVE)
            certificate = root / "candidate.json"
            self._write_certificate(certificate, obligation)
            record_candidate(db, obligation.obligation_id, WDL.LOSS, certificate, worker="worker-a")
            checker = root / "checker.json"
            self._write_checker(
                checker,
                obligation=obligation,
                certificate=certificate,
                wdl=WDL.LOSS.value,
            )
            mark_verified(db, obligation.obligation_id, verifier=VERIFIER, checker_record=checker)

            # Removing the final event leaves the remaining hash chain internally
            # valid; semantic replay must still refuse the promoted row.
            with closing(sqlite3.connect(db)) as conn:
                conn.execute("DELETE FROM events WHERE action='candidate_verified'")
                conn.commit()

            audit = verify_campaign(db)
            self.assertFalse(audit["valid"])
            self.assertTrue(any("event-replayed status" in error for error in audit["errors"]), audit["errors"])
            self.assertEqual(audit["root_wdl"], WDL.UNKNOWN.value)
            self.assertFalse(audit["game_solved"])

    def test_10_malformed_database_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = ("meta", "event", "child_history")
            for case in cases:
                with self.subTest(case=case):
                    case_root = root / case
                    db = case_root / "campaign.sqlite3"
                    init_campaign(db, case_root / "shards")
                    with closing(sqlite3.connect(db)) as conn:
                        if case == "meta":
                            conn.execute(
                                "UPDATE meta SET value=? WHERE key='root_history_counts'",
                                ("{not-json",),
                            )
                        elif case == "event":
                            conn.execute("UPDATE events SET payload_json=? WHERE sequence=1", ("{not-json",))
                        else:
                            conn.execute(
                                "UPDATE jobs SET child_history_json=? WHERE obligation_id=(SELECT obligation_id FROM jobs ORDER BY obligation_id LIMIT 1)",
                                ("{not-json",),
                            )
                        conn.commit()

                    audit = verify_campaign(db)
                    self.assertFalse(audit["valid"])
                    self.assertEqual(audit["root_wdl"], WDL.UNKNOWN.value)
                    self.assertFalse(audit["game_solved"])

    def test_11_rehashed_shard_must_still_match_the_canonical_obligation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards")
            with closing(sqlite3.connect(db)) as conn:
                row = conn.execute(
                    "SELECT obligation_id,shard_path FROM jobs ORDER BY obligation_id LIMIT 1"
                ).fetchone()
                self.assertIsNotNone(row)
                obligation_id, stored_path = row
                shard = db.parent / stored_path
                payload = json.loads(shard.read_text(encoding="utf-8"))
                payload["target"] = "tampered-but-rehashed"
                shard.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                conn.execute(
                    "UPDATE jobs SET shard_sha256=? WHERE obligation_id=?",
                    (hashlib.sha256(shard.read_bytes()).hexdigest(), obligation_id),
                )
                conn.commit()

            audit = verify_campaign(db)
            self.assertFalse(audit["valid"])
            self.assertTrue(any("shard content" in error for error in audit["errors"]), audit["errors"])

    def test_12_public_status_and_export_ignore_forged_verified_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards")

            # Before this hardening, one directly edited LOSS child was enough
            # for campaign_status (and therefore snapshots/exports) to report
            # a root WIN without any certificate or verification event.
            with closing(sqlite3.connect(db)) as conn:
                conn.execute(
                    """UPDATE jobs SET status='verified',wdl='loss',
                       verification='independent-check:forged'
                       WHERE obligation_id=(
                           SELECT obligation_id FROM jobs ORDER BY obligation_id LIMIT 1
                       )"""
                )
                conn.commit()

            status = campaign_status(db)
            self.assertFalse(status["audit_valid"])
            self.assertTrue(status["audit_errors"])
            self.assertEqual(status["root_wdl"], WDL.UNKNOWN.value)
            self.assertFalse(status["game_solved"])
            self.assertEqual(status["verified_children"], 0)
            # Operational row counts remain visible, but cannot become proof
            # authority.
            self.assertEqual(status["status_counts"].get("verified"), 1)

            destination = root / "tampered-checkpoint.json"
            export_campaign(db, destination)
            checkpoint = json.loads(destination.read_text(encoding="utf-8"))
            self.assertFalse(checkpoint["status"]["audit_valid"])
            self.assertEqual(checkpoint["status"]["root_wdl"], WDL.UNKNOWN.value)
            self.assertFalse(checkpoint["status"]["game_solved"])

    def test_13_public_status_fails_closed_when_verification_event_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=MATE_PARENT_FEN)
            obligation = self._obligation(MATE_PARENT_FEN, MATE_MOVE)
            certificate = root / "candidate.json"
            self._write_certificate(certificate, obligation)
            record_candidate(db, obligation.obligation_id, WDL.LOSS, certificate, worker="worker-a")
            checker = root / "checker.json"
            self._write_checker(
                checker,
                obligation=obligation,
                certificate=certificate,
                wdl=WDL.LOSS.value,
            )
            mark_verified(db, obligation.obligation_id, verifier=VERIFIER, checker_record=checker)
            self.assertTrue(campaign_status(db)["game_solved"])

            with closing(sqlite3.connect(db)) as conn:
                conn.execute("DELETE FROM events WHERE action='candidate_verified'")
                conn.commit()

            status = campaign_status(db)
            self.assertFalse(status["audit_valid"])
            self.assertEqual(status["root_wdl"], WDL.UNKNOWN.value)
            self.assertFalse(status["game_solved"])
            self.assertEqual(status["verified_children"], 0)

    def test_14_promotion_rejects_valid_certificate_for_substituted_job_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(db, root / "shards", root_fen=MATE_PARENT_FEN)
            canonical = self._obligation(MATE_PARENT_FEN, MATE_MOVE)

            substituted = Position.from_fen("k7/2Q5/2K5/8/8/8/8/8 b - - 0 1")
            substituted_history = HistoryContext.initial(substituted)
            result = BoundedWDLSolver().solve(
                substituted,
                max_plies=0,
                history=substituted_history,
            )
            self.assertTrue(result.completed)
            self.assertEqual(result.root.value, WDL.DRAW)
            certificate = root / "substituted-valid-certificate.json"
            certificate.write_text(
                json.dumps(result.record(), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            record_candidate(
                db,
                canonical.obligation_id,
                WDL.DRAW,
                certificate,
                worker="worker-a",
            )

            substituted_game_hash = game_state_sha256(substituted, substituted_history)
            with closing(sqlite3.connect(db)) as conn:
                conn.execute(
                    """UPDATE jobs SET child_fen=?,child_position_sha256=?,
                       child_game_state_sha256=?,child_history_json=?,child_side_to_move=?
                       WHERE obligation_id=?""",
                    (
                        substituted.to_fen(),
                        state_sha256(substituted),
                        substituted_game_hash,
                        json.dumps(substituted_history.record(), separators=(",", ":")),
                        "black",
                        canonical.obligation_id,
                    ),
                )
                conn.commit()

            checker = root / "substituted-checker.json"
            checker.write_text(
                json.dumps(
                    {
                        "schema": "ugts-chess-independent-check-2.0",
                        "valid": True,
                        "obligation_id": canonical.obligation_id,
                        "wdl": WDL.DRAW.value,
                        "certificate_sha256": hashlib.sha256(certificate.read_bytes()).hexdigest(),
                        "child_game_state_sha256": substituted_game_hash,
                        "checker": VERIFIER,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "canonical root obligation"):
                mark_verified(
                    db,
                    canonical.obligation_id,
                    verifier=VERIFIER,
                    checker_record=checker,
                )
            with closing(sqlite3.connect(db)) as conn:
                status = conn.execute(
                    "SELECT status FROM jobs WHERE obligation_id=?",
                    (canonical.obligation_id,),
                ).fetchone()[0]
            self.assertEqual(status, "candidate")

    def test_15_automatic_root_adjudication_handles_75_move_and_checkmate_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            draw_fen = MATE_PARENT_FEN.replace(" 0 1", " 150 1")
            draw_db = root / "automatic-draw.sqlite3"
            initialized = init_campaign(draw_db, root / "draw-shards", root_fen=draw_fen)
            self.assertEqual(initialized["obligation_count"], 0)
            draw_audit = verify_campaign(draw_db)
            self.assertTrue(draw_audit["valid"], draw_audit["errors"])
            self.assertEqual(draw_audit["root_automatic_code"], "seventy_five_move")
            self.assertEqual(draw_audit["root_wdl"], WDL.DRAW.value)
            self.assertTrue(draw_audit["game_solved"])
            self.assertFalse(draw_audit["classical_initial_solved"])
            draw_status = campaign_status(draw_db)
            self.assertEqual(draw_status["root_wdl"], WDL.DRAW.value)
            self.assertTrue(draw_status["game_solved"])
            self.assertFalse(draw_status["classical_initial_solved"])

            checkmate_fen = "k7/1Q6/2K5/8/8/8/8/8 b - - 150 1"
            checkmate_db = root / "checkmate.sqlite3"
            initialized = init_campaign(
                checkmate_db,
                root / "checkmate-shards",
                root_fen=checkmate_fen,
            )
            self.assertEqual(initialized["obligation_count"], 0)
            checkmate_audit = verify_campaign(checkmate_db)
            self.assertTrue(checkmate_audit["valid"], checkmate_audit["errors"])
            self.assertEqual(checkmate_audit["root_automatic_code"], "checkmate")
            self.assertEqual(checkmate_audit["root_wdl"], WDL.LOSS.value)
            self.assertTrue(checkmate_audit["game_solved"])
            self.assertFalse(checkmate_audit["classical_initial_solved"])

    def test_16_root_fifty_move_claims_prevent_false_loss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for halfmove, expected_claim in (
                (99, "move:a1a2:claim_fifty_move_by_move"),
                (100, "current:claim_fifty_move_current"),
            ):
                with self.subTest(halfmove=halfmove):
                    case_root = root / str(halfmove)
                    root_fen = f"8/8/8/8/8/8/8/K1kq4 w - - {halfmove} 1"
                    db = case_root / "campaign.sqlite3"
                    init_campaign(db, case_root / "shards", root_fen=root_fen)
                    obligation = self._obligation(root_fen, "a1a2")
                    certificate = case_root / "child-win.json"
                    payload = self._write_certificate(certificate, obligation, max_plies=2)
                    self.assertTrue(payload["completed"])
                    self.assertEqual(payload["root"]["value"], WDL.WIN.value)
                    record_candidate(
                        db,
                        obligation.obligation_id,
                        WDL.WIN,
                        certificate,
                        worker="worker-a",
                    )
                    checker = case_root / "checker.json"
                    self._write_checker(
                        checker,
                        obligation=obligation,
                        certificate=certificate,
                        wdl=WDL.WIN.value,
                    )
                    mark_verified(
                        db,
                        obligation.obligation_id,
                        verifier=VERIFIER,
                        checker_record=checker,
                    )

                    audit = verify_campaign(db)
                    self.assertTrue(audit["valid"], audit["errors"])
                    self.assertEqual(audit["verified_children"], 1)
                    self.assertIn(expected_claim, audit["root_claim_actions"])
                    # The only normal move is a child WIN, which would make
                    # the root a LOSS without the optional claim action.
                    self.assertEqual(audit["root_wdl"], WDL.DRAW.value)
                    self.assertTrue(audit["game_solved"])
                    self.assertFalse(audit["classical_initial_solved"])

    def test_17_snapshot_schema_accepts_custom_root_job_counts(self) -> None:
        try:
            import jsonschema
        except ModuleNotFoundError:
            self.skipTest("jsonschema is available in the validation environment only")

        schema_path = Path(__file__).resolve().parents[1] / "spec" / "ugts_chess_campaign_snapshot.schema.json"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cases = (
                ("classical", START_FEN, 20),
                ("terminal", MATE_PARENT_FEN.replace(" 0 1", " 150 1"), 0),
                ("single-move", "8/8/8/8/8/8/8/K1kq4 w - - 100 1", 1),
            )
            for name, root_fen, expected_jobs in cases:
                with self.subTest(name=name):
                    case_root = root / name
                    db = case_root / "campaign.sqlite3"
                    init_campaign(db, case_root / "shards", root_fen=root_fen)
                    destination = case_root / "snapshot.json"
                    export_campaign(db, destination)
                    snapshot = json.loads(destination.read_text(encoding="utf-8"))
                    self.assertEqual(len(snapshot["jobs"]), expected_jobs)
                    jsonschema.validate(snapshot, schema)
                    if name == "terminal":
                        forged_scope = json.loads(json.dumps(snapshot))
                        forged_scope["status"]["is_classical_initial_root"] = True
                        forged_scope["status"]["classical_initial_solved"] = True
                        with self.assertRaises(jsonschema.ValidationError):
                            jsonschema.validate(forged_scope, schema)

    def test_18_obligation_schemas_accept_canonical_three_digit_indices(self) -> None:
        try:
            import jsonschema
        except ModuleNotFoundError:
            self.skipTest("jsonschema is available in the validation environment only")

        repository = Path(__file__).resolve().parents[1]
        obligation_schema = json.loads(
            (repository / "spec" / "ugts_chess_proof_obligation.schema.json").read_text(
                encoding="utf-8"
            )
        )
        checker_schema = json.loads(
            (repository / "spec" / "ugts_chess_independent_check.schema.json").read_text(
                encoding="utf-8"
            )
        )
        campaign_schema = json.loads(
            (repository / "spec" / "ugts_chess_campaign_snapshot.schema.json").read_text(
                encoding="utf-8"
            )
        )
        for schema in (obligation_schema, checker_schema, campaign_schema):
            jsonschema.Draft202012Validator.check_schema(schema)

        obligation = json.loads(
            (
                repository
                / "examples"
                / "campaign"
                / "root_shards"
                / "root-01-a2a3.json"
            ).read_text(encoding="utf-8")
        )
        obligation["obligation_id"] = "root-100-a2a3"
        jsonschema.validate(obligation, obligation_schema)

        checker = {
            "schema": "ugts-chess-independent-check-2.0",
            "valid": True,
            "obligation_id": "root-100-a2a3",
            "wdl": WDL.DRAW.value,
            "certificate_sha256": "a" * 64,
            "child_game_state_sha256": "b" * 64,
            "checker": "schema-test",
        }
        jsonschema.validate(checker, checker_schema)

        for invalid_id in ("root-1-a2a3", "root-00-a2a3", "root-010-a2a3"):
            with self.subTest(invalid_id=invalid_id):
                obligation["obligation_id"] = invalid_id
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(obligation, obligation_schema)
                checker["obligation_id"] = invalid_id
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(checker, checker_schema)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = root / "campaign.sqlite3"
            init_campaign(
                db,
                root / "shards",
                root_fen="8/8/8/8/8/8/8/K1kq4 w - - 100 1",
            )
            destination = root / "snapshot.json"
            export_campaign(db, destination)
            snapshot = json.loads(destination.read_text(encoding="utf-8"))
            snapshot["jobs"][0]["obligation_id"] = "root-100-a1a2"
            jsonschema.validate(snapshot, campaign_schema)


if __name__ == "__main__":
    unittest.main()
