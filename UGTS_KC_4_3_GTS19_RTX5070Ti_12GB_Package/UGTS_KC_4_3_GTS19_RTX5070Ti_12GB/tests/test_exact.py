from __future__ import annotations

import unittest

from ugts_go19.engine import apply_move, play_sequence
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
        result = ExactSolver(rules, node_budget=20_000).solve(State.initial(rules))
        self.assertEqual(result.value2, 1)
        self.assertGreater(result.stats.terminals, 0)
        self.assertGreater(result.stats.nodes, result.stats.terminals)
        self.assertLessEqual(result.stats.nodes, 20_000)

    def test_deterministic_rerun(self) -> None:
        rules = Rules(size=2, komi2=1, profile_id="fixture-2x2")
        first = ExactSolver(rules, node_budget=20_000).solve(State.initial(rules))
        second = ExactSolver(rules, node_budget=20_000).solve(State.initial(rules))
        self.assertEqual(first.value2, second.value2)
        self.assertEqual(first.principal_variation, second.principal_variation)

    def test_pass_first_ordering_can_be_disabled_without_changing_value(self) -> None:
        rules = Rules(
            size=2,
            komi2=1,
            passes_to_end=1,
            profile_id="pass-order-differential",
        )
        root = State.initial(rules)
        optimized = ExactSolver(rules, pass_first=True).solve(root)
        reference = ExactSolver(rules, pass_first=False).solve(root)
        self.assertEqual(optimized.value2, reference.value2)
        self.assertLess(optimized.stats.nodes, reference.stats.nodes)

    def test_completed_root_survives_pv_budget_stop(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="pv-budget")
        result = ExactSolver(rules, node_budget=3).solve(State.initial(rules))
        self.assertEqual(result.value2, -1)
        self.assertFalse(result.principal_variation_complete)

    def test_exact_solver_rejects_profiles_with_undefined_cycles(self) -> None:
        for superko in ("none", "simple_ko"):
            with self.subTest(superko=superko):
                rules = Rules(
                    size=2,
                    komi2=1,
                    superko=superko,
                    profile_id=f"cyclic-{superko}",
                )
                with self.assertRaisesRegex(ValueError, "finite superko"):
                    ExactSolver(rules).solve(State.initial(rules))

    def test_best_move_is_not_replaced_by_a_fail_soft_tie(self) -> None:
        rules = Rules(size=2, komi2=1, profile_id="best-move-bound")
        state = play_sequence(State.initial(rules), [0, 1], rules)
        result = ExactSolver(rules, node_budget=20_000).solve(state)
        self.assertEqual(result.value2, 7)
        self.assertEqual(result.best_move, 3)
        self.assertEqual(result.principal_variation[0], result.best_move)
        child = apply_move(state, result.best_move, rules)
        child_result = ExactSolver(rules, node_budget=20_000).solve(child)
        self.assertEqual(child_result.value2, result.value2)


if __name__ == "__main__":
    unittest.main()
