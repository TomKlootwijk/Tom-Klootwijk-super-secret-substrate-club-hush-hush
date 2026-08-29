from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ugts_chess.endgame_fact_adapter import (
    BundledEndgameFactAdapter,
    EndgameFactLimits,
    EndgameTablebaseError,
    MAX_NODE_BUDGET,
    MAX_PLIES,
    append_bundled_endgame_fact,
)
from ugts_chess.game_state import HistoryContext
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import canonical_json_bytes, repetition_key
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.rules import apply_uci
from ugts_chess.tablebase import (
    KXKTablebase,
    TablebaseProbe,
    encode_state,
    normalize_kxk_position,
)
from ugts_chess.wdl import BoundedWDLSolver
from ugts_chess.wdl_fact_journal import MAX_CERTIFICATE_BYTES, WDLFactJournal
from ugts_chess.wdl_fact_journal import WDLFactConflictError


KQK_MATE_IN_TWO = "8/8/8/8/8/k7/8/1QK5 w - - {halfmove} {fullmove}"
KQK_CHECKMATE = "k7/1Q6/2K5/8/8/8/8/8 b - - {halfmove} 1"
KRK_CHECKMATE = "8/8/8/8/8/R7/8/k1K5 b - - {halfmove} 1"
KQK_CAPTURE_DRAW = "8/8/8/8/2k5/2Q5/8/K7 b - - 0 1"


class EndgameFactAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.dag = ProofDAG(root / "proof.sqlite3", root / "proof.frontier")
        self.journal = WDLFactJournal(root / "facts.v2", self.dag)

    def tearDown(self) -> None:
        self.journal.close()
        self.dag.close()
        self.temporary.cleanup()

    def append_root(
        self,
        fen: str,
        *,
        history: HistoryContext | None = None,
    ):
        position = Position.from_fen(fen)
        actual_history = HistoryContext.initial(position) if history is None else history
        return self.dag.append_root(position, actual_history)

    @staticmethod
    def limits(**changes: int) -> EndgameFactLimits:
        values = {
            "node_budget": 250_000,
            "max_plies": 3,
            "max_certificate_bytes": 64 * 1024 * 1024,
        }
        values.update(changes)
        return EndgameFactLimits(**values)

    def test_01_kqk_probe_becomes_independently_replayable_seed(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=7))
        result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            target.node.node_sha256,
            limits=self.limits(),
        )

        self.assertTrue(result.promoted)
        self.assertEqual(result.status, "promoted")
        self.assertEqual(result.value, WDL.WIN)
        self.assertEqual(result.material, "KQK")
        self.assertEqual((result.tablebase_outcome, result.tablebase_dtm_plies), ("win", 3))
        self.assertEqual(result.search_max_plies, 3)
        self.assertGreater(result.nodes_searched or 0, 0)
        self.assertEqual(len(result.tablebase_transport_sha256 or ""), 64)

        entries = tuple(self.journal.iter_entries())
        self.assertEqual(len(entries), 1)
        fact = entries[0].fact
        self.assertEqual(fact.kind, "seed")
        self.assertEqual(fact.claimed_wdl, WDL.WIN)
        self.assertEqual(self.dag.get_node(target.node.node_sha256).wdl, WDL.UNKNOWN)
        bundle = json.loads(fact.seed_certificate_bytes)
        root_record = next(
            node
            for node in bundle["nodes"]
            if node["certificate_hash"] == bundle["root_certificate_hash"]
        )
        self.assertEqual(root_record["fen"], target.node.fen)
        self.assertEqual(root_record["history_counts"], target.node.history.record())
        self.assertEqual(root_record["state_hash"], target.node.game_state_sha256)
        self.assertTrue(self.journal.audit().valid)

        duplicate = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            target.node.node_sha256,
            limits=self.limits(node_budget=1, max_plies=0),
        )
        self.assertEqual(duplicate.status, "already_verified")
        self.assertFalse(duplicate.promoted)
        self.assertEqual(duplicate.value, WDL.WIN)
        self.assertEqual(len(tuple(self.journal.iter_entries())), 1)

    def test_02_checkmate_precedes_75_move_and_fivefold_draws(self) -> None:
        for fen in (
            KQK_CHECKMATE.format(halfmove=150),
            KRK_CHECKMATE.format(halfmove=150),
        ):
            with self.subTest(fen=fen):
                position = Position.from_fen(fen)
                history = HistoryContext(((repetition_key(position), 5),))
                target = self.append_root(fen, history=history)
                result = append_bundled_endgame_fact(
                    self.dag,
                    self.journal,
                    target.node.node_sha256,
                    limits=self.limits(max_plies=0),
                )
                self.assertEqual(result.value, WDL.LOSS)
                self.assertEqual(result.automatic_code, "checkmate")
                self.assertEqual(result.search_max_plies, 0)
                self.assertIsNone(result.tablebase_outcome)

    def test_03_automatic_75_move_and_fivefold_draws_are_seeded(self) -> None:
        seventy_five = self.append_root(
            KQK_MATE_IN_TWO.format(halfmove=150, fullmove=1)
        )
        result_75 = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            seventy_five.node.node_sha256,
            limits=self.limits(max_plies=0),
        )
        self.assertEqual(result_75.value, WDL.DRAW)
        self.assertEqual(result_75.automatic_code, "seventy_five_move")

        position = Position.from_fen(
            KQK_MATE_IN_TWO.format(halfmove=0, fullmove=2)
        )
        history = HistoryContext(((repetition_key(position), 5),))
        fivefold = self.append_root(position.to_fen(), history=history)
        result_fivefold = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            fivefold.node.node_sha256,
            limits=self.limits(max_plies=0),
        )
        self.assertEqual(result_fivefold.value, WDL.DRAW)
        self.assertEqual(result_fivefold.automatic_code, "fivefold_repetition")

        current_position = Position.from_fen(
            KQK_MATE_IN_TWO.format(halfmove=0, fullmove=10)
        )
        current_history = HistoryContext(
            ((repetition_key(current_position), 3),)
        )
        current = self.append_root(
            current_position.to_fen(),
            history=current_history,
        )
        current_result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            current.node.node_sha256,
            limits=self.limits(),
        )
        self.assertEqual(current_result.value, WDL.WIN)
        self.assertIn(
            "claim_threefold_current",
            current_result.current_claim_actions,
        )

    def test_04_bare_win_probe_cannot_override_fifty_move_claim_semantics(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=100, fullmove=1))
        result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            target.node.node_sha256,
            limits=self.limits(),
        )

        self.assertEqual(result.tablebase_outcome, "win")
        self.assertIn("claim_fifty_move_current", result.current_claim_actions)
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.value, WDL.UNKNOWN)
        self.assertEqual(result.reason, "bounded_certificate_unknown")
        self.assertIsNone(self.journal.get_fact(target.node.node_sha256))

        position = Position.from_fen(
            KQK_MATE_IN_TWO.format(halfmove=0, fullmove=11)
        )
        intended_child = apply_uci(position, "b1b5")
        intended_history = HistoryContext(
            tuple(
                sorted(
                    (
                        (repetition_key(position), 1),
                        (repetition_key(intended_child), 2),
                    )
                )
            )
        )
        intended = self.append_root(
            position.to_fen(),
            history=intended_history,
        )
        intended_result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            intended.node.node_sha256,
            limits=self.limits(),
        )
        self.assertEqual(intended_result.tablebase_outcome, "win")
        self.assertEqual(intended_result.value, WDL.UNKNOWN)
        self.assertIsNone(self.journal.get_fact(intended.node.node_sha256))

    def test_05_rule_adjusted_draw_requires_a_real_certificate(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=149, fullmove=1))
        result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            target.node.node_sha256,
            limits=self.limits(),
        )

        self.assertEqual(result.tablebase_outcome, "win")
        self.assertEqual(result.value, WDL.DRAW)
        self.assertTrue(result.promoted)
        self.assertIn("history-aware FIDE rules changed", result.detail)
        self.assertEqual(
            self.journal.effective_wdl(target.node.node_sha256),
            WDL.DRAW,
        )

    def test_06_draw_probe_and_resource_cutoffs_never_promote_unknown(self) -> None:
        draw = self.append_root(KQK_CAPTURE_DRAW)
        draw_result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            draw.node.node_sha256,
            limits=self.limits(max_plies=0),
        )
        self.assertEqual(draw_result.tablebase_outcome, "draw")
        self.assertEqual(draw_result.value, WDL.UNKNOWN)
        self.assertEqual(draw_result.reason, "bounded_certificate_unknown")

        bounded = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=3))
        budget_result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            bounded.node.node_sha256,
            limits=self.limits(node_budget=1),
        )
        self.assertEqual(budget_result.value, WDL.UNKNOWN)
        self.assertEqual(budget_result.reason, "node_budget_exhausted")
        self.assertIsNone(self.journal.get_fact(bounded.node.node_sha256))

    def test_07_unsupported_material_and_excess_dtm_are_structured_unknown(self) -> None:
        unsupported = self.append_root(Position.initial().to_fen())
        unsupported_result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            unsupported.node.node_sha256,
            limits=self.limits(),
        )
        self.assertEqual(unsupported_result.reason, "unsupported_material")

        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=4))
        depth_result = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            target.node.node_sha256,
            limits=self.limits(max_plies=2),
        )
        self.assertEqual(depth_result.reason, "ply_limit")
        self.assertEqual(depth_result.value, WDL.UNKNOWN)

    def test_08_a_lying_bare_probe_at_zero_depth_is_not_a_fact(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=5))
        normalized = normalize_kxk_position(target.node.position, "Q")
        self.assertIsNotNone(normalized)
        strong_king, strong_piece, weak_king, side, _ = normalized  # type: ignore[misc]
        lie = TablebaseProbe(
            material="KQK",
            outcome="win",
            dtm_plies=0,
            side_to_move="white",
            strong_side="white",
            exact=True,
            key=encode_state(strong_king, strong_piece, weak_king, side),
        )
        with mock.patch.object(KXKTablebase, "probe", return_value=lie):
            result = append_bundled_endgame_fact(
                self.dag,
                self.journal,
                target.node.node_sha256,
                limits=self.limits(),
            )
        self.assertEqual(result.tablebase_outcome, "win")
        self.assertEqual(result.search_max_plies, 0)
        self.assertEqual(result.value, WDL.UNKNOWN)
        self.assertIsNone(self.journal.get_fact(target.node.node_sha256))

    def test_09_foreign_exact_certificate_fails_root_binding(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=6))
        foreign_position = Position.from_fen(KQK_CHECKMATE.format(halfmove=0))
        foreign = BoundedWDLSolver(node_budget=100).solve(
            foreign_position,
            max_plies=0,
            history=HistoryContext.initial(foreign_position),
        )
        self.assertTrue(foreign.root.exact)

        with mock.patch.object(BoundedWDLSolver, "solve", return_value=foreign):
            result = append_bundled_endgame_fact(
                self.dag,
                self.journal,
                target.node.node_sha256,
                limits=self.limits(),
            )
        self.assertEqual(result.reason, "certificate_verification_failed")
        self.assertEqual(result.value, WDL.UNKNOWN)
        self.assertIsNone(self.journal.get_fact(target.node.node_sha256))

    def test_10_transport_and_certificate_size_fail_closed(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=8))
        with mock.patch(
            "ugts_chess.endgame_fact_adapter._load_bundled_tablebase",
            side_effect=EndgameTablebaseError("tampered transport"),
        ):
            unavailable = append_bundled_endgame_fact(
                self.dag,
                self.journal,
                target.node.node_sha256,
                limits=self.limits(),
            )
        self.assertEqual(unavailable.reason, "tablebase_unavailable")
        self.assertIsNone(self.journal.get_fact(target.node.node_sha256))

        too_large = append_bundled_endgame_fact(
            self.dag,
            self.journal,
            target.node.node_sha256,
            limits=self.limits(max_certificate_bytes=1),
        )
        self.assertEqual(too_large.reason, "certificate_size_limit")
        self.assertGreater(too_large.certificate_size or 0, 1)
        self.assertIsNone(self.journal.get_fact(target.node.node_sha256))

    def test_11_existing_different_valid_seed_short_circuits_safely(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=9))
        generated = BoundedWDLSolver(node_budget=250_000).solve(
            target.node.position,
            max_plies=4,
            history=target.node.history,
        )
        self.assertTrue(generated.root.exact)
        existing = self.journal.append_seed_certificate(
            target.node.node_sha256,
            canonical_json_bytes(generated.certificate_bundle()),
        )

        with mock.patch(
            "ugts_chess.endgame_fact_adapter._load_bundled_tablebase",
            side_effect=AssertionError("existing fact must short-circuit tablebase load"),
        ):
            result = BundledEndgameFactAdapter(
                self.dag,
                self.journal,
                limits=self.limits(),
            ).adapt(target.node.node_sha256)
        self.assertEqual(result.status, "already_verified")
        self.assertEqual(result.fact_content_sha256, existing.entry.content_sha256)
        self.assertEqual(len(tuple(self.journal.iter_entries())), 1)

    def test_12_limits_are_strict_and_bounded_by_the_journal(self) -> None:
        invalid = (
            {"node_budget": 0},
            {"node_budget": True},
            {"max_plies": -1},
            {"max_plies": True},
            {"max_plies": MAX_PLIES + 1},
            {"max_certificate_bytes": 0},
            {"max_certificate_bytes": MAX_CERTIFICATE_BYTES + 1},
            {"node_budget": MAX_NODE_BUDGET + 1},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValueError):
                EndgameFactLimits(**values)

    def test_13_recursive_search_failure_is_structured_unknown(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=12))
        with mock.patch.object(
            BoundedWDLSolver,
            "solve",
            side_effect=RecursionError("synthetic recursion exhaustion"),
        ):
            result = append_bundled_endgame_fact(
                self.dag,
                self.journal,
                target.node.node_sha256,
                limits=self.limits(),
            )
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.reason, "search_recursion_limit")
        self.assertIsNone(self.journal.get_fact(target.node.node_sha256))

    def test_14_conflict_result_reports_only_winning_fact_evidence(self) -> None:
        target = self.append_root(KQK_MATE_IN_TWO.format(halfmove=0, fullmove=13))
        alternate = BoundedWDLSolver(node_budget=250_000).solve(
            target.node.position,
            max_plies=4,
            history=target.node.history,
        )
        alternate_bytes = canonical_json_bytes(alternate.certificate_bundle())
        original_append = self.journal.append_seed_certificate

        def concurrent_winner(*_args: object, **_kwargs: object) -> None:
            original_append(target.node.node_sha256, alternate_bytes)
            raise WDLFactConflictError("synthetic competing writer")

        with mock.patch.object(
            self.journal,
            "append_seed_certificate",
            side_effect=concurrent_winner,
        ):
            result = append_bundled_endgame_fact(
                self.dag,
                self.journal,
                target.node.node_sha256,
                limits=self.limits(),
            )

        self.assertEqual(result.status, "already_verified")
        self.assertEqual(result.reason, "concurrent_fact_won")
        self.assertEqual(
            result.certificate_sha256,
            hashlib.sha256(alternate_bytes).hexdigest(),
        )
        self.assertIsNone(result.root_certificate_hash)
        self.assertEqual(len(tuple(self.journal.iter_entries())), 1)


if __name__ == "__main__":
    unittest.main()
