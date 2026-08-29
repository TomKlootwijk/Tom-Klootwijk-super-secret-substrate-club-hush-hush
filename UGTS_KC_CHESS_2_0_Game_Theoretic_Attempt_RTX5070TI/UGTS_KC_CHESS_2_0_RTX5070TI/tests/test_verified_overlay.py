from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib

from ugts_chess.game_state import HistoryContext, game_state_sha256
from ugts_chess.game_theory import WDL
from ugts_chess.hashing import canonical_json_bytes
from ugts_chess.position import Position, START_FEN
from ugts_chess.proof_dag import ProofDAG
from ugts_chess.verified_overlay import (
    RECORD_MAGIC,
    RECORD_PREFIX_SIZE,
    VerifiedCertificateOverlay,
    VerifiedOverlayCommitError,
    VerifiedOverlayConflictError,
    VerifiedOverlayError,
    VerifiedOverlayIntegrityError,
    VerifiedOverlayRecoveryError,
    VerifiedOverlayWriterLockedError,
    recover_verified_overlay,
    verify_verified_overlay,
)
from ugts_chess.wdl import BoundedWDLSolver


CHECKMATE_FEN_1 = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1"
CHECKMATE_FEN_2 = "7k/6Q1/6K1/8/8/8/8/8 b - - 0 2"
STALEMATE_FEN = "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"


def certificate_bytes(
    position: Position,
    history: HistoryContext,
    *,
    max_plies: int = 0,
) -> bytes:
    result = BoundedWDLSolver().solve(
        position,
        max_plies=max_plies,
        history=history,
    )
    return canonical_json_bytes(result.certificate_bundle())


class VerifiedOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.dags: list[ProofDAG] = []
        self.overlays: list[VerifiedCertificateOverlay] = []

    def tearDown(self) -> None:
        for overlay in reversed(self.overlays):
            overlay.close()
        for dag in reversed(self.dags):
            dag.close()
        self.temp.cleanup()

    def make_dag(self, name: str = "main") -> ProofDAG:
        dag = ProofDAG(
            self.root / f"{name}.sqlite",
            self.root / f"{name}.frontier",
        )
        self.dags.append(dag)
        return dag

    def make_overlay(
        self,
        dag: ProofDAG,
        name: str = "verified.overlay",
    ) -> VerifiedCertificateOverlay:
        overlay = VerifiedCertificateOverlay(self.root / name, dag)
        self.overlays.append(overlay)
        return overlay

    @staticmethod
    def append_root(
        dag: ProofDAG,
        fen: str,
        *,
        history: HistoryContext | None = None,
        lineage: object = None,
    ):
        position = Position.from_fen(fen)
        exact_history = history or HistoryContext.initial(position)
        return dag.append_root(position, exact_history, lineage=lineage)

    @staticmethod
    def _close_overlay(overlay: VerifiedCertificateOverlay) -> None:
        overlay.close()

    @staticmethod
    def _rewrite_payload(
        path: Path,
        frame_offset: int,
        transform,
    ) -> None:
        with path.open("r+b", buffering=0) as stream:
            stream.seek(frame_offset)
            prefix = stream.read(RECORD_PREFIX_SIZE)
            magic, payload_length = struct.unpack(">4sQ", prefix)
            assert magic == RECORD_MAGIC
            payload = stream.read(payload_length)
            raw = json.loads(payload)
            transform(raw)
            rewritten = canonical_json_bytes(raw)
            if len(rewritten) != payload_length:
                raise AssertionError("test rewrite must preserve payload length")
            digest = hashlib.sha256(rewritten).digest()
            crc = zlib.crc32(prefix)
            crc = zlib.crc32(rewritten, crc)
            crc = zlib.crc32(digest, crc) & 0xFFFFFFFF
            stream.seek(frame_offset)
            stream.write(prefix + rewritten + digest + struct.pack(">I", crc))
            stream.flush()

    @staticmethod
    def _rewrite_only_frame_with_new_length(
        path: Path,
        frame_offset: int,
        transform,
    ) -> None:
        with path.open("r+b", buffering=0) as stream:
            stream.seek(frame_offset)
            prefix = stream.read(RECORD_PREFIX_SIZE)
            magic, payload_length = struct.unpack(">4sQ", prefix)
            assert magic == RECORD_MAGIC
            payload = stream.read(payload_length)
            raw = json.loads(payload)
            transform(raw)
            rewritten = canonical_json_bytes(raw)
            new_prefix = struct.pack(">4sQ", RECORD_MAGIC, len(rewritten))
            digest = hashlib.sha256(rewritten).digest()
            crc = zlib.crc32(new_prefix)
            crc = zlib.crc32(rewritten, crc)
            crc = zlib.crc32(digest, crc) & 0xFFFFFFFF
            stream.seek(frame_offset)
            stream.write(new_prefix + rewritten + digest + struct.pack(">I", crc))
            stream.truncate()
            stream.flush()

    def test_01_exact_loss_is_stored_without_orientation_inversion_and_replays(self) -> None:
        dag = self.make_dag()
        appended = self.append_root(dag, CHECKMATE_FEN_1)
        position = appended.node.position
        history = appended.node.history
        cert = certificate_bytes(position, history)
        overlay = self.make_overlay(dag)

        self.assertEqual(appended.node.wdl, WDL.UNKNOWN)
        result = overlay.append_verified_certificate(appended.node.node_sha256, cert)
        self.assertTrue(result.appended)
        self.assertEqual(result.entry.binding.claimed_wdl, WDL.LOSS)
        self.assertEqual(overlay.effective_wdl(appended.node.node_sha256), WDL.LOSS)
        self.assertEqual(dag.get_node(appended.node.node_sha256).wdl, WDL.UNKNOWN)
        self.assertEqual(result.entry.binding.certificate_bytes, cert)
        self.assertEqual(
            result.entry.binding.frontier_content_sha256,
            appended.edge.frontier_content_sha256,
        )

        duplicate = overlay.append_verified_certificate(appended.node.node_sha256, cert)
        self.assertFalse(duplicate.appended)
        self.assertEqual(overlay.audit().record_count, 1)
        overlay.close()

        reopened = self.make_overlay(dag)
        self.assertEqual(reopened.audit().record_count, 1)
        self.assertEqual(reopened.effective_wdl(appended.node.node_sha256), WDL.LOSS)

    def test_02_exact_full_fen_is_required_even_when_game_state_hash_matches(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_2)
        certificate_position = Position.from_fen(CHECKMATE_FEN_1)
        certificate_history = HistoryContext.initial(certificate_position)
        self.assertEqual(
            game_state_sha256(certificate_position, certificate_history),
            target.node.game_state_sha256,
        )
        cert = certificate_bytes(certificate_position, certificate_history)
        overlay = self.make_overlay(dag)

        with self.assertRaisesRegex(ValueError, "FEN does not exactly match"):
            overlay.append_verified_certificate(target.node.node_sha256, cert)
        self.assertEqual(overlay.effective_wdl(target.node.node_sha256), WDL.UNKNOWN)

    def test_03_history_certificate_substitution_and_unknown_are_rejected(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        key = target.node.history.counts[0][0]
        different_history = HistoryContext(((key, 2),))
        history_cert = certificate_bytes(target.node.position, different_history)
        overlay = self.make_overlay(dag)

        with self.assertRaisesRegex(ValueError, "history does not exactly match"):
            overlay.append_verified_certificate(target.node.node_sha256, history_cert)

        start = self.append_root(dag, START_FEN, lineage={"second-root": True})
        unknown_cert = certificate_bytes(start.node.position, start.node.history)
        with self.assertRaisesRegex(ValueError, "UNKNOWN|not a completed proof"):
            overlay.append_verified_certificate(start.node.node_sha256, unknown_cert)

        stalemate = Position.from_fen(STALEMATE_FEN)
        stale_cert = certificate_bytes(stalemate, HistoryContext.initial(stalemate))
        with self.assertRaisesRegex(ValueError, "FEN does not exactly match"):
            overlay.append_verified_certificate(target.node.node_sha256, stale_cert)

    def test_04_only_canonical_strict_bundle_bytes_and_profile_are_accepted(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay = self.make_overlay(dag)

        with self.assertRaisesRegex(ValueError, "canonical bare JSON"):
            overlay.append_verified_certificate(target.node.node_sha256, cert + b"\n")

        bundle = json.loads(cert)
        bundle["unexpected"] = True
        with self.assertRaisesRegex(ValueError, "missing or unexpected"):
            overlay.append_verified_certificate(
                target.node.node_sha256,
                canonical_json_bytes(bundle),
            )

        bundle = json.loads(cert)
        bundle["rules_profile"] = "forged-profile"
        with self.assertRaisesRegex(ValueError, "rule profile mismatch"):
            overlay.append_verified_certificate(
                target.node.node_sha256,
                canonical_json_bytes(bundle),
            )

    def test_05_same_node_different_certificate_is_an_immutable_conflict(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert_0 = certificate_bytes(target.node.position, target.node.history, max_plies=0)
        cert_1 = certificate_bytes(target.node.position, target.node.history, max_plies=1)
        self.assertNotEqual(cert_0, cert_1)
        overlay = self.make_overlay(dag)
        overlay.append_verified_certificate(target.node.node_sha256, cert_0)

        with self.assertRaises(VerifiedOverlayConflictError):
            overlay.append_verified_certificate(target.node.node_sha256, cert_1)
        self.assertEqual(overlay.audit().record_count, 1)
        self.assertEqual(
            overlay.get_binding(target.node.node_sha256).certificate_bytes,
            cert_0,
        )

    def test_06_crc_tamper_and_semantic_forgery_fail_closed(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        appended = overlay.append_verified_certificate(target.node.node_sha256, cert)
        frame = appended.entry
        overlay.close()

        with overlay_path.open("r+b", buffering=0) as stream:
            stream.seek(frame.payload_offset + 10)
            original = stream.read(1)
            stream.seek(frame.payload_offset + 10)
            stream.write(bytes([original[0] ^ 1]))
        report = verify_verified_overlay(overlay_path, dag)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "record_crc32_mismatch")
        with self.assertRaises(VerifiedOverlayIntegrityError):
            self.make_overlay(dag)

        # Restore by recreating this test-local journal, then forge claimed WDL
        # while recomputing both physical checksums.  Semantic replay still
        # rejects it; CRC/SHA are integrity mechanisms, not proof authority.
        overlay_path.unlink()
        clean = self.make_overlay(dag)
        frame = clean.append_verified_certificate(target.node.node_sha256, cert).entry
        clean.close()
        self._rewrite_payload(
            overlay_path,
            frame.frame_offset,
            lambda raw: raw.__setitem__("claimed_wdl", "draw"),
        )
        report = verify_verified_overlay(overlay_path, dag)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "record_semantic_invalid")

    def test_07_torn_tail_is_preserved_before_explicit_recovery(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        overlay.append_verified_certificate(target.node.node_sha256, cert)
        overlay.close()
        torn = RECORD_MAGIC + b"\x00\x01"
        with overlay_path.open("ab", buffering=0) as stream:
            stream.write(torn)

        before = verify_verified_overlay(overlay_path, dag)
        self.assertFalse(before.valid)
        self.assertTrue(before.issue.recoverable_tail)
        with self.assertRaises(VerifiedOverlayIntegrityError):
            self.make_overlay(dag)

        recovered = recover_verified_overlay(overlay_path, dag)
        self.assertEqual(recovered.truncated_bytes, len(torn))
        self.assertEqual(recovered.preserved_suffix_path.read_bytes(), torn)
        self.assertEqual(
            hashlib.sha256(torn).hexdigest(),
            recovered.preserved_suffix_sha256,
        )
        reopened = self.make_overlay(dag)
        self.assertEqual(reopened.effective_wdl(target.node.node_sha256), WDL.LOSS)

    def test_08_complete_frame_tamper_is_never_truncated(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        frame = overlay.append_verified_certificate(target.node.node_sha256, cert).entry
        overlay.close()
        with overlay_path.open("r+b", buffering=0) as stream:
            stream.seek(frame.crc32_offset)
            stored = stream.read(4)
            stream.seek(frame.crc32_offset)
            stream.write(bytes([stored[0] ^ 1]) + stored[1:])

        with self.assertRaises(VerifiedOverlayRecoveryError):
            recover_verified_overlay(overlay_path, dag)

    def test_09_final_length_ambiguity_is_loss_preserved(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        frame = overlay.append_verified_certificate(target.node.node_sha256, cert).entry
        overlay.close()
        original_suffix = overlay_path.read_bytes()[frame.frame_offset :]
        with overlay_path.open("r+b", buffering=0) as stream:
            stream.seek(frame.frame_offset + 4)
            length = struct.unpack(">Q", stream.read(8))[0]
            stream.seek(frame.frame_offset + 4)
            stream.write(struct.pack(">Q", length + 1))
        corrupted_suffix = overlay_path.read_bytes()[frame.frame_offset :]

        recovered = recover_verified_overlay(overlay_path, dag)
        self.assertEqual(recovered.truncated_bytes, len(corrupted_suffix))
        self.assertEqual(
            recovered.preserved_suffix_path.read_bytes(),
            corrupted_suffix,
        )
        self.assertNotEqual(original_suffix, corrupted_suffix)
        reopened = self.make_overlay(dag)
        self.assertEqual(reopened.effective_wdl(target.node.node_sha256), WDL.UNKNOWN)

    def test_10_corrupt_middle_length_cannot_hide_a_valid_suffix(self) -> None:
        dag = self.make_dag()
        mate = self.append_root(dag, CHECKMATE_FEN_1, lineage={"root": "mate"})
        draw = self.append_root(dag, STALEMATE_FEN, lineage={"root": "draw"})
        mate_cert = certificate_bytes(mate.node.position, mate.node.history)
        draw_cert = certificate_bytes(draw.node.position, draw.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        first = overlay.append_verified_certificate(mate.node.node_sha256, mate_cert).entry
        overlay.append_verified_certificate(draw.node.node_sha256, draw_cert)
        overlay.close()
        with overlay_path.open("r+b", buffering=0) as stream:
            stream.seek(first.frame_offset + 4)
            length = struct.unpack(">Q", stream.read(8))[0]
            stream.seek(first.frame_offset + 4)
            stream.write(struct.pack(">Q", length + first.payload_length))

        report = verify_verified_overlay(overlay_path, dag)
        self.assertFalse(report.valid)
        self.assertFalse(report.issue.recoverable_tail)
        with self.assertRaises(VerifiedOverlayRecoveryError):
            recover_verified_overlay(overlay_path, dag)

    def test_11_copied_overlay_rejects_dag_without_bound_node(self) -> None:
        source = self.make_dag("source")
        target = self.append_root(source, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(source)
        overlay.append_verified_certificate(target.node.node_sha256, cert)
        overlay.close()

        unrelated = self.make_dag("unrelated")
        self.append_root(unrelated, STALEMATE_FEN)
        report = verify_verified_overlay(overlay_path, unrelated)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "record_semantic_invalid")
        with self.assertRaises(VerifiedOverlayIntegrityError):
            self.make_overlay(unrelated)

    def test_12_writer_lock_and_live_byte_change_are_fail_closed(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        frame = overlay.append_verified_certificate(target.node.node_sha256, cert).entry

        with self.assertRaises(VerifiedOverlayWriterLockedError):
            VerifiedCertificateOverlay(overlay_path, dag)
        with overlay_path.open("r+b", buffering=0) as stream:
            stream.seek(frame.payload_offset)
            original = stream.read(1)
            stream.seek(frame.payload_offset)
            stream.write(bytes([original[0] ^ 1]))
        with self.assertRaises(VerifiedOverlayIntegrityError):
            overlay.get_binding(target.node.node_sha256)

    def test_13_mutable_input_is_snapshotted_once_before_verification(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        original = certificate_bytes(target.node.position, target.node.history)
        mutable = bytearray(original)
        overlay = self.make_overlay(dag)

        from ugts_chess import verified_overlay as module

        real_new_binding = module._new_binding

        def mutate_caller_after_snapshot(*args, **kwargs):
            mutable[:] = b"{}"
            return real_new_binding(*args, **kwargs)

        with mock.patch.object(module, "_new_binding", side_effect=mutate_caller_after_snapshot):
            overlay.append_verified_certificate(target.node.node_sha256, mutable)
        self.assertEqual(
            overlay.get_binding(target.node.node_sha256).certificate_bytes,
            original,
        )

    def test_14_transposition_edges_share_one_fact_but_distinct_nodes_do_not(self) -> None:
        dag = self.make_dag()
        first = self.append_root(dag, CHECKMATE_FEN_1, lineage={"route": 1})
        second = self.append_root(dag, CHECKMATE_FEN_1, lineage={"route": 2})
        self.assertEqual(first.node.node_sha256, second.node.node_sha256)
        self.assertNotEqual(
            first.edge.frontier_content_sha256,
            second.edge.frontier_content_sha256,
        )
        fullmove_distinct = self.append_root(
            dag,
            CHECKMATE_FEN_2,
            lineage={"route": 3},
        )
        self.assertNotEqual(first.node.node_sha256, fullmove_distinct.node.node_sha256)
        cert = certificate_bytes(first.node.position, first.node.history)
        overlay = self.make_overlay(dag)
        binding = overlay.append_verified_certificate(
            first.node.node_sha256,
            cert,
        ).entry.binding

        self.assertEqual(binding.frontier_content_sha256, first.edge.frontier_content_sha256)
        self.assertEqual(overlay.effective_wdl(second.node.node_sha256), WDL.LOSS)
        self.assertEqual(
            overlay.effective_wdl(fullmove_distinct.node.node_sha256),
            WDL.UNKNOWN,
        )

    def test_15_compact_key_collision_cannot_redirect_promotion(self) -> None:
        with mock.patch("ugts_chess.proof_dag.compact_key64", return_value=7):
            dag = self.make_dag()
            mate = self.append_root(dag, CHECKMATE_FEN_1, lineage={"kind": "mate"})
            draw = self.append_root(dag, STALEMATE_FEN, lineage={"kind": "draw"})
            self.assertEqual(mate.node.index_key64, draw.node.index_key64)
            cert = certificate_bytes(mate.node.position, mate.node.history)
            overlay = self.make_overlay(dag)
            overlay.append_verified_certificate(mate.node.node_sha256, cert)

            self.assertEqual(overlay.effective_wdl(mate.node.node_sha256), WDL.LOSS)
            self.assertEqual(overlay.effective_wdl(draw.node.node_sha256), WDL.UNKNOWN)

    def test_16_native_nonterminal_exact_win_bundle_promotes_without_inversion(self) -> None:
        dag = self.make_dag()
        position = Position.from_fen("8/8/8/8/8/k7/8/1QK5 w - - 0 1")
        history = HistoryContext.initial(position)
        target = dag.append_root(position, history)
        result = BoundedWDLSolver(node_budget=200_000).solve(
            position,
            max_plies=3,
            history=history,
        )
        self.assertEqual(result.root.value, WDL.WIN)
        self.assertTrue(result.root.exact)
        bundle = result.certificate_bundle()
        self.assertLess(len(bundle["nodes"]), len(result.node_store))
        overlay = self.make_overlay(dag)

        bound = overlay.append_verified_certificate(
            target.node.node_sha256,
            canonical_json_bytes(bundle),
        ).entry.binding
        self.assertEqual(bound.claimed_wdl, WDL.WIN)
        self.assertEqual(overlay.effective_wdl(target.node.node_sha256), WDL.WIN)

    def test_17_corrupt_earlier_frame_blocks_later_value_and_poisons_handle(self) -> None:
        dag = self.make_dag()
        mate = self.append_root(dag, CHECKMATE_FEN_1, lineage={"order": 1})
        draw = self.append_root(dag, STALEMATE_FEN, lineage={"order": 2})
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        first = overlay.append_verified_certificate(
            mate.node.node_sha256,
            certificate_bytes(mate.node.position, mate.node.history),
        ).entry
        overlay.append_verified_certificate(
            draw.node.node_sha256,
            certificate_bytes(draw.node.position, draw.node.history),
        )
        with overlay_path.open("r+b", buffering=0) as stream:
            stream.seek(first.payload_offset + 20)
            original = stream.read(1)
            stream.seek(first.payload_offset + 20)
            stream.write(bytes([original[0] ^ 1]))

        with self.assertRaises(VerifiedOverlayIntegrityError):
            overlay.effective_wdl(draw.node.node_sha256)
        with self.assertRaises(VerifiedOverlayCommitError):
            overlay.effective_wdl(mate.node.node_sha256)

    def test_18_bool_numeric_aliases_are_rejected_after_checksum_rewrite(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        frame = overlay.append_verified_certificate(target.node.node_sha256, cert).entry
        overlay.close()

        self._rewrite_only_frame_with_new_length(
            overlay_path,
            frame.frame_offset,
            lambda raw: raw.__setitem__("record_index", False),
        )
        report = verify_verified_overlay(overlay_path, dag)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "record_semantic_invalid")

        overlay_path.unlink()
        clean = self.make_overlay(dag)
        frame = clean.append_verified_certificate(target.node.node_sha256, cert).entry
        clean.close()
        self._rewrite_only_frame_with_new_length(
            overlay_path,
            frame.frame_offset,
            lambda raw: raw["verifier_result"].__setitem__(
                "unreferenced_nodes",
                False,
            ),
        )
        report = verify_verified_overlay(overlay_path, dag)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "record_semantic_invalid")

    def test_19_append_always_fsyncs_before_returning_authority(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay = self.make_overlay(dag)

        from ugts_chess import verified_overlay as module

        with mock.patch.object(module.os, "fsync", wraps=module.os.fsync) as fsync:
            overlay.append_verified_certificate(target.node.node_sha256, cert)
        self.assertGreaterEqual(fsync.call_count, 1)
        with self.assertRaises(TypeError):
            overlay.append_verified_certificate(  # type: ignore[call-arg]
                target.node.node_sha256,
                cert,
                fsync=False,
            )

    def test_20_constructor_rejects_path_not_naming_retained_audited_fd(self) -> None:
        dag = self.make_dag()
        overlay_path = self.root / "verified.overlay"

        from ugts_chess import verified_overlay as module

        with mock.patch.object(module.os.path, "samestat", return_value=False):
            with self.assertRaisesRegex(VerifiedOverlayError, "no longer names"):
                VerifiedCertificateOverlay(overlay_path, dag)

    def test_21_recovery_rechecks_same_fd_identity_before_destructive_step(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        overlay.append_verified_certificate(target.node.node_sha256, cert)
        overlay.close()
        torn = RECORD_MAGIC + b"\x00"
        with overlay_path.open("ab", buffering=0) as stream:
            stream.write(torn)
        original = overlay_path.read_bytes()

        from ugts_chess import verified_overlay as module

        with mock.patch.object(
            module.os.path,
            "samestat",
            side_effect=[True, False],
        ):
            with self.assertRaisesRegex(
                VerifiedOverlayRecoveryError,
                "changed during recovery scan",
            ):
                recover_verified_overlay(overlay_path, dag)
        self.assertEqual(overlay_path.read_bytes(), original)
        self.assertFalse(tuple(self.root.glob("*.recovery-*.bin")))

    def test_22_public_verifier_rebinds_path_after_same_fd_scan(self) -> None:
        dag = self.make_dag()
        target = self.append_root(dag, CHECKMATE_FEN_1)
        cert = certificate_bytes(target.node.position, target.node.history)
        overlay_path = self.root / "verified.overlay"
        overlay = self.make_overlay(dag)
        overlay.append_verified_certificate(target.node.node_sha256, cert)
        overlay.close()

        from ugts_chess import verified_overlay as module

        with mock.patch.object(
            module.os.path,
            "samestat",
            side_effect=[True, False],
        ):
            report = verify_verified_overlay(overlay_path, dag)
        self.assertFalse(report.valid)
        self.assertEqual(report.issue.code, "path_replaced_during_read")


if __name__ == "__main__":
    unittest.main()
