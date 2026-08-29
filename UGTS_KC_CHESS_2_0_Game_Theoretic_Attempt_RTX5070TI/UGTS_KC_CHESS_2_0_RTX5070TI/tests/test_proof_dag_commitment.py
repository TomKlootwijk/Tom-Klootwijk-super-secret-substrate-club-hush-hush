from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ugts_chess.game_state import HistoryContext, RULE_PROFILE_ID
from ugts_chess.hashing import canonical_json_bytes
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.rules import apply_move, legal_moves
from ugts_chess.proof_dag_commitment import (
    PROOF_DAG_HEAD_SCHEMA,
    ProofDAGConcurrentMutationError,
    ProofDAGHead,
    ProofDAGHeadMismatchError,
    ProofDAGRollbackError,
    audit_proof_dag_head,
    require_external_dag_head,
)
from ugts_chess.wdl_expansion import _snapshot_dag_head as expansion_dag_head


CHECKMATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"


class ProofDAGCommitmentTests(unittest.TestCase):
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
    def append_root(dag: ProofDAG, position: Position, *, lineage: object = None):
        return dag.append_root(
            position,
            HistoryContext.initial(position),
            lineage=lineage,
        )

    @staticmethod
    def append_move(dag: ProofDAG, parent, uci: str):
        move = next(move for move in legal_moves(parent.node.position) if move.uci() == uci)
        child = apply_move(parent.node.position, move)
        history = parent.node.history.push(child)
        return dag.append_move(
            child,
            history,
            parent_frontier_content_sha256=parent.edge.frontier_content_sha256,
            uci=uci,
            lineage={"fixture": "move"},
        )

    def test_01_empty_head_is_canonical_and_externally_requireable(self) -> None:
        dag = self.make_dag("empty")

        head = audit_proof_dag_head(dag)

        self.assertEqual(head.rule_profile_id, RULE_PROFILE_ID)
        self.assertEqual(head.frontier_record_count, 0)
        self.assertEqual(head.sqlite_edge_count, 0)
        self.assertEqual(head.sqlite_node_count, 0)
        self.assertGreater(head.frontier_size, 0)
        self.assertIsNone(head.last_frontier_content_sha256)
        self.assertEqual(head.record()["schema"], PROOF_DAG_HEAD_SCHEMA)
        self.assertEqual(ProofDAGHead.from_bytes(head.canonical_bytes()), head)
        self.assertEqual(require_external_dag_head(dag, head), head)

    def test_02_append_advances_head_and_retained_prefix_remains_exact(self) -> None:
        dag = self.make_dag("advance")
        position = Position.initial()
        first = self.append_root(dag, position, lineage={"occurrence": 1})
        retained = audit_proof_dag_head(dag)

        self.append_root(dag, position, lineage={"occurrence": 2})
        current = audit_proof_dag_head(dag)

        self.assertEqual(retained.frontier_record_count, 1)
        self.assertEqual(retained.sqlite_node_count, 1)
        self.assertEqual(current.frontier_record_count, 2)
        self.assertEqual(current.sqlite_node_count, 1)
        self.assertGreater(current.frontier_size, retained.frontier_size)
        self.assertNotEqual(
            current.frontier_manifest_sha256,
            retained.frontier_manifest_sha256,
        )
        self.assertEqual(require_external_dag_head(dag, retained), current)
        self.assertEqual(
            dag.get_node(first.node.node_sha256).first_frontier_record_index,  # type: ignore[union-attr]
            0,
        )

    def test_03_manifest_matches_expansion_algorithm_for_exact_move_edge(self) -> None:
        dag = self.make_dag("compatible")
        root = self.append_root(dag, Position.initial(), lineage={"fixture": "root"})
        self.append_move(dag, root, "a2a3")

        committed = audit_proof_dag_head(dag)
        expansion = expansion_dag_head(dag)

        for field in (
            "rule_profile_id",
            "frontier_record_count",
            "sqlite_edge_count",
            "sqlite_node_count",
            "frontier_size",
            "last_frontier_content_sha256",
            "frontier_manifest_sha256",
        ):
            self.assertEqual(getattr(committed, field), getattr(expansion, field))

    def test_04_manifest_distinguishes_earlier_same_size_rewrite(self) -> None:
        first = self.make_dag("rewrite-a")
        second = self.make_dag("rewrite-b")
        initial = Position.initial()
        terminal = Position.from_fen(CHECKMATE_FEN)

        self.append_root(first, initial, lineage={"variant": "a"})
        self.append_root(first, terminal, lineage={"common": True})
        self.append_root(second, initial, lineage={"variant": "b"})
        self.append_root(second, terminal, lineage={"common": True})
        expected = audit_proof_dag_head(first)
        rewritten = audit_proof_dag_head(second)

        self.assertEqual(expected.frontier_record_count, rewritten.frontier_record_count)
        self.assertEqual(expected.sqlite_node_count, rewritten.sqlite_node_count)
        self.assertEqual(expected.frontier_size, rewritten.frontier_size)
        self.assertEqual(
            expected.last_frontier_content_sha256,
            rewritten.last_frontier_content_sha256,
        )
        self.assertNotEqual(
            expected.frontier_manifest_sha256,
            rewritten.frontier_manifest_sha256,
        )
        with self.assertRaises(ProofDAGHeadMismatchError):
            require_external_dag_head(second, expected)

    def test_05_canonical_parser_rejects_hostile_shapes_and_values(self) -> None:
        dag = self.make_dag("canonical")
        self.append_root(dag, Position.initial())
        head = audit_proof_dag_head(dag)
        record = head.record()

        hostile = {
            "leading_whitespace": b" " + head.canonical_bytes(),
            "invalid_utf8": b"\xff",
            "wrong_schema": canonical_json_bytes(
                {**record, "schema": "ugts-chess-proof-dag-head-9.0"}
            ),
            "wrong_profile": canonical_json_bytes(
                {**record, "rule_profile_id": "not-the-supported-profile"}
            ),
            "boolean_count": canonical_json_bytes(
                {**record, "frontier_record_count": True}
            ),
            "count_disagreement": canonical_json_bytes(
                {**record, "sqlite_edge_count": head.sqlite_edge_count + 1}
            ),
            "uppercase_hash": canonical_json_bytes(
                {
                    **record,
                    "frontier_manifest_sha256": head.frontier_manifest_sha256.upper(),
                }
            ),
            "extra_field": canonical_json_bytes({**record, "extra": 1}),
            "missing_field": canonical_json_bytes(
                {key: value for key, value in record.items() if key != "frontier_size"}
            ),
        }
        for name, value in hostile.items():
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    ProofDAGHead.from_bytes(value)
        with self.assertRaises(TypeError):
            ProofDAGHead.from_bytes("not bytes")  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            require_external_dag_head(dag, object())  # type: ignore[arg-type]

    def test_06_wrong_count_or_hash_fails_with_explicit_error(self) -> None:
        dag = self.make_dag("forged")
        self.append_root(dag, Position.initial())
        current = audit_proof_dag_head(dag)
        wrong_hash = replace(current, frontier_manifest_sha256="0" * 64)
        wrong_last = replace(current, last_frontier_content_sha256="1" * 64)
        longer = replace(
            current,
            frontier_record_count=current.frontier_record_count + 1,
            sqlite_edge_count=current.sqlite_edge_count + 1,
        )

        for forged in (wrong_hash, wrong_last):
            with self.subTest(forged=forged):
                with self.assertRaises(ProofDAGHeadMismatchError):
                    require_external_dag_head(dag, forged)
        with self.assertRaises(ProofDAGRollbackError):
            require_external_dag_head(dag, longer)

    def test_07_clean_rollback_is_detected_against_retained_head(self) -> None:
        database = self.root / "rollback.sqlite3"
        frontier = self.root / "rollback.frontier"
        dag = ProofDAG(database, frontier)
        self.dags.append(dag)
        self.append_root(dag, Position.initial(), lineage={"order": 1})
        prefix = audit_proof_dag_head(dag)
        self.append_root(
            dag,
            Position.from_fen(CHECKMATE_FEN),
            lineage={"order": 2},
        )
        retained = audit_proof_dag_head(dag)
        dag.close()

        with frontier.open("r+b", buffering=0) as stream:
            stream.truncate(prefix.frontier_size)
            stream.flush()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{database}{suffix}").unlink(missing_ok=True)

        reopened = ProofDAG(database, frontier)
        self.dags.append(reopened)
        self.assertEqual(audit_proof_dag_head(reopened), prefix)
        with self.assertRaises(ProofDAGRollbackError) as captured:
            require_external_dag_head(reopened, retained)
        self.assertEqual(captured.exception.expected, retained)
        self.assertEqual(captured.exception.current, prefix)

    def test_08_repeated_concurrent_movement_fails_closed(self) -> None:
        dag = self.make_dag("movement")
        self.append_root(dag, Position.initial())
        stable = dag.audit().require_valid()
        moved = replace(stable, frontier_size=stable.frontier_size + 1)
        alternating = [item for _ in range(8) for item in (stable, moved)]

        with mock.patch.object(dag, "audit", side_effect=alternating) as audit:
            with self.assertRaises(ProofDAGConcurrentMutationError):
                audit_proof_dag_head(dag)
        self.assertEqual(audit.call_count, 16)

    def test_09_closed_and_non_dag_inputs_fail_closed(self) -> None:
        dag = self.make_dag("closed")
        dag.close()
        with self.assertRaises(TypeError):
            audit_proof_dag_head(dag)
        with self.assertRaises(TypeError):
            audit_proof_dag_head(object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
