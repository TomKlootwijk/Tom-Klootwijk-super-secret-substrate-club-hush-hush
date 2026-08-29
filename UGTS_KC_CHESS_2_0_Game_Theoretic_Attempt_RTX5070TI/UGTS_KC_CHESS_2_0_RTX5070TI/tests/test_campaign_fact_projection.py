from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from ugts_chess.campaign_fact_projection import (
    CAMPAIGN_FACT_PROJECTION_SCHEMA,
    CampaignFactProjectionAuthorityError,
    CampaignFactProjectionMismatchError,
    CampaignWDLFactProjection,
    create_campaign_fact_projection,
    parse_campaign_fact_projection,
    verify_campaign_fact_projection,
)
from ugts_chess.game_state import HistoryContext
from ugts_chess.game_theory import ProofObligation, WDL, root_obligations
from ugts_chess.hashing import canonical_json_bytes
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.proof_dag_commitment import (
    ProofDAGHeadMismatchError,
    ProofDAGRollbackError,
    audit_proof_dag_head,
)
from ugts_chess.rules import apply_move, legal_moves
from ugts_chess.wdl_fact_journal import (
    FactJournalHead,
    WDLFactJournal,
    WDLFactRollbackError,
    canonical_derivation_evidence_bytes,
)


CAMPAIGN_ROOT_FEN = "k7/8/2K5/1Q6/8/8/8/8 w - - 0 1"
CAMPAIGN_MOVE = "b5b7"
MATE_IN_ONE_FEN = "k7/2K5/1Q6/8/8/8/8/8 w - - 0 1"
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


class CampaignFactProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database_path = self.root / "proof.sqlite3"
        self.frontier_path = self.root / "proof.frontier"
        self.fact_path = self.root / "facts.v2"
        self.dag = ProofDAG(self.database_path, self.frontier_path)
        self.journal = WDLFactJournal(self.fact_path, self.dag)

        self.campaign_root = Position.from_fen(CAMPAIGN_ROOT_FEN)
        self.campaign_history = HistoryContext.initial(self.campaign_root)
        self.obligation = next(
            item
            for item in root_obligations(
                self.campaign_root,
                self.campaign_history,
            )
            if item.move_uci == CAMPAIGN_MOVE
        )
        child = Position.from_fen(self.obligation.child_fen, strict=True)
        child_history = HistoryContext(self.obligation.child_history_counts)
        self.target = self.dag.append_root(
            child,
            child_history,
            lineage={"fixture": "campaign-child"},
        )

    def tearDown(self) -> None:
        self.journal.close()
        self.dag.close()
        self.temporary.cleanup()

    @staticmethod
    def _terminal_evidence(code: str, value: WDL) -> bytes:
        return canonical_derivation_evidence_bytes(
            root_value=value,
            proof_height=0,
            derivation_code=code,
            move_dependencies=(),
        )

    def _append_target_fact(self):
        return self.journal.append_derivation(
            self.target.node.node_sha256,
            self._terminal_evidence("checkmate", WDL.LOSS),
        ).entry

    def _create(self) -> CampaignWDLFactProjection:
        return create_campaign_fact_projection(
            campaign_root=self.campaign_root,
            campaign_root_history=self.campaign_history,
            obligation=self.obligation,
            dag=self.dag,
            journal=self.journal,
        )

    def _verify(
        self,
        projection: CampaignWDLFactProjection | bytes,
        *,
        obligation: ProofObligation | None = None,
    ):
        return verify_campaign_fact_projection(
            projection,
            campaign_root=self.campaign_root,
            campaign_root_history=self.campaign_history,
            obligation=self.obligation if obligation is None else obligation,
            dag=self.dag,
            journal=self.journal,
        )

    def _append_terminal_root(
        self,
        fen: str,
        *,
        code: str,
        value: WDL,
        lineage: object,
    ):
        position = Position.from_fen(fen)
        appended = self.dag.append_root(
            position,
            HistoryContext.initial(position),
            lineage=lineage,
        )
        fact = self.journal.append_derivation(
            appended.node.node_sha256,
            self._terminal_evidence(code, value),
        ).entry
        return appended, fact

    def test_01_canonical_receipt_verifies_and_accepts_later_extensions(self) -> None:
        target_fact = self._append_target_fact()
        projection = self._create()

        self.assertEqual(
            projection.fact_journal_head.record_count,
            target_fact.record_index + 1,
        )
        self.assertEqual(
            projection.fact_journal_head.head_content_sha256,
            target_fact.content_sha256,
        )
        self.assertEqual(
            projection.fact_journal_head.file_size,
            target_fact.frame_end_offset,
        )
        self.assertEqual(projection.claimed_wdl, WDL.LOSS)
        self.assertEqual(
            projection.record()["schema"],
            CAMPAIGN_FACT_PROJECTION_SCHEMA,
        )
        self.assertEqual(
            CampaignWDLFactProjection.from_bytes(projection.canonical_bytes()),
            projection,
        )
        self.assertEqual(
            parse_campaign_fact_projection(projection.canonical_bytes()),
            projection,
        )
        self.assertNotIn(b"certificate_base64", projection.canonical_bytes())

        later_position = Position.from_fen(STALEMATE_FEN)
        later = self.dag.append_root(
            later_position,
            HistoryContext.initial(later_position),
            lineage={"fixture": "later-dag-only-extension"},
        )
        dag_only_verified = self._verify(projection)
        self.assertGreater(
            dag_only_verified.current_proof_dag_head.frontier_record_count,
            projection.proof_dag_head.frontier_record_count,
        )
        self.assertEqual(
            dag_only_verified.current_fact_journal_head.record_count,
            projection.fact_journal_head.record_count,
        )

        self.journal.append_derivation(
            later.node.node_sha256,
            self._terminal_evidence("stalemate", WDL.DRAW),
        )
        verified = self._verify(projection)
        self.assertEqual(verified.claimed_wdl, WDL.LOSS)
        self.assertEqual(verified.fact_record_index, target_fact.record_index)
        self.assertEqual(verified.fact_content_sha256, target_fact.content_sha256)
        self.assertGreater(
            verified.current_proof_dag_head.frontier_record_count,
            projection.proof_dag_head.frontier_record_count,
        )
        self.assertGreater(
            verified.current_fact_journal_head.record_count,
            projection.fact_journal_head.record_count,
        )

    def test_02_exact_obligation_node_history_and_wdl_are_reconstructed(self) -> None:
        self._append_target_fact()
        projection = self._create()

        with self.assertRaisesRegex(
            CampaignFactProjectionMismatchError,
            "fact WDL",
        ):
            self._verify(replace(projection, claimed_wdl=WDL.WIN))

        receipt_substitutions = {
            "root": replace(
                projection,
                campaign_root_identity_sha256="0" * 64,
            ),
            "node": replace(projection, child_node_sha256="1" * 64),
            "game_state": replace(
                projection,
                child_game_state_sha256="2" * 64,
            ),
        }
        for name, substituted in receipt_substitutions.items():
            with self.subTest(receipt_field=name):
                with self.assertRaises(CampaignFactProjectionMismatchError):
                    self._verify(substituted)

        other_obligation = next(
            item
            for item in root_obligations(
                self.campaign_root,
                self.campaign_history,
            )
            if item.move_uci != self.obligation.move_uci
        )
        with self.assertRaises(CampaignFactProjectionMismatchError):
            self._verify(projection, obligation=other_obligation)

        fullmove_twin = replace(
            self.obligation,
            child_fen=self.obligation.child_fen.rsplit(" ", 1)[0] + " 42",
        )
        with self.assertRaisesRegex(ValueError, "exact canonical root obligation"):
            self._verify(projection, obligation=fullmove_twin)

        wrong_history = replace(
            self.obligation,
            child_history_counts=(("0" * 64, 1),),
        )
        with self.assertRaisesRegex(ValueError, "exact canonical root obligation"):
            self._verify(projection, obligation=wrong_history)

    def test_03_strict_parser_rejects_hostile_shapes_and_unknown(self) -> None:
        self._append_target_fact()
        projection = self._create()
        record = projection.record()
        fact_head = dict(record["fact_journal_head"])  # type: ignore[arg-type]

        hostile = {
            "leading_whitespace": b" " + projection.canonical_bytes(),
            "wrong_schema": canonical_json_bytes(
                {**record, "schema": "ugts-chess-campaign-wdl-fact-projection-9.0"}
            ),
            "unknown": canonical_json_bytes({**record, "claimed_wdl": "unknown"}),
            "uppercase_hash": canonical_json_bytes(
                {
                    **record,
                    "child_node_sha256": projection.child_node_sha256.upper(),
                }
            ),
            "boolean_count": canonical_json_bytes(
                {
                    **record,
                    "fact_journal_head": {**fact_head, "record_count": True},
                }
            ),
            "extra": canonical_json_bytes({**record, "extra": 1}),
            "missing": canonical_json_bytes(
                {key: value for key, value in record.items() if key != "obligation_id"}
            ),
        }
        for name, encoded in hostile.items():
            with self.subTest(name=name):
                with self.assertRaises((TypeError, ValueError)):
                    parse_campaign_fact_projection(encoded)
        with self.assertRaises(TypeError):
            parse_campaign_fact_projection("not bytes")  # type: ignore[arg-type]

    def test_04_cross_binding_rejects_fact_dependency_after_embedded_dag_head(self) -> None:
        parent_position = Position.from_fen(MATE_IN_ONE_FEN)
        parent_history = HistoryContext.initial(parent_position)
        move = next(move for move in legal_moves(parent_position) if move.uci() == "b6b7")
        child_position = apply_move(parent_position, move)
        child_history = parent_history.push(child_position)
        child_first = self.dag.append_root(
            child_position,
            child_history,
            lineage={"fixture": "derived-child-first"},
        )
        child_fact = self.journal.append_derivation(
            child_first.node.node_sha256,
            self._terminal_evidence("checkmate", WDL.LOSS),
        ).entry
        parent = self.dag.append_root(
            parent_position,
            parent_history,
            lineage={"fixture": "derived-parent"},
        )
        # This valid retained head contains every fact's first node occurrence,
        # but not the later exact parent->child occurrence named by the compact
        # derivation.  A verifier that checks only first occurrences would
        # therefore accept the forged head pair.
        short_dag_head = audit_proof_dag_head(self.dag)
        child = self.dag.append_move(
            child_position,
            child_history,
            parent_frontier_content_sha256=parent.edge.frontier_content_sha256,
            uci=move.uci(),
            lineage={"fixture": "derived-child"},
        )
        self.assertEqual(child.node.node_sha256, child_first.node.node_sha256)
        self.assertLess(
            child_first.edge.frontier_record_index,
            short_dag_head.frontier_record_count,
        )
        self.assertGreaterEqual(
            child.edge.frontier_record_index,
            short_dag_head.frontier_record_count,
        )
        dependency = {
            "uci": move.uci(),
            "dag_edge_record_index": child.edge.frontier_record_index,
            "dag_edge_content_sha256": child.edge.frontier_content_sha256,
            "child_node_sha256": child.node.node_sha256,
            "fact_record_index": child_fact.record_index,
            "fact_content_sha256": child_fact.content_sha256,
            "child_wdl": child_fact.fact.claimed_wdl.value,
            "child_proof_height": child_fact.fact.proof_height,
        }
        parent_fact = self.journal.append_derivation(
            parent.node.node_sha256,
            canonical_derivation_evidence_bytes(
                root_value=WDL.WIN,
                proof_height=1,
                derivation_code="winning_move_witness",
                move_dependencies=(dependency,),
            ),
        ).entry
        self._append_target_fact()
        projection = self._create()
        self.assertGreater(
            projection.proof_dag_head.frontier_record_count,
            short_dag_head.frontier_record_count,
        )

        forged_pair = replace(projection, proof_dag_head=short_dag_head)
        with self.assertRaisesRegex(
            CampaignFactProjectionAuthorityError,
            "derivation dependency lies beyond the embedded DAG head",
        ):
            self._verify(forged_pair)

        unrelated_fact_head = FactJournalHead(
            rule_profile_id=parent_fact.fact.rule_profile_id,
            record_count=parent_fact.record_index + 1,
            head_content_sha256=parent_fact.content_sha256,
            file_size=parent_fact.frame_end_offset,
        )
        with self.assertRaises(CampaignFactProjectionMismatchError):
            self._verify(
                replace(
                    projection,
                    fact_journal_head=unrelated_fact_head,
                )
            )

    def test_05_clean_fact_rollback_is_rejected(self) -> None:
        _, prefix_fact = self._append_terminal_root(
            STALEMATE_FEN,
            code="stalemate",
            value=WDL.DRAW,
            lineage={"fixture": "prefix-fact"},
        )
        self._append_target_fact()
        projection = self._create()
        self.journal.close()
        with self.fact_path.open("r+b", buffering=0) as stream:
            stream.truncate(prefix_fact.frame_end_offset)
            stream.flush()
        self.journal = WDLFactJournal(self.fact_path, self.dag)

        with self.assertRaises(WDLFactRollbackError):
            self._verify(projection)

    def test_06_clean_dag_rollback_is_rejected(self) -> None:
        self._append_target_fact()
        prefix_end = self.target.edge.frame_end_offset
        extra = Position.from_fen(STALEMATE_FEN)
        self.dag.append_root(
            extra,
            HistoryContext.initial(extra),
            lineage={"fixture": "dag-only-extension"},
        )
        projection = self._create()
        self.journal.close()
        self.dag.close()
        with self.frontier_path.open("r+b", buffering=0) as stream:
            stream.truncate(prefix_end)
            stream.flush()
        for suffix in ("", "-wal", "-shm"):
            Path(f"{self.database_path}{suffix}").unlink(missing_ok=True)
        self.dag = ProofDAG(self.database_path, self.frontier_path)
        self.journal = WDLFactJournal(self.fact_path, self.dag)

        with self.assertRaises(ProofDAGRollbackError):
            self._verify(projection)

    def test_07_same_size_dag_prefix_rewrite_is_rejected(self) -> None:
        self._append_target_fact()
        extra = Position.from_fen(STALEMATE_FEN)
        self.dag.append_root(
            extra,
            HistoryContext.initial(extra),
            lineage={"variant": "a"},
        )
        projection = self._create()

        alternate_root = self.root / "alternate"
        alternate_root.mkdir()
        alternate_dag = ProofDAG(
            alternate_root / "proof.sqlite3",
            alternate_root / "proof.frontier",
        )
        alternate_journal: WDLFactJournal | None = None
        try:
            alternate_target = alternate_dag.append_root(
                self.target.node.position,
                self.target.node.history,
                lineage={"fixture": "campaign-child"},
            )
            alternate_dag.append_root(
                extra,
                HistoryContext.initial(extra),
                lineage={"variant": "b"},
            )
            alternate_journal = WDLFactJournal(
                alternate_root / "facts.v2",
                alternate_dag,
            )
            alternate_journal.append_derivation(
                alternate_target.node.node_sha256,
                self._terminal_evidence("checkmate", WDL.LOSS),
            )
            self.assertEqual(
                projection.proof_dag_head.frontier_size,
                audit_proof_dag_head(alternate_dag).frontier_size,
            )
            with self.assertRaises(ProofDAGHeadMismatchError):
                verify_campaign_fact_projection(
                    projection,
                    campaign_root=self.campaign_root,
                    campaign_root_history=self.campaign_history,
                    obligation=self.obligation,
                    dag=alternate_dag,
                    journal=alternate_journal,
                )
        finally:
            if alternate_journal is not None:
                alternate_journal.close()
            alternate_dag.close()

    def test_08_schema_accepts_canonical_transport_and_rejects_unknown(self) -> None:
        try:
            import jsonschema
        except ModuleNotFoundError:
            self.skipTest("jsonschema is available in the validation environment only")

        self._append_target_fact()
        projection = self._create()
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "spec"
                / "ugts_chess_campaign_fact_projection.schema.json"
            ).read_text(encoding="utf-8")
        )
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(projection.record(), schema)

        # Draft 2020-12 has no portable sibling-value equality keyword.  The
        # transport schema therefore validates field shapes, while the runtime
        # canonical head parser enforces edge-count equality and all other
        # cross-field invariants.
        cross_field_forgery = projection.record()
        dag_head = dict(cross_field_forgery["proof_dag_head"])  # type: ignore[arg-type]
        dag_head["sqlite_edge_count"] = int(dag_head["sqlite_edge_count"]) + 1
        cross_field_forgery["proof_dag_head"] = dag_head
        jsonschema.validate(cross_field_forgery, schema)
        with self.assertRaises(ValueError):
            parse_campaign_fact_projection(
                canonical_json_bytes(cross_field_forgery)
            )

        unknown = projection.record()
        unknown["claimed_wdl"] = WDL.UNKNOWN.value
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(unknown, schema)


if __name__ == "__main__":
    unittest.main()
