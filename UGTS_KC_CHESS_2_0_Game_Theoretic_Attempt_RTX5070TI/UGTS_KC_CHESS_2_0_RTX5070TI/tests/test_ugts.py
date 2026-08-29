from __future__ import annotations

import unittest

from ugts_chess.hashing import state_sha256
from ugts_chess.position import Position
from ugts_chess.rules import parse_uci_move
from ugts_chess.ugts import commit_move, propose_move, replay


class UGTSEventTests(unittest.TestCase):
    def test_01_legal_proposal_passes_all_gates(self) -> None:
        p = Position.initial()
        proposal = propose_move(p, parse_uci_move(p, "e2e4"))
        self.assertTrue(proposal.verified)
        self.assertEqual(proposal.reason_codes, ())

    def test_02_wrong_side_fails_compatibility(self) -> None:
        p = Position.initial()
        from ugts_chess.move import Move
        proposal = propose_move(p, Move(48, 40))
        self.assertFalse(proposal.compatibility_ok)
        self.assertIn("side_or_occupancy_incompatible", proposal.reason_codes)

    def test_03_commit_hash_chain(self) -> None:
        p = Position.initial()
        move = parse_uci_move(p, "e2e4")
        child, event = commit_move(p, move, sequence=1)
        self.assertEqual(event.pre_hash, state_sha256(p))
        self.assertEqual(event.post_hash, state_sha256(child))
        self.assertEqual(event.move_san, "e4")

    def test_04_replay_reconstructs_state(self) -> None:
        p = Position.initial()
        events = []
        current = p
        for sequence, uci in enumerate(("e2e4", "e7e5", "g1f3"), 1):
            current, event = commit_move(current, parse_uci_move(current, uci), sequence=sequence)
            events.append(event.to_dict())
        clone = replay(p, events)
        self.assertEqual(clone, current)

    def test_05_replay_detects_tamper(self) -> None:
        p = Position.initial()
        child, event = commit_move(p, parse_uci_move(p, "e2e4"), sequence=1)
        record = event.to_dict()
        record["post_hash"] = "0" * 64
        with self.assertRaises(ValueError):
            replay(p, [record])

    def test_06_rejected_commit_raises(self) -> None:
        from ugts_chess.move import Move
        with self.assertRaises(ValueError):
            commit_move(Position.initial(), Move(0, 16))


if __name__ == "__main__":
    unittest.main()
