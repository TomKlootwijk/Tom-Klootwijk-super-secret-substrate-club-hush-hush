from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

from ugts_chess.game_state import HistoryContext
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import canonical_json_bytes
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.rules import apply_move, legal_moves
from ugts_chess.verified_overlay import VerifiedCertificateOverlay
from ugts_chess.wdl import BoundedWDLSolver
from ugts_chess.wdl_fact_journal import (
    RECORD_MAGIC,
    RECORD_PREFIX_SIZE,
    FactJournalHead,
    WDLFactCommitError,
    WDLFactConflictError,
    WDLFactJournal,
    WDLFactJournalError,
    WDLFactJournalIntegrityError,
    WDLFactJournalRecoveryError,
    WDLFactJournalWriterLockedError,
    WDLFactRollbackError,
    canonical_derivation_evidence_bytes,
    migrate_verified_overlay_v1,
    recover_wdl_fact_journal,
    verify_wdl_fact_journal,
)


CHECKMATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"
MATE_IN_ONE_FEN = "k7/2K5/1Q6/8/8/8/8/8 w - - 0 1"


class WDLFactJournalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dag = ProofDAG(self.root / "proof.sqlite3", self.root / "proof.frontier")
        self.journals: list[WDLFactJournal] = []
        self.overlays: list[VerifiedCertificateOverlay] = []

    def tearDown(self) -> None:
        for journal in reversed(self.journals):
            journal.close()
        for overlay in reversed(self.overlays):
            overlay.close()
        self.dag.close()
        self.temporary.cleanup()

    def make_journal(
        self,
        name: str = "facts.v2",
        *,
        required_head: FactJournalHead | None = None,
    ) -> WDLFactJournal:
        journal = WDLFactJournal(
            self.root / name,
            self.dag,
            required_head=required_head,
        )
        self.journals.append(journal)
        return journal

    def make_overlay(self, name: str = "verified.v1") -> VerifiedCertificateOverlay:
        overlay = VerifiedCertificateOverlay(self.root / name, self.dag)
        self.overlays.append(overlay)
        return overlay

    def append_root(self, fen: str, *, lineage: object = None):
        position = Position.from_fen(fen)
        return self.dag.append_root(
            position,
            HistoryContext.initial(position),
            lineage=lineage,
        )

    def append_child(self, parent, uci: str):
        move = next(move for move in legal_moves(parent.node.position) if move.uci() == uci)
        child_position = apply_move(parent.node.position, move)
        child_history = parent.node.history.push(child_position)
        return self.dag.append_move(
            child_position,
            child_history,
            parent_frontier_content_sha256=parent.edge.frontier_content_sha256,
            uci=uci,
        )

    @staticmethod
    def certificate(node, *, max_plies: int = 0) -> bytes:
        result = BoundedWDLSolver(node_budget=200_000).solve(
            node.position,
            max_plies=max_plies,
            history=node.history,
        )
        if not result.root.exact:
            raise AssertionError("test fixture did not produce an exact certificate")
        return canonical_json_bytes(result.certificate_bundle())

    @staticmethod
    def rewrite_last_frame(path: Path, entry, transform) -> None:
        """Rewrite one final frame with valid physical SHA/CRC protection."""

        with path.open("r+b", buffering=0) as stream:
            stream.seek(entry.frame_offset)
            prefix = stream.read(RECORD_PREFIX_SIZE)
            magic, payload_length = struct.unpack(">4sQ", prefix)
            if magic != RECORD_MAGIC:
                raise AssertionError("test fixture frame magic mismatch")
            raw = json.loads(stream.read(payload_length))
            transform(raw)
            payload = canonical_json_bytes(raw)
            new_prefix = struct.pack(">4sQ", RECORD_MAGIC, len(payload))
            digest = hashlib.sha256(payload).digest()
            crc = zlib.crc32(new_prefix)
            crc = zlib.crc32(payload, crc)
            crc = zlib.crc32(digest, crc) & 0xFFFFFFFF
            stream.seek(entry.frame_offset)
            stream.write(new_prefix + payload + digest + struct.pack(">I", crc))
            stream.truncate()
            stream.flush()

    def make_win_derivation_fixture(self, journal: WDLFactJournal):
        parent = self.append_root(MATE_IN_ONE_FEN, lineage={"kind": "parent"})
        solved = BoundedWDLSolver(node_budget=200_000).solve(
            parent.node.position,
            max_plies=1,
            history=parent.node.history,
        )
        self.assertTrue(solved.root.exact)
        self.assertEqual(solved.root.value, WDL.WIN)
        witness = next(
            child.move
            for child in solved.root.children
            if child.kind == "move" and child.child_value == WDL.LOSS
        )
        self.assertIsNotNone(witness)
        child = self.append_child(parent, witness)  # type: ignore[arg-type]
        unrelated = self.append_root(STALEMATE_FEN, lineage={"kind": "unrelated"})

        unrelated_entry = journal.append_seed_certificate(
            unrelated.node.node_sha256,
            self.certificate(unrelated.node),
        ).entry
        child_entry = journal.append_seed_certificate(
            child.node.node_sha256,
            self.certificate(child.node),
        ).entry
        self.assertEqual(unrelated_entry.record_index, 0)
        self.assertEqual(child_entry.record_index, 1)
        self.assertEqual(child_entry.fact.claimed_wdl, WDL.LOSS)

        dependency = {
            "uci": witness,
            "dag_edge_record_index": child.edge.frontier_record_index,
            "dag_edge_content_sha256": child.edge.frontier_content_sha256,
            "child_node_sha256": child.node.node_sha256,
            "fact_record_index": child_entry.record_index,
            "fact_content_sha256": child_entry.content_sha256,
            "child_wdl": child_entry.fact.claimed_wdl.value,
            "child_proof_height": child_entry.fact.proof_height,
        }
        return parent, unrelated_entry, child_entry, dependency

    @staticmethod
    def derivation_bytes(dependency: dict[str, object]) -> bytes:
        return canonical_derivation_evidence_bytes(
            root_value=WDL.WIN,
            proof_height=int(dependency["child_proof_height"]) + 1,
            derivation_code="winning_move_witness",
            move_dependencies=[dependency],
        )

    def test_01_seed_append_reopen_preserves_exact_wdl_and_height(self) -> None:
        target = self.append_root(MATE_IN_ONE_FEN)
        certificate = self.certificate(target.node, max_plies=1)
        path = self.root / "facts.v2"
        journal = self.make_journal()

        appended = journal.append_seed_certificate(
            target.node.node_sha256,
            certificate,
        )
        self.assertTrue(appended.appended)
        self.assertEqual(appended.entry.fact.kind, "seed")
        self.assertEqual(appended.entry.fact.claimed_wdl, WDL.WIN)
        self.assertEqual(appended.entry.fact.proof_height, 1)
        self.assertEqual(appended.entry.fact.seed_certificate_bytes, certificate)
        self.assertEqual(journal.effective_wdl(target.node.node_sha256), WDL.WIN)
        self.assertEqual(self.dag.get_node(target.node.node_sha256).wdl, WDL.UNKNOWN)
        retained_head = journal.head_snapshot()
        journal.close()

        reopened = self.make_journal(required_head=retained_head)
        fact = reopened.get_fact(target.node.node_sha256)
        self.assertIsNotNone(fact)
        self.assertEqual(fact.claimed_wdl, WDL.WIN)  # type: ignore[union-attr]
        self.assertEqual(fact.proof_height, 1)  # type: ignore[union-attr]
        self.assertEqual(fact.seed_certificate_bytes, certificate)  # type: ignore[union-attr]
        self.assertEqual(reopened.audit().record_count, 1)
        self.assertTrue(verify_wdl_fact_journal(path, self.dag).valid)

    def test_02_v1_migration_is_deterministic_and_idempotent(self) -> None:
        mate = self.append_root(CHECKMATE_FEN, lineage={"order": 0})
        draw = self.append_root(STALEMATE_FEN, lineage={"order": 1})
        certificates = {
            mate.node.node_sha256: self.certificate(mate.node),
            draw.node.node_sha256: self.certificate(draw.node),
        }
        source = self.make_overlay()
        for target in (mate, draw):
            source.append_verified_certificate(
                target.node.node_sha256,
                certificates[target.node.node_sha256],
            )

        first = self.make_journal("first.v2")
        first_result = migrate_verified_overlay_v1(source, first)
        self.assertEqual(first_result.source_record_count, 2)
        self.assertEqual(first_result.imported_count, 2)
        self.assertEqual(first_result.already_present_count, 0)
        first.close()

        second = self.make_journal("second.v2")
        second_result = second.migrate_v1_overlay(source)
        self.assertEqual(second_result.imported_count, 2)
        before_duplicate = (self.root / "second.v2").read_bytes()
        duplicate = second.migrate_v1_overlay(source)
        self.assertEqual(duplicate.imported_count, 0)
        self.assertEqual(duplicate.already_present_count, 2)
        self.assertEqual((self.root / "second.v2").read_bytes(), before_duplicate)
        second.close()

        self.assertEqual(
            (self.root / "first.v2").read_bytes(),
            (self.root / "second.v2").read_bytes(),
        )

    def test_03_duplicate_is_idempotent_and_different_evidence_conflicts(self) -> None:
        target = self.append_root(CHECKMATE_FEN)
        certificate_0 = self.certificate(target.node, max_plies=0)
        certificate_1 = self.certificate(target.node, max_plies=1)
        self.assertNotEqual(certificate_0, certificate_1)
        journal = self.make_journal()

        first = journal.append_seed_certificate(target.node.node_sha256, certificate_0)
        duplicate = journal.append_seed_certificate(target.node.node_sha256, certificate_0)
        self.assertTrue(first.appended)
        self.assertFalse(duplicate.appended)
        self.assertEqual(first.entry.content_sha256, duplicate.entry.content_sha256)

        with self.assertRaises(WDLFactConflictError):
            journal.append_seed_certificate(target.node.node_sha256, certificate_1)
        terminal_derivation = canonical_derivation_evidence_bytes(
            root_value=WDL.LOSS,
            proof_height=0,
            derivation_code="checkmate",
            move_dependencies=[],
        )
        with self.assertRaises(WDLFactConflictError):
            journal.append_derivation(target.node.node_sha256, terminal_derivation)
        self.assertEqual(journal.audit().record_count, 1)

    def test_04_external_head_detects_clean_rollback_and_requires_exact_prefix(self) -> None:
        first_target = self.append_root(CHECKMATE_FEN, lineage={"order": 0})
        second_target = self.append_root(STALEMATE_FEN, lineage={"order": 1})
        path = self.root / "facts.v2"
        journal = self.make_journal()
        journal.append_seed_certificate(
            first_target.node.node_sha256,
            self.certificate(first_target.node),
        )
        prefix = journal.head_snapshot()
        journal.append_seed_certificate(
            second_target.node.node_sha256,
            self.certificate(second_target.node),
        )
        final = journal.head_snapshot()
        self.assertEqual(FactJournalHead.from_bytes(final.canonical_bytes()), final)
        self.assertEqual(journal.require_external_head(prefix), final)

        forged = FactJournalHead(
            final.rule_profile_id,
            final.record_count,
            "0" * 64,
            final.file_size,
        )
        with self.assertRaises(WDLFactRollbackError):
            journal.require_external_head(forged)
        with self.assertRaises(ValueError):
            FactJournalHead.from_bytes(
                canonical_json_bytes({**final.record(), "record_count": False})
            )
        journal.close()

        with path.open("r+b", buffering=0) as stream:
            stream.truncate(prefix.file_size)
        rolled_back = verify_wdl_fact_journal(path, self.dag)
        self.assertTrue(rolled_back.valid)
        self.assertEqual(rolled_back.record_count, 1)
        with self.assertRaises(WDLFactRollbackError):
            WDLFactJournal(path, self.dag, required_head=final)

        reopened = self.make_journal(required_head=prefix)
        self.assertEqual(reopened.effective_wdl(first_target.node.node_sha256), WDL.LOSS)
        self.assertEqual(reopened.effective_wdl(second_target.node.node_sha256), WDL.UNKNOWN)

    def test_05_derivation_references_exact_fact_and_edge_addresses(self) -> None:
        journal = self.make_journal()
        parent, unrelated, child, dependency = self.make_win_derivation_fixture(journal)

        substitutions = {
            "wrong_fact_index": {"fact_record_index": unrelated.record_index},
            "wrong_fact_hash": {"fact_content_sha256": unrelated.content_sha256},
            "self_reference": {"fact_record_index": 2},
            "forward_reference": {"fact_record_index": 3},
            "wrong_edge_index": {
                "dag_edge_record_index": int(dependency["dag_edge_record_index"]) - 1
            },
            "wrong_edge_hash": {"dag_edge_content_sha256": "0" * 64},
            "wrong_child_node": {"child_node_sha256": unrelated.fact.node_sha256},
        }
        for name, replacement in substitutions.items():
            with self.subTest(name=name):
                forged = dict(dependency)
                forged.update(replacement)
                with self.assertRaises(ValueError):
                    journal.append_derivation(
                        parent.node.node_sha256,
                        self.derivation_bytes(forged),
                    )

        valid = journal.append_derivation(
            parent.node.node_sha256,
            self.derivation_bytes(dependency),
        )
        self.assertTrue(valid.appended)
        self.assertEqual(valid.entry.fact.claimed_wdl, WDL.WIN)
        self.assertEqual(valid.entry.fact.proof_height, child.fact.proof_height + 1)
        self.assertEqual(journal.effective_wdl(parent.node.node_sha256), WDL.WIN)

    def test_06_checksum_rewritten_dependency_substitution_fails_replay(self) -> None:
        path = self.root / "facts.v2"
        journal = self.make_journal()
        parent, unrelated, _, dependency = self.make_win_derivation_fixture(journal)
        derived = journal.append_derivation(
            parent.node.node_sha256,
            self.derivation_bytes(dependency),
        ).entry
        journal.close()

        def substitute(raw: dict[str, object]) -> None:
            evidence = raw["evidence"]
            assert isinstance(evidence, dict)
            dependencies = evidence["move_dependencies"]
            assert isinstance(dependencies, list)
            dependency_record = dependencies[0]
            assert isinstance(dependency_record, dict)
            dependency_record["fact_record_index"] = unrelated.record_index
            raw["evidence_sha256"] = hashlib.sha256(
                canonical_json_bytes(evidence)
            ).hexdigest()

        self.rewrite_last_frame(path, derived, substitute)
        report = verify_wdl_fact_journal(path, self.dag)
        self.assertFalse(report.valid)
        self.assertIsNotNone(report.issue)
        self.assertEqual(report.issue.code, "record_semantic_invalid")  # type: ignore[union-attr]
        self.assertIn("content hash mismatch", report.issue.message)  # type: ignore[union-attr]
        with self.assertRaises(WDLFactJournalIntegrityError):
            self.make_journal()

    def test_07_complete_corruption_is_not_recovered_but_torn_tail_is_preserved(self) -> None:
        first_target = self.append_root(CHECKMATE_FEN, lineage={"order": 0})
        second_target = self.append_root(STALEMATE_FEN, lineage={"order": 1})

        corrupt_path = self.root / "corrupt.v2"
        corrupt = self.make_journal("corrupt.v2")
        entry = corrupt.append_seed_certificate(
            first_target.node.node_sha256,
            self.certificate(first_target.node),
        ).entry
        corrupt.close()
        original = corrupt_path.read_bytes()
        with corrupt_path.open("r+b", buffering=0) as stream:
            stream.seek(entry.crc32_offset)
            stored = stream.read(4)
            stream.seek(entry.crc32_offset)
            stream.write(bytes([stored[0] ^ 1]) + stored[1:])
        complete = verify_wdl_fact_journal(corrupt_path, self.dag)
        self.assertFalse(complete.valid)
        self.assertFalse(complete.issue.recoverable_tail)  # type: ignore[union-attr]
        corrupt_bytes = corrupt_path.read_bytes()
        self.assertNotEqual(corrupt_bytes, original)
        with self.assertRaises(WDLFactJournalRecoveryError):
            recover_wdl_fact_journal(corrupt_path, self.dag)
        self.assertEqual(corrupt_path.read_bytes(), corrupt_bytes)

        torn_path = self.root / "torn.v2"
        torn = self.make_journal("torn.v2")
        first = torn.append_seed_certificate(
            first_target.node.node_sha256,
            self.certificate(first_target.node),
        ).entry
        second = torn.append_seed_certificate(
            second_target.node.node_sha256,
            self.certificate(second_target.node),
        ).entry
        torn.close()
        with torn_path.open("r+b", buffering=0) as stream:
            stream.truncate(second.frame_end_offset - 5)
        incomplete_suffix = torn_path.read_bytes()[second.frame_offset :]
        before = verify_wdl_fact_journal(torn_path, self.dag)
        self.assertFalse(before.valid)
        self.assertTrue(before.issue.recoverable_tail)  # type: ignore[union-attr]

        recovered = recover_wdl_fact_journal(torn_path, self.dag)
        self.assertEqual(recovered.after.record_count, 1)
        self.assertEqual(recovered.after.last_good_offset, first.frame_end_offset)
        self.assertEqual(recovered.truncated_bytes, len(incomplete_suffix))
        self.assertEqual(recovered.preserved_suffix_path.read_bytes(), incomplete_suffix)  # type: ignore[union-attr]
        self.assertEqual(
            recovered.preserved_suffix_sha256,
            hashlib.sha256(incomplete_suffix).hexdigest(),
        )
        reopened = self.make_journal("torn.v2")
        self.assertEqual(reopened.effective_wdl(first_target.node.node_sha256), WDL.LOSS)
        self.assertEqual(reopened.effective_wdl(second_target.node.node_sha256), WDL.UNKNOWN)

    def test_08_live_full_replay_blocks_other_facts_after_same_size_corruption(self) -> None:
        first_target = self.append_root(CHECKMATE_FEN, lineage={"order": 0})
        second_target = self.append_root(STALEMATE_FEN, lineage={"order": 1})
        path = self.root / "facts.v2"
        journal = self.make_journal()
        first = journal.append_seed_certificate(
            first_target.node.node_sha256,
            self.certificate(first_target.node),
        ).entry
        journal.append_seed_certificate(
            second_target.node.node_sha256,
            self.certificate(second_target.node),
        )
        with path.open("r+b", buffering=0) as stream:
            stream.seek(first.payload_offset + 20)
            original = stream.read(1)
            stream.seek(first.payload_offset + 20)
            stream.write(bytes([original[0] ^ 1]))

        with self.assertRaises(WDLFactJournalIntegrityError):
            journal.effective_wdl(second_target.node.node_sha256)
        with self.assertRaises(WDLFactCommitError):
            journal.effective_wdl(first_target.node.node_sha256)

    def test_09_fsync_writer_lock_and_path_identity_are_fail_closed(self) -> None:
        target = self.append_root(CHECKMATE_FEN)
        certificate = self.certificate(target.node)
        path = self.root / "facts.v2"
        journal = self.make_journal()

        from ugts_chess import wdl_fact_journal as module

        with mock.patch.object(module.os, "fsync", wraps=module.os.fsync) as fsync:
            journal.append_seed_certificate(target.node.node_sha256, certificate)
        self.assertGreaterEqual(fsync.call_count, 1)
        with self.assertRaises(WDLFactJournalWriterLockedError):
            WDLFactJournal(path, self.dag)
        journal.close()

        with mock.patch.object(
            module.os.path,
            "samestat",
            side_effect=[True, False],
        ):
            report = verify_wdl_fact_journal(path, self.dag)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "path_replaced_during_read")  # type: ignore[union-attr]

        identity_path = self.root / "identity.v2"
        with mock.patch.object(module.os.path, "samestat", return_value=False):
            with self.assertRaisesRegex(WDLFactJournalError, "no longer names"):
                WDLFactJournal(identity_path, self.dag)

    def test_10_failed_post_append_readback_poison_handle_but_preserves_bytes(self) -> None:
        target = self.append_root(CHECKMATE_FEN)
        certificate = self.certificate(target.node)
        path = self.root / "facts.v2"
        journal = self.make_journal()

        from ugts_chess import wdl_fact_journal as module

        real_scan = module._scan_fact_stream
        scan_calls = 0

        def fail_second_scan(*args, **kwargs):
            nonlocal scan_calls
            scan_calls += 1
            report = real_scan(*args, **kwargs)
            if scan_calls == 2:
                raise OSError("simulated post-fsync readback failure")
            return report

        with mock.patch.object(module, "_scan_fact_stream", side_effect=fail_second_scan):
            with self.assertRaises(WDLFactCommitError):
                journal.append_seed_certificate(target.node.node_sha256, certificate)
        self.assertEqual(scan_calls, 2)
        with self.assertRaises(WDLFactCommitError):
            journal.get_fact(target.node.node_sha256)
        journal.close()

        replay = verify_wdl_fact_journal(path, self.dag)
        self.assertTrue(replay.valid)
        self.assertEqual(replay.record_count, 1)
        self.assertEqual(replay.entries[0].fact.claimed_wdl, WDL.LOSS)


if __name__ == "__main__":
    unittest.main()
