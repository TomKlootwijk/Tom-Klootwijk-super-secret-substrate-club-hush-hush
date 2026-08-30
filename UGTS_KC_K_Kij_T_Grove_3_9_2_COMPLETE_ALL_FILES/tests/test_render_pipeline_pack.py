from __future__ import annotations

import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import build_android_project  # noqa: E402
from ugts_kc3.mobile3d import Mobile3DProject  # noqa: E402
from ugts_kc3.renderpack import (  # noqa: E402
    RENDER_PACK_BYTES,
    RENDER_PACK_ENDIAN,
    RENDER_PACK_MAGIC,
    RENDER_PACK_VERSION,
    RENDER_PACK_VERSION_V2,
    RENDER_PACK_V2_BYTES,
    RENDER_SUBSTRATE_PACK_ASSET,
    RenderPackError,
    compile_render_substrate_pack_bytes,
    inspect_render_substrate_pack,
)
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402


class RenderPipelinePackTests(unittest.TestCase):
    def test_absent_metadata_emits_no_asset_and_preserves_export(self) -> None:
        project = blank_mobile3d_project()
        self.assertEqual(compile_render_substrate_pack_bytes(project), b"")

        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            asset = (
                built.output_dir
                / "app/src/main/assets"
                / RENDER_SUBSTRATE_PACK_ASSET
            )
            self.assertIsNone(built.render_substrate_pack)
            self.assertIsNone(built.render_pack)
            self.assertFalse(asset.exists())
            report = json.loads(built.build_report.read_text("utf-8"))
            self.assertIsNone(report["render_substrate_runtime"])

    def test_default_record_is_exact_deterministic_and_little_endian(self) -> None:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {}
        packed = compile_render_substrate_pack_bytes(project)
        clone = Mobile3DProject.from_dict(project.to_dict())

        self.assertEqual(len(packed), RENDER_PACK_BYTES)
        self.assertEqual(compile_render_substrate_pack_bytes(clone), packed)
        self.assertEqual(
            struct.unpack("<8sIIBBHfQ", packed),
            (
                RENDER_PACK_MAGIC,
                RENDER_PACK_ENDIAN,
                RENDER_PACK_VERSION,
                0,
                1,
                64,
                struct.unpack("<f", struct.pack("<f", 0.30))[0],
                0,
            ),
        )
        info = inspect_render_substrate_pack(packed)
        self.assertEqual(info["byte_length"], 32)
        self.assertEqual(
            info["sha256"],
            "82811b7c5bd6d787b35942a1edf37f9783b2e2f239ef4da8e1055795df2f0610",
        )
        self.assertEqual(info["polar_mode"], "auto")
        self.assertEqual(info["bayer_mode"], "subtle")
        self.assertTrue(info["bayer_enabled"])
        self.assertEqual(info["levels"], 64)
        self.assertAlmostEqual(info["strength"], 0.30)
        self.assertEqual(info["format_version"], RENDER_PACK_VERSION)
        self.assertEqual(info["polar_material_mode"], "off")
        self.assertFalse(info["polar_material_enabled"])

    def test_polar_material_v2_is_exact_and_keeps_the_v1_prefix_layout(self) -> None:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {
            "polar_mode": "lut",
            "bayer_mode": "custom",
            "levels": 128,
            "strength": 0.25,
            "seed": 0x0123456789ABCDEF,
            "polar_material_mode": "bands",
            "polar_material_bands": 12,
            "polar_material_strength": 0.625,
        }
        packed = compile_render_substrate_pack_bytes(project)

        self.assertEqual(len(packed), RENDER_PACK_V2_BYTES)
        self.assertEqual(
            struct.unpack("<8sIIBBHfQ", packed[:RENDER_PACK_BYTES]),
            (
                RENDER_PACK_MAGIC,
                RENDER_PACK_ENDIAN,
                RENDER_PACK_VERSION_V2,
                1,
                3,
                128,
                0.25,
                0x0123456789ABCDEF,
            ),
        )
        self.assertEqual(struct.unpack("<BBHf", packed[RENDER_PACK_BYTES:]), (1, 12, 0, 0.625))
        info = inspect_render_substrate_pack(packed)
        self.assertEqual(info["format_version"], RENDER_PACK_VERSION_V2)
        self.assertEqual(info["polar_material_mode"], "bands")
        self.assertEqual(info["polar_material_mode_code"], 1)
        self.assertEqual(info["polar_material_bands"], 12)
        self.assertEqual(info["polar_material_strength"], 0.625)
        self.assertTrue(info["polar_material_enabled"])
        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNotNone(built.render_substrate_pack)
            self.assertEqual(built.render_substrate_pack.read_bytes(), packed)
            report = json.loads(built.build_report.read_text("utf-8"))
            runtime = report["render_substrate_runtime"]
            self.assertEqual(runtime["byte_length"], RENDER_PACK_V2_BYTES)
            self.assertEqual(runtime["format_version"], RENDER_PACK_VERSION_V2)
            self.assertEqual(runtime["polar_material_mode"], "bands")
            self.assertTrue(runtime["polar_material_enabled"])

    def test_modes_presets_custom_values_and_uint64_seed_round_trip(self) -> None:
        cases = (
            (
                {"polar_mode": "cpu", "bayer_mode": "off", "seed": 2**64 - 1},
                ("cpu", 3, "off", 0, 2, 0.0, 2**64 - 1, False),
            ),
            (
                {"polar_mode": "direct", "bayer_mode": "retro"},
                ("direct", 2, "retro", 2, 4, 1.0, 0, True),
            ),
            (
                {
                    "polar_mode": "lut",
                    "bayer_mode": "custom",
                    "levels": 256,
                    "strength": 0.125,
                    "seed": 0x123456789ABCDEF0,
                },
                ("lut", 1, "custom", 3, 256, 0.125, 0x123456789ABCDEF0, True),
            ),
            (
                {"bayer_mode": "subtle", "levels": 32, "strength": 0.5},
                ("auto", 0, "subtle", 1, 32, 0.5, 0, True),
            ),
        )
        for metadata, expected in cases:
            with self.subTest(metadata=metadata):
                project = blank_mobile3d_project()
                project.metadata["substrate_render"] = metadata
                info = inspect_render_substrate_pack(
                    compile_render_substrate_pack_bytes(project)
                )
                actual = (
                    info["polar_mode"],
                    info["polar_mode_code"],
                    info["bayer_mode"],
                    info["bayer_mode_code"],
                    info["levels"],
                    info["strength"],
                    info["seed"],
                    info["bayer_enabled"],
                )
                self.assertEqual(actual, expected)

    def test_metadata_validation_fails_clearly(self) -> None:
        invalid = (
            ([], "must be an object"),
            ({"mystery": 1}, "unknown key"),
            ({"polar_mode": "gpu"}, "polar_mode must be one of"),
            ({"bayer_mode": "blue-noise"}, "bayer_mode must be one of"),
            ({"bayer_mode": "custom", "strength": 0.5}, "requires explicit levels"),
            ({"bayer_mode": "custom", "levels": 64}, "requires explicit strength"),
            ({"levels": True}, "levels must be an integer"),
            ({"levels": 1}, "levels must be from 2 to 256"),
            ({"levels": 257}, "levels must be from 2 to 256"),
            ({"strength": False}, "strength must be a finite number"),
            ({"strength": math.nan}, "strength must be a finite number"),
            ({"strength": math.inf}, "strength must be a finite number"),
            ({"strength": -0.01}, "strength must be a finite number"),
            ({"strength": 1.01}, "strength must be a finite number"),
            ({"seed": True}, "seed must be an unsigned 64-bit integer"),
            ({"seed": -1}, "seed must be an unsigned 64-bit integer"),
            ({"seed": 2**64}, "seed must be an unsigned 64-bit integer"),
            ({"bayer_mode": "off", "strength": 0.01}, "requires strength exactly 0"),
            ({"polar_material_mode": "bands"}, "requires explicit"),
            ({"polar_material_bands": 4}, "requires explicit"),
            ({"polar_material_strength": 0.5}, "requires explicit"),
            (
                {
                    "polar_material_mode": "ribbons",
                    "polar_material_bands": 4,
                    "polar_material_strength": 0.5,
                },
                "polar_material_mode must be one of",
            ),
            (
                {
                    "polar_material_mode": "bands",
                    "polar_material_bands": True,
                    "polar_material_strength": 0.5,
                },
                "polar_material_bands must be an integer",
            ),
            (
                {
                    "polar_material_mode": "bands",
                    "polar_material_bands": 0,
                    "polar_material_strength": 0.5,
                },
                "polar_material_bands must be from 1 to 32",
            ),
            (
                {
                    "polar_material_mode": "bands",
                    "polar_material_bands": 33,
                    "polar_material_strength": 0.5,
                },
                "polar_material_bands must be from 1 to 32",
            ),
            (
                {
                    "polar_material_mode": "bands",
                    "polar_material_bands": 4,
                    "polar_material_strength": math.nan,
                },
                "polar_material_strength must be a finite",
            ),
            (
                {
                    "polar_material_mode": "bands",
                    "polar_material_bands": 4,
                    "polar_material_strength": -0.0,
                },
                "polar_material_strength must be a finite positive-zero",
            ),
            (
                {
                    "polar_material_mode": "bands",
                    "polar_material_bands": 4,
                    "polar_material_strength": 1.01,
                },
                "polar_material_strength must be a finite positive-zero",
            ),
            (
                {
                    "polar_material_mode": "off",
                    "polar_material_bands": 1,
                    "polar_material_strength": 0.01,
                },
                "off mode requires strength exactly",
            ),
        )
        for raw, message in invalid:
            with self.subTest(raw=raw):
                project = blank_mobile3d_project()
                project.metadata["substrate_render"] = raw
                with self.assertRaisesRegex(RenderPackError, message):
                    compile_render_substrate_pack_bytes(project)

    def test_inspector_rejects_truncation_trailing_bytes_and_bad_fields(self) -> None:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {"bayer_mode": "off"}
        packed = compile_render_substrate_pack_bytes(project)

        with self.assertRaisesRegex(RenderPackError, "truncated"):
            inspect_render_substrate_pack(packed[:-1])
        with self.assertRaisesRegex(RenderPackError, "trailing bytes: 1"):
            inspect_render_substrate_pack(packed + b"x")

        corruptions = []
        bad_magic = bytearray(packed)
        bad_magic[0] ^= 0xFF
        corruptions.append((bad_magic, "magic mismatch"))
        bad_endian = bytearray(packed)
        struct.pack_into("<I", bad_endian, 8, 0)
        corruptions.append((bad_endian, "endian marker mismatch"))
        bad_version = bytearray(packed)
        struct.pack_into("<I", bad_version, 12, 3)
        corruptions.append((bad_version, "unsupported render-substrate version"))
        bad_polar = bytearray(packed)
        bad_polar[16] = 4
        corruptions.append((bad_polar, "polar mode is invalid"))
        bad_bayer = bytearray(packed)
        bad_bayer[17] = 4
        corruptions.append((bad_bayer, "Bayer mode is invalid"))
        bad_levels = bytearray(packed)
        struct.pack_into("<H", bad_levels, 18, 1)
        corruptions.append((bad_levels, "Bayer levels are invalid"))
        bad_strength = bytearray(packed)
        struct.pack_into("<f", bad_strength, 20, math.nan)
        corruptions.append((bad_strength, "Bayer strength is invalid"))
        inconsistent_off = bytearray(packed)
        struct.pack_into("<f", inconsistent_off, 20, 0.5)
        corruptions.append((inconsistent_off, "off Bayer mode has nonzero strength"))

        for corrupted, message in corruptions:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RenderPackError, message):
                    inspect_render_substrate_pack(corrupted)

    def test_inspector_rejects_mixed_or_malformed_v2_records(self) -> None:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {
            "polar_material_mode": "bands",
            "polar_material_bands": 8,
            "polar_material_strength": 0.75,
        }
        packed = compile_render_substrate_pack_bytes(project)
        legacy = bytearray(packed[:RENDER_PACK_BYTES])
        struct.pack_into("<I", legacy, 12, RENDER_PACK_VERSION)

        with self.assertRaisesRegex(RenderPackError, "truncated"):
            inspect_render_substrate_pack(packed[:RENDER_PACK_BYTES])
        with self.assertRaisesRegex(RenderPackError, "trailing bytes: 8"):
            inspect_render_substrate_pack(legacy + packed[RENDER_PACK_BYTES:])

        corruptions = []
        bad_mode = bytearray(packed)
        bad_mode[32] = 2
        corruptions.append((bad_mode, "Polar Material mode is invalid"))
        bad_bands_low = bytearray(packed)
        bad_bands_low[33] = 0
        corruptions.append((bad_bands_low, "Polar Material bands are invalid"))
        bad_bands_high = bytearray(packed)
        bad_bands_high[33] = 33
        corruptions.append((bad_bands_high, "Polar Material bands are invalid"))
        bad_reserved = bytearray(packed)
        struct.pack_into("<H", bad_reserved, 34, 1)
        corruptions.append((bad_reserved, "reserved field is nonzero"))
        bad_nan = bytearray(packed)
        struct.pack_into("<f", bad_nan, 36, math.nan)
        corruptions.append((bad_nan, "Polar Material strength is invalid"))
        bad_negative_zero = bytearray(packed)
        struct.pack_into("<f", bad_negative_zero, 36, -0.0)
        corruptions.append((bad_negative_zero, "Polar Material strength is invalid"))
        inconsistent_off = bytearray(packed)
        inconsistent_off[32] = 0
        corruptions.append((inconsistent_off, "off mode has nonzero strength"))

        for corrupted, message in corruptions:
            with self.subTest(message=message):
                with self.assertRaisesRegex(RenderPackError, message):
                    inspect_render_substrate_pack(corrupted)

    def test_android_export_packages_asset_path_and_report_inspection(self) -> None:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {
            "polar_mode": "lut",
            "bayer_mode": "custom",
            "levels": 128,
            "strength": 0.25,
            "seed": 42,
        }
        expected = compile_render_substrate_pack_bytes(project)

        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            expected_path = (
                built.output_dir
                / "app/src/main/assets"
                / RENDER_SUBSTRATE_PACK_ASSET
            )
            self.assertEqual(built.render_substrate_pack, expected_path)
            self.assertEqual(built.render_pack, expected_path)
            self.assertEqual(expected_path.read_bytes(), expected)

            report = json.loads(built.build_report.read_text("utf-8"))
            runtime = report["render_substrate_runtime"]
            self.assertEqual(runtime["byte_length"], 32)
            self.assertEqual(runtime["sha256"], inspect_render_substrate_pack(expected)["sha256"])
            self.assertEqual(runtime["polar_mode"], "lut")
            self.assertEqual(runtime["bayer_mode"], "custom")
            self.assertEqual(runtime["levels"], 128)
            self.assertEqual(runtime["strength"], 0.25)
            self.assertEqual(runtime["seed"], 42)
            self.assertIn(
                f"app/src/main/assets/{RENDER_SUBSTRATE_PACK_ASSET}",
                {entry["path"] for entry in report["files"]},
            )

    def test_invalid_metadata_does_not_destroy_existing_output(self) -> None:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {"bayer_mode": "custom"}
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "android"
            output.mkdir()
            sentinel = output / "keep.txt"
            sentinel.write_text("keep", encoding="utf-8")
            with self.assertRaisesRegex(RenderPackError, "requires explicit"):
                build_android_project(project, output)
            self.assertEqual(sentinel.read_text("utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
