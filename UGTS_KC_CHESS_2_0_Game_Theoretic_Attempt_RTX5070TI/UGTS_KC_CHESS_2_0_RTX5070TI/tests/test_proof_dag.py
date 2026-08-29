from __future__ import annotations

import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ugts_chess.frontier as frontier_module
from ugts_chess.frontier import (
    FrontierIntegrityError,
    FrontierRecord,
    FrontierWriter,
    recover_frontier,
)
from ugts_chess.game_state import HistoryContext, RULE_PROFILE_ID
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import compact_key64, repetition_key
from ugts_chess.position import Position
from ugts_chess.proof_dag import (
    DAGMoveAppendRequest,
    MAX_MOVE_APPEND_BATCH,
    ProofDAG,
    ProofDAGCommitError,
    ProofDAGIntegrityError,
)
from ugts_chess.rules import apply_uci, legal_moves


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
            ended_history = HistoryContext(
                tuple(
                    sorted(
                        ((repetition_key(self.root), 1), ("0" * 64, 5))
                    )
                )
            )
            with self.assertRaisesRegex(ValueError, "already ended automatically"):
                dag.append_root(self.root, ended_history)
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

    def _batch_request(
        self,
        parent,
        uci: str,
        *,
        lineage: object = None,
    ) -> DAGMoveAppendRequest:
        child = apply_uci(parent.node.position, uci)
        return DAGMoveAppendRequest(
            child_position=child,
            child_history=parent.node.history.push(child),
            parent_frontier_content_sha256=parent.edge.frontier_content_sha256,
            uci=uci,
            lineage=lineage,
        )

    def test_19_batch_is_one_sync_one_transaction_ordered_and_exactly_deduplicated(self) -> None:
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history, lineage="root")
            first = self._batch_request(root, "a2a3", lineage="first")
            second = self._batch_request(root, "a2a4", lineage="second")
            distinct_occurrence = self._batch_request(
                root,
                "a2a4",
                lineage="different-lineage",
            )
            statements: list[str] = []
            dag._db.set_trace_callback(statements.append)
            writer = dag._frontier_writer
            original_append = writer.append
            original_sync = writer.sync
            with (
                patch.object(writer, "append", wraps=original_append) as append_mock,
                patch.object(writer, "sync", wraps=original_sync) as sync_mock,
            ):
                result = dag.append_moves_batch(
                    (first, first, second, distinct_occurrence)
                )
            dag._db.set_trace_callback(None)

            self.assertEqual([item.appended for item in result.results], [True, False, True, True])
            self.assertEqual(result.request_count, 4)
            self.assertEqual(result.appended_count, 3)
            self.assertEqual(result.appended_record_indexes, (1, 2, 3))
            self.assertEqual(
                [item.edge.frontier_record_index for item in result.results],
                [1, 1, 2, 3],
            )
            self.assertEqual(result.frontier_record_count_before, 1)
            self.assertEqual(result.frontier_record_count_after, 4)
            self.assertEqual(append_mock.call_count, 3)
            self.assertTrue(
                all(call.kwargs.get("fsync") is False for call in append_mock.call_args_list)
            )
            self.assertEqual(sync_mock.call_count, 1)
            normalized = [statement.strip().upper() for statement in statements]
            self.assertEqual(normalized.count("BEGIN IMMEDIATE"), 1)
            self.assertEqual(normalized.count("COMMIT"), 1)
            self.assertEqual(normalized.count("ROLLBACK"), 0)
            self.assertTrue(dag.audit().valid)

            stable_bytes = self.frontier.read_bytes()
            statements.clear()
            dag._db.set_trace_callback(statements.append)
            with (
                patch.object(writer, "append", wraps=original_append) as append_mock,
                patch.object(writer, "sync", wraps=original_sync) as sync_mock,
            ):
                duplicate = dag.append_moves_batch(
                    (first, first, second, distinct_occurrence)
                )
                empty = dag.append_moves_batch(())
            dag._db.set_trace_callback(None)
            self.assertEqual(duplicate.appended_count, 0)
            self.assertEqual(empty.request_count, 0)
            self.assertEqual(append_mock.call_count, 0)
            self.assertEqual(sync_mock.call_count, 0)
            self.assertFalse(
                any(
                    statement.strip().upper() in {"BEGIN IMMEDIATE", "COMMIT"}
                    for statement in statements
                )
            )
            self.assertEqual(self.frontier.read_bytes(), stable_bytes)

    def test_20_batch_prevalidates_every_request_before_writing(self) -> None:
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            valid = self._batch_request(root, "a2a3")
            expected_second = self._batch_request(root, "a2a4")
            invalid = DAGMoveAppendRequest(
                child_position=valid.child_position,
                child_history=expected_second.child_history,
                parent_frontier_content_sha256=root.edge.frontier_content_sha256,
                uci="a2a4",
            )
            bytes_before = self.frontier.read_bytes()
            audit_before = dag.audit().require_valid()
            with self.assertRaisesRegex(ValueError, "child position differs"):
                dag.append_moves_batch((valid, invalid))
            self.assertEqual(self.frontier.read_bytes(), bytes_before)
            self.assertEqual(dag.audit().require_valid(), audit_before)

            original_metadata = dag._validated_metadata
            metadata_calls = 0

            def fail_inside_transaction():
                nonlocal metadata_calls
                metadata_calls += 1
                if metadata_calls == 2:
                    raise RuntimeError("injected pre-write transaction failure")
                return original_metadata()

            with (
                patch.object(
                    dag,
                    "_validated_metadata",
                    side_effect=fail_inside_transaction,
                ),
                self.assertRaisesRegex(RuntimeError, "pre-write transaction failure"),
            ):
                dag.append_moves_batch((valid,))
            self.assertFalse(dag.closed)
            self.assertEqual(self.frontier.read_bytes(), bytes_before)
            self.assertEqual(dag.audit().require_valid(), audit_before)

            # Failures before the first frontier write do not poison the handle.
            appended = dag.append_move(
                valid.child_position,
                valid.child_history,
                parent_frontier_content_sha256=valid.parent_frontier_content_sha256,
                uci=valid.uci,
            )
            self.assertTrue(appended.appended)

    def test_21_synced_batch_index_failure_is_poisoned_and_fully_replayed(self) -> None:
        requests: tuple[DAGMoveAppendRequest, ...]
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history, lineage="root")
            requests = tuple(
                self._batch_request(root, move.uci(), lineage={"uci": move.uci()})
                for move in legal_moves(self.root)[:3]
            )
            original_insert = dag._insert_entry
            insert_count = 0

            def fail_second_insert(entry):
                nonlocal insert_count
                insert_count += 1
                if insert_count == 2:
                    raise RuntimeError("injected batch index failure")
                return original_insert(entry)

            with (
                patch.object(dag, "_insert_entry", side_effect=fail_second_insert),
                self.assertRaisesRegex(
                    ProofDAGCommitError,
                    "complete frontier batch was synced",
                ),
            ):
                dag.append_moves_batch(requests)
            self.assertTrue(dag.closed)
            with self.assertRaisesRegex(ProofDAGCommitError, "reopen"):
                dag.append_moves_batch(requests)
            with self.assertRaisesRegex(ProofDAGCommitError, "reopen"):
                dag.append_root(self.root, self.root_history, lineage="blocked")

        with ProofDAG(self.database, self.frontier) as recovered:
            audit = recovered.audit().require_valid()
            self.assertEqual(audit.frontier_record_count, 4)
            outgoing = recovered.outgoing_edges(root.node.node_sha256)
            self.assertEqual(
                [edge.action["uci"] for edge in outgoing],
                [request.uci for request in requests],
            )
            replay = recovered.append_moves_batch(requests)
            self.assertEqual(replay.appended_count, 0)

    def test_22_interrupted_batch_prefix_retry_matches_uninterrupted_bytes(self) -> None:
        interrupted_database = self.database
        interrupted_frontier = self.frontier
        with ProofDAG(interrupted_database, interrupted_frontier) as dag:
            root = dag.append_root(self.root, self.root_history, lineage="root")
            requests = tuple(
                self._batch_request(root, move.uci(), lineage={"uci": move.uci()})
                for move in legal_moves(self.root)[:3]
            )
            writer = dag._frontier_writer
            original_append = writer.append
            append_count = 0

            def fail_before_second(record, *, fsync=None):
                nonlocal append_count
                append_count += 1
                if append_count == 2:
                    raise RuntimeError("injected second-frame failure")
                return original_append(record, fsync=fsync)

            with (
                patch.object(writer, "append", side_effect=fail_before_second),
                self.assertRaisesRegex(ProofDAGCommitError, "batch prefix"),
            ):
                dag.append_moves_batch(requests)

        with ProofDAG(interrupted_database, interrupted_frontier) as recovered:
            prefix = recovered.audit().require_valid()
            self.assertEqual(prefix.frontier_record_count, 2)
            retried = recovered.append_moves_batch(requests)
            self.assertEqual(
                [item.appended for item in retried.results],
                [False, True, True],
            )
            interrupted_bytes = interrupted_frontier.read_bytes()

        clean_database = self.root_history_path("clean.sqlite3")
        clean_frontier = self.root_history_path("clean.frontier")
        with ProofDAG(clean_database, clean_frontier) as clean:
            clean_root = clean.append_root(self.root, self.root_history, lineage="root")
            clean_requests = tuple(
                self._batch_request(
                    clean_root,
                    move.uci(),
                    lineage={"uci": move.uci()},
                )
                for move in legal_moves(self.root)[:3]
            )
            clean.append_moves_batch(clean_requests)
            clean_bytes = clean_frontier.read_bytes()
        self.assertEqual(interrupted_bytes, clean_bytes)

    def root_history_path(self, name: str) -> Path:
        return self.database.parent / name

    def test_23_intra_batch_parent_and_oversized_batches_fail_before_writes(self) -> None:
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            first = self._batch_request(root, "a2a3", lineage="first")
            prospective_record = FrontierRecord(
                first.child_position,
                first.child_history,
                parent_content_sha256=first.parent_frontier_content_sha256,
                action={"kind": "move", "uci": first.uci},
                lineage=first.lineage,
            )
            grandchild_move = legal_moves(first.child_position)[0]
            grandchild = apply_uci(first.child_position, grandchild_move.uci())
            intra_batch = DAGMoveAppendRequest(
                child_position=grandchild,
                child_history=first.child_history.push(grandchild),
                parent_frontier_content_sha256=prospective_record.content_sha256,
                uci=grandchild_move.uci(),
            )
            before = self.frontier.read_bytes()
            with self.assertRaisesRegex(ValueError, "not indexed"):
                dag.append_moves_batch((first, intra_batch))
            self.assertEqual(self.frontier.read_bytes(), before)

            with self.assertRaisesRegex(ValueError, "exceeds maximum"):
                dag.append_moves_batch(
                    first for _ in range(MAX_MOVE_APPEND_BATCH + 1)
                )
            self.assertEqual(self.frontier.read_bytes(), before)

            with (
                patch("ugts_chess.proof_dag.MAX_MOVE_APPEND_BATCH_BYTES", 1),
                self.assertRaisesRegex(ValueError, "encoded bytes exceed maximum"),
            ):
                dag.append_moves_batch((first,))
            self.assertEqual(self.frontier.read_bytes(), before)
            self.assertTrue(dag.audit().valid)

    def test_24_sync_exception_after_durable_flush_poisoned_then_replays(self) -> None:
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            requests = tuple(
                self._batch_request(root, move.uci(), lineage=move.uci())
                for move in legal_moves(self.root)[:2]
            )
            writer = dag._frontier_writer
            original_sync = writer.sync

            def sync_then_fail() -> None:
                original_sync()
                raise RuntimeError("injected error after durable frontier sync")

            with (
                patch.object(writer, "sync", side_effect=sync_then_fail),
                self.assertRaisesRegex(ProofDAGCommitError, "frontier may contain"),
            ):
                dag.append_moves_batch(requests)
            self.assertTrue(dag.closed)
            with self.assertRaisesRegex(ProofDAGCommitError, "reopen"):
                dag.append_moves_batch(requests)

        with ProofDAG(self.database, self.frontier) as recovered:
            audit = recovered.audit().require_valid()
            self.assertEqual(audit.frontier_record_count, 3)
            self.assertEqual(
                [
                    edge.action["uci"]
                    for edge in recovered.outgoing_edges(root.node.node_sha256)
                ],
                [request.uci for request in requests],
            )

    def test_25_torn_second_batch_frame_requires_preserved_tail_recovery(self) -> None:
        with ProofDAG(self.database, self.frontier) as dag:
            root = dag.append_root(self.root, self.root_history)
            requests = tuple(
                self._batch_request(root, move.uci(), lineage=move.uci())
                for move in legal_moves(self.root)[:2]
            )
            writer = dag._frontier_writer
            original_append = writer.append
            append_count = 0

            def tear_second_frame(record, *, fsync=None):
                nonlocal append_count
                append_count += 1
                if append_count == 1:
                    return original_append(record, fsync=fsync)
                frame, _, _ = frontier_module._encode_frame(record)
                stream = writer._stream
                self.assertIsNotNone(stream)
                stream.write(frame[: len(frame) // 2])  # type: ignore[union-attr]
                stream.flush()  # type: ignore[union-attr]
                raise OSError("injected torn second batch frame")

            with (
                patch.object(writer, "append", side_effect=tear_second_frame),
                self.assertRaisesRegex(ProofDAGCommitError, "torn batch prefix"),
            ):
                dag.append_moves_batch(requests)
            self.assertTrue(dag.closed)

        with self.assertRaises(FrontierIntegrityError):
            ProofDAG(self.database, self.frontier)
        recovery = recover_frontier(self.frontier)
        self.assertGreater(recovery.truncated_bytes, 0)
        self.assertIsNotNone(recovery.preserved_suffix_path)
        self.assertTrue(recovery.preserved_suffix_path.exists())  # type: ignore[union-attr]

        with ProofDAG(self.database, self.frontier) as recovered:
            prefix = recovered.audit().require_valid()
            self.assertEqual(prefix.frontier_record_count, 2)
            retried = recovered.append_moves_batch(requests)
            self.assertEqual(
                [result.appended for result in retried.results],
                [False, True],
            )
            self.assertTrue(recovered.audit().valid)


if __name__ == "__main__":
    unittest.main()
