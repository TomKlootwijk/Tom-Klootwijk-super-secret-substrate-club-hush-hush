from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ugts_chess.game_state import HistoryContext
from ugts_chess.hashing import canonical_json_bytes
from ugts_chess.position import Position
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.verified_overlay import (
    OverlayHeadCommitment,
    OverlayRecordCommitment,
    VerifiedCertificateOverlay,
    VerifiedOverlayHeadMismatchError,
    VerifiedOverlayReferenceError,
)
from ugts_chess.wdl import BoundedWDLSolver


CHECKMATE_FEN = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


class OverlayCommitmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.dag = ProofDAG(self.root / "proof.sqlite3", self.root / "proof.frontier")
        self.overlay_path = self.root / "verified.overlay"
        self.overlay = VerifiedCertificateOverlay(self.overlay_path, self.dag)

    def tearDown(self) -> None:
        self.overlay.close()
        self.dag.close()
        self.temporary.cleanup()

    def bind(self, fen: str, *, lineage: object = None):
        position = Position.from_fen(fen)
        history = HistoryContext.initial(position)
        appended = self.dag.append_root(position, history, lineage=lineage)
        result = BoundedWDLSolver().solve(position, max_plies=0, history=history)
        self.assertTrue(result.root.exact)
        certificate = canonical_json_bytes(result.certificate_bundle())
        overlay_result = self.overlay.append_verified_certificate(
            appended.node.node_sha256,
            certificate,
        )
        return appended, overlay_result

    def reopen_overlay(self) -> None:
        self.overlay.close()
        self.overlay = VerifiedCertificateOverlay(self.overlay_path, self.dag)

    def test_01_canonical_commitments_are_stable_across_restart(self) -> None:
        empty = self.overlay.audited_snapshot()
        self.assertEqual(empty.head.record_count, 0)
        self.assertIsNone(empty.head.head_record_sha256)
        self.assertEqual(empty.head.journal_size_bytes, empty.header_size)
        self.assertEqual(
            OverlayHeadCommitment.from_canonical_bytes(
                empty.head.canonical_bytes()
            ),
            empty.head,
        )

        target, _ = self.bind(CHECKMATE_FEN)
        before = self.overlay.audited_snapshot()
        self.assertEqual(before.head.record_count, 1)
        self.assertEqual(len(before.records), 1)
        commitment = before.records[0].commitment
        self.assertEqual(commitment.node_sha256, target.node.node_sha256)
        self.assertEqual(
            OverlayRecordCommitment.from_canonical_bytes(
                commitment.canonical_bytes()
            ),
            commitment,
        )
        self.assertEqual(
            canonical_json_bytes(json.loads(commitment.canonical_bytes())),
            commitment.canonical_bytes(),
        )

        head_bytes = before.head.canonical_bytes()
        record_bytes = commitment.canonical_bytes()
        self.reopen_overlay()
        after = self.overlay.audited_snapshot()
        self.assertEqual(after.head.canonical_bytes(), head_bytes)
        self.assertEqual(after.records[0].commitment.canonical_bytes(), record_bytes)

    def test_02_audited_snapshot_performs_exactly_one_live_replay(self) -> None:
        self.bind(CHECKMATE_FEN)
        with mock.patch.object(
            self.overlay,
            "_replay_live_journal",
            wraps=self.overlay._replay_live_journal,
        ) as replay:
            snapshot = self.overlay.audited_snapshot()
        self.assertEqual(replay.call_count, 1)
        self.assertEqual(snapshot.head.record_count, 1)

    def test_03_reference_resolution_requires_exact_index_hash_and_semantics(self) -> None:
        mate, _ = self.bind(CHECKMATE_FEN, lineage={"record": 0})
        draw, _ = self.bind(STALEMATE_FEN, lineage={"record": 1})
        snapshot = self.overlay.audited_snapshot()
        first = snapshot.records[0].commitment
        second = snapshot.records[1].commitment

        resolved = snapshot.resolve_reference(first.canonical_bytes())
        self.assertEqual(resolved.binding.node_sha256, mate.node.node_sha256)
        self.assertEqual(
            snapshot.reference_for_node(draw.node.node_sha256),
            second,
        )

        wrong_hash = first.record()
        wrong_hash["record_content_sha256"] = second.record_content_sha256
        with self.assertRaisesRegex(VerifiedOverlayReferenceError, "do not match"):
            snapshot.resolve_reference(canonical_json_bytes(wrong_hash))

        wrong_index = first.record()
        wrong_index["record_index"] = 1
        wrong_index["previous_record_sha256"] = first.record_content_sha256
        with self.assertRaisesRegex(VerifiedOverlayReferenceError, "do not match"):
            snapshot.resolve_reference(canonical_json_bytes(wrong_index))

        wrong_semantics = first.record()
        wrong_semantics["node_sha256"] = second.node_sha256
        with self.assertRaisesRegex(VerifiedOverlayReferenceError, "do not match"):
            snapshot.resolve_reference(canonical_json_bytes(wrong_semantics))

    def test_04_reference_bytes_are_strictly_canonical_and_noncoercive(self) -> None:
        self.bind(CHECKMATE_FEN)
        snapshot = self.overlay.audited_snapshot()
        reference = snapshot.records[0].commitment

        with self.assertRaisesRegex(ValueError, "canonical JSON"):
            snapshot.resolve_reference(reference.canonical_bytes() + b"\n")

        boolean_index = reference.record()
        boolean_index["record_index"] = False
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            snapshot.resolve_reference(canonical_json_bytes(boolean_index))

        extra = reference.record()
        extra["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "missing or unexpected"):
            snapshot.resolve_reference(canonical_json_bytes(extra))

    def test_05_prefix_head_and_anchor_bounds_survive_extension(self) -> None:
        first_target, _ = self.bind(CHECKMATE_FEN, lineage={"record": 0})
        prefix = self.overlay.audited_snapshot()
        first_reference = prefix.records[0].commitment

        second_target, _ = self.bind(STALEMATE_FEN, lineage={"record": 1})
        extended = self.overlay.audited_snapshot()
        second_reference = extended.records[1].commitment
        self.assertEqual(
            extended.require_head(prefix.head.canonical_bytes()),
            prefix.head,
        )
        self.assertEqual(
            extended.resolve_reference(
                first_reference,
                anchor=prefix.head,
            ).binding.node_sha256,
            first_target.node.node_sha256,
        )
        with self.assertRaisesRegex(
            VerifiedOverlayReferenceError,
            "outside its committed overlay head",
        ):
            extended.resolve_reference(second_reference, anchor=prefix.head)
        with self.assertRaisesRegex(
            VerifiedOverlayHeadMismatchError,
            "extends beyond",
        ):
            extended.require_head(prefix.head, allow_extension=False)
        self.assertEqual(
            extended.resolve_reference(second_reference).binding.node_sha256,
            second_target.node.node_sha256,
        )

    def test_06_forged_or_ahead_heads_fail_closed(self) -> None:
        self.bind(CHECKMATE_FEN)
        snapshot = self.overlay.audited_snapshot()

        ahead = snapshot.head.record()
        ahead["record_count"] = 2
        ahead["journal_size_bytes"] += 1
        with self.assertRaisesRegex(
            VerifiedOverlayHeadMismatchError,
            "ahead",
        ):
            snapshot.require_head(canonical_json_bytes(ahead))

        wrong_hash = snapshot.head.record()
        wrong_hash["head_record_sha256"] = "0" * 64
        with self.assertRaisesRegex(
            VerifiedOverlayHeadMismatchError,
            "not an exact audited prefix",
        ):
            snapshot.require_head(canonical_json_bytes(wrong_hash))

        wrong_header = snapshot.head.record()
        wrong_header["header_sha256"] = "1" * 64
        with self.assertRaisesRegex(
            VerifiedOverlayHeadMismatchError,
            "different overlay",
        ):
            snapshot.require_head(canonical_json_bytes(wrong_header))

    def test_07_external_head_detects_clean_valid_suffix_rollback(self) -> None:
        self.bind(CHECKMATE_FEN, lineage={"record": 0})
        prefix = self.overlay.audited_snapshot()
        first_end = prefix.records[0].frame_end_offset
        self.bind(STALEMATE_FEN, lineage={"record": 1})
        externally_retained = self.overlay.head_commitment()
        self.assertEqual(externally_retained.record_count, 2)
        self.overlay.close()

        # This is a clean truncation at a valid frame boundary: the journal
        # alone cannot detect it, but the separately retained head must.
        with self.overlay_path.open("r+b", buffering=0) as stream:
            stream.truncate(first_end)
            stream.flush()
        self.overlay = VerifiedCertificateOverlay(self.overlay_path, self.dag)
        rolled_back = self.overlay.audited_snapshot()
        self.assertEqual(rolled_back.head.record_count, 1)
        with self.assertRaisesRegex(
            VerifiedOverlayHeadMismatchError,
            "ahead",
        ):
            self.overlay.require_external_head(externally_retained)
        accepted = self.overlay.require_external_head(prefix.head.canonical_bytes())
        self.assertEqual(accepted.head, prefix.head)

    def test_08_head_commitment_bytes_are_canonical_and_noncoercive(self) -> None:
        self.bind(CHECKMATE_FEN)
        head = self.overlay.head_commitment()
        with self.assertRaisesRegex(ValueError, "canonical JSON"):
            OverlayHeadCommitment.from_canonical_bytes(head.canonical_bytes() + b" ")

        boolean_count = head.record()
        boolean_count["record_count"] = True
        with self.assertRaisesRegex(ValueError, "non-negative integer"):
            OverlayHeadCommitment.from_canonical_bytes(
                canonical_json_bytes(boolean_count)
            )

        extra = head.record()
        extra["unexpected"] = None
        with self.assertRaisesRegex(ValueError, "missing or unexpected"):
            OverlayHeadCommitment.from_canonical_bytes(canonical_json_bytes(extra))


if __name__ == "__main__":
    unittest.main()
