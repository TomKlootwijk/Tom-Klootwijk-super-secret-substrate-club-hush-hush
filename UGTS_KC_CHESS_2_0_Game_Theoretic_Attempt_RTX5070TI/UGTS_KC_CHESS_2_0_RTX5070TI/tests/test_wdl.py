from __future__ import annotations

import copy
import hashlib
import unittest

from ugts_chess.game_state import HistoryContext, game_state_sha256
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import canonical_json_bytes, repetition_key
from ugts_chess.position import Position
from ugts_chess.wdl import (
    BoundedWDLSolver,
    ChildObligation,
    WDLNode,
    WDLResult,
    WDLVerificationError,
    verify_wdl_certificate,
)


class WDLTests(unittest.TestCase):
    @staticmethod
    def _rehash_root(bundle: dict[str, object]) -> dict[str, object]:
        root_hash = bundle["root_certificate_hash"]
        nodes = bundle["nodes"]
        assert isinstance(nodes, list)
        root = next(node for node in nodes if node["certificate_hash"] == root_hash)
        payload = dict(root)
        payload.pop("certificate_hash")
        new_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        root["certificate_hash"] = new_hash
        bundle["root_certificate_hash"] = new_hash
        bundle["root_state_hash"] = root["state_hash"]
        return root

    def test_01_checkmate_is_exact_loss(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        result = BoundedWDLSolver().solve(position, max_plies=0)
        self.assertTrue(result.root.exact)
        self.assertEqual(result.root.value, WDL.LOSS)
        verified = verify_wdl_certificate(result.certificate_bundle())
        self.assertTrue(verified["root_exact"])

    def test_02_stalemate_is_exact_draw(self) -> None:
        position = Position.from_fen("k7/2Q5/2K5/8/8/8/8/8 b - - 0 1")
        result = BoundedWDLSolver().solve(position, max_plies=0)
        self.assertEqual(result.root.value, WDL.DRAW)
        self.assertTrue(result.root.exact)

    def test_03_mate_in_two_closes_as_win(self) -> None:
        position = Position.from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1")
        result = BoundedWDLSolver(node_budget=200_000).solve(position, max_plies=3)
        self.assertEqual(result.root.value, WDL.WIN)
        self.assertTrue(result.root.exact)
        bundle = result.certificate_bundle()
        verified = verify_wdl_certificate(bundle)
        self.assertEqual(verified["root_value"], "win")
        self.assertEqual(verified["unreferenced_nodes"], 0)
        self.assertLess(len(bundle["nodes"]), len(result.node_store))

    def test_04_draw_claim_at_horizon_is_not_an_exact_draw(self) -> None:
        position = Position.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 100 1")
        result = BoundedWDLSolver().solve(position, max_plies=0)
        self.assertEqual(result.root.value, WDL.UNKNOWN)
        self.assertFalse(result.root.exact)
        verified = verify_wdl_certificate(result.certificate_bundle(), allow_unknown_root=True)
        self.assertFalse(verified["root_exact"])

    def test_05_tampered_certificate_hash_is_rejected(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        bundle = BoundedWDLSolver().solve(position, max_plies=0).certificate_bundle()
        tampered = copy.deepcopy(bundle)
        tampered["nodes"][0]["value"] = "win"
        with self.assertRaises(WDLVerificationError):
            verify_wdl_certificate(tampered)

    def test_06_wrong_rules_profile_is_rejected(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        bundle = BoundedWDLSolver().solve(position, max_plies=0).certificate_bundle()
        bundle["rules_profile"] = "different-chess-rules"

        with self.assertRaises(WDLVerificationError):
            verify_wdl_certificate(bundle)

    def test_07_history_counts_are_not_coerced(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        original = BoundedWDLSolver().solve(position, max_plies=0).certificate_bundle()

        for non_integer in (True, "1", 1.0):
            with self.subTest(non_integer=non_integer):
                bundle = copy.deepcopy(original)
                node = bundle["nodes"][0]
                node["history_counts"][0][1] = non_integer
                node_without_hash = dict(node)
                node_without_hash.pop("certificate_hash")
                new_hash = hashlib.sha256(canonical_json_bytes(node_without_hash)).hexdigest()
                node["certificate_hash"] = new_hash
                bundle["root_certificate_hash"] = new_hash

                with self.assertRaisesRegex(WDLVerificationError, "occurrence count must be an integer"):
                    verify_wdl_certificate(bundle)

    def test_08_bundle_bound_must_match_root_depth(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        bundle = BoundedWDLSolver().solve(position, max_plies=0).certificate_bundle()
        bundle["max_plies"] = 99

        with self.assertRaisesRegex(WDLVerificationError, "max_plies does not match root depth"):
            verify_wdl_certificate(bundle)

    def test_09_rehashed_win_with_already_ended_history_is_rejected(self) -> None:
        position = Position.from_fen("k7/2K5/1Q6/8/8/8/8/8 w - - 0 1")
        result = BoundedWDLSolver().solve(position, max_plies=1)
        self.assertEqual(result.root.value, WDL.WIN)
        self.assertTrue(result.root.exact)
        bundle = copy.deepcopy(result.certificate_bundle())
        root = next(
            node
            for node in bundle["nodes"]
            if node["certificate_hash"] == bundle["root_certificate_hash"]
        )
        current_key = repetition_key(position)
        ended_key = "0" * 64
        self.assertNotEqual(ended_key, current_key)
        forged_history = HistoryContext(
            tuple(sorted(((current_key, 1), (ended_key, 5))))
        )
        root["history_counts"] = forged_history.record()
        root["state_hash"] = game_state_sha256(position, forged_history)
        self._rehash_root(bundle)

        with self.assertRaisesRegex(
            WDLVerificationError,
            "non-current position at five occurrences",
        ):
            verify_wdl_certificate(bundle)
        with self.assertRaisesRegex(ValueError, "already ended automatically"):
            BoundedWDLSolver().solve(
                position,
                max_plies=1,
                history=forged_history,
            )

    def test_10_win_witness_rejects_rehashed_claim_records(self) -> None:
        position = Position.from_fen("k7/2K5/1Q6/8/8/8/8/8 w - - 0 1")
        bundle = copy.deepcopy(
            BoundedWDLSolver().solve(position, max_plies=1).certificate_bundle()
        )
        root = next(
            node
            for node in bundle["nodes"]
            if node["certificate_hash"] == bundle["root_certificate_hash"]
        )
        root["children"].append(
            {
                "action_id": "claim:forged:current",
                "kind": "claim",
                "move": None,
                "san": None,
                "claim_code": "forged",
                "child_state_hash": None,
                "child_value": "draw",
                "value_for_parent": "draw",
                "child_certificate_hash": None,
                "exact": True,
            }
        )
        self._rehash_root(bundle)

        with self.assertRaisesRegex(
            WDLVerificationError,
            "WIN witness coverage must not contain claim-action records",
        ):
            verify_wdl_certificate(bundle)

    def test_11_claim_records_are_canonical_and_not_set_collapsed(self) -> None:
        position = Position.from_fen(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 100 1"
        )
        original = BoundedWDLSolver().solve(
            position,
            max_plies=0,
        ).certificate_bundle()

        duplicate = copy.deepcopy(original)
        duplicate_root = next(
            node
            for node in duplicate["nodes"]
            if node["certificate_hash"] == duplicate["root_certificate_hash"]
        )
        claim = copy.deepcopy(duplicate_root["children"][0])
        claim["action_id"] = "claim:duplicate-but-semantically-identical"
        duplicate_root["children"].append(claim)
        self._rehash_root(duplicate)
        with self.assertRaisesRegex(
            WDLVerificationError,
            "canonical record",
        ):
            verify_wdl_certificate(duplicate)

        metadata_forgery = copy.deepcopy(original)
        forged_root = next(
            node
            for node in metadata_forgery["nodes"]
            if node["certificate_hash"] == metadata_forgery["root_certificate_hash"]
        )
        forged_root["children"][0]["san"] = "forged metadata"
        self._rehash_root(metadata_forgery)
        with self.assertRaisesRegex(
            WDLVerificationError,
            "canonical record",
        ):
            verify_wdl_certificate(metadata_forgery)

    def test_12_current_fivefold_uses_automatic_terminal_precedence(self) -> None:
        ongoing = Position.initial()
        ongoing_history = HistoryContext(((repetition_key(ongoing), 5),))
        draw = BoundedWDLSolver().solve(
            ongoing,
            max_plies=0,
            history=ongoing_history,
        )
        self.assertEqual(draw.root.value, WDL.DRAW)
        self.assertEqual(draw.root.terminal_code, "fivefold_repetition")
        self.assertTrue(verify_wdl_certificate(draw.certificate_bundle())["valid"])

        checkmate = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        mate_history = HistoryContext(((repetition_key(checkmate), 5),))
        loss = BoundedWDLSolver().solve(
            checkmate,
            max_plies=0,
            history=mate_history,
        )
        self.assertEqual(loss.root.value, WDL.LOSS)
        self.assertEqual(loss.root.terminal_code, "checkmate")
        self.assertTrue(verify_wdl_certificate(loss.certificate_bundle())["valid"])

    def test_13_bundle_export_rejects_cycle_missing_child_and_duplicate_hash(self) -> None:
        position = Position.from_fen("k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")
        history = HistoryContext.initial(position)

        def fake_node(certificate_hash: str, child_hash: str | None) -> WDLNode:
            children = ()
            if child_hash is not None:
                children = (
                    ChildObligation(
                        action_id="move:a1a2",
                        kind="move",
                        move="a1a2",
                        child_certificate_hash=child_hash,
                    ),
                )
            return WDLNode(
                state_hash=game_state_sha256(position, history),
                fen=position.to_fen(),
                history_counts=history.counts,
                depth_remaining=1,
                value=WDL.UNKNOWN,
                terminal_code="fabricated-test-node",
                current_claim_actions=(),
                legal_move_count=1,
                coverage="cutoff",
                children=children,
                exact=False,
                certificate_hash=certificate_hash,
            )

        hash_a = "a" * 64
        hash_b = "b" * 64
        hash_c = "c" * 64
        cyclic_a = fake_node(hash_a, hash_b)
        cyclic_b = fake_node(hash_b, hash_a)
        cycle = WDLResult(cyclic_a, 0, 0, 0, 0.0, 1, (cyclic_a, cyclic_b))
        with self.assertRaisesRegex(ValueError, "cycle"):
            cycle.certificate_bundle()

        missing = fake_node(hash_a, hash_c)
        missing_result = WDLResult(missing, 0, 0, 0, 0.0, 1, (missing,))
        with self.assertRaisesRegex(ValueError, "missing child"):
            missing_result.certificate_bundle()

        duplicate_a = fake_node(hash_a, None)
        duplicate_b = fake_node(hash_a, hash_b)
        duplicate = WDLResult(
            duplicate_a,
            0,
            0,
            0,
            0.0,
            1,
            (duplicate_a, duplicate_b),
        )
        with self.assertRaisesRegex(ValueError, "duplicate certificate hash"):
            duplicate.certificate_bundle()


if __name__ == "__main__":
    unittest.main()
