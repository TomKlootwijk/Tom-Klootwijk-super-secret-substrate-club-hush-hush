from __future__ import annotations

from dataclasses import replace
import gzip
import hashlib
from importlib import resources
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from ugts_chess.constants import BLACK, WHITE
from ugts_chess.hashing import canonical_json_bytes
import ugts_chess.kxk_partition_lemma as lemma
from ugts_chess.kxk_partition_lemma import (
    KXK_PARTITION_LEMMA_HEAD_SCHEMA,
    KXKPartitionLemmaHead,
    KXKPartitionLemmaHeadMismatchError,
    KXKPartitionLemmaIntegrityError,
    KXKPartitionLemmaSourceChangedError,
    clear_kxk_partition_lemma_cache,
    verify_bundled_kxk_partition,
    verify_kxk_partition_files,
)
from ugts_chess.position import Position
from ugts_chess.rules import legal_moves


def kqk_metrics() -> lemma._ReplayMetrics:
    return lemma._ReplayMetrics(
        valid_positions=368452,
        invalid_positions=155836,
        win_positions=144508,
        loss_positions=200896,
        draw_positions=23048,
        initial_checkmates=364,
        initial_stalemates=872,
        legal_transition_count=4891672,
        capture_draw_exit_count=22176,
        max_rank=20,
    )


def kqk_head() -> KXKPartitionLemmaHead:
    return KXKPartitionLemmaHead(
        verifier_profile=lemma.KXK_PARTITION_LEMMA_VERIFIER_PROFILE,
        rules_profile_id=lemma.RULE_PROFILE_ID,
        base_game_profile=lemma.KXK_BASE_GAME_PROFILE,
        source_schema=lemma.KXK_SOURCE_SCHEMA,
        piece="Q",
        material="KQK",
        address_bits=lemma.ADDRESS_BITS,
        address_count=lemma.ADDRESS_COUNT,
        transport_size=144368,
        transport_sha256=(
            "3f38429ccd04c07f1871047082f21a809d74aa2e03d7b251d780c3900ea54743"
        ),
        metadata_size=720,
        metadata_sha256=(
            "6d10ad8a88bc8e4c704fd7d73cdf51641ed3aecc1e586fe6277af33f7c5b1982"
        ),
        decoded_size=lemma.DECODED_BYTES,
        decoded_sha256=(
            "f564613d8362650e6c8290660c3be52adbb853ba0ca9eaf5f4a5ec41b920aef5"
        ),
        valid_positions=368452,
        invalid_positions=155836,
        win_positions=144508,
        loss_positions=200896,
        draw_positions=23048,
        initial_checkmates=364,
        initial_stalemates=872,
        legal_transition_count=4891672,
        capture_draw_exit_count=22176,
        max_rank=20,
    )


class KXKPartitionLemmaTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_kxk_partition_lemma_cache()
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        clear_kxk_partition_lemma_cache()
        self.temporary.cleanup()

    def copy_kqk_sources(self) -> tuple[Path, Path]:
        package = resources.files("ugts_chess.resources")
        transport = self.root / "kqk.tb.gz"
        metadata = self.root / "kqk.tb.json"
        transport.write_bytes(package.joinpath("kqk.tb.gz").read_bytes())
        metadata.write_bytes(package.joinpath("kqk.tb.json").read_bytes())
        return transport, metadata

    def test_01_head_is_strict_canonical_and_schema_valid(self) -> None:
        head = kqk_head()
        self.assertEqual(head.record()["schema"], KXK_PARTITION_LEMMA_HEAD_SCHEMA)
        self.assertEqual(
            head.head_sha256,
            "48f8e342a23be6448f922eaa2014040f862133f61ab6f93a7428d7e0e4ce9dac",
        )
        self.assertEqual(KXKPartitionLemmaHead.from_bytes(head.canonical_bytes()), head)

        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema is available in the validation environment only")
        schema_path = (
            Path(__file__).resolve().parents[1]
            / "spec"
            / "ugts_chess_kxk_partition_lemma_head.schema.json"
        )
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(head.record(), schema)

    def test_02_head_parser_rejects_hostile_shapes_and_cross_fields(self) -> None:
        head = kqk_head()
        record = head.record()
        hostile = {
            "whitespace": b" " + head.canonical_bytes(),
            "invalid_utf8": b"\xff",
            "oversized": b"{" + b" " * lemma.MAX_KXK_PARTITION_LEMMA_HEAD_BYTES,
            "wrong_schema": canonical_json_bytes({**record, "schema": "wrong"}),
            "wrong_piece_material": canonical_json_bytes(
                {**record, "piece": "R", "material": "KQK"}
            ),
            "boolean_count": canonical_json_bytes(
                {**record, "valid_positions": True}
            ),
            "bad_count_sum": canonical_json_bytes(
                {**record, "invalid_positions": head.invalid_positions + 1}
            ),
            "bad_wdl_sum": canonical_json_bytes(
                {**record, "draw_positions": head.draw_positions - 1}
            ),
            "transition_overflow": canonical_json_bytes(
                {
                    **record,
                    "legal_transition_count": lemma.MAX_LEGAL_TRANSITIONS + 1,
                }
            ),
            "exit_overflow": canonical_json_bytes(
                {
                    **record,
                    "legal_transition_count": lemma.MAX_LEGAL_TRANSITIONS,
                    "capture_draw_exit_count": lemma.MAX_LEGAL_TRANSITIONS + 1,
                }
            ),
            "uppercase_hash": canonical_json_bytes(
                {**record, "decoded_sha256": head.decoded_sha256.upper()}
            ),
            "extra": canonical_json_bytes({**record, "extra": 1}),
            "missing": canonical_json_bytes(
                {key: value for key, value in record.items() if key != "max_rank"}
            ),
        }
        for name, payload in hostile.items():
            with self.subTest(name=name), self.assertRaises(ValueError):
                KXKPartitionLemmaHead.from_bytes(payload)
        with self.assertRaises(TypeError):
            KXKPartitionLemmaHead.from_bytes("not bytes")  # type: ignore[arg-type]
        for oversized in (
            bytearray(lemma.MAX_KXK_PARTITION_LEMMA_HEAD_BYTES + 1),
            memoryview(bytearray(lemma.MAX_KXK_PARTITION_LEMMA_HEAD_BYTES + 1)),
        ):
            with self.subTest(oversized_type=type(oversized).__name__), self.assertRaises(
                ValueError
            ):
                KXKPartitionLemmaHead.from_bytes(oversized)

    def test_03_local_rank_equations_accept_exact_terminal_and_cycle_rules(self) -> None:
        accepted = (
            dict(index=0, outcome=lemma._LOSS, rank=0, terminal="checkmate", children=()),
            dict(index=1, outcome=lemma._DRAW, rank=0, terminal="stalemate", children=()),
            dict(index=2, outcome=lemma._WIN, rank=3, terminal=None, children=((lemma._LOSS, 2), (lemma._DRAW, 0))),
            dict(index=3, outcome=lemma._LOSS, rank=5, terminal=None, children=((lemma._WIN, 2), (lemma._WIN, 4))),
            dict(index=4, outcome=lemma._DRAW, rank=0, terminal=None, children=((lemma._WIN, 7), (lemma._DRAW, 0))),
        )
        for values in accepted:
            with self.subTest(values=values):
                lemma._check_rank_equation(**values)

    def test_04_local_rank_equations_reject_false_draws_and_rank_cycles(self) -> None:
        rejected = (
            dict(index=0, outcome=lemma._WIN, rank=0, terminal="checkmate", children=()),
            dict(index=1, outcome=lemma._DRAW, rank=0, terminal=None, children=((lemma._LOSS, 0), (lemma._DRAW, 0))),
            dict(index=2, outcome=lemma._DRAW, rank=0, terminal=None, children=((lemma._WIN, 1),)),
            dict(index=3, outcome=lemma._WIN, rank=3, terminal=None, children=((lemma._LOSS, 3),)),
            dict(index=4, outcome=lemma._LOSS, rank=4, terminal=None, children=((lemma._WIN, 4),)),
            dict(index=5, outcome=lemma._LOSS, rank=2, terminal=None, children=((lemma._DRAW, 0),)),
            dict(index=6, outcome=lemma._DRAW, rank=1, terminal=None, children=((lemma._DRAW, 0),)),
        )
        for values in rejected:
            with self.subTest(values=values), self.assertRaises(
                KXKPartitionLemmaIntegrityError
            ):
                lemma._check_rank_equation(**values)

    def test_05_canonical_validity_uses_rule_oracle_not_tablebase_helpers(self) -> None:
        checkmate = lemma._encode_key(42, 49, 56, BLACK)
        position = lemma._canonical_position(checkmate, "Q")
        self.assertIsNotNone(position)
        self.assertEqual(position.to_fen(), "k7/1Q6/2K5/8/8/8/8/8 b - - 0 1")  # type: ignore[union-attr]

        collision = lemma._encode_key(0, 0, 63, WHITE)
        adjacent_kings = lemma._encode_key(0, 8, 1, BLACK)
        impossible_previous_check = lemma._encode_key(42, 49, 56, WHITE)
        for key in (collision, adjacent_kings, impossible_previous_check):
            with self.subTest(key=key):
                self.assertIsNone(lemma._canonical_position(key, "Q"))

        castling_rights = Position.from_fen(
            "6k1/8/8/8/8/8/8/4K2R w K - 0 1"
        )
        self.assertIn("e1g1", {move.uci() for move in legal_moves(castling_rights)})
        canonical_krk = lemma._canonical_position(
            lemma._encode_key(4, 7, 62, WHITE),
            "R",
        )
        self.assertIsNotNone(canonical_krk)
        self.assertEqual(
            canonical_krk.to_fen(),  # type: ignore[union-attr]
            "6k1/8/8/8/8/8/8/4K2R w - - 0 1",
        )
        self.assertNotIn(
            "e1g1",
            {move.uci() for move in legal_moves(canonical_krk)},  # type: ignore[arg-type]
        )
        self.assertEqual(canonical_krk.castling, 0)  # type: ignore[union-attr]
        self.assertEqual(canonical_krk.ep_square, -1)  # type: ignore[union-attr]

    def test_06_source_capture_rejects_mutation_and_strict_transport_metadata(self) -> None:
        transport, metadata = self.copy_kqk_sources()
        with mock.patch.object(lemma, "_read_bounded", side_effect=[b"a", b"b"]):
            with self.assertRaises(KXKPartitionLemmaSourceChangedError):
                lemma._stable_snapshot(transport, maximum=lemma.MAX_TRANSPORT_BYTES, label="test")

        stable_path = self.root / "stable-source.bin"
        stable_path.write_bytes(b"aaaa")
        stable = lemma._stable_snapshot(stable_path, maximum=4, label="stable")
        stable_path.write_bytes(b"bbbb")
        os.utime(
            stable_path,
            ns=(stable.identity.modified_ns, stable.identity.modified_ns),
        )
        with self.assertRaises(KXKPartitionLemmaSourceChangedError):
            lemma._confirm_snapshot(stable, label="stable")

        broken_transport = bytearray(transport.read_bytes())
        broken_transport[0] ^= 0x01
        transport.write_bytes(broken_transport)
        with self.assertRaises(KXKPartitionLemmaIntegrityError):
            verify_kxk_partition_files(transport, metadata, piece="Q")

        transport, metadata = self.copy_kqk_sources()
        self.assertEqual(
            len(lemma._decode_transport(transport.read_bytes(), piece="Q")),
            lemma.DECODED_BYTES,
        )
        with self.assertRaises(KXKPartitionLemmaIntegrityError):
            lemma._decode_transport(
                transport.read_bytes() + gzip.compress(b""),
                piece="Q",
            )
        raw_transport = gzip.decompress(transport.read_bytes())
        noncanonical_header = bytearray(raw_transport)
        noncanonical_header[9] = 1
        with self.assertRaises(KXKPartitionLemmaIntegrityError):
            lemma._decode_transport(
                gzip.compress(noncanonical_header),
                piece="Q",
            )
        duplicate_piece = metadata.read_bytes().replace(
            b"{",
            b'{"piece":"Q",',
            1,
        )
        with self.assertRaises(KXKPartitionLemmaIntegrityError):
            lemma._strict_metadata(
                duplicate_piece,
                piece="Q",
                transport_size=transport.stat().st_size,
                transport_sha256=kqk_head().transport_sha256,
            )

        canonical_metadata = json.loads(metadata.read_text(encoding="utf-8"))
        for key in (
            "address_bits",
            "address_count",
            "raw_payload_bytes",
            "file_bytes",
        ):
            floated = dict(canonical_metadata)
            floated[key] = float(floated[key])
            with self.subTest(float_metadata_key=key), self.assertRaises(
                KXKPartitionLemmaIntegrityError
            ):
                lemma._strict_metadata(
                    json.dumps(floated).encode("utf-8"),
                    piece="Q",
                    transport_size=transport.stat().st_size,
                    transport_sha256=kqk_head().transport_sha256,
                )

        raw = json.loads(metadata.read_text(encoding="utf-8"))
        raw["semantics"] = "trust the probe"
        metadata.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(KXKPartitionLemmaIntegrityError):
            verify_kxk_partition_files(transport, metadata, piece="Q")

    def test_07_cache_is_published_only_after_complete_success_and_hashes_sources(self) -> None:
        transport, metadata = self.copy_kqk_sources()
        with mock.patch.object(
            lemma,
            "_replay_partition",
            side_effect=KXKPartitionLemmaIntegrityError("synthetic replay failure"),
        ):
            with self.assertRaises(KXKPartitionLemmaIntegrityError):
                verify_kxk_partition_files(transport, metadata, piece="Q")
        self.assertFalse(lemma._VERIFIED_CACHE)

        metrics = kqk_metrics()
        with mock.patch.object(lemma, "_replay_partition", return_value=metrics) as replay:
            first = verify_kxk_partition_files(transport, metadata, piece="Q")
            second = verify_kxk_partition_files(transport, metadata, piece="Q")
        self.assertFalse(first.cache_hit)
        self.assertTrue(second.cache_hit)
        self.assertEqual(replay.call_count, 1)
        self.assertEqual(first.head, kqk_head())

        mutated = json.loads(metadata.read_text(encoding="utf-8"))
        mutated["max_dtm_plies"] = 21
        metadata.write_text(json.dumps(mutated), encoding="utf-8")
        with mock.patch.object(
            lemma,
            "_replay_partition",
            side_effect=KXKPartitionLemmaIntegrityError("new hash replayed"),
        ) as mutated_replay:
            with self.assertRaises(KXKPartitionLemmaIntegrityError):
                verify_kxk_partition_files(transport, metadata, piece="Q")
        self.assertEqual(mutated_replay.call_count, 1)

    def test_08_external_head_is_exact_and_type_checked(self) -> None:
        transport, metadata = self.copy_kqk_sources()
        with mock.patch.object(lemma, "_replay_partition", return_value=kqk_metrics()):
            verified = verify_kxk_partition_files(
                transport,
                metadata,
                piece="Q",
                required_head=kqk_head(),
            )
        self.assertEqual(verified.head, kqk_head())

        forged = replace(kqk_head(), legal_transition_count=4891673)
        with self.assertRaises(KXKPartitionLemmaHeadMismatchError) as captured:
            verify_kxk_partition_files(
                transport,
                metadata,
                piece="Q",
                required_head=forged,
            )
        self.assertEqual(captured.exception.expected, forged)
        self.assertEqual(captured.exception.current, kqk_head())
        with self.assertRaises(TypeError):
            verify_kxk_partition_files(
                transport,
                metadata,
                piece="Q",
                required_head=object(),  # type: ignore[arg-type]
            )
        with self.assertRaises(TypeError):
            verify_kxk_partition_files(
                transport,
                metadata,
                piece="Q",
                use_cache=1,  # type: ignore[arg-type]
            )

    def test_09_retained_head_artifacts_have_exact_lf_and_hashes(self) -> None:
        validation = Path(__file__).resolve().parents[1] / "validation" / "endgame"
        expected = {
            "kqk": (
                "48f8e342a23be6448f922eaa2014040f862133f61ab6f93a7428d7e0e4ce9dac",
                "12269b92d8d32649154b267d03f99be924585cd0bc0b8a6540161abcbde9aa35",
            ),
            "krk": (
                "00534bf1dca4cbd1ea42308509fc8b94363a3747cf2ec4b19227dc64be5a2b43",
                "2d355dd1232f6e75e494774e15ef0f2a4c18d5b9aa1761efc131b17b559f5372",
            ),
        }
        for name, (head_sha256, raw_sha256) in expected.items():
            with self.subTest(name=name):
                raw = (validation / f"{name}-partition-lemma-head.json").read_bytes()
                canonical = canonical_json_bytes(json.loads(raw))
                retained = KXKPartitionLemmaHead.from_bytes(canonical)
                self.assertEqual(raw, retained.canonical_bytes() + b"\n")
                self.assertEqual(retained.head_sha256, head_sha256)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), raw_sha256)

    @unittest.skipUnless(
        os.environ.get("UGTS_RUN_SLOW_KXK_LEMMA") == "1",
        "set UGTS_RUN_SLOW_KXK_LEMMA=1 for ~3 minute full KQK/KRK replay",
    )
    def test_10_real_bundled_resources_reproduce_retained_heads(self) -> None:
        validation = Path(__file__).resolve().parents[1] / "validation" / "endgame"
        for piece, name in (("Q", "kqk"), ("R", "krk")):
            with self.subTest(piece=piece):
                raw = (validation / f"{name}-partition-lemma-head.json").read_bytes()
                canonical = canonical_json_bytes(json.loads(raw))
                retained = KXKPartitionLemmaHead.from_bytes(canonical)
                self.assertEqual(raw, retained.canonical_bytes() + b"\n")
                result = verify_bundled_kxk_partition(
                    piece,
                    required_head=retained,
                    use_cache=False,
                )
                self.assertFalse(result.cache_hit)
                self.assertEqual(result.head, retained)


if __name__ == "__main__":
    unittest.main()
