from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ugts_chess.game_state import HistoryContext
from ugts_chess.hashing import canonical_json_bytes
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.proof_dag_commitment import ProofDAGRollbackError
from ugts_chess.wdl import BoundedWDLSolver
from ugts_chess.wdl_fact_journal import WDLFactJournal
from ugts_chess.wdl_fact_replay_checkpoint import (
    CHECKPOINT_FILE_PREFIX,
    WDLFactReplayCheckpoint,
    WDLFactReplayCheckpointBusyError,
    WDLFactReplayCheckpointHead,
    WDLFactReplayCheckpointIntegrityError,
    WDLFactReplayCheckpointRollbackError,
    publish_wdl_fact_replay_checkpoint,
    verify_wdl_fact_replay_checkpoint_prefix,
)


CHECKMATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


class WDLFactReplayCheckpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dag = ProofDAG(self.root / "proof.sqlite3", self.root / "proof.frontier")
        self.fact_path = self.root / "facts.v2"
        self.checkpoint_directory = self.root / "checkpoints"
        self.journal: WDLFactJournal | None = WDLFactJournal(
            self.fact_path,
            self.dag,
        )

    def tearDown(self) -> None:
        if self.journal is not None:
            self.journal.close()
        self.dag.close()
        self.temporary.cleanup()

    def close_journal(self) -> None:
        assert self.journal is not None
        self.journal.close()
        self.journal = None

    def reopen_journal(self) -> WDLFactJournal:
        self.journal = WDLFactJournal(self.fact_path, self.dag)
        return self.journal

    def append_root(self, fen: str, order: int):
        position = Position.from_fen(fen)
        return self.dag.append_root(
            position,
            HistoryContext.initial(position),
            lineage={"order": order},
        )

    @staticmethod
    def certificate(node) -> bytes:
        result = BoundedWDLSolver(node_budget=50_000).solve(
            node.position,
            max_plies=0,
            history=node.history,
        )
        if not result.root.exact:
            raise AssertionError("terminal checkpoint fixture was not exact")
        return canonical_json_bytes(result.certificate_bundle())

    def add_seed(self, fen: str, order: int):
        assert self.journal is not None
        target = self.append_root(fen, order)
        return self.journal.append_seed_certificate(
            target.node.node_sha256,
            self.certificate(target.node),
        ).entry

    def publish_one(self):
        self.add_seed(CHECKMATE_FEN, 0)
        self.close_journal()
        return publish_wdl_fact_replay_checkpoint(
            self.checkpoint_directory,
            self.fact_path,
            self.dag,
        )

    def test_01_trusted_publish_roundtrips_and_verifies_exact_prefix(self) -> None:
        publication = self.publish_one()
        self.assertTrue(publication.created)
        self.assertEqual(
            publication.path.name,
            f"{CHECKPOINT_FILE_PREFIX}-{publication.head.checkpoint_sha256}.json",
        )
        self.assertEqual(
            hashlib.sha256(publication.path.read_bytes()).hexdigest(),
            publication.head.checkpoint_sha256,
        )
        self.assertEqual(
            WDLFactReplayCheckpoint.from_bytes(publication.path.read_bytes()),
            publication.checkpoint,
        )
        self.assertEqual(
            WDLFactReplayCheckpointHead.from_bytes(
                publication.head.canonical_bytes()
            ),
            publication.head,
        )
        self.assertEqual(len(publication.checkpoint.facts), 1)
        summary = publication.checkpoint.facts[0]
        self.assertEqual(summary.record_index, 0)
        self.assertEqual(
            summary.content_sha256,
            publication.checkpoint.fact_journal_head.head_content_sha256,
        )

        verified = verify_wdl_fact_replay_checkpoint_prefix(
            self.fact_path,
            self.dag,
            publication.path,
            publication.head,
        )
        self.assertEqual(verified.trailing_unverified_bytes, 0)
        self.assertEqual(
            verified.verified_prefix_size,
            publication.checkpoint.fact_journal_head.file_size,
        )

        repeated = publish_wdl_fact_replay_checkpoint(
            self.checkpoint_directory,
            self.fact_path,
            self.dag,
        )
        self.assertFalse(repeated.created)
        self.assertEqual(repeated.path, publication.path)
        self.assertEqual(repeated.head, publication.head)

    def test_02_append_only_suffix_is_reported_but_never_blessed(self) -> None:
        publication = self.publish_one()
        self.reopen_journal()
        self.add_seed(STALEMATE_FEN, 1)
        self.close_journal()

        verified = verify_wdl_fact_replay_checkpoint_prefix(
            self.fact_path,
            self.dag,
            publication.path,
            publication.head,
        )
        self.assertGreater(verified.trailing_unverified_bytes, 0)
        self.assertEqual(
            verified.checkpoint.fact_journal_head.record_count,
            1,
        )
        self.assertFalse(hasattr(verified, "current_fact_journal_head"))

    def test_03_same_size_sidecar_and_live_prefix_rewrites_fail_closed(self) -> None:
        publication = self.publish_one()
        original_sidecar = publication.path.read_bytes()
        mutated = bytearray(original_sidecar)
        mutated[len(mutated) // 2] ^= 1
        publication.path.write_bytes(mutated)
        with self.assertRaisesRegex(
            WDLFactReplayCheckpointIntegrityError,
            "SHA-256",
        ):
            verify_wdl_fact_replay_checkpoint_prefix(
                self.fact_path,
                self.dag,
                publication.path,
                publication.head,
            )
        publication.path.write_bytes(original_sidecar)

        with self.fact_path.open("r+b", buffering=0) as stream:
            stream.seek(publication.checkpoint.fact_journal_head.file_size // 2)
            original = stream.read(1)
            stream.seek(-1, 1)
            stream.write(bytes([original[0] ^ 1]))
            stream.flush()
        with self.assertRaisesRegex(
            WDLFactReplayCheckpointIntegrityError,
            "prefix SHA-256",
        ):
            verify_wdl_fact_replay_checkpoint_prefix(
                self.fact_path,
                self.dag,
                publication.path,
                publication.head,
            )

    def test_04_fact_rollback_and_wrong_external_head_fail_closed(self) -> None:
        publication = self.publish_one()
        forged_head = replace(publication.head, checkpoint_sha256="0" * 64)
        with self.assertRaises(WDLFactReplayCheckpointIntegrityError):
            verify_wdl_fact_replay_checkpoint_prefix(
                self.fact_path,
                self.dag,
                publication.path,
                forged_head,
            )

        with self.fact_path.open("r+b", buffering=0) as stream:
            stream.truncate(publication.checkpoint.fact_journal_head.file_size - 1)
        with self.assertRaises(WDLFactReplayCheckpointRollbackError):
            verify_wdl_fact_replay_checkpoint_prefix(
                self.fact_path,
                self.dag,
                publication.path,
                publication.head,
            )

    def test_05_proof_dag_rollback_is_rejected_by_exact_prefix_head(self) -> None:
        publication = self.publish_one()
        alternate = ProofDAG(
            self.root / "other.sqlite3",
            self.root / "other.frontier",
        )
        try:
            with self.assertRaises(ProofDAGRollbackError):
                verify_wdl_fact_replay_checkpoint_prefix(
                    self.fact_path,
                    alternate,
                    publication.path,
                    publication.head,
                )
        finally:
            alternate.close()

    def test_06_builder_requires_exclusive_source_and_full_valid_replay(self) -> None:
        self.add_seed(CHECKMATE_FEN, 0)
        with self.assertRaises(WDLFactReplayCheckpointBusyError):
            publish_wdl_fact_replay_checkpoint(
                self.checkpoint_directory,
                self.fact_path,
                self.dag,
            )
        self.close_journal()
        with self.fact_path.open("r+b", buffering=0) as stream:
            stream.seek(-1, 2)
            original = stream.read(1)
            stream.seek(-1, 2)
            stream.write(bytes([original[0] ^ 1]))
        with self.assertRaisesRegex(
            WDLFactReplayCheckpointIntegrityError,
            "valid full fact replay",
        ):
            publish_wdl_fact_replay_checkpoint(
                self.checkpoint_directory,
                self.fact_path,
                self.dag,
            )

    def test_07_publication_fsyncs_and_readback_precedes_anchor_return(self) -> None:
        self.add_seed(CHECKMATE_FEN, 0)
        self.close_journal()
        from ugts_chess import wdl_fact_replay_checkpoint as module

        with mock.patch.object(module.os, "fsync", wraps=module.os.fsync) as fsync:
            publication = publish_wdl_fact_replay_checkpoint(
                self.checkpoint_directory,
                self.fact_path,
                self.dag,
            )
        self.assertGreaterEqual(fsync.call_count, 1)
        self.assertTrue(publication.path.exists())

        with mock.patch.object(
            module,
            "_load_authenticated_checkpoint",
            side_effect=WDLFactReplayCheckpointIntegrityError("readback failed"),
        ):
            with self.assertRaises(WDLFactReplayCheckpointIntegrityError):
                publish_wdl_fact_replay_checkpoint(
                    self.root / "second-checkpoints",
                    self.fact_path,
                    self.dag,
                )

    def test_08_schema_accepts_canonical_body_and_head(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is available in the validation environment only")
        publication = self.publish_one()
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "spec"
            / "ugts_chess_wdl_fact_replay_checkpoint_v1.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(publication.checkpoint.record(), schema)
        jsonschema.validate(publication.head.record(), schema)
        forged = publication.head.record()
        forged["checkpoint_size"] = True
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(forged, schema)


if __name__ == "__main__":
    unittest.main()
