from __future__ import annotations

import unittest

from ugts_go19.exact import ExactSolver
from ugts_go19.rules import Rules
from ugts_go19.state import State


class ExactSolverTests(unittest.TestCase):
    def test_empty_1x1_with_half_point_komi_is_white_win(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="fixture-1x1")
        result = ExactSolver(rules, node_budget=20_000).solve(State.initial(rules))
        self.assertEqual(result.value2, -1)

    def test_empty_2x2_fixture_matches_kc42(self) -> None:
        rules = Rules(size=2, komi2=1, profile_id="fixture-2x2")
        result = ExactSolver(rules, node_budget=2_000_000).solve(State.initial(rules))
        self.assertEqual(result.value2, 1)
        self.assertGreater(result.stats.terminals, 0)
        self.assertGreater(result.stats.nodes, result.stats.terminals)

    def test_deterministic_rerun(self) -> None:
        rules = Rules(size=2, komi2=1, profile_id="fixture-2x2")
        first = ExactSolver(rules, node_budget=2_000_000).solve(State.initial(rules))
        second = ExactSolver(rules, node_budget=2_000_000).solve(State.initial(rules))
        self.assertEqual(first.value2, second.value2)
        self.assertEqual(first.principal_variation, second.principal_variation)


if __name__ == "__main__":
    unittest.main()
