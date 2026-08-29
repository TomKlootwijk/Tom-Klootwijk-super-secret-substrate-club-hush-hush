from __future__ import annotations

from collections import Counter
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ugts_chess.game_state import (
    HistoryContext,
    automatic_status,
    current_claim_actions,
)
from ugts_chess.hashing import canonical_json_bytes, repetition_key
from ugts_chess.position import Position
from ugts_chess.proof_dag import DAGMoveAppendRequest, ProofDAG
from ugts_chess.rules import apply_move, legal_moves
from ugts_chess.wdl import BoundedWDLSolver
from ugts_chess.wdl_expansion import (
    EXPANSION_SCHEMA,
    ExpansionConcurrentMutationError,
    ExpansionLimits,
    ExpansionStopReason,
    expand_proof_dag,
)
from ugts_chess.wdl_fact_journal import WDLFactJournal


ONE_MOVE_TO_DEAD_POSITION_FEN = "7K/8/8/8/8/8/R1B5/k7 b - - 0 1"
CHECKMATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
SEVENTY_FIVE_MOVE_FEN = "7k/8/8/8/8/8/8/KR6 w - - 150 1"


class WDLExpansionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dags: list[ProofDAG] = []

    def tearDown(self) -> None:
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

    @staticmethod
    def append_root(
        dag: ProofDAG,
        position: Position,
        history: HistoryContext | None = None,
        *,
        lineage: object = None,
    ):
        return dag.append_root(
            position,
            HistoryContext.initial(position) if history is None else history,
            lineage=lineage,
        )

    @staticmethod
    def append_move(dag: ProofDAG, parent, uci: str, *, lineage: object = None):
        move = next(move for move in legal_moves(parent.node.position) if move.uci() == uci)
        child = apply_move(parent.node.position, move)
        history = parent.node.history.push(child)
        return dag.append_move(
            child,
            history,
            parent_frontier_content_sha256=parent.edge.frontier_content_sha256,
            uci=uci,
            lineage=lineage,
        )

    @staticmethod
    def certificate(node, *, max_plies: int = 0) -> bytes:
        solved = BoundedWDLSolver(node_budget=200_000).solve(
            node.position,
            max_plies=max_plies,
            history=node.history,
        )
        if not solved.root.exact:
            raise AssertionError("test fixture did not produce an exact WDL certificate")
        return canonical_json_bytes(solved.certificate_bundle())

    def test_01_complete_small_closure_is_restart_byte_stable_and_not_solved(self) -> None:
        dag = self.make_dag("stable")
        position = Position.from_fen(ONE_MOVE_TO_DEAD_POSITION_FEN)
        root = self.append_root(dag, position, lineage={"fixture": "root"})
        self.assertEqual([move.uci() for move in legal_moves(position)], ["a1a2"])

        report = expand_proof_dag(dag)
        self.assertEqual(
            report.stop_reason,
            ExpansionStopReason.LOCAL_MATERIALIZED_EDGE_CLOSURE_NOT_CHESS_SOLVED,
        )
        self.assertTrue(report.local_materialized_edge_closure)
        self.assertTrue(report.all_materialized_nonterminal_parents_complete)
        self.assertFalse(report.chess_solved)
        self.assertEqual(report.parents_attempted, 1)
        self.assertEqual(report.parents_completed, 1)
        self.assertEqual(report.edges_appended, 1)
        self.assertEqual(report.dag_head_before.frontier_record_count, 1)
        self.assertEqual(report.dag_head_after.frontier_record_count, 2)
        self.assertNotEqual(
            report.dag_head_before.frontier_manifest_sha256,
            report.dag_head_after.frontier_manifest_sha256,
        )
        parent_result = report.parent_results[0]
        self.assertEqual(parent_result.node_sha256, root.node.node_sha256)
        self.assertEqual(parent_result.appended_moves, ("a1a2",))
        self.assertEqual(parent_result.remaining_moves, ())
        self.assertTrue(parent_result.complete_after)

        outgoing = dag.outgoing_edges(root.node.node_sha256)
        self.assertEqual(len(outgoing), 1)
        child = dag.get_node(outgoing[0].child_node_sha256)
        self.assertIsNotNone(child)
        self.assertEqual(automatic_status(child.position, child.history).code, "dead_position")  # type: ignore[union-attr]
        self.assertEqual(
            outgoing[0].lineage,
            {
                "kind": "deterministic_wdl_expansion",
                "schema": EXPANSION_SCHEMA,
                "parent_node_sha256": root.node.node_sha256,
                "uci": "a1a2",
            },
        )

        bytes_after_first = dag.frontier_path.read_bytes()
        restarted = expand_proof_dag(dag)
        self.assertEqual(restarted.edges_appended, 0)
        self.assertEqual(restarted.parents_attempted, 0)
        self.assertEqual(restarted.dag_head_before, restarted.dag_head_after)
        self.assertEqual(dag.frontier_path.read_bytes(), bytes_after_first)

    def test_02_all_automatic_terminals_are_skipped_without_edges(self) -> None:
        dag = self.make_dag("terminals")
        checkmate = self.append_root(dag, Position.from_fen(CHECKMATE_FEN))
        automatic_draw = self.append_root(
            dag,
            Position.from_fen(SEVENTY_FIVE_MOVE_FEN),
        )
        repeated_position = Position.initial()
        fivefold_draw = self.append_root(
            dag,
            repeated_position,
            HistoryContext.from_keys((repetition_key(repeated_position),) * 5),
        )
        size_before = dag.frontier_path.stat().st_size

        report = expand_proof_dag(dag)

        self.assertTrue(report.local_materialized_edge_closure)
        self.assertEqual(report.parents_attempted, 0)
        self.assertEqual(report.edges_appended, 0)
        self.assertEqual(
            report.terminal_node_sha256s,
            (
                checkmate.node.node_sha256,
                automatic_draw.node.node_sha256,
                fivefold_draw.node.node_sha256,
            ),
        )
        self.assertEqual(report.incomplete_parent_node_sha256s, ())
        self.assertEqual(dag.frontier_path.stat().st_size, size_before)
        self.assertEqual(dag.outgoing_edges(checkmate.node.node_sha256), ())
        self.assertEqual(dag.outgoing_edges(automatic_draw.node.node_sha256), ())
        self.assertEqual(dag.outgoing_edges(fivefold_draw.node.node_sha256), ())

    def test_03_partial_resume_matches_uninterrupted_frontier_bytes(self) -> None:
        position = Position.initial()
        legal_uci = tuple(move.uci() for move in legal_moves(position))
        interrupted_db = self.root / "interrupted.sqlite3"
        interrupted_frontier = self.root / "interrupted.frontier"

        with ProofDAG(interrupted_db, interrupted_frontier) as dag:
            root = self.append_root(dag, position, lineage={"fixture": "root"})
            first = expand_proof_dag(dag, ExpansionLimits(max_edges=3))
            self.assertEqual(first.stop_reason, ExpansionStopReason.EDGE_LIMIT)
            self.assertEqual(first.parent_results[0].appended_moves, legal_uci[:3])
            self.assertEqual(first.parent_results[0].remaining_moves, legal_uci[3:])
            self.assertFalse(first.parent_results[0].complete_after)
            self.assertIn(root.node.node_sha256, first.incomplete_parent_node_sha256s)

        with ProofDAG(interrupted_db, interrupted_frontier) as reopened:
            resumed = expand_proof_dag(
                reopened,
                ExpansionLimits(max_parents=1, max_edges=len(legal_uci) - 3),
            )
            self.assertEqual(resumed.stop_reason, ExpansionStopReason.PARENT_LIMIT)
            self.assertEqual(resumed.parent_results[0].existing_moves_before, legal_uci[:3])
            self.assertEqual(resumed.parent_results[0].appended_moves, legal_uci[3:])
            self.assertTrue(resumed.parent_results[0].complete_after)
            resumed_bytes = interrupted_frontier.read_bytes()

        uninterrupted_db = self.root / "uninterrupted.sqlite3"
        uninterrupted_frontier = self.root / "uninterrupted.frontier"
        with ProofDAG(uninterrupted_db, uninterrupted_frontier) as dag:
            uninterrupted_root = self.append_root(
                dag,
                position,
                lineage={"fixture": "root"},
            )
            uninterrupted = expand_proof_dag(
                dag,
                ExpansionLimits(max_parents=1),
            )
            self.assertEqual(uninterrupted.stop_reason, ExpansionStopReason.PARENT_LIMIT)
            self.assertEqual(uninterrupted.parent_results[0].appended_moves, legal_uci)
            self.assertEqual(
                tuple(edge.action["uci"] for edge in dag.outgoing_edges(uninterrupted_root.node.node_sha256)),
                legal_uci,
            )
            uninterrupted_bytes = uninterrupted_frontier.read_bytes()

        self.assertEqual(resumed_bytes, uninterrupted_bytes)

    def test_04_priority_and_children_preserve_history_and_fullmove_twins(self) -> None:
        dag = self.make_dag("twins")
        first_position = Position.from_fen(ONE_MOVE_TO_DEAD_POSITION_FEN)
        repeated_history = HistoryContext(
            ((repetition_key(first_position), 2),)
        )
        later_position = Position.from_fen(
            ONE_MOVE_TO_DEAD_POSITION_FEN.rsplit(" ", 1)[0] + " 2"
        )
        first = self.append_root(dag, first_position)
        repeated = self.append_root(dag, first_position, repeated_history)
        later = self.append_root(dag, later_position)
        self.assertEqual(first.node.position, repeated.node.position)
        self.assertNotEqual(first.node.history, repeated.node.history)
        self.assertNotEqual(first.node.node_sha256, repeated.node.node_sha256)
        self.assertNotEqual(first.node.node_sha256, later.node.node_sha256)

        report = expand_proof_dag(dag, ExpansionLimits(max_parents=3))

        self.assertTrue(report.local_materialized_edge_closure)
        self.assertEqual(report.edges_appended, 3)
        self.assertEqual(
            tuple(result.node_sha256 for result in report.parent_results),
            (
                first.node.node_sha256,
                repeated.node.node_sha256,
                later.node.node_sha256,
            ),
        )
        children = []
        for parent in (first, repeated, later):
            outgoing = dag.outgoing_edges(parent.node.node_sha256)
            self.assertEqual(len(outgoing), 1)
            children.append(dag.get_node(outgoing[0].child_node_sha256))
        self.assertTrue(all(child is not None for child in children))
        self.assertEqual(len({child.node_sha256 for child in children}), 3)  # type: ignore[union-attr]
        self.assertEqual(children[0].position.to_fen(), children[1].position.to_fen())  # type: ignore[union-attr]
        self.assertNotEqual(children[0].history, children[1].history)  # type: ignore[union-attr]
        self.assertNotEqual(children[0].position.to_fen(), children[2].position.to_fen())  # type: ignore[union-attr]

    def test_05_duplicate_equivalent_occurrences_do_not_duplicate_work(self) -> None:
        dag = self.make_dag("duplicates")
        position = Position.initial()
        first_root = self.append_root(dag, position, lineage="first")
        second_root = self.append_root(dag, position, lineage="second")
        self.assertEqual(first_root.node.node_sha256, second_root.node.node_sha256)
        self.append_move(dag, first_root, "a2a3", lineage="first-edge")
        self.append_move(dag, second_root, "a2a3", lineage="duplicate-edge")

        report = expand_proof_dag(dag, ExpansionLimits(max_edges=1))

        self.assertEqual(report.stop_reason, ExpansionStopReason.EDGE_LIMIT)
        result = report.parent_results[0]
        self.assertEqual(result.parent_frontier_content_sha256, first_root.edge.frontier_content_sha256)
        self.assertEqual(result.existing_moves_before, ("a2a3",))
        self.assertEqual(result.duplicate_existing_occurrences, 1)
        self.assertEqual(result.appended_moves, ("a2a4",))
        counts = Counter(
            edge.action["uci"]
            for edge in dag.outgoing_edges(first_root.node.node_sha256)
        )
        self.assertEqual(counts["a2a3"], 2)
        self.assertEqual(counts["a2a4"], 1)

    def test_06_zero_limits_are_cooperative_and_leave_incompleteness_explicit(self) -> None:
        for name, limits, reason in (
            ("parents", ExpansionLimits(max_parents=0), ExpansionStopReason.PARENT_LIMIT),
            ("edges", ExpansionLimits(max_edges=0), ExpansionStopReason.EDGE_LIMIT),
            ("time", ExpansionLimits(max_seconds=0), ExpansionStopReason.TIME_LIMIT),
        ):
            with self.subTest(limit=name):
                dag = self.make_dag(name)
                root = self.append_root(dag, Position.initial())
                before = dag.frontier_path.read_bytes()
                report = expand_proof_dag(dag, limits)
                self.assertEqual(report.stop_reason, reason)
                self.assertEqual(report.parents_attempted, 0)
                self.assertEqual(report.edges_appended, 0)
                self.assertEqual(report.dag_head_before, report.dag_head_after)
                self.assertEqual(
                    report.incomplete_parent_node_sha256s,
                    (root.node.node_sha256,),
                )
                self.assertFalse(report.all_materialized_nonterminal_parents_complete)
                self.assertFalse(report.chess_solved)
                self.assertEqual(dag.frontier_path.read_bytes(), before)

    def test_07_unexpected_interleaved_append_fails_closed_then_resumes(self) -> None:
        dag = self.make_dag("movement")
        root = self.append_root(dag, Position.initial())
        ordered_moves = legal_moves(root.node.position)
        original_append_move = dag.append_move
        original_append_batch = dag.append_moves_batch
        injected = False

        def interleaved_append(requests):
            nonlocal injected
            if not injected:
                injected = True
                alternative = ordered_moves[1]
                alternative_child = apply_move(root.node.position, alternative)
                original_append_move(
                    alternative_child,
                    root.node.history.push(alternative_child),
                    parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                    uci=alternative.uci(),
                    lineage={"injected": True},
                )
            return original_append_batch(requests)

        with mock.patch.object(
            dag,
            "append_moves_batch",
            side_effect=interleaved_append,
        ):
            with self.assertRaisesRegex(
                ExpansionConcurrentMutationError,
                "unexpected",
            ):
                expand_proof_dag(dag, ExpansionLimits(max_edges=1))

        recovered = expand_proof_dag(dag, ExpansionLimits(max_parents=1))
        self.assertEqual(recovered.stop_reason, ExpansionStopReason.PARENT_LIMIT)
        actions = [
            edge.action["uci"]
            for edge in dag.outgoing_edges(root.node.node_sha256)
        ]
        self.assertEqual(Counter(actions), Counter(move.uci() for move in ordered_moves))
        self.assertEqual(len(actions), len(ordered_moves))
        self.assertTrue(dag.audit().valid)

    def test_08_limits_and_inputs_are_strict(self) -> None:
        self.assertEqual(ExpansionLimits().max_parents, 1)
        self.assertIsNone(ExpansionLimits(max_parents=None).max_parents)
        for kwargs in (
            {"max_parents": -1},
            {"max_parents": True},
            {"max_edges": -1},
            {"max_edges": False},
            {"max_seconds": -0.1},
            {"max_seconds": float("inf")},
            {"max_seconds": float("nan")},
            {"max_seconds": 10**10000},
            {"max_seconds": True},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    ExpansionLimits(**kwargs)

        dag = self.make_dag("strict")
        self.append_root(dag, Position.initial())
        with self.assertRaises(TypeError):
            expand_proof_dag(dag, object())  # type: ignore[arg-type]
        dag.close()
        with self.assertRaises(TypeError):
            expand_proof_dag(dag)
        with self.assertRaises(TypeError):
            expand_proof_dag(object())  # type: ignore[arg-type]

    def test_09_redirected_equivalent_parent_or_lineage_fails_closed(self) -> None:
        dag = self.make_dag("redirected")
        position = Position.initial()
        first = self.append_root(dag, position, lineage={"root": 1})
        second = self.append_root(dag, position, lineage={"root": 2})
        self.assertEqual(first.node.node_sha256, second.node.node_sha256)
        original_append_batch = dag.append_moves_batch

        def redirected_append(requests):
            redirected = tuple(
                DAGMoveAppendRequest(
                    child_position=request.child_position,
                    child_history=request.child_history,
                    parent_frontier_content_sha256=(
                        second.edge.frontier_content_sha256
                    ),
                    uci=request.uci,
                    lineage={"redirected": True},
                )
                for request in requests
            )
            return original_append_batch(redirected)

        with mock.patch.object(
            dag,
            "append_moves_batch",
            side_effect=redirected_append,
        ):
            with self.assertRaisesRegex(
                ExpansionConcurrentMutationError,
                "substituted",
            ):
                expand_proof_dag(dag, ExpansionLimits(max_edges=1))

        first_uci = min(move.uci() for move in legal_moves(position))
        occurrences = [
            edge
            for edge in dag.outgoing_edges(first.node.node_sha256)
            if edge.action["uci"] == first_uci
        ]
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(
            occurrences[0].parent_frontier_content_sha256,
            second.edge.frontier_content_sha256,
        )
        self.assertTrue(dag.audit().valid)

    def test_10_edge_limit_caps_one_parent_batch_and_uses_one_frontier_sync(self) -> None:
        dag = self.make_dag("one-batch")
        root = self.append_root(dag, Position.initial())
        legal_uci = tuple(move.uci() for move in legal_moves(root.node.position))
        writer = dag._frontier_writer
        original_sync = writer.sync
        original_batch = dag.append_moves_batch
        captured_requests: list[tuple[DAGMoveAppendRequest, ...]] = []

        def capture_batch(requests):
            materialized = tuple(requests)
            captured_requests.append(materialized)
            return original_batch(materialized)

        with (
            mock.patch.object(writer, "sync", wraps=original_sync) as sync_mock,
            mock.patch.object(
                dag,
                "append_moves_batch",
                side_effect=capture_batch,
            ) as batch_mock,
        ):
            report = expand_proof_dag(dag, ExpansionLimits(max_edges=5))

        self.assertEqual(report.stop_reason, ExpansionStopReason.EDGE_LIMIT)
        self.assertEqual(report.edges_appended, 5)
        self.assertEqual(batch_mock.call_count, 1)
        self.assertEqual(sync_mock.call_count, 1)
        self.assertEqual(len(captured_requests), 1)
        self.assertEqual(
            tuple(request.uci for request in captured_requests[0]),
            legal_uci[:5],
        )
        self.assertEqual(report.parent_results[0].appended_moves, legal_uci[:5])
        self.assertEqual(report.parent_results[0].remaining_moves, legal_uci[5:])

    def test_11_full_materialisation_scans_are_constant_across_parent_batches(self) -> None:
        scan_counts: list[tuple[int, int, int]] = []
        for parent_count in (1, 3):
            with self.subTest(parent_count=parent_count):
                dag = self.make_dag(f"scan-{parent_count}")
                for fullmove in range(1, parent_count + 1):
                    position = Position.from_fen(
                        ONE_MOVE_TO_DEAD_POSITION_FEN.rsplit(" ", 1)[0]
                        + f" {fullmove}"
                    )
                    self.append_root(dag, position)

                with (
                    mock.patch.object(dag, "audit", wraps=dag.audit) as audit_mock,
                    mock.patch.object(
                        dag,
                        "iter_nodes",
                        wraps=dag.iter_nodes,
                    ) as nodes_mock,
                    mock.patch.object(
                        dag,
                        "iter_edges",
                        wraps=dag.iter_edges,
                    ) as edges_mock,
                    mock.patch.object(
                        dag,
                        "append_moves_batch",
                        wraps=dag.append_moves_batch,
                    ) as batch_mock,
                ):
                    report = expand_proof_dag(
                        dag,
                        ExpansionLimits(max_parents=parent_count),
                    )

                self.assertTrue(report.local_materialized_edge_closure)
                self.assertEqual(report.parents_attempted, parent_count)
                self.assertEqual(batch_mock.call_count, parent_count)
                counts = (
                    audit_mock.call_count,
                    nodes_mock.call_count,
                    edges_mock.call_count,
                )
                self.assertEqual(counts, (4, 2, 2))
                scan_counts.append(counts)
        self.assertEqual(scan_counts[0], scan_counts[1])

    def test_12_incremental_state_handles_two_parent_transpositions(self) -> None:
        dag = self.make_dag("transposition")
        parent_a_position = Position.from_fen(
            "r6k/8/8/8/8/8/8/1K6 w - - 0 1"
        )
        parent_b_position = Position.from_fen(
            "r6k/8/8/8/8/8/8/3K4 w - - 0 1"
        )
        shared_history = HistoryContext.from_keys(
            (
                repetition_key(parent_a_position),
                repetition_key(parent_b_position),
            )
        )
        parent_a = self.append_root(dag, parent_a_position, shared_history)
        parent_b = self.append_root(dag, parent_b_position, shared_history)
        target_move_a = next(
            move for move in legal_moves(parent_a_position) if move.uci() == "b1c1"
        )
        target_move_b = next(
            move for move in legal_moves(parent_b_position) if move.uci() == "d1c1"
        )
        target = apply_move(parent_a_position, target_move_a)
        self.assertEqual(target, apply_move(parent_b_position, target_move_b))
        target_history = shared_history.push(target)

        report = expand_proof_dag(dag, ExpansionLimits(max_parents=2))

        self.assertEqual(report.parents_attempted, 2)
        self.assertEqual(
            tuple(result.node_sha256 for result in report.parent_results),
            (parent_a.node.node_sha256, parent_b.node.node_sha256),
        )
        target_nodes = [
            node
            for node in dag.iter_nodes()
            if node.position == target and node.history == target_history
        ]
        self.assertEqual(len(target_nodes), 1)
        matching = list(dag.incoming_edges(target_nodes[0].node_sha256))
        self.assertEqual(
            {(edge.parent_node_sha256, edge.action["uci"]) for edge in matching},
            {
                (parent_a.node.node_sha256, "b1c1"),
                (parent_b.node.node_sha256, "d1c1"),
            },
        )
        shared_node = dag.get_node(matching[0].child_node_sha256)
        self.assertIsNotNone(shared_node)
        self.assertEqual(
            shared_node.first_frontier_record_index,  # type: ignore[union-attr]
            min(edge.frontier_record_index for edge in matching),
        )
        self.assertEqual(
            report.dag_head_after.frontier_record_count
            - report.dag_head_before.frontier_record_count,
            report.edges_appended,
        )
        self.assertTrue(dag.audit().valid)

    def test_13_verified_incomplete_node_is_skipped_without_claiming_raw_closure(self) -> None:
        dag = self.make_dag("fact-skip")
        first_position = Position.from_fen(ONE_MOVE_TO_DEAD_POSITION_FEN)
        second_position = Position.from_fen(
            ONE_MOVE_TO_DEAD_POSITION_FEN.rsplit(" ", 1)[0] + " 2"
        )
        verified = self.append_root(dag, first_position)
        eligible = self.append_root(dag, second_position)
        frontier_before = dag.frontier_path.read_bytes()

        with WDLFactJournal(self.root / "fact-skip.facts", dag) as journal:
            journal.append_seed_certificate(
                verified.node.node_sha256,
                self.certificate(verified.node, max_plies=1),
            )
            with mock.patch.object(
                journal,
                "audit",
                wraps=journal.audit,
            ) as fact_audit:
                report = expand_proof_dag(
                    dag,
                    ExpansionLimits(max_parents=1),
                    journal=journal,
                )

            self.assertEqual(fact_audit.call_count, 2)
            self.assertEqual(report.fact_head_before, report.fact_head_after)
            self.assertIsNotNone(report.fact_head_before)

        self.assertEqual(
            tuple(result.node_sha256 for result in report.parent_results),
            (eligible.node.node_sha256,),
        )
        self.assertEqual(
            report.stop_reason,
            ExpansionStopReason.LOCAL_ELIGIBLE_EDGE_CLOSURE_NOT_CHESS_SOLVED,
        )
        self.assertEqual(
            report.incomplete_parent_node_sha256s,
            (verified.node.node_sha256,),
        )
        self.assertEqual(report.eligible_incomplete_parent_node_sha256s, ())
        self.assertEqual(
            report.verified_skipped_node_sha256s,
            (verified.node.node_sha256,),
        )
        self.assertTrue(report.eligible_materialized_edge_closure)
        self.assertFalse(report.local_materialized_edge_closure)
        self.assertFalse(report.all_materialized_nonterminal_parents_complete)
        self.assertFalse(report.materialized_dag_empty)
        self.assertFalse(report.chess_solved)
        self.assertNotEqual(dag.frontier_path.read_bytes(), frontier_before)
        self.assertEqual(dag.outgoing_edges(verified.node.node_sha256), ())

    def test_14_fact_head_movement_fails_closed_and_durable_edges_resume(self) -> None:
        dag = self.make_dag("fact-movement")
        root = self.append_root(dag, Position.from_fen(ONE_MOVE_TO_DEAD_POSITION_FEN))
        terminal = self.append_root(dag, Position.from_fen(CHECKMATE_FEN))
        terminal_certificate = self.certificate(terminal.node)

        with WDLFactJournal(self.root / "fact-movement.facts", dag) as journal:
            original_batch = dag.append_moves_batch

            def append_then_move_fact_head(requests):
                result = original_batch(requests)
                journal.append_seed_certificate(
                    terminal.node.node_sha256,
                    terminal_certificate,
                )
                return result

            with mock.patch.object(
                dag,
                "append_moves_batch",
                side_effect=append_then_move_fact_head,
            ):
                with self.assertRaisesRegex(
                    ExpansionConcurrentMutationError,
                    "fact-journal authority moved",
                ):
                    expand_proof_dag(dag, journal=journal)

            durable_bytes = dag.frontier_path.read_bytes()
            self.assertEqual(len(dag.outgoing_edges(root.node.node_sha256)), 1)
            self.assertTrue(dag.audit().valid)
            resumed = expand_proof_dag(dag, journal=journal)
            self.assertEqual(resumed.edges_appended, 0)
            self.assertEqual(dag.frontier_path.read_bytes(), durable_bytes)

    def test_15_exception_after_durable_batch_has_no_report_and_restart_is_stable(self) -> None:
        dag = self.make_dag("post-write-exception")
        position = Position.from_fen(ONE_MOVE_TO_DEAD_POSITION_FEN)
        root = self.append_root(dag, position, lineage={"fixture": "root"})
        original_batch = dag.append_moves_batch

        def append_then_raise(requests):
            original_batch(requests)
            raise RuntimeError("injected after durable move batch")

        with mock.patch.object(
            dag,
            "append_moves_batch",
            side_effect=append_then_raise,
        ):
            with self.assertRaisesRegex(RuntimeError, "after durable"):
                expand_proof_dag(dag)

        self.assertEqual(len(dag.outgoing_edges(root.node.node_sha256)), 1)
        self.assertTrue(dag.audit().valid)
        durable_bytes = dag.frontier_path.read_bytes()
        resumed = expand_proof_dag(dag)
        self.assertEqual(resumed.edges_appended, 0)
        self.assertEqual(dag.frontier_path.read_bytes(), durable_bytes)

        clean = self.make_dag("post-write-clean")
        self.append_root(clean, position, lineage={"fixture": "root"})
        expand_proof_dag(clean)
        self.assertEqual(dag.frontier_path.read_bytes(), clean.frontier_path.read_bytes())

    def test_16_empty_dag_and_claimable_draws_remain_explicit(self) -> None:
        empty = self.make_dag("empty")
        empty_report = expand_proof_dag(empty)
        self.assertTrue(empty_report.materialized_dag_empty)
        self.assertTrue(empty_report.local_materialized_edge_closure)
        self.assertTrue(empty_report.eligible_materialized_edge_closure)
        self.assertEqual(empty_report.dag_head_before.frontier_record_count, 0)
        self.assertEqual(empty_report.dag_head_before, empty_report.dag_head_after)
        self.assertFalse(empty_report.chess_solved)

        for name, position, history in (
            (
                "fifty",
                Position.from_fen(
                    Position.initial().to_fen().replace(" 0 1", " 100 1")
                ),
                None,
            ),
            (
                "threefold",
                Position.initial(),
                HistoryContext.from_keys(
                    (repetition_key(Position.initial()),) * 3
                ),
            ),
        ):
            with self.subTest(claim=name):
                dag = self.make_dag(f"claim-{name}")
                exact_history = (
                    HistoryContext.initial(position) if history is None else history
                )
                self.assertFalse(automatic_status(position, exact_history).terminal)
                self.assertTrue(current_claim_actions(position, exact_history))
                root = self.append_root(dag, position, exact_history)
                report = expand_proof_dag(dag, ExpansionLimits(max_edges=1))
                self.assertEqual(report.stop_reason, ExpansionStopReason.EDGE_LIMIT)
                self.assertEqual(report.edges_appended, 1)
                self.assertEqual(len(dag.outgoing_edges(root.node.node_sha256)), 1)
                self.assertFalse(report.chess_solved)


if __name__ == "__main__":
    unittest.main()
