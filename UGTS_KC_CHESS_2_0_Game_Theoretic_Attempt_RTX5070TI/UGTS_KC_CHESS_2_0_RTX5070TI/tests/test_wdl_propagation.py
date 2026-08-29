from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ugts_chess.game_state import HistoryContext, game_state_sha256
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import canonical_json_bytes, repetition_key
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG, node_identity_sha256
from ugts_chess.rules import apply_move, legal_moves
from ugts_chess.verified_overlay import VerifiedCertificateOverlay
from ugts_chess.wdl import BoundedWDLSolver, verify_wdl_certificate
from ugts_chess.wdl_propagation import propagate_wdl_one_hop


CHECKMATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
MATE_IN_ONE_FEN = "k7/2K5/1Q6/8/8/8/8/8 w - - 0 1"
ONE_MOVE_LOSS_FEN = "8/8/8/8/8/8/8/k1KQ4 b - - {halfmove} 1"
MANY_75_MOVE_CHILDREN_FEN = "7k/8/8/8/8/8/8/KR6 w - - 149 1"


class WDLPropagationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.dag = ProofDAG(root / "proof.sqlite3", root / "proof.frontier")
        self.overlay = VerifiedCertificateOverlay(root / "verified.overlay", self.dag)

    def tearDown(self) -> None:
        self.overlay.close()
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

    def append_root(self, fen: str):
        position = Position.from_fen(fen)
        return self.dag.append_root(position, HistoryContext.initial(position))

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

    def bind(self, node, *, max_plies: int) -> bytes:
        certificate = self.certificate_bytes(
            node.position,
            node.history,
            max_plies=max_plies,
        )
        self.overlay.append_verified_certificate(node.node_sha256, certificate)
        return certificate

    def test_01_terminal_promotes_directly_without_mutating_dag(self) -> None:
        target = self.append_root(CHECKMATE_FEN)

        with mock.patch.object(
            self.overlay,
            "iter_bindings",
            wraps=self.overlay.iter_bindings,
        ) as snapshot:
            result = propagate_wdl_one_hop(
                self.dag,
                self.overlay,
                target.node.node_sha256,
            )
        self.assertEqual(snapshot.call_count, 1)

        self.assertTrue(result.promoted)
        self.assertEqual(result.value, WDL.LOSS)
        self.assertEqual(result.reason, "terminal_promoted")
        self.assertEqual(self.dag.get_node(target.node.node_sha256).wdl, WDL.UNKNOWN)
        binding = self.overlay.get_binding(target.node.node_sha256)
        self.assertIsNotNone(binding)
        verified = verify_wdl_certificate(json.loads(binding.certificate_bytes))  # type: ignore[union-attr]
        self.assertEqual(verified["root_value"], WDL.LOSS.value)
        self.assertEqual(verified["unreferenced_nodes"], 0)

        duplicate = propagate_wdl_one_hop(
            self.dag,
            self.overlay,
            target.node.node_sha256,
        )
        self.assertEqual(duplicate.status, "already_verified")
        self.assertFalse(duplicate.promoted)

    def test_02_win_uses_one_loss_child_and_collapses_duplicate_occurrences(self) -> None:
        parent = self.append_root(MATE_IN_ONE_FEN)
        solved = BoundedWDLSolver().solve(
            parent.node.position,
            max_plies=1,
            history=parent.node.history,
        )
        self.assertEqual(solved.root.value, WDL.WIN)
        witness = next(child.move for child in solved.root.children if child.kind == "move")
        self.assertIsNotNone(witness)
        first = self.append_child(parent, witness, lineage={"copy": 1})  # type: ignore[arg-type]
        second = self.append_child(parent, witness, lineage={"copy": 2})  # type: ignore[arg-type]
        self.assertEqual(first.node.node_sha256, second.node.node_sha256)
        self.assertNotEqual(
            first.edge.frontier_content_sha256,
            second.edge.frontier_content_sha256,
        )
        self.bind(first.node, max_plies=0)

        result = propagate_wdl_one_hop(
            self.dag,
            self.overlay,
            parent.node.node_sha256,
        )

        self.assertTrue(result.promoted)
        self.assertEqual(result.value, WDL.WIN)
        self.assertEqual(result.witness_move, witness)
        self.assertEqual(result.used_moves, (witness,))
        self.assertGreater(len(result.legal_moves), 1)
        binding = self.overlay.get_binding(parent.node.node_sha256)
        bundle = json.loads(binding.certificate_bytes)  # type: ignore[union-attr]
        root = next(
            node
            for node in bundle["nodes"]
            if node["certificate_hash"] == bundle["root_certificate_hash"]
        )
        move_children = [child for child in root["children"] if child["kind"] == "move"]
        self.assertEqual([child["move"] for child in move_children], [witness])

    def test_03_complete_one_move_loss_and_draw_claim_precedence(self) -> None:
        expected = {
            0: WDL.LOSS,
            99: WDL.DRAW,
            100: WDL.DRAW,
        }
        expected_claims = {
            0: set(),
            99: {"claim_fifty_move_by_move"},
            100: {
                "claim_fifty_move_current",
                "claim_fifty_move_by_move",
            },
        }
        for halfmove in (0, 99, 100):
            with self.subTest(halfmove=halfmove):
                parent = self.append_root(ONE_MOVE_LOSS_FEN.format(halfmove=halfmove))
                moves = legal_moves(parent.node.position)
                self.assertEqual(len(moves), 1)
                child = self.append_child(parent, moves[0].uci())
                if halfmove == 0:
                    duplicate = self.append_child(
                        parent,
                        moves[0].uci(),
                        lineage={"duplicate": True},
                    )
                    self.assertEqual(duplicate.node.node_sha256, child.node.node_sha256)
                child_cert = self.bind(child.node, max_plies=1)
                self.assertEqual(json.loads(child_cert)["root_value"], WDL.WIN.value)

                result = propagate_wdl_one_hop(
                    self.dag,
                    self.overlay,
                    parent.node.node_sha256,
                )

                self.assertEqual(result.value, expected[halfmove])
                binding = self.overlay.get_binding(parent.node.node_sha256)
                bundle = json.loads(binding.certificate_bytes)  # type: ignore[union-attr]
                root = next(
                    node
                    for node in bundle["nodes"]
                    if node["certificate_hash"] == bundle["root_certificate_hash"]
                )
                claims = {
                    child["claim_code"]
                    for child in root["children"]
                    if child["kind"] == "claim"
                }
                self.assertEqual(claims, expected_claims[halfmove])
                self.assertEqual(verify_wdl_certificate(bundle)["root_value"], expected[halfmove].value)

    def test_04_complete_draw_rebases_different_child_depths(self) -> None:
        parent = self.append_root(MANY_75_MOVE_CHILDREN_FEN)
        original_depths: set[int] = set()
        for index, move in enumerate(
            sorted(legal_moves(parent.node.position), key=lambda candidate: candidate.uci())
        ):
            child = self.append_child(parent, move.uci())
            depth = index % 3
            original_depths.add(depth)
            certificate = self.bind(child.node, max_plies=depth)
            self.assertEqual(json.loads(certificate)["root_value"], WDL.DRAW.value)
        self.assertEqual(original_depths, {0, 1, 2})

        result = propagate_wdl_one_hop(
            self.dag,
            self.overlay,
            parent.node.node_sha256,
        )

        self.assertTrue(result.promoted)
        self.assertEqual(result.value, WDL.DRAW)
        self.assertEqual(result.used_moves, result.legal_moves)
        binding = self.overlay.get_binding(parent.node.node_sha256)
        bundle = json.loads(binding.certificate_bytes)  # type: ignore[union-attr]
        root = next(
            node
            for node in bundle["nodes"]
            if node["certificate_hash"] == bundle["root_certificate_hash"]
        )
        self.assertEqual(bundle["max_plies"], 3)
        self.assertEqual(root["depth_remaining"], 3)
        move_roots = {
            child["child_certificate_hash"]
            for child in root["children"]
            if child["kind"] == "move"
        }
        by_hash = {node["certificate_hash"]: node for node in bundle["nodes"]}
        self.assertTrue(move_roots)
        self.assertEqual({by_hash[key]["depth_remaining"] for key in move_roots}, {2})
        verified = verify_wdl_certificate(bundle, allow_unknown_root=False)
        self.assertEqual(verified["unreferenced_nodes"], 0)

    def test_05_missing_edge_and_exact_child_fact_remain_unknown(self) -> None:
        parent = self.append_root(ONE_MOVE_LOSS_FEN.format(halfmove=149))
        legal = legal_moves(parent.node.position)
        self.assertEqual(len(legal), 1)

        missing_edge = propagate_wdl_one_hop(
            self.dag,
            self.overlay,
            parent.node.node_sha256,
        )
        self.assertEqual(missing_edge.value, WDL.UNKNOWN)
        self.assertEqual(missing_edge.reason, "missing_frontier_moves")
        self.assertEqual(missing_edge.missing_frontier_moves, (legal[0].uci(),))

        actual = self.append_child(parent, legal[0].uci())
        actual_position = actual.node.position
        twin_fields = actual_position.to_fen().split()
        twin_fields[-1] = str(int(twin_fields[-1]) + 1)
        fullmove_twin = Position.from_fen(" ".join(twin_fields))
        twin = self.dag.append_root(fullmove_twin, actual.node.history)
        self.assertEqual(twin.node.game_state_sha256, actual.node.game_state_sha256)
        self.assertNotEqual(twin.node.node_sha256, actual.node.node_sha256)
        self.bind(twin.node, max_plies=0)

        counts = dict(actual.node.history.counts)
        counts[repetition_key(actual_position)] += 1
        different_history = HistoryContext(tuple(sorted(counts.items())))
        history_twin = self.dag.append_root(actual_position, different_history)
        self.assertEqual(history_twin.node.fen, actual.node.fen)
        self.assertNotEqual(history_twin.node.node_sha256, actual.node.node_sha256)
        self.bind(history_twin.node, max_plies=0)

        missing_fact = propagate_wdl_one_hop(
            self.dag,
            self.overlay,
            parent.node.node_sha256,
        )
        self.assertEqual(missing_fact.value, WDL.UNKNOWN)
        self.assertEqual(missing_fact.reason, "missing_verified_children")
        self.assertEqual(missing_fact.missing_certificate_moves, (legal[0].uci(),))
        self.assertIsNone(self.overlay.get_binding(parent.node.node_sha256))

    def test_06_public_node_identity_covers_fullmove_and_history(self) -> None:
        position = Position.from_fen(CHECKMATE_FEN)
        history = HistoryContext.initial(position)
        later = Position.from_fen(CHECKMATE_FEN.rsplit(" ", 1)[0] + " 2")
        repeated = HistoryContext(((repetition_key(position), 2),))

        base = node_identity_sha256(position, history)
        self.assertNotEqual(base, node_identity_sha256(later, history))
        self.assertNotEqual(base, node_identity_sha256(position, repeated))
        self.assertEqual(
            game_state_sha256(position, history),
            game_state_sha256(later, history),
        )

    def test_07_ambiguous_replay_fails_closed_before_a_winning_witness(self) -> None:
        parent = self.append_root(MATE_IN_ONE_FEN)
        solved = BoundedWDLSolver().solve(
            parent.node.position,
            max_plies=1,
            history=parent.node.history,
        )
        witness = next(child.move for child in solved.root.children if child.kind == "move")
        self.assertIsNotNone(witness)
        child = self.append_child(parent, witness)  # type: ignore[arg-type]
        self.bind(child.node, max_plies=0)
        twin_fields = child.node.fen.split()
        twin_fields[-1] = str(int(twin_fields[-1]) + 1)
        twin_position = Position.from_fen(" ".join(twin_fields))
        twin = self.dag.append_root(twin_position, child.node.history)
        valid_edge = self.dag.outgoing_edges(parent.node.node_sha256)[0]
        forged_edge = replace(valid_edge, child_node_sha256=twin.node.node_sha256)

        with mock.patch.object(
            self.dag,
            "outgoing_edges",
            return_value=(valid_edge, forged_edge),
        ):
            result = propagate_wdl_one_hop(
                self.dag,
                self.overlay,
                parent.node.node_sha256,
            )

        self.assertEqual(result.value, WDL.UNKNOWN)
        self.assertEqual(result.reason, "ambiguous_frontier")
        self.assertEqual(result.ambiguous_moves, (witness,))
        self.assertIsNone(self.overlay.get_binding(parent.node.node_sha256))

    def test_08_composed_certificate_size_cap_returns_unknown(self) -> None:
        parent = self.append_root(ONE_MOVE_LOSS_FEN.format(halfmove=0))
        move = legal_moves(parent.node.position)[0]
        child = self.append_child(parent, move.uci())
        child_certificate = self.bind(child.node, max_plies=1)

        with mock.patch(
            "ugts_chess.wdl_propagation.MAX_CERTIFICATE_BYTES",
            len(child_certificate) - 1,
        ):
            result = propagate_wdl_one_hop(
                self.dag,
                self.overlay,
                parent.node.node_sha256,
            )

        self.assertEqual(result.value, WDL.UNKNOWN)
        self.assertEqual(result.reason, "certificate_size_limit")
        self.assertIsNone(self.overlay.get_binding(parent.node.node_sha256))


if __name__ == "__main__":
    unittest.main()
