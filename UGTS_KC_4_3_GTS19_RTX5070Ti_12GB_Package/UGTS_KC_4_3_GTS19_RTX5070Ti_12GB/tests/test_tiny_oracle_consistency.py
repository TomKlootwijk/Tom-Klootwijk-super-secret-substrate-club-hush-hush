from __future__ import annotations

import unittest
from collections import deque

from ugts_go19.constants import BLACK, PASS
from ugts_go19.digests import state_digest
from ugts_go19.engine import apply_move, ordered_children
from ugts_go19.exact import ExactSolver
from ugts_go19.pns import INF, ProofNumberSearch
from ugts_go19.rules import Rules
from ugts_go19.score import area_score2
from ugts_go19.state import State


CORPUS_DEPTH_CAP = 3
CORPUS_STATE_CAP = 28
EXACT_NODE_BUDGET = 50_000
PNS_NODE_BUDGET = 10_000


def _bounded_breadth_first_corpus(rules: Rules) -> list[State]:
    """Return the first deterministic full-history states in a bounded BFS.

    The exact 2x2 PSK history space is already large.  This acceptance corpus is
    deliberately capped at depth three and 28 collision-free states so it checks
    varied point/pass histories, a terminal, and the former best-move regression
    while staying fast enough to run on every acceptance pass.
    """

    root = State.initial(rules)
    pending: deque[tuple[State, int]] = deque(((root, 0),))
    seen: set[tuple] = set()
    corpus: list[State] = []

    while pending and len(corpus) < CORPUS_STATE_CAP:
        state, depth = pending.popleft()
        key = state.exact_key()
        if key in seen:
            continue
        seen.add(key)
        corpus.append(state)
        if depth >= CORPUS_DEPTH_CAP or state.is_terminal(rules):
            continue
        for _move, child, _priority in ordered_children(state, rules):
            pending.append((child, depth + 1))

    return corpus


class TinyOracleConsistencyTests(unittest.TestCase):
    def test_bounded_depth3_first28_reachable_2x2_psk_states_are_consistent(
        self,
    ) -> None:
        rules = Rules(
            size=2,
            komi2=1,
            superko="positional_superko",
            allow_suicide=False,
            scoring="area",
            passes_to_end=2,
            profile_id="oracle-consistency-2x2-psk",
        )
        corpus = _bounded_breadth_first_corpus(rules)

        self.assertEqual(len(corpus), CORPUS_STATE_CAP)
        self.assertEqual(max(state.ply for state in corpus), CORPUS_DEPTH_CAP)
        self.assertTrue(any(state.is_terminal(rules) for state in corpus))
        # Minimal reachable regression for fail-soft bounds corrupting best_move.
        self.assertTrue(
            any(
                state.board == bytes((1, 2, 0, 0))
                and state.to_play == BLACK
                and state.ply == 2
                for state in corpus
            )
        )

        value_cache: dict[tuple, int] = {}

        def exact_value(state: State) -> int:
            key = state.exact_key()
            if key not in value_cache:
                value_cache[key] = ExactSolver(
                    rules, node_budget=EXACT_NODE_BUDGET
                ).solve(state).value2
            return value_cache[key]

        for index, state in enumerate(corpus):
            label = f"{index}:{state_digest(state, rules)[:12]}:ply{state.ply}"
            with self.subTest(state=label):
                exact = ExactSolver(
                    rules,
                    node_budget=EXACT_NODE_BUDGET,
                    use_symmetry=False,
                ).solve(state)
                symmetric = ExactSolver(
                    rules,
                    node_budget=EXACT_NODE_BUDGET,
                    use_symmetry=True,
                ).solve(state)
                value_cache[state.exact_key()] = exact.value2

                self.assertEqual(
                    (
                        symmetric.value2,
                        symmetric.best_move,
                        symmetric.principal_variation,
                        symmetric.principal_variation_complete,
                    ),
                    (
                        exact.value2,
                        exact.best_move,
                        exact.principal_variation,
                        exact.principal_variation_complete,
                    ),
                )

                if state.is_terminal(rules):
                    self.assertEqual(exact.best_move, PASS)
                else:
                    move_values = {
                        move: exact_value(child)
                        for move, child, _priority in ordered_children(state, rules)
                    }
                    expected = (
                        max(move_values.values())
                        if state.to_play == BLACK
                        else min(move_values.values())
                    )
                    self.assertEqual(exact.value2, expected)
                    self.assertIn(exact.best_move, move_values)
                    self.assertEqual(move_values[exact.best_move], expected)
                    if exact.principal_variation:
                        self.assertEqual(
                            exact.principal_variation[0], exact.best_move
                        )

                pv_state = state
                for move in exact.principal_variation:
                    pv_state = apply_move(pv_state, move, rules)
                if exact.principal_variation_complete:
                    self.assertTrue(pv_state.is_terminal(rules))
                    self.assertEqual(area_score2(pv_state.board, rules), exact.value2)

                at_value = ProofNumberSearch(
                    rules,
                    threshold2=exact.value2,
                    node_budget=PNS_NODE_BUDGET,
                ).run(state)
                above_value = ProofNumberSearch(
                    rules,
                    threshold2=exact.value2 + 2,
                    node_budget=PNS_NODE_BUDGET,
                ).run(state)
                self.assertEqual(at_value.status, "PROVEN")
                self.assertEqual(at_value.proof_number, 0)
                self.assertEqual(at_value.disproof_number, INF)
                self.assertEqual(above_value.status, "DISPROVEN")
                self.assertEqual(above_value.proof_number, INF)
                self.assertEqual(above_value.disproof_number, 0)


if __name__ == "__main__":
    unittest.main()
