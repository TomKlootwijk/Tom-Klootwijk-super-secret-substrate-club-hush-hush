from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import ugts_chess.wdl_worklist as wdl_worklist_module
from ugts_chess.game_state import HistoryContext, automatic_status
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import canonical_json_bytes
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.rules import apply_move, legal_moves
from ugts_chess.wdl import BoundedWDLSolver
from ugts_chess.wdl_fact_journal import WDLFactJournal
from ugts_chess.wdl_worklist import (
    DeterministicWDLWorklist,
    WorklistLimits,
    WorklistStepStatus,
    WorklistStopReason,
    run_wdl_worklist,
)


CHECKMATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
CHECKMATE_FULLMOVE_2_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 2"
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
ONE_MOVE_LOSS_FEN = "8/8/8/8/8/8/8/k1KQ4 b - - 0 1"
MANY_75_MOVE_CHILDREN_FEN = "7k/8/8/8/8/8/8/KR6 w - - 149 1"


class WDLWorklistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dags: list[ProofDAG] = []
        self.journals: list[WDLFactJournal] = []
        self.dag = self.make_dag("main")

    def tearDown(self) -> None:
        for journal in reversed(self.journals):
            journal.close()
        for dag in reversed(self.dags):
            dag.close()
        self.temporary.cleanup()

    def make_dag(self, name: str) -> ProofDAG:
        dag = ProofDAG(
            self.root / f"{name}.sqlite3",
            self.root / f"{name}.frontier",
        )
        self.dags.append(dag)
        return dag

    def make_journal(
        self,
        dag: ProofDAG | None = None,
        name: str = "facts.v2",
    ) -> WDLFactJournal:
        actual_dag = self.dag if dag is None else dag
        journal = WDLFactJournal(self.root / name, actual_dag)
        self.journals.append(journal)
        return journal

    @staticmethod
    def append_root(
        dag: ProofDAG,
        fen: str,
        *,
        lineage: object = None,
    ):
        position = Position.from_fen(fen)
        return dag.append_root(
            position,
            HistoryContext.initial(position),
            lineage=lineage,
        )

    @staticmethod
    def append_child(
        dag: ProofDAG,
        parent,
        uci: str,
        *,
        lineage: object = None,
    ):
        move = next(move for move in legal_moves(parent.node.position) if move.uci() == uci)
        child_position = apply_move(parent.node.position, move)
        child_history = parent.node.history.push(child_position)
        return dag.append_move(
            child_position,
            child_history,
            parent_frontier_content_sha256=parent.edge.frontier_content_sha256,
            uci=uci,
            lineage=lineage,
        )

    @staticmethod
    def certificate(node, *, max_plies: int) -> bytes:
        result = BoundedWDLSolver(node_budget=200_000).solve(
            node.position,
            max_plies=max_plies,
            history=node.history,
        )
        if not result.root.exact:
            raise AssertionError("test fixture did not produce an exact certificate")
        return canonical_json_bytes(result.certificate_bundle())

    def build_three_hop_chain(self):
        """Build LOSS parent -> WIN child -> checkmated LOSS child."""

        loss_parent = self.append_root(self.dag, ONE_MOVE_LOSS_FEN)
        only_move = legal_moves(loss_parent.node.position)
        self.assertEqual(len(only_move), 1)
        win_child = self.append_child(self.dag, loss_parent, only_move[0].uci())

        solved = BoundedWDLSolver(node_budget=200_000).solve(
            win_child.node.position,
            max_plies=1,
            history=win_child.node.history,
        )
        self.assertTrue(solved.root.exact)
        self.assertEqual(solved.root.value, WDL.WIN)
        witness = next(
            child.move
            for child in solved.root.children
            if child.kind == "move" and child.child_value == WDL.LOSS
        )
        self.assertIsNotNone(witness)
        terminal = self.append_child(
            self.dag,
            win_child,
            witness,  # type: ignore[arg-type]
        )
        status = automatic_status(terminal.node.position, terminal.node.history)
        self.assertTrue(status.terminal)
        self.assertEqual(status.code, "checkmate")
        return loss_parent, win_child, terminal

    def test_01_terminal_win_loss_closure_is_deterministic_and_multi_hop(self) -> None:
        loss_parent, win_child, terminal = self.build_three_hop_chain()
        journal = self.make_journal()
        worklist = DeterministicWDLWorklist(self.dag, journal)

        report = worklist.run()

        self.assertEqual(report.stop_reason, WorklistStopReason.LOCAL_QUIESCENCE_NOT_CHESS_SOLVED)
        self.assertTrue(report.local_quiescence)
        self.assertFalse(report.chess_solved)
        self.assertEqual(report.attempts, 3)
        self.assertEqual(report.promotions, 3)
        self.assertEqual(report.open_attempts, 0)
        self.assertEqual(report.pending_count, 0)
        entries = tuple(journal.iter_entries())
        self.assertEqual(
            [entry.fact.node_sha256 for entry in entries],
            [
                terminal.node.node_sha256,
                win_child.node.node_sha256,
                loss_parent.node.node_sha256,
            ],
        )
        self.assertEqual(
            [entry.fact.claimed_wdl for entry in entries],
            [WDL.LOSS, WDL.WIN, WDL.LOSS],
        )
        self.assertEqual([entry.fact.proof_height for entry in entries], [0, 1, 2])
        self.assertTrue(all(node.wdl == WDL.UNKNOWN for node in self.dag.iter_nodes()))

    def test_02_interrupted_reopen_converges_byte_identically(self) -> None:
        self.build_three_hop_chain()
        uninterrupted_path = self.root / "uninterrupted.v2"
        interrupted_path = self.root / "interrupted.v2"

        uninterrupted = self.make_journal(name="uninterrupted.v2")
        full_report = DeterministicWDLWorklist(self.dag, uninterrupted).run()
        self.assertEqual(full_report.promotions, 3)
        uninterrupted.close()

        interrupted = self.make_journal(name="interrupted.v2")
        partial = DeterministicWDLWorklist(self.dag, interrupted).run(
            WorklistLimits(max_promotions=1)
        )
        self.assertEqual(partial.stop_reason, WorklistStopReason.PROMOTION_LIMIT)
        self.assertEqual(partial.promotions, 1)
        self.assertEqual(interrupted.audit().record_count, 1)
        retained_head = interrupted.head_snapshot()
        interrupted.close()

        reopened = WDLFactJournal(
            interrupted_path,
            self.dag,
            required_head=retained_head,
        )
        self.journals.append(reopened)
        resumed = DeterministicWDLWorklist(self.dag, reopened).run()
        self.assertEqual(resumed.promotions, 2)
        self.assertTrue(resumed.local_quiescence)
        reopened.close()

        self.assertEqual(interrupted_path.read_bytes(), uninterrupted_path.read_bytes())

    def test_03_duplicate_incoming_parent_occurrences_enqueue_parent_once(self) -> None:
        parent = self.append_root(
            self.dag,
            "k7/2K5/1Q6/8/8/8/8/8 w - - 0 1",
        )
        solved = BoundedWDLSolver(node_budget=200_000).solve(
            parent.node.position,
            max_plies=1,
            history=parent.node.history,
        )
        witness = next(child.move for child in solved.root.children if child.kind == "move")
        first = self.append_child(
            self.dag,
            parent,
            witness,  # type: ignore[arg-type]
            lineage={"copy": 1},
        )
        second = self.append_child(
            self.dag,
            parent,
            witness,  # type: ignore[arg-type]
            lineage={"copy": 2},
        )
        self.assertEqual(first.node.node_sha256, second.node.node_sha256)
        self.assertEqual(len(self.dag.incoming_edges(first.node.node_sha256)), 2)

        journal = self.make_journal()
        worklist = DeterministicWDLWorklist(self.dag, journal)
        self.assertEqual(worklist.rebuild(), 1)
        terminal_step = worklist.step()
        self.assertEqual(terminal_step.status, WorklistStepStatus.PROMOTED)
        self.assertEqual(
            terminal_step.enqueued_parent_node_sha256s,
            (parent.node.node_sha256,),
        )
        self.assertEqual(worklist.pending_count, 1)
        parent_step = worklist.step()
        self.assertEqual(parent_step.status, WorklistStepStatus.PROMOTED)
        self.assertEqual(parent_step.node_sha256, parent.node.node_sha256)
        self.assertEqual(worklist.pending_count, 0)

    def test_04_open_nodes_are_attempted_once_and_do_not_hot_loop(self) -> None:
        parent = self.append_root(self.dag, MANY_75_MOVE_CHILDREN_FEN)
        moves = sorted(legal_moves(parent.node.position), key=lambda move: move.uci())
        self.assertGreater(len(moves), 1)
        child = self.append_child(self.dag, parent, moves[0].uci())
        self.assertTrue(automatic_status(child.node.position, child.node.history).terminal)
        journal = self.make_journal()
        worklist = DeterministicWDLWorklist(self.dag, journal)

        first_run = worklist.run()
        self.assertTrue(first_run.local_quiescence)
        self.assertEqual(first_run.promotions, 1)
        self.assertEqual(first_run.open_attempts, 1)
        self.assertEqual(first_run.attempts, 2)
        self.assertEqual(first_run.pending_count, 0)
        self.assertIsNone(journal.get_fact(parent.node.node_sha256))

        second_run = worklist.run()
        self.assertTrue(second_run.local_quiescence)
        self.assertEqual(second_run.attempts, 0)
        self.assertEqual(second_run.steps, 0)
        self.assertEqual(second_run.pending_count, 0)

    def test_05_head_changes_rebuild_before_zero_limits_are_applied(self) -> None:
        loss_parent = self.append_root(self.dag, ONE_MOVE_LOSS_FEN)
        only_move = legal_moves(loss_parent.node.position)[0]
        win_child = self.append_child(self.dag, loss_parent, only_move.uci())

        fact_journal = self.make_journal(name="fact-change.v2")
        fact_worklist = DeterministicWDLWorklist(self.dag, fact_journal)
        self.assertEqual(fact_worklist.rebuild(), 0)
        generation = fact_worklist.generation
        fact_journal.append_seed_certificate(
            win_child.node.node_sha256,
            self.certificate(win_child.node, max_plies=1),
        )

        fact_report = fact_worklist.run(WorklistLimits(max_promotions=0))
        self.assertEqual(fact_report.stop_reason, WorklistStopReason.PROMOTION_LIMIT)
        self.assertEqual(fact_report.attempts, 0)
        self.assertEqual(fact_report.rebuilds, 1)
        self.assertEqual(fact_report.pending_count, 1)
        self.assertEqual(fact_worklist.generation, generation + 1)
        self.assertEqual(fact_report.initial_fact_head.record_count, 1)
        self.assertEqual(fact_report.final_fact_head.record_count, 1)

        dag_journal = self.make_journal(name="dag-change.v2")
        dag_worklist = DeterministicWDLWorklist(self.dag, dag_journal)
        self.assertEqual(dag_worklist.rebuild(), 0)
        dag_generation = dag_worklist.generation
        terminal = self.append_root(
            self.dag,
            CHECKMATE_FEN,
            lineage={"new": "terminal"},
        )

        dag_report = dag_worklist.run(WorklistLimits(max_attempts=0))
        self.assertEqual(dag_report.stop_reason, WorklistStopReason.ATTEMPT_LIMIT)
        self.assertEqual(dag_report.attempts, 0)
        self.assertEqual(dag_report.rebuilds, 1)
        self.assertEqual(dag_report.pending_count, 1)
        self.assertEqual(dag_worklist.generation, dag_generation + 1)
        self.assertEqual(
            dag_report.initial_dag_head.last_frontier_content_sha256,
            terminal.edge.frontier_content_sha256,
        )
        self.assertEqual(
            dag_worklist.dag_head.last_frontier_content_sha256,  # type: ignore[union-attr]
            terminal.edge.frontier_content_sha256,
        )

    def test_06_observer_exceptions_and_reentrancy_are_post_commit_only(self) -> None:
        mate = self.append_root(self.dag, CHECKMATE_FEN)
        draw = self.append_root(self.dag, STALEMATE_FEN)
        journal = self.make_journal()
        worklist = DeterministicWDLWorklist(self.dag, journal)
        observed_after_commit: list[tuple[str, WDL, int]] = []

        def reporting_failure(result) -> None:
            observed_after_commit.append(
                (
                    result.node_sha256,
                    journal.effective_wdl(result.node_sha256),
                    journal.audit().record_count,
                )
            )
            raise RuntimeError("observer failed")

        first = worklist.step(observer=reporting_failure)
        self.assertTrue(first.promoted)
        self.assertEqual(first.node_sha256, mate.node.node_sha256)
        self.assertEqual(first.observer_error, "RuntimeError: observer failed")
        self.assertEqual(
            observed_after_commit,
            [(mate.node.node_sha256, WDL.LOSS, 1)],
        )
        self.assertEqual(journal.effective_wdl(mate.node.node_sha256), WDL.LOSS)

        def reentrant(result) -> None:
            observed_after_commit.append(
                (
                    result.node_sha256,
                    journal.effective_wdl(result.node_sha256),
                    journal.audit().record_count,
                )
            )
            worklist.step()

        second = worklist.step(observer=reentrant)
        self.assertTrue(second.promoted)
        self.assertEqual(second.node_sha256, draw.node.node_sha256)
        self.assertIn("WorklistReentrancyError", second.observer_error)  # type: ignore[operator]
        self.assertEqual(
            observed_after_commit[-1],
            (draw.node.node_sha256, WDL.DRAW, 2),
        )
        self.assertEqual(journal.effective_wdl(draw.node.node_sha256), WDL.DRAW)
        self.assertEqual(journal.audit().record_count, 2)

        observed_empty = []
        empty = worklist.step(observer=observed_empty.append)
        self.assertEqual(empty.status, WorklistStepStatus.EMPTY)
        self.assertEqual(observed_empty, [empty])

        new_terminal = self.append_root(
            self.dag,
            CHECKMATE_FULLMOVE_2_FEN,
            lineage={"observer": "head-change"},
        )
        observed_rebuild = []
        head_change = worklist.step(observer=observed_rebuild.append)
        self.assertEqual(head_change.status, WorklistStepStatus.HEAD_CHANGE_REBUILT)
        self.assertEqual(observed_rebuild, [head_change])
        self.assertEqual(
            head_change.dag_head_after.last_frontier_content_sha256,
            new_terminal.edge.frontier_content_sha256,
        )

    def test_07_stable_empty_is_local_quiescence_never_chess_solved(self) -> None:
        journal = self.make_journal()
        report = run_wdl_worklist(self.dag, journal)

        self.assertEqual(report.stop_reason, WorklistStopReason.LOCAL_QUIESCENCE_NOT_CHESS_SOLVED)
        self.assertTrue(report.local_quiescence)
        self.assertFalse(report.chess_solved)
        self.assertEqual(report.attempts, 0)
        self.assertEqual(report.promotions, 0)
        self.assertEqual(report.steps, 0)
        self.assertEqual(report.pending_count, 0)
        self.assertIsNone(report.last_step)
        self.assertEqual(report.initial_dag_head, report.final_dag_head)
        self.assertEqual(report.initial_fact_head, report.final_fact_head)

    def test_08_full_frontier_manifest_commits_earlier_ordered_content(self) -> None:
        first_dag = self.make_dag("manifest-a")
        second_dag = self.make_dag("manifest-b")
        first_a = self.append_root(
            first_dag,
            CHECKMATE_FEN,
            lineage={"route": "a"},
        )
        first_b = self.append_root(
            second_dag,
            CHECKMATE_FEN,
            lineage={"route": "b"},
        )
        last_a = self.append_root(
            first_dag,
            STALEMATE_FEN,
            lineage={"shared": True},
        )
        last_b = self.append_root(
            second_dag,
            STALEMATE_FEN,
            lineage={"shared": True},
        )
        self.assertNotEqual(
            first_a.edge.frontier_content_sha256,
            first_b.edge.frontier_content_sha256,
        )
        self.assertEqual(
            last_a.edge.frontier_content_sha256,
            last_b.edge.frontier_content_sha256,
        )

        first_journal = self.make_journal(first_dag, "manifest-a.v2")
        second_journal = self.make_journal(second_dag, "manifest-b.v2")
        first_worklist = DeterministicWDLWorklist(first_dag, first_journal)
        second_worklist = DeterministicWDLWorklist(second_dag, second_journal)
        first_worklist.rebuild()
        second_worklist.rebuild()
        first_head = first_worklist.dag_head
        second_head = second_worklist.dag_head
        self.assertIsNotNone(first_head)
        self.assertIsNotNone(second_head)

        self.assertEqual(first_head.frontier_record_count, second_head.frontier_record_count)  # type: ignore[union-attr]
        self.assertEqual(first_head.sqlite_edge_count, second_head.sqlite_edge_count)  # type: ignore[union-attr]
        self.assertEqual(first_head.sqlite_node_count, second_head.sqlite_node_count)  # type: ignore[union-attr]
        self.assertEqual(first_head.frontier_size, second_head.frontier_size)  # type: ignore[union-attr]
        self.assertEqual(
            first_head.last_frontier_content_sha256,  # type: ignore[union-attr]
            second_head.last_frontier_content_sha256,  # type: ignore[union-attr]
        )
        self.assertNotEqual(
            first_head.frontier_manifest_sha256,  # type: ignore[union-attr]
            second_head.frontier_manifest_sha256,  # type: ignore[union-attr]
        )

    def test_09_invalid_limits_and_driver_types_fail_closed(self) -> None:
        invalid_limits = (
            {"max_attempts": -1},
            {"max_attempts": True},
            {"max_attempts": 1.0},
            {"max_promotions": -1},
            {"max_promotions": False},
            {"max_promotions": "1"},
            {"max_seconds": -0.01},
            {"max_seconds": True},
            {"max_seconds": float("nan")},
            {"max_seconds": float("inf")},
            {"max_seconds": 10**10000},
            {"max_seconds": "1"},
        )
        for kwargs in invalid_limits:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    WorklistLimits(**kwargs)  # type: ignore[arg-type]

        journal = self.make_journal()
        worklist = DeterministicWDLWorklist(self.dag, journal)
        with self.assertRaises(TypeError):
            worklist.run({})  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            run_wdl_worklist(self.dag, journal, object())  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            DeterministicWDLWorklist(self.dag, object())  # type: ignore[arg-type]

    def test_10_propagation_exception_cannot_drop_a_candidate(self) -> None:
        terminal = self.append_root(self.dag, CHECKMATE_FEN)
        journal = self.make_journal()
        worklist = DeterministicWDLWorklist(self.dag, journal)
        self.assertEqual(worklist.rebuild(), 1)
        original = wdl_worklist_module.propagate_wdl_fact_one_hop
        attempts = 0

        def fail_once(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("transient propagation failure")
            return original(*args, **kwargs)

        with mock.patch.object(
            wdl_worklist_module,
            "propagate_wdl_fact_one_hop",
            side_effect=fail_once,
        ):
            with self.assertRaisesRegex(RuntimeError, "transient propagation"):
                worklist.step()
            self.assertFalse(worklist.built)
            report = worklist.run()

        self.assertTrue(report.local_quiescence)
        self.assertEqual(report.promotions, 1)
        self.assertEqual(journal.effective_wdl(terminal.node.node_sha256), WDL.LOSS)

    def test_11_parent_scheduling_exception_forces_restart_reconstruction(self) -> None:
        loss_parent, win_child, terminal = self.build_three_hop_chain()
        journal = self.make_journal()
        worklist = DeterministicWDLWorklist(self.dag, journal)
        self.assertEqual(worklist.rebuild(), 1)
        original = worklist._enqueue_exact_parents
        scheduling_attempts = 0

        def fail_once(child_node_sha256: str):
            nonlocal scheduling_attempts
            scheduling_attempts += 1
            if scheduling_attempts == 1:
                raise RuntimeError("transient parent scheduling failure")
            return original(child_node_sha256)

        with mock.patch.object(
            worklist,
            "_enqueue_exact_parents",
            side_effect=fail_once,
        ):
            with self.assertRaisesRegex(RuntimeError, "parent scheduling"):
                worklist.step()

        self.assertEqual(journal.effective_wdl(terminal.node.node_sha256), WDL.LOSS)
        self.assertFalse(worklist.built)
        report = worklist.run()

        self.assertTrue(report.local_quiescence)
        self.assertEqual(report.promotions, 2)
        self.assertEqual(journal.effective_wdl(win_child.node.node_sha256), WDL.WIN)
        self.assertEqual(journal.effective_wdl(loss_parent.node.node_sha256), WDL.LOSS)


if __name__ == "__main__":
    unittest.main()
