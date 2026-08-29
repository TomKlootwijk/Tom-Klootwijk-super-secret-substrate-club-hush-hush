from __future__ import annotations

import unittest

from ugts_go19.engine import apply_move
from ugts_go19.frontier import canonical_frontier
from ugts_go19.pns import INF, PNSNode, ProofNumberSearch, _sat_add
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

    def test_frontier_stops_at_terminal_states(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="frontier-terminal")
        states, summary = canonical_frontier(rules, depth=3)
        self.assertEqual(states, [])
        self.assertEqual(summary.depth, 3)

    def test_pns_rejects_profiles_with_undefined_cycles(self) -> None:
        rules = Rules(
            size=2,
            komi2=1,
            superko="simple_ko",
            profile_id="pns-cyclic-simple-ko",
        )
        with self.assertRaisesRegex(ValueError, "finite superko"):
            ProofNumberSearch(rules, threshold2=1, node_budget=10)

    def test_bounded_19_attempt_has_honest_status(self) -> None:
        rules = Rules.canonical_19x19()
        result = ProofNumberSearch(rules, threshold2=1, node_budget=2).run()
        self.assertIn(result.status, {"PROVEN", "DISPROVEN", "UNKNOWN"})
        if result.status == "UNKNOWN":
            self.assertGreater(result.proof_number, 0)
            self.assertGreater(result.disproof_number, 0)

    def test_empty_2x2_thresholds_match_exact_value(self) -> None:
        rules = Rules(size=2, komi2=1, profile_id="pns-2x2")
        proven = ProofNumberSearch(rules, threshold2=1, node_budget=1_000).run()
        disproven = ProofNumberSearch(rules, threshold2=3, node_budget=1_000).run()
        self.assertEqual(proven.status, "PROVEN")
        self.assertEqual(proven.proof_number, 0)
        self.assertEqual(disproven.status, "DISPROVEN")
        self.assertEqual(disproven.disproof_number, 0)

    def test_pns_instance_reuse_resets_search_counters(self) -> None:
        rules = Rules(size=2, komi2=1, profile_id="pns-reuse")
        search = ProofNumberSearch(rules, threshold2=1, node_budget=1_000)
        first = search.run()
        second = search.run()
        self.assertEqual(first.status, second.status)
        self.assertEqual(first.expanded_nodes, second.expanded_nodes)
        self.assertEqual(first.generated_nodes, second.generated_nodes)
        self.assertEqual(first.max_ply, second.max_ply)

    def test_most_proving_tie_break_distinguishes_pass_from_point_zero(self) -> None:
        rules = Rules(size=1, komi2=1, profile_id="pns-move-tie")
        state = State.initial(rules)
        point_zero = PNSNode(state=state, move=0)
        passed = PNSNode(state=state, move=PASS)
        root = PNSNode(
            state=state,
            children=[point_zero, passed],
            expanded=True,
            proof=1,
            disproof=1,
        )
        selected = ProofNumberSearch(
            rules, threshold2=1, node_budget=1
        )._select_most_proving(root)
        self.assertIs(selected, passed)

    def test_proof_arithmetic_is_declared_saturating_uint64(self) -> None:
        self.assertEqual(INF, (1 << 64) - 1)
        self.assertEqual(_sat_add([INF - 1, 1]), INF)
        self.assertEqual(_sat_add([INF - 1, 2]), INF)
        rules = Rules(size=1, komi2=1, profile_id="pns-arithmetic")
        payload = ProofNumberSearch(rules, threshold2=1, node_budget=1).run().as_dict()
        self.assertEqual(
            payload["proof_arithmetic"],
            {
                "bits": 64,
                "endianness": "little",
                "infinity": "18446744073709551615",
                "kind": "saturating_uint64",
            },
        )


if __name__ == "__main__":
    unittest.main()
