from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ugts_chess.game_state import HistoryContext
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import canonical_json_bytes, repetition_key
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.rules import apply_move, legal_moves
from ugts_chess.wdl import BoundedWDLSolver
from ugts_chess.wdl_fact_journal import WDLFactJournal
from ugts_chess.wdl_fact_propagation import propagate_wdl_fact_one_hop


CHECKMATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 150 1"
MATE_IN_ONE_FEN = "k7/2K5/1Q6/8/8/8/8/8 w - - 0 1"
ONE_MOVE_LOSS_FEN = "8/8/8/8/8/8/8/k1KQ4 b - - {halfmove} 1"
MANY_75_MOVE_CHILDREN_FEN = "7k/8/8/8/8/8/8/KR6 w - - 149 1"


class WDLFactPropagationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.dag = ProofDAG(root / "proof.sqlite3", root / "proof.frontier")
        self.journal = WDLFactJournal(root / "verified-facts.v2", self.dag)

    def tearDown(self) -> None:
        self.journal.close()
        self.dag.close()
        self.temporary.cleanup()

    @staticmethod
    def certificate_bytes(
        position: Position,
        history: HistoryContext,
        *,
        max_plies: int,
    ) -> bytes:
        result = BoundedWDLSolver(node_budget=200_000).solve(
            position,
            max_plies=max_plies,
            history=history,
        )
        if not result.root.exact:
            raise AssertionError("test fixture did not produce an exact certificate")
        return canonical_json_bytes(result.certificate_bundle())

    def append_root(
        self,
        fen: str,
        *,
        history: HistoryContext | None = None,
        lineage: object = None,
    ):
        position = Position.from_fen(fen)
        actual_history = HistoryContext.initial(position) if history is None else history
        return self.dag.append_root(position, actual_history, lineage=lineage)

    def append_child(self, parent, uci: str, *, lineage: object = None):
        move = next(move for move in legal_moves(parent.node.position) if move.uci() == uci)
        child = apply_move(parent.node.position, move)
        history = parent.node.history.push(child)
        return self.dag.append_move(
            child,
            history,
            parent_frontier_content_sha256=parent.edge.frontier_content_sha256,
            uci=uci,
            lineage=lineage,
        )

    def seed(self, node, *, max_plies: int):
        certificate = self.certificate_bytes(
            node.position,
            node.history,
            max_plies=max_plies,
        )
        result = self.journal.append_seed_certificate(node.node_sha256, certificate)
        return result, certificate

    def test_01_terminal_derivation_is_compact_and_dag_remains_unknown(self) -> None:
        position = Position.from_fen(CHECKMATE_FEN)
        history = HistoryContext(((repetition_key(position), 5),))
        target = self.append_root(CHECKMATE_FEN, history=history)

        with mock.patch.object(
            self.journal,
            "iter_entries",
            wraps=self.journal.iter_entries,
        ) as snapshot:
            result = propagate_wdl_fact_one_hop(
                self.dag,
                self.journal,
                target.node.node_sha256,
            )
        self.assertEqual(snapshot.call_count, 1)
        self.assertTrue(result.promoted)
        self.assertEqual(result.value, WDL.LOSS)
        self.assertEqual(result.proof_height, 0)
        self.assertEqual(self.dag.get_node(target.node.node_sha256).wdl, WDL.UNKNOWN)

        entry = tuple(self.journal.iter_entries())[0]
        self.assertEqual(entry.fact.kind, "derivation")
        self.assertEqual(entry.fact.claimed_wdl, WDL.LOSS)
        self.assertEqual(entry.fact.evidence["derivation_code"], "checkmate")
        self.assertEqual(entry.fact.evidence["move_dependencies"], ())
        self.assertLess(entry.payload_length, 4096)

        duplicate = propagate_wdl_fact_one_hop(
            self.dag,
            self.journal,
            target.node.node_sha256,
        )
        self.assertFalse(duplicate.promoted)
        self.assertEqual(duplicate.status, "already_verified")
        self.assertEqual(duplicate.fact_content_sha256, result.fact_content_sha256)

    def test_02_win_uses_one_prior_fact_and_earliest_duplicate_edge(self) -> None:
        parent = self.append_root(MATE_IN_ONE_FEN)
        solved = BoundedWDLSolver().solve(
            parent.node.position,
            max_plies=1,
            history=parent.node.history,
        )
        witness = next(child.move for child in solved.root.children if child.kind == "move")
        self.assertIsNotNone(witness)
        first = self.append_child(parent, witness, lineage={"copy": 1})  # type: ignore[arg-type]
        second = self.append_child(parent, witness, lineage={"copy": 2})  # type: ignore[arg-type]
        self.assertEqual(first.node.node_sha256, second.node.node_sha256)
        self.seed(first.node, max_plies=0)

        result = propagate_wdl_fact_one_hop(
            self.dag,
            self.journal,
            parent.node.node_sha256,
        )

        self.assertEqual(result.value, WDL.WIN)
        self.assertEqual(result.witness_move, witness)
        self.assertEqual(result.used_moves, (witness,))
        self.assertGreater(len(result.legal_moves), 1)
        fact = self.journal.get_fact(parent.node.node_sha256)
        self.assertIsNotNone(fact)
        dependencies = fact.evidence["move_dependencies"]  # type: ignore[union-attr]
        self.assertEqual(len(dependencies), 1)
        self.assertEqual(
            dependencies[0]["dag_edge_record_index"],
            first.edge.frontier_record_index,
        )
        self.assertEqual(
            dependencies[0]["dag_edge_content_sha256"],
            first.edge.frontier_content_sha256,
        )

    def test_03_complete_loss_and_claim_draws_use_all_uci_actions(self) -> None:
        expected = {0: WDL.LOSS, 99: WDL.DRAW, 100: WDL.DRAW}
        for halfmove in (0, 99, 100):
            with self.subTest(halfmove=halfmove):
                parent = self.append_root(
                    ONE_MOVE_LOSS_FEN.format(halfmove=halfmove),
                    lineage={"halfmove": halfmove},
                )
                move = legal_moves(parent.node.position)[0]
                child = self.append_child(parent, move.uci())
                self.seed(child.node, max_plies=1)

                result = propagate_wdl_fact_one_hop(
                    self.dag,
                    self.journal,
                    parent.node.node_sha256,
                )

                self.assertEqual(result.value, expected[halfmove])
                self.assertEqual(result.used_moves, (move.uci(),))
                fact = self.journal.get_fact(parent.node.node_sha256)
                self.assertIsNotNone(fact)
                self.assertEqual(
                    fact.evidence["derivation_code"],  # type: ignore[union-attr]
                    "all_legal_moves_lose"
                    if halfmove == 0
                    else "draw_action_and_no_winning_move",
                )

    def test_04_many_child_proofs_are_referenced_not_copied(self) -> None:
        parent = self.append_root(MANY_75_MOVE_CHILDREN_FEN)
        seed_certificate_bytes = 0
        for move in sorted(
            legal_moves(parent.node.position), key=lambda candidate: candidate.uci()
        ):
            child = self.append_child(parent, move.uci())
            _, certificate = self.seed(child.node, max_plies=0)
            seed_certificate_bytes += len(certificate)

        result = propagate_wdl_fact_one_hop(
            self.dag,
            self.journal,
            parent.node.node_sha256,
        )

        self.assertEqual(result.value, WDL.DRAW)
        self.assertEqual(result.proof_height, 1)
        entry = tuple(self.journal.iter_entries())[-1]
        self.assertEqual(len(entry.fact.evidence["move_dependencies"]), len(result.legal_moves))
        self.assertLess(entry.payload_length, seed_certificate_bytes)
        self.assertNotIn("certificate_base64", json.loads(entry.fact.payload_bytes())["evidence"])

    def test_05_missing_edges_and_exact_facts_remain_unknown(self) -> None:
        parent = self.append_root(ONE_MOVE_LOSS_FEN.format(halfmove=0))
        move = legal_moves(parent.node.position)[0]

        missing_edge = propagate_wdl_fact_one_hop(
            self.dag,
            self.journal,
            parent.node.node_sha256,
        )
        self.assertEqual(missing_edge.reason, "missing_frontier_moves")
        self.assertEqual(missing_edge.missing_frontier_moves, (move.uci(),))

        actual = self.append_child(parent, move.uci())
        twin_fields = actual.node.fen.split()
        twin_fields[-1] = str(int(twin_fields[-1]) + 1)
        twin_position = Position.from_fen(" ".join(twin_fields))
        twin = self.dag.append_root(twin_position, actual.node.history)
        self.seed(twin.node, max_plies=1)

        missing_fact = propagate_wdl_fact_one_hop(
            self.dag,
            self.journal,
            parent.node.node_sha256,
        )
        self.assertEqual(missing_fact.value, WDL.UNKNOWN)
        self.assertEqual(missing_fact.reason, "missing_verified_children")
        self.assertEqual(missing_fact.missing_fact_moves, (move.uci(),))
        self.assertIsNone(self.journal.get_fact(parent.node.node_sha256))

    def test_06_ambiguous_replay_blocks_even_a_winning_witness(self) -> None:
        parent = self.append_root(MATE_IN_ONE_FEN)
        solved = BoundedWDLSolver().solve(
            parent.node.position,
            max_plies=1,
            history=parent.node.history,
        )
        witness = next(child.move for child in solved.root.children if child.kind == "move")
        child = self.append_child(parent, witness)  # type: ignore[arg-type]
        self.seed(child.node, max_plies=0)
        twin_fields = child.node.fen.split()
        twin_fields[-1] = str(int(twin_fields[-1]) + 1)
        twin = self.dag.append_root(Position.from_fen(" ".join(twin_fields)), child.node.history)
        valid_edge = self.dag.outgoing_edges(parent.node.node_sha256)[0]
        forged_edge = replace(valid_edge, child_node_sha256=twin.node.node_sha256)

        with mock.patch.object(
            self.dag,
            "outgoing_edges",
            return_value=(valid_edge, forged_edge),
        ):
            result = propagate_wdl_fact_one_hop(
                self.dag,
                self.journal,
                parent.node.node_sha256,
            )

        self.assertEqual(result.value, WDL.UNKNOWN)
        self.assertEqual(result.reason, "ambiguous_frontier")
        self.assertEqual(result.ambiguous_moves, (witness,))

    def test_07_current_and_intended_threefold_claims_prevent_false_loss(self) -> None:
        base_position = Position.from_fen(ONE_MOVE_LOSS_FEN.format(halfmove=0))
        only_move = legal_moves(base_position)[0]
        child_position = apply_move(base_position, only_move)
        histories = {
            "current": HistoryContext(((repetition_key(base_position), 3),)),
            "intended": HistoryContext(
                tuple(
                    sorted(
                        (
                            (repetition_key(base_position), 1),
                            (repetition_key(child_position), 2),
                        )
                    )
                )
            ),
        }

        for label, history in histories.items():
            with self.subTest(claim=label):
                parent = self.append_root(
                    ONE_MOVE_LOSS_FEN.format(halfmove=0),
                    history=history,
                    lineage={"threefold": label},
                )
                child = self.append_child(parent, only_move.uci())
                self.seed(child.node, max_plies=1)

                result = propagate_wdl_fact_one_hop(
                    self.dag,
                    self.journal,
                    parent.node.node_sha256,
                )

                self.assertEqual(result.value, WDL.DRAW)
                fact = self.journal.get_fact(parent.node.node_sha256)
                self.assertIsNotNone(fact)
                self.assertEqual(
                    fact.evidence["derivation_code"],  # type: ignore[union-attr]
                    "draw_action_and_no_winning_move",
                )


if __name__ == "__main__":
    unittest.main()
