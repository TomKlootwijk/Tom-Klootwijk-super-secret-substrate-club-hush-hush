from __future__ import annotations

import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

from ugts_chess.frontier import (
    FrontierIntegrityError,
    FrontierReader,
    FrontierRecord,
    FrontierRecoveryError,
    FrontierWriter,
    FrontierWriterLockedError,
    RECORD_CRC32_SIZE,
    RECORD_PREFIX_SIZE,
    RECORD_SHA256_SIZE,
    read_frontier,
    truncate_corrupt_tail,
    verify_frontier,
)
from ugts_chess.game_state import HistoryContext, RULE_PROFILE_ID
from ugts_chess.hashing import repetition_key
from ugts_chess.position import Position
from ugts_chess.rules import apply_uci, move_to_san, parse_uci_move


class FrontierFormatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "frontier.ugtsf"
        self.root = Position.initial()
        self.root_history = HistoryContext.initial(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def root_record(self, **changes: object) -> FrontierRecord:
        values: dict[str, object] = {
            "position": self.root,
            "history": self.root_history,
            "lineage": {
                "campaign": "classical-root",
                "dedication": "Anna Cramling / Cow Opening",
                "sequence": 0,
            },
        }
        values.update(changes)
        return FrontierRecord(**values)  # type: ignore[arg-type]

    def child_record(self, parent: FrontierRecord) -> FrontierRecord:
        move = parse_uci_move(self.root, "e2e3")
        child = apply_uci(self.root, "e2e3")
        return FrontierRecord(
            child,
            self.root_history.push(child),
            parent_content_sha256=parent.content_sha256,
            action={"kind": "move", "uci": move.uci(), "san": move_to_san(self.root, move)},
            lineage={"obligation": "root-e2e3", "ply": 1, "source_shard": "cow-opening"},
        )

    def write_pair(self) -> tuple[FrontierRecord, FrontierRecord, object, object]:
        root = self.root_record()
        child = self.child_record(root)
        with FrontierWriter(self.path) as writer:
            first = writer.append(root)
            second = writer.append(child)
        return root, child, first, second

    def write_triplet(self) -> tuple[object, object, object]:
        root = self.root_record()
        child = self.child_record(root)
        later = self.root_record(
            lineage={
                "campaign": "classical-root",
                "dedication": "Anna Cramling / Cow Opening",
                "sequence": 2,
            }
        )
        with FrontierWriter(self.path) as writer:
            first = writer.append(root)
            second = writer.append(child)
            third = writer.append(later)
        return first, second, third

    def test_01_round_trip_retains_complete_state_history_and_dag_metadata(self) -> None:
        root, child, first, second = self.write_pair()

        report = verify_frontier(self.path)
        self.assertTrue(report.valid)
        self.assertEqual(report.record_count, 2)
        self.assertEqual(report.last_good_offset, report.file_size)
        self.assertEqual(report.header.rule_profile_id, RULE_PROFILE_ID)  # type: ignore[union-attr]

        recovered = read_frontier(self.path)
        self.assertEqual(recovered[0].position, root.position)
        self.assertEqual(recovered[0].history.counts, root.history.counts)
        self.assertEqual(recovered[1].position.to_fen(), child.position.to_fen())
        self.assertEqual(recovered[1].history.counts, child.history.counts)
        self.assertEqual(recovered[1].parent_content_sha256, root.content_sha256)
        self.assertEqual(recovered[1].action["uci"], "e2e3")
        self.assertEqual(recovered[1].lineage["source_shard"], "cow-opening")
        self.assertEqual(first.content_sha256, root.content_sha256)  # type: ignore[attr-defined]
        self.assertEqual(second.content_sha256, child.content_sha256)  # type: ignore[attr-defined]

        payload = child.payload_record()
        self.assertEqual(payload["state"]["fen"], child.position.to_fen())  # type: ignore[index]
        self.assertEqual(payload["state"]["history_counts"], child.history.record())  # type: ignore[index]
        self.assertNotIn("compact_key64", payload["state"])  # type: ignore[operator]

    def test_02_content_identity_is_canonical_and_covers_lineage_fullmove_and_history(self) -> None:
        extra_key = "f" * 64
        history_a = HistoryContext(((extra_key, 2), (repetition_key(self.root), 1)))
        history_b = HistoryContext(((repetition_key(self.root), 1), (extra_key, 2)))
        first = FrontierRecord(
            self.root,
            history_a,
            action={"uci": "e2e3", "kind": "move"},
            lineage={"z": 3, "a": 1},
        )
        reordered = FrontierRecord(
            self.root,
            history_b,
            action={"kind": "move", "uci": "e2e3"},
            lineage={"a": 1, "z": 3},
        )
        self.assertEqual(first.history.counts, reordered.history.counts)
        self.assertEqual(first.content_sha256, reordered.content_sha256)

        changed_lineage = FrontierRecord(
            self.root,
            history_b,
            action={"kind": "move", "uci": "e2e3"},
            lineage={"a": 1, "z": 4},
        )
        changed_history = FrontierRecord(
            self.root,
            HistoryContext(((repetition_key(self.root), 2), (extra_key, 2))),
            action={"kind": "move", "uci": "e2e3"},
            lineage={"a": 1, "z": 3},
        )
        later_fen = Position.from_fen(self.root.to_fen().rsplit(" ", 1)[0] + " 9")
        changed_fullmove = FrontierRecord(
            later_fen,
            history_b,
            action={"kind": "move", "uci": "e2e3"},
            lineage={"a": 1, "z": 3},
        )
        self.assertNotEqual(first.content_sha256, changed_lineage.content_sha256)
        self.assertNotEqual(first.content_sha256, changed_history.content_sha256)
        self.assertNotEqual(first.content_sha256, changed_fullmove.content_sha256)

    def test_03_append_fsyncs_and_reopen_only_appends(self) -> None:
        root = self.root_record()
        child = self.child_record(root)
        with patch("ugts_chess.frontier.os.fsync") as fsync:
            with FrontierWriter(self.path) as writer:
                fsync.reset_mock()
                first = writer.append(root)
                fsync.assert_called_once()
        original_size = self.path.stat().st_size

        with FrontierWriter(self.path) as writer:
            second = writer.append(child, fsync=False)
            writer.sync()

        self.assertEqual(first.frame_end_offset, original_size)
        self.assertEqual(second.frame_offset, original_size)
        self.assertGreater(self.path.stat().st_size, original_size)
        self.assertEqual(verify_frontier(self.path).record_count, 2)

    def test_03a_new_journal_persists_its_parent_directory_entry_once(self) -> None:
        with patch("ugts_chess.frontier._fsync_parent_directory") as fsync_parent:
            with FrontierWriter(self.path):
                pass
            fsync_parent.assert_called_once_with(self.path)

        with patch("ugts_chess.frontier._fsync_parent_directory") as fsync_parent:
            with FrontierWriter(self.path):
                pass
            fsync_parent.assert_not_called()

    def test_04_torn_tail_is_reported_rejected_and_only_explicitly_truncated(self) -> None:
        root, _, first, second = self.write_pair()
        torn_size = second.frame_end_offset - 9  # type: ignore[attr-defined]
        with self.path.open("r+b") as stream:
            stream.truncate(torn_size)

        report = verify_frontier(self.path)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "torn_record_body")  # type: ignore[union-attr]
        self.assertEqual(report.record_count, 1)
        self.assertEqual(report.last_good_offset, first.frame_end_offset)  # type: ignore[attr-defined]
        self.assertEqual(report.truncation_boundary, first.frame_end_offset)  # type: ignore[attr-defined]
        self.assertEqual(report.invalid_suffix_bytes, torn_size - first.frame_end_offset)  # type: ignore[attr-defined]

        entries = FrontierReader(self.path).iter_entries()
        self.assertEqual(next(entries).record, root)
        with self.assertRaises(FrontierIntegrityError):
            next(entries)
        with self.assertRaises(FrontierIntegrityError):
            FrontierWriter(self.path)

        expected_suffix = self.path.read_bytes()[report.last_good_offset :]
        recovery = truncate_corrupt_tail(self.path)
        self.assertEqual(recovery.truncated_bytes, report.invalid_suffix_bytes)
        self.assertIsNotNone(recovery.preserved_suffix_path)
        self.assertEqual(recovery.preserved_suffix_path.read_bytes(), expected_suffix)  # type: ignore[union-attr]
        self.assertEqual(recovery.preserved_suffix_sha256, hashlib.sha256(expected_suffix).hexdigest())
        self.assertTrue(recovery.after.valid)
        self.assertEqual(read_frontier(self.path), (root,))

    def test_05_crc32_detects_corruption_at_the_last_good_boundary(self) -> None:
        _, _, first, second = self.write_pair()
        with self.path.open("r+b") as stream:
            stream.seek(second.payload_offset + 7)  # type: ignore[attr-defined]
            original = stream.read(1)
            stream.seek(-1, 1)
            stream.write(bytes((original[0] ^ 1,)))

        report = verify_frontier(self.path)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "record_crc32_mismatch")  # type: ignore[union-attr]
        self.assertEqual(report.record_count, 1)
        self.assertEqual(report.last_good_offset, first.frame_end_offset)  # type: ignore[attr-defined]

    def test_06_sha256_is_checked_independently_of_crc32(self) -> None:
        _, _, _, second = self.write_pair()
        with self.path.open("r+b") as stream:
            stream.seek(second.frame_offset)  # type: ignore[attr-defined]
            frame = bytearray(stream.read(second.frame_length))  # type: ignore[attr-defined]
            digest_index = RECORD_PREFIX_SIZE + second.payload_length  # type: ignore[attr-defined]
            frame[digest_index] ^= 1
            crc = zlib.crc32(frame[:-RECORD_CRC32_SIZE]) & 0xFFFFFFFF
            frame[-RECORD_CRC32_SIZE:] = struct.pack(">I", crc)
            stream.seek(second.frame_offset)  # type: ignore[attr-defined]
            stream.write(frame)

        report = verify_frontier(self.path)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "record_sha256_mismatch")  # type: ignore[union-attr]

    def test_06a_mid_journal_integrity_failure_can_never_be_truncated(self) -> None:
        _, second, _ = self.write_triplet()
        original_size = self.path.stat().st_size
        with self.path.open("r+b") as stream:
            stream.seek(second.payload_offset + 7)  # type: ignore[attr-defined]
            original = stream.read(1)
            stream.seek(-1, 1)
            stream.write(bytes((original[0] ^ 1,)))

        report = verify_frontier(self.path)
        self.assertEqual(report.issue.code, "record_crc32_mismatch")  # type: ignore[union-attr]
        self.assertFalse(report.issue.recoverable_tail)  # type: ignore[union-attr]
        with self.assertRaises(FrontierRecoveryError):
            truncate_corrupt_tail(self.path)
        self.assertEqual(self.path.stat().st_size, original_size)

    def test_06b_corrupt_length_cannot_hide_and_truncate_a_valid_suffix(self) -> None:
        _, second, third = self.write_triplet()
        original_size = self.path.stat().st_size
        hidden_suffix_bytes = original_size - third.frame_offset  # type: ignore[attr-defined]
        forged_length = second.payload_length + hidden_suffix_bytes + 1  # type: ignore[attr-defined]
        with self.path.open("r+b") as stream:
            stream.seek(second.frame_offset + 4)  # type: ignore[attr-defined]
            stream.write(struct.pack(">I", forged_length))

        report = verify_frontier(self.path)
        self.assertEqual(report.issue.code, "torn_record_body")  # type: ignore[union-attr]
        self.assertFalse(report.issue.recoverable_tail)  # type: ignore[union-attr]
        self.assertIn("later independently valid frame", report.issue.message)  # type: ignore[union-attr]
        with self.assertRaises(FrontierRecoveryError):
            truncate_corrupt_tail(self.path)
        self.assertEqual(self.path.stat().st_size, original_size)

    def test_06c_final_upward_length_corruption_is_preserved_before_truncation(self) -> None:
        root, _, first, second = self.write_pair()
        with self.path.open("r+b") as stream:
            stream.seek(second.frame_offset + 4)  # type: ignore[attr-defined]
            stream.write(struct.pack(">I", second.payload_length + 1))  # type: ignore[attr-defined]

        report = verify_frontier(self.path)
        self.assertEqual(report.issue.code, "torn_record_body")  # type: ignore[union-attr]
        self.assertTrue(report.issue.recoverable_tail)  # type: ignore[union-attr]
        self.assertEqual(report.last_good_offset, first.frame_end_offset)  # type: ignore[attr-defined]
        expected_suffix = self.path.read_bytes()[report.last_good_offset :]

        recovery = truncate_corrupt_tail(self.path)

        self.assertEqual(read_frontier(self.path), (root,))
        self.assertEqual(recovery.truncated_bytes, len(expected_suffix))
        self.assertIsNotNone(recovery.preserved_suffix_path)
        self.assertEqual(recovery.preserved_suffix_path.read_bytes(), expected_suffix)  # type: ignore[union-attr]
        self.assertEqual(recovery.preserved_suffix_sha256, hashlib.sha256(expected_suffix).hexdigest())

    def test_06d_conflicting_recovery_sidecar_refuses_to_truncate(self) -> None:
        _, _, first, second = self.write_pair()
        with self.path.open("r+b") as stream:
            stream.truncate(second.frame_end_offset - 7)  # type: ignore[attr-defined]
        original = self.path.read_bytes()
        suffix = original[first.frame_end_offset :]  # type: ignore[attr-defined]
        suffix_sha256 = hashlib.sha256(suffix).hexdigest()
        recovery_path = self.path.with_name(
            f"{self.path.name}.recovery-{first.frame_end_offset:016x}-{suffix_sha256}.bin"  # type: ignore[attr-defined]
        )
        recovery_path.write_bytes(b"conflicting sidecar")

        with self.assertRaisesRegex(FrontierRecoveryError, "wrong size"):
            truncate_corrupt_tail(self.path)

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(recovery_path.read_bytes(), b"conflicting sidecar")

    def test_07_reconstruction_hashes_are_checked_after_frame_hashes(self) -> None:
        _, _, _, second = self.write_pair()
        with self.path.open("r+b") as stream:
            stream.seek(second.frame_offset)  # type: ignore[attr-defined]
            frame = bytearray(stream.read(second.frame_length))  # type: ignore[attr-defined]
            payload_start = RECORD_PREFIX_SIZE
            payload_end = payload_start + second.payload_length  # type: ignore[attr-defined]
            payload = bytes(frame[payload_start:payload_end])
            marker = b'"position_sha256":"'
            hash_index = payload.index(marker) + len(marker)
            frame[payload_start + hash_index] = ord("0") if payload[hash_index] != ord("0") else ord("1")
            digest = hashlib.sha256(frame[payload_start:payload_end]).digest()
            digest_start = payload_end
            frame[digest_start : digest_start + RECORD_SHA256_SIZE] = digest
            crc = zlib.crc32(frame[:-RECORD_CRC32_SIZE]) & 0xFFFFFFFF
            frame[-RECORD_CRC32_SIZE:] = struct.pack(">I", crc)
            stream.seek(second.frame_offset)  # type: ignore[attr-defined]
            stream.write(frame)

        report = verify_frontier(self.path)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "record_payload_invalid")  # type: ignore[union-attr]
        self.assertIn("position SHA-256", report.issue.message)  # type: ignore[union-attr]

    def test_08_rule_profile_is_versioned_and_bound_in_header_and_record(self) -> None:
        alternate = "fide-classical-test-claims-as-actions-v9"
        record = self.root_record(rule_profile_id=alternate)
        with FrontierWriter(self.path, rule_profile_id=alternate) as writer:
            writer.append(record)

        mismatch = verify_frontier(self.path)
        self.assertFalse(mismatch.valid)
        self.assertEqual(mismatch.issue.code, "rule_profile_mismatch")  # type: ignore[union-attr]
        accepted = verify_frontier(self.path, expected_rule_profile_id=alternate)
        self.assertTrue(accepted.valid)
        self.assertEqual(
            read_frontier(self.path, expected_rule_profile_id=alternate)[0].rule_profile_id,
            alternate,
        )

    def test_09_random_access_rechecks_the_content_address(self) -> None:
        _, child, _, second = self.write_pair()
        reader = FrontierReader(self.path)
        recovered = reader.read_entry_at(
            second.frame_offset,  # type: ignore[attr-defined]
            expected_content_sha256=child.content_sha256,
        )
        self.assertEqual(recovered.record, child)
        self.assertEqual(reader.find_entry(child.content_sha256).frame_offset, second.frame_offset)  # type: ignore[union-attr,attr-defined]
        with self.assertRaises(FrontierIntegrityError):
            reader.read_entry_at(second.frame_offset, expected_content_sha256="0" * 64)  # type: ignore[attr-defined]

    def test_10_header_corruption_is_not_treated_as_a_recoverable_tail(self) -> None:
        with FrontierWriter(self.path) as writer:
            writer.append(self.root_record())
        with self.path.open("r+b") as stream:
            stream.seek(0)
            stream.write(b"X")

        report = verify_frontier(self.path)
        self.assertEqual(report.issue.code, "file_magic_mismatch")  # type: ignore[union-attr]
        self.assertFalse(report.issue.recoverable_tail)  # type: ignore[union-attr]
        original_size = self.path.stat().st_size
        with self.assertRaises(FrontierRecoveryError):
            truncate_corrupt_tail(self.path)
        self.assertEqual(self.path.stat().st_size, original_size)

    def test_11_current_position_must_be_present_and_all_counts_are_1_through_5(self) -> None:
        current_key = repetition_key(self.root)
        with self.assertRaisesRegex(ValueError, "does not contain the current position"):
            FrontierRecord(self.root, HistoryContext((("f" * 64, 1),)))

        for invalid_count in (-1, 0, 6):
            with self.subTest(count=invalid_count):
                with self.assertRaisesRegex(ValueError, "range 1..5"):
                    FrontierRecord(
                        self.root,
                        HistoryContext(((current_key, invalid_count),)),
                    )

        terminal_boundary = FrontierRecord(
            self.root,
            HistoryContext(((current_key, 5),)),
        )
        self.assertEqual(terminal_boundary.history.counts, ((current_key, 5),))

    def test_12_constructor_and_decoder_both_reject_structurally_invalid_fen(self) -> None:
        invalid = Position.from_fen(
            "rnbqqbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            strict=False,
        )
        with self.assertRaisesRegex(ValueError, "exactly one white king and one black king"):
            FrontierRecord(invalid, HistoryContext.initial(invalid))

        with FrontierWriter(self.path) as writer:
            entry = writer.append(self.root_record())
        with self.path.open("r+b") as stream:
            stream.seek(entry.frame_offset)
            frame = bytearray(stream.read(entry.frame_length))
            payload_start = RECORD_PREFIX_SIZE
            payload_end = payload_start + entry.payload_length
            payload = bytes(frame[payload_start:payload_end])
            valid_placement = b"RNBQKBNR"
            invalid_placement = b"RNBQQBNR"
            self.assertIn(valid_placement, payload)
            payload = payload.replace(valid_placement, invalid_placement, 1)
            frame[payload_start:payload_end] = payload
            digest = hashlib.sha256(payload).digest()
            frame[payload_end : payload_end + RECORD_SHA256_SIZE] = digest
            crc = zlib.crc32(frame[:-RECORD_CRC32_SIZE]) & 0xFFFFFFFF
            frame[-RECORD_CRC32_SIZE:] = struct.pack(">I", crc)
            stream.seek(entry.frame_offset)
            stream.write(frame)

        report = verify_frontier(self.path)
        self.assertEqual(report.issue.code, "record_payload_invalid")  # type: ignore[union-attr]
        self.assertIn("exactly one white king", report.issue.message)  # type: ignore[union-attr]

    def test_13_second_writer_is_excluded_and_reopen_offsets_remain_exact(self) -> None:
        root = self.root_record()
        child = self.child_record(root)
        first_writer = FrontierWriter(self.path)
        try:
            first_entry = first_writer.append(root)
            with self.assertRaises(FrontierWriterLockedError):
                FrontierWriter(self.path)
            with self.assertRaises(FrontierWriterLockedError):
                truncate_corrupt_tail(self.path)
        finally:
            first_writer.close()

        with FrontierWriter(self.path) as reopened:
            second_entry = reopened.append(child)
        self.assertEqual(second_entry.frame_offset, first_entry.frame_end_offset)
        self.assertEqual(verify_frontier(self.path).record_count, 2)

    def test_14_writer_lock_excludes_an_independent_process_and_releases_cleanly(self) -> None:
        source_root = Path(__file__).resolve().parents[1] / "src"
        environment = os.environ.copy()
        old_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(source_root)
            if not old_pythonpath
            else str(source_root) + os.pathsep + old_pythonpath
        )
        environment["UGTS_FRONTIER_LOCK_TEST_PATH"] = str(self.path)
        probe = (
            "import os\n"
            "from ugts_chess.frontier import FrontierWriter, FrontierWriterLockedError\n"
            "try:\n"
            "    writer = FrontierWriter(os.environ['UGTS_FRONTIER_LOCK_TEST_PATH'])\n"
            "except FrontierWriterLockedError:\n"
            "    print('locked')\n"
            "else:\n"
            "    writer.close()\n"
            "    print('acquired')\n"
        )

        writer = FrontierWriter(self.path)
        try:
            blocked = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                check=True,
                env=environment,
                text=True,
                timeout=10,
            )
            self.assertEqual(blocked.stdout.strip(), "locked")
        finally:
            writer.close()

        released = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            check=True,
            env=environment,
            text=True,
            timeout=10,
        )
        self.assertEqual(released.stdout.strip(), "acquired")

    def test_15_decoder_rejects_missing_current_history_and_count_six(self) -> None:
        current_key = repetition_key(self.root)
        history_fragment = f'"history_counts":[["{current_key}",1]]'.encode("ascii")
        cases = (
            (
                history_fragment.replace(current_key.encode("ascii"), b"0" * 64),
                "does not contain the current position",
            ),
            (history_fragment[:-3] + b"6]]", "range 1..5"),
        )
        for index, (replacement, expected_message) in enumerate(cases):
            with self.subTest(case=index):
                path = Path(self.temporary.name) / f"bad-history-{index}.ugtsf"
                with FrontierWriter(path) as writer:
                    entry = writer.append(self.root_record())
                with path.open("r+b") as stream:
                    stream.seek(entry.frame_offset)
                    frame = bytearray(stream.read(entry.frame_length))
                    payload_start = RECORD_PREFIX_SIZE
                    payload_end = payload_start + entry.payload_length
                    payload = bytes(frame[payload_start:payload_end])
                    self.assertIn(history_fragment, payload)
                    payload = payload.replace(history_fragment, replacement, 1)
                    self.assertEqual(len(payload), entry.payload_length)
                    frame[payload_start:payload_end] = payload
                    frame[payload_end : payload_end + RECORD_SHA256_SIZE] = hashlib.sha256(
                        payload
                    ).digest()
                    crc = zlib.crc32(frame[:-RECORD_CRC32_SIZE]) & 0xFFFFFFFF
                    frame[-RECORD_CRC32_SIZE:] = struct.pack(">I", crc)
                    stream.seek(entry.frame_offset)
                    stream.write(frame)

                report = verify_frontier(path)
                self.assertEqual(report.issue.code, "record_payload_invalid")  # type: ignore[union-attr]
                self.assertIn(expected_message, report.issue.message)  # type: ignore[union-attr]

    def test_16_constructor_and_decoder_reject_history_after_fivefold_end(self) -> None:
        current_key = repetition_key(self.root)
        ended_key = "0" * 64
        self.assertNotEqual(ended_key, current_key)
        unreachable = HistoryContext(
            tuple(sorted(((current_key, 1), (ended_key, 5))))
        )
        with self.assertRaisesRegex(ValueError, "already ended automatically"):
            FrontierRecord(self.root, unreachable)

        reachable = HistoryContext(
            tuple(sorted(((current_key, 1), (ended_key, 4))))
        )
        record = FrontierRecord(self.root, reachable)
        path = Path(self.temporary.name) / "already-ended-history.ugtsf"
        with FrontierWriter(path) as writer:
            entry = writer.append(record)
        with path.open("r+b") as stream:
            stream.seek(entry.frame_offset)
            frame = bytearray(stream.read(entry.frame_length))
            payload_start = RECORD_PREFIX_SIZE
            payload_end = payload_start + entry.payload_length
            payload = bytes(frame[payload_start:payload_end])
            old_fragment = f'["{ended_key}",4]'.encode("ascii")
            new_fragment = f'["{ended_key}",5]'.encode("ascii")
            self.assertIn(old_fragment, payload)
            payload = payload.replace(old_fragment, new_fragment, 1)
            frame[payload_start:payload_end] = payload
            frame[payload_end : payload_end + RECORD_SHA256_SIZE] = hashlib.sha256(
                payload
            ).digest()
            crc = zlib.crc32(frame[:-RECORD_CRC32_SIZE]) & 0xFFFFFFFF
            frame[-RECORD_CRC32_SIZE:] = struct.pack(">I", crc)
            stream.seek(entry.frame_offset)
            stream.write(frame)

        report = verify_frontier(path)
        self.assertEqual(report.issue.code, "record_payload_invalid")  # type: ignore[union-attr]
        self.assertIn("already ended automatically", report.issue.message)  # type: ignore[union-attr]


if __name__ == "__main__":
    unittest.main()
