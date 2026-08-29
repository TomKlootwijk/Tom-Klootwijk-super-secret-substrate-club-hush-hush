from __future__ import annotations

import unittest

from ugts_go19.engine import apply_move
from ugts_go19.frontier import canonical_frontier
from ugts_go19.pns import ProofNumberSearch
from ugts_go19.rules import Rules
from ugts_go19.state import State
from ugts_go19.constants import PASS


class FrontierAndPNSTests(unittest.TestCase):
    def test_empty_19_opening_has_56_d4_classes_including_pass(self) -> None:
        rules = Rules.canonical_19x19()
        states, summary = canonical_frontier(rules, depth=1)
        self.assertEqual(summary.canonical_states, 56)
        self.assertEqual(len(states), 56)

    def test_terminal_threshold_is_proven_or_disproven(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="pns-terminal")
        state = State.initial(rules)
        state = apply_move(state, PASS, rules)
        state = apply_move(state, PASS, rules)
        result = ProofNumberSearch(rules, threshold2=1, node_budget=1).run(state)
        self.assertEqual(result.status, "DISPROVEN")

    def test_bounded_19_attempt_has_honest_status(self) -> None:
        rules = Rules.canonical_19x19()
        result = ProofNumberSearch(rules, threshold2=1, node_budget=2).run()
        self.assertIn(result.status, {"PROVEN", "DISPROVEN", "UNKNOWN"})
        if result.status == "UNKNOWN":
            self.assertGreater(result.proof_number, 0)
            self.assertGreater(result.disproof_number, 0)


if __name__ == "__main__":
    unittest.main()
