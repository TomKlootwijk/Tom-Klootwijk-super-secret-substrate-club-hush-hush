from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from ugts_chess import Position
from ugts_chess.game_state import (
    HistoryContext,
    automatic_status,
    current_claim_actions,
    intended_move_claims,
)
from ugts_chess.game_theory import WDL as CampaignWDL, aggregate_root_wdl, root_obligations
from ugts_chess.rules import apply_move, parse_uci_move
from ugts_chess.wdl import BoundedWDLSolver, WDL
from ugts_chess.campaign import init_campaign, campaign_status, lease_next, verify_campaign


class DrawClaimAndWDLTests(unittest.TestCase):
    def test_01_fifty_move_claim_is_optional_action(self) -> None:
        p = Position.from_fen("8/8/8/1Q6/8/8/k7/2K5 w - - 100 2")
        history = HistoryContext.initial(p)
        self.assertIn("claim_fifty_move_current", current_claim_actions(p, history))
        result = BoundedWDLSolver(node_budget=100_000).solve(p, max_plies=1, history=history)
        self.assertEqual(result.root.value, WDL.WIN)
        self.assertTrue(result.root.exact)
        self.assertEqual(result.root.terminal_code, "winning_move_witness")

    def test_02_intended_move_claim_is_declared_action(self) -> None:
        p = Position.from_fen("8/8/8/8/8/8/R3k3/K7 w - - 99 1")
        child = apply_move(p, parse_uci_move(p, "a2a3"))
        history = HistoryContext.initial(p).push(child)
        self.assertIn("claim_fifty_move_by_move", intended_move_claims(child, history))

    def test_03_automatic_75_move_draw(self) -> None:
        p = Position.from_fen("8/8/8/8/8/8/R3k3/K7 w - - 150 1")
        status = automatic_status(p, HistoryContext.initial(p))
        self.assertTrue(status.terminal)
        self.assertEqual(status.code, "seventy_five_move")

    def test_04_checkmate_is_loss_for_side_to_move(self) -> None:
        p = Position.from_fen("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        result = BoundedWDLSolver().solve(p, max_plies=0)
        self.assertEqual(result.root.value, WDL.LOSS)
        self.assertTrue(result.root.exact)

    def test_05_initial_depth_one_remains_unknown(self) -> None:
        result = BoundedWDLSolver(node_budget=100_000).solve(Position.initial(), max_plies=1)
        self.assertEqual(result.root.value, WDL.UNKNOWN)
        self.assertFalse(result.root.exact)


class RootCampaignTests(unittest.TestCase):
    def test_06_root_obligations_and_aggregation(self) -> None:
        obligations = root_obligations()
        self.assertEqual(len(obligations), 20)
        self.assertEqual(aggregate_root_wdl([CampaignWDL.LOSS] + [CampaignWDL.UNKNOWN] * 19), CampaignWDL.WIN)
        self.assertEqual(aggregate_root_wdl([CampaignWDL.WIN] * 20), CampaignWDL.LOSS)
        self.assertEqual(aggregate_root_wdl([CampaignWDL.DRAW] + [CampaignWDL.WIN] * 19), CampaignWDL.DRAW)
        self.assertEqual(aggregate_root_wdl([CampaignWDL.UNKNOWN] + [CampaignWDL.WIN] * 19), CampaignWDL.UNKNOWN)

    def test_07_sqlite_campaign_hash_chain_and_lease(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "campaign.sqlite3"
            shards = root / "shards"
            result = init_campaign(db, shards)
            self.assertEqual(result["obligation_count"], 20)
            status = campaign_status(db)
            self.assertEqual(status["root_wdl"], "unknown")
            self.assertEqual(status["obligations"], 20)
            leased = lease_next(db, "test-worker", seconds=30)
            self.assertIsNotNone(leased)
            verification = verify_campaign(db)
            self.assertTrue(verification["valid"], verification["errors"])
            self.assertEqual(verification["job_count"], 20)


if __name__ == "__main__":
    unittest.main()
