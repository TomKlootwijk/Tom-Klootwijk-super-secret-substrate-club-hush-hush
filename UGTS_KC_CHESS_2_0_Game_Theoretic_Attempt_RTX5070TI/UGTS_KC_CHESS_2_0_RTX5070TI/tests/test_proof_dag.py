from __future__ import annotations

import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ugts_chess.frontier import FrontierIntegrityError, FrontierRecord, FrontierWriter
from ugts_chess.game_state import HistoryContext, RULE_PROFILE_ID
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import compact_key64, repetition_key
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG, ProofDAGCommitError, ProofDAGIntegrityError
from ugts_chess.rules import apply_uci


class ProofDAGTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database = directory / "proof-dag.sqlite3"
        self.frontier = directory / "proof-dag.frontier"
        self.root = Position.initial()
        self.root_history = HistoryContext.initial(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_01_append_reopen_and_deterministic_full_audit(self) -> None:
        child = apply_uci(self.root, "e2e3")
        child_history = self.root_history.push(child)
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history, lineage={"sequence": 0})
            added = dag.append_move(
                child,
                child_history,
                parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                uci="e2e3",
                lineage={"sequence": 1},
            )
            self.assertTrue(root.appended)
            self.assertTrue(added.appended)
            self.assertEqual(root.node.wdl, WDL.UNKNOWN)
            self.assertEqual(added.node.wdl, WDL.UNKNOWN)
            self.assertTrue(dag.audit().valid)

        with ProofDAG(self.database, self.frontier) as reopened:
            report = reopened.audit().require_valid()
            self.assertEqual(report.frontier_record_count, 2)
            self.assertEqual(report.sqlite_edge_count, 2)
            self.assertEqual(report.sqlite_node_count, 2)
            self.assertEqual(
                [edge.frontier_record_index for edge in reopened.iter_edges()],
                [0, 1],
            )
            recovered = reopened.get_node(added.node.node_sha256)
            self.assertIsNotNone(recovered)
            self.assertEqual(recovered.position.to_fen(), child.to_fen())  # type: ignore[union-attr]
            self.assertEqual(recovered.history, child_history)  # type: ignore[union-attr]

    def test_02_exact_history_and_full_fen_distinguish_nodes_despite_shared_indexes(self) -> None:
        repeated_history = HistoryContext(((repetition_key(self.root), 2),))
        later_fen = Position.from_fen(self.root.to_fen().rsplit(" ", 1)[0] + " 2")
        with ProofDAG(self.database, self.frontier) as dag:
            first = dag.append_root(self.root, self.root_history, lineage="first")
            repeated = dag.append_root(self.root, repeated_history, lineage="repeated")
            later = dag.append_root(later_fen, self.root_history, lineage="later-fen")

            self.assertEqual(first.node.index_key64, repeated.node.index_key64)
            self.assertEqual(first.node.index_key64, later.node.index_key64)
            self.assertNotEqual(first.node.node_sha256, repeated.node.node_sha256)
            self.assertNotEqual(first.node.node_sha256, later.node.node_sha256)
            self.assertNotEqual(first.node.game_state_sha256, repeated.node.game_state_sha256)
            self.assertEqual(first.node.game_state_sha256, later.node.game_state_sha256)

            collision_bucket = dag.find_nodes_by_index_key(first.node.index_key64)
            self.assertEqual(len(collision_bucket), 3)
            self.assertEqual(
                {item.node_sha256 for item in collision_bucket},
                {first.node.node_sha256, repeated.node.node_sha256, later.node.node_sha256},
            )

    def test_03_transposition_node_preserves_multiple_distinct_parent_edges(self) -> None:
        parent_a_position = Position.from_fen("r6k/8/8/8/8/8/8/1K6 w - - 0 1")
        parent_b_position = Position.from_fen("r6k/8/8/8/8/8/8/3K4 w - - 0 1")
        shared_history = HistoryContext.from_keys(
            (repetition_key(parent_a_position), repetition_key(parent_b_position))
        )
        target = apply_uci(parent_a_position, "b1c1")
        self.assertEqual(target, apply_uci(parent_b_position, "d1c1"))
        target_history = shared_history.push(target)
        with ProofDAG(self.database, self.frontier) as dag:
            parent_a = dag.append_root(
                parent_a_position,
                shared_history,
                lineage="parent-a",
            )
            parent_b = dag.append_root(
                parent_b_position,
                shared_history,
                lineage="parent-b",
            )
            via_a = dag.append_move(
                target,
                target_history,
                parent_frontier_content_sha256=parent_a.edge.frontier_content_sha256,
                uci="b1c1",
                lineage="via-a",
            )
            via_b = dag.append_move(
                target,
                target_history,
                parent_frontier_content_sha256=parent_b.edge.frontier_content_sha256,
                uci="d1c1",
                lineage="via-b",
            )

            self.assertEqual(via_a.node.node_sha256, via_b.node.node_sha256)
            self.assertNotEqual(
                via_a.edge.frontier_content_sha256,
                via_b.edge.frontier_content_sha256,
            )
            incoming = dag.incoming_edges(via_a.node.node_sha256)
            self.assertEqual(len(incoming), 2)
            self.assertEqual(
                {edge.parent_node_sha256 for edge in incoming},
                {parent_a.node.node_sha256, parent_b.node.node_sha256},
            )

    def test_04_compact_index_spoof_is_detected_before_lookup_can_redirect(self) -> None:
        child = apply_uci(self.root, "e2e3")
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            child_result = dag.append_root(child, HistoryContext.initial(child))
            self.assertNotEqual(root.node.index_key64, child_result.node.index_key64)

        attacker = sqlite3.connect(self.database)
        try:
            attacker.execute(
                "UPDATE nodes SET index_key64 = ? WHERE node_sha256 = ?",
                (
                    root.node.index_key64.to_bytes(8, "big"),
                    child_result.node.node_sha256,
                ),
            )
            attacker.commit()
        finally:
            attacker.close()

        with self.assertRaisesRegex(ProofDAGIntegrityError, "SQLite node"):
            ProofDAG(self.database, self.frontier)

    def test_05_frontier_ahead_of_sqlite_is_replayed_as_crash_recovery(self) -> None:
        child = apply_uci(self.root, "e2e3")
        child_history = self.root_history.push(child)
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)

        crash_suffix = FrontierRecord(
            child,
            child_history,
            parent_content_sha256=root.edge.frontier_content_sha256,
            action={"kind": "move", "uci": "e2e3"},
            lineage={"source": "durable-before-sqlite-commit"},
        )
        with FrontierWriter(self.frontier) as writer:
            writer.append(crash_suffix)

        with ProofDAG(self.database, self.frontier) as recovered:
            report = recovered.audit().require_valid()
            self.assertEqual(report.frontier_record_count, 2)
            self.assertEqual(report.sqlite_edge_count, 2)
            edge = recovered.get_edge(crash_suffix.content_sha256)
            self.assertIsNotNone(edge)
            self.assertEqual(edge.parent_node_sha256, root.node.node_sha256)  # type: ignore[union-attr]

    def test_06_sqlite_frontier_offset_divergence_is_rejected_on_reopen(self) -> None:
        with ProofDAG(self.database, self.frontier) as dag:
            dag.append_root(self.root, self.root_history)

        attacker = sqlite3.connect(self.database)
        try:
            attacker.execute("UPDATE edges SET frame_offset = frame_offset + 1")
            attacker.commit()
        finally:
            attacker.close()

        with self.assertRaisesRegex(ProofDAGIntegrityError, "edge differs"):
            ProofDAG(self.database, self.frontier)

    def test_07_frontier_corruption_is_never_hidden_by_the_sqlite_index(self) -> None:
        with ProofDAG(self.database, self.frontier) as dag:
            dag.append_root(self.root, self.root_history)

        with self.frontier.open("r+b") as stream:
            stream.seek(-1, 2)
            last = stream.read(1)
            stream.seek(-1, 2)
            stream.write(bytes([last[0] ^ 0x01]))

        with self.assertRaises(FrontierIntegrityError):
            ProofDAG(self.database, self.frontier)

    def test_08_non_unknown_sqlite_value_is_rejected_even_if_constraints_are_bypassed(self) -> None:
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            self.assertEqual(root.node.wdl, WDL.UNKNOWN)

        attacker = sqlite3.connect(self.database)
        try:
            attacker.execute("PRAGMA ignore_check_constraints = ON")
            attacker.execute(
                "UPDATE nodes SET wdl = 'win' WHERE node_sha256 = ?",
                (root.node.node_sha256,),
            )
            attacker.commit()
        finally:
            attacker.close()

        with self.assertRaisesRegex(ProofDAGIntegrityError, "SQLite node"):
            ProofDAG(self.database, self.frontier)

    def test_09_wrong_profile_and_missing_current_history_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "canonical rule profile"):
            ProofDAG(
                self.database,
                self.frontier,
                rule_profile_id="invented-rules",
            )
        with ProofDAG(self.database, self.frontier) as dag:
            with self.assertRaisesRegex(ValueError, "does not contain the current position"):
                dag.append_root(self.root, HistoryContext((("f" * 64, 1),)))
        self.assertEqual(RULE_PROFILE_ID, "fide-classical-2023-claims-as-actions-v2")
        self.assertIsInstance(compact_key64(self.root), int)

    def test_10_failed_sqlite_commit_leaves_replayable_durable_suffix(self) -> None:
        child = apply_uci(self.root, "e2e3")
        child_history = self.root_history.push(child)
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            with (
                patch.object(ProofDAG, "_insert_entry", side_effect=RuntimeError("fault")),
                self.assertRaisesRegex(ProofDAGCommitError, "reopen to replay suffix"),
            ):
                dag.append_move(
                    child,
                    child_history,
                    parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                    uci="e2e3",
                )
            with self.assertRaisesRegex(ProofDAGCommitError, "reopen"):
                dag.append_root(self.root, self.root_history, lineage="blocked-after-fault")

        with ProofDAG(self.database, self.frontier) as recovered:
            report = recovered.audit().require_valid()
            self.assertEqual(report.frontier_record_count, 2)
            self.assertEqual(report.sqlite_edge_count, 2)
            recovered_children = recovered.outgoing_edges(root.node.node_sha256)
            self.assertEqual(len(recovered_children), 1)
            self.assertEqual(
                recovered.get_node(recovered_children[0].child_node_sha256).position,
                child,
            )

    def test_11_illegal_and_noncanonical_move_tokens_are_rejected(self) -> None:
        child = apply_uci(self.root, "e2e3")
        child_history = self.root_history.push(child)
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            with self.assertRaisesRegex(ValueError, "not a legal move"):
                dag.append_move(
                    child,
                    child_history,
                    parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                    uci="e2e5",
                )
            with self.assertRaisesRegex(ValueError, "must be canonical"):
                dag.append_move(
                    child,
                    child_history,
                    parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                    uci=" E2E3 ",
                )

    def test_12_wrong_child_position_is_rejected(self) -> None:
        expected = apply_uci(self.root, "e2e3")
        wrong = apply_uci(self.root, "d2d3")
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            with self.assertRaisesRegex(ValueError, "child position differs"):
                dag.append_move(
                    wrong,
                    self.root_history.push(expected),
                    parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                    uci="e2e3",
                )

    def test_13_wrong_child_history_is_rejected(self) -> None:
        child = apply_uci(self.root, "e2e3")
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            with self.assertRaisesRegex(ValueError, "child history differs"):
                dag.append_move(
                    child,
                    HistoryContext.initial(child),
                    parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                    uci="e2e3",
                )

    def test_14_forged_parent_content_address_is_rejected(self) -> None:
        child = apply_uci(self.root, "e2e3")
        with ProofDAG(self.database, self.frontier) as dag:
            dag.append_root(self.root, self.root_history)
            with self.assertRaisesRegex(ValueError, "parent frontier content address is not indexed"):
                dag.append_move(
                    child,
                    self.root_history.push(child),
                    parent_frontier_content_sha256="f" * 64,
                    uci="e2e3",
                )

    def test_15_fullmove_only_child_forgery_is_rejected(self) -> None:
        child = apply_uci(self.root, "e2e3")
        fields = child.to_fen().split()
        fields[-1] = str(child.fullmove_number + 1)
        forged = Position.from_fen(" ".join(fields))
        # Repetition and semantic game-state hashes deliberately ignore the
        # fullmove counter, so the exact FEN comparison is independently vital.
        self.assertEqual(repetition_key(forged), repetition_key(child))
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            with self.assertRaisesRegex(ValueError, "child position differs"):
                dag.append_move(
                    forged,
                    self.root_history.push(child),
                    parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                    uci="e2e3",
                )

    def test_16_claim_or_dependency_metadata_cannot_create_a_state_edge(self) -> None:
        child = apply_uci(self.root, "e2e3")
        child_history = self.root_history.push(child)
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            for action in (
                {"kind": "claim", "claim": "claim_threefold_current"},
                {"kind": "dependency", "uci": "e2e3"},
                {"kind": "move", "uci": "e2e3", "san": "e3"},
            ):
                with self.subTest(action=action), self.assertRaisesRegex(
                    ValueError,
                    "non-root state action must be exactly",
                ):
                    dag.append_state(
                        child,
                        child_history,
                        parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                        action=action,
                    )

    def test_17_recovery_rejects_a_hand_authored_invalid_transition(self) -> None:
        wrong = apply_uci(self.root, "d2d3")
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)

        forged = FrontierRecord(
            wrong,
            self.root_history.push(wrong),
            parent_content_sha256=root.edge.frontier_content_sha256,
            action={"kind": "move", "uci": "e2e3"},
        )
        with FrontierWriter(self.frontier) as writer:
            writer.append(forged)
        with self.assertRaisesRegex(ProofDAGIntegrityError, "child differs"):
            ProofDAG(self.database, self.frontier)

    def test_18_live_handle_excludes_coordinated_sqlite_edge_redirection(self) -> None:
        child = apply_uci(self.root, "e2e3")
        with ProofDAG(self.database, self.frontier) as dag:
            first = dag.append_root(self.root, self.root_history, lineage="first")
            second = dag.append_root(
                child,
                HistoryContext.initial(child),
                lineage="second",
            )
            # Without the retained SQLite exclusive lock, these coordinated
            # edits make the second valid frame masquerade as ordinal zero in
            # the live random-access getter: the deleted row frees the UNIQUE
            # ordinal and the node's claimed first occurrence is rewritten too.
            attacker = sqlite3.connect(self.database, timeout=0.0, isolation_level=None)
            try:
                sql = f"""
                    BEGIN IMMEDIATE;
                    DELETE FROM edges
                    WHERE frontier_content_sha256 = '{first.edge.frontier_content_sha256}';
                    DELETE FROM nodes
                    WHERE node_sha256 = '{first.node.node_sha256}';
                    UPDATE edges SET frontier_record_index = 0
                    WHERE frontier_content_sha256 = '{second.edge.frontier_content_sha256}';
                    UPDATE nodes SET first_frontier_record_index = 0
                    WHERE node_sha256 = '{second.node.node_sha256}';
                    COMMIT;
                """
                with self.assertRaisesRegex(sqlite3.OperationalError, "database is locked"):
                    attacker.executescript(sql)
            finally:
                if attacker.in_transaction:
                    attacker.rollback()
                attacker.close()

            live = dag.get_edge(second.edge.frontier_content_sha256)
            self.assertIsNotNone(live)
            self.assertEqual(live.frontier_record_index, 1)  # type: ignore[union-attr]
            self.assertTrue(dag.audit().valid)

        # Closing the append handle releases the database lock normally.
        observer = sqlite3.connect(self.database, timeout=0.0)
        try:
            self.assertEqual(observer.execute("SELECT COUNT(*) FROM edges").fetchone()[0], 2)
        finally:
            observer.close()


if __name__ == "__main__":
    unittest.main()
