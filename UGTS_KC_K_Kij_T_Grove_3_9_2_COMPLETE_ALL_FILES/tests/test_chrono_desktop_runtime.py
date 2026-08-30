import hashlib
import importlib.util
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np

from ugts_kc3.chrono_desktop import (
    ChronoDesktopPlayer,
    chrono_bundle_from_project,
    chrono_owner_node_id,
    decode_chrono_desktop_timeline,
)
from ugts_kc3.chrono_video import (
    CVPTS_APPLY_UGCVLUT1_Q8,
    CVPTS_LOOP,
    CVPTS_MEDIA_ORIGINAL_SOURCE,
    ChronoVideoProfile,
    compile_chrono_video,
    generate_video_pts_cache,
)
from ugts_kc3.mobile3d import Mobile3DProject


class ChronoDesktopTimelineTests(unittest.TestCase):
    def setUp(self):
        self.entries = [
            {
                "media_index": 0,
                "source_frame_index": 0,
                "source_pts": 100,
                "display_until_source_pts": 140,
            },
            {
                "media_index": 1,
                "source_frame_index": 1,
                "source_pts": 140,
                "display_until_source_pts": 180,
            },
            {
                "media_index": 2,
                "source_frame_index": 2,
                "source_pts": 180,
                "display_until_source_pts": 221,
            },
        ]
        self.source_hash = hashlib.sha256(b"source").hexdigest()
        self.profile_hash = hashlib.sha256(b"profile").hexdigest()
        self.media_hash = hashlib.sha256(b"source").hexdigest()

    def _timeline(self, *, loop=False):
        payload = generate_video_pts_cache(
            entries=self.entries,
            source_frame_count=3,
            media_width=64,
            media_height=48,
            time_base_num=1,
            time_base_den=1000,
            source_sha256=self.source_hash,
            profile_sha256=self.profile_hash,
            media_sha256=self.media_hash,
            flags=(
                CVPTS_MEDIA_ORIGINAL_SOURCE
                | CVPTS_APPLY_UGCVLUT1_Q8
                | (CVPTS_LOOP if loop else 0)
            ),
        )
        return decode_chrono_desktop_timeline(payload)

    def test_integer_half_open_selector_matches_native_boundaries(self):
        timeline = self._timeline()
        self.assertEqual(timeline.select_for_elapsed_nanoseconds(0), 0)
        self.assertEqual(timeline.select_for_elapsed_nanoseconds(39_999_999), 0)
        self.assertEqual(timeline.select_for_elapsed_nanoseconds(40_000_000), 1)
        self.assertEqual(timeline.select_for_elapsed_nanoseconds(79_999_999), 1)
        self.assertEqual(timeline.select_for_elapsed_nanoseconds(80_000_000), 2)
        self.assertEqual(timeline.select_for_elapsed_nanoseconds(121_000_000), 2)
        self.assertEqual(timeline.completed_cycles_for_elapsed_nanoseconds(999_000_000), 0)

    def test_loop_is_explicit_integer_modulo_only(self):
        timeline = self._timeline(loop=True)
        self.assertTrue(timeline.loops)
        self.assertEqual(timeline.select_for_elapsed_nanoseconds(120_999_999), 2)
        self.assertEqual(timeline.select_for_elapsed_nanoseconds(121_000_000), 0)
        self.assertEqual(timeline.completed_cycles_for_elapsed_nanoseconds(121_000_000), 1)

    def test_negative_or_noninteger_elapsed_time_is_rejected(self):
        timeline = self._timeline()
        for value in (-1, 1.0, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    timeline.select_for_elapsed_nanoseconds(value)  # type: ignore[arg-type]


@unittest.skipUnless(
    shutil.which("ffmpeg")
    and shutil.which("ffprobe")
    and importlib.util.find_spec("av")
    and importlib.util.find_spec("cv2"),
    "ffmpeg, ffprobe, PyAV, and OpenCV are required",
)
class ChronoDesktopPlayerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._temporary = tempfile.TemporaryDirectory()
        root = Path(cls._temporary.name)
        cls.source = root / "source.mp4"
        cls.bundle = root / "bundle"
        subprocess.run(
            [
                shutil.which("ffmpeg") or "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=64x48:rate=5:duration=0.8",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-bf",
                "0",
                str(cls.source),
            ],
            check=True,
        )
        profile = ChronoVideoProfile(
            theta_bins=32,
            rho_bins=16,
            sample_stride=1,
            tile_size=8,
            batch_size=1,
            max_vram_mib=128,
            embed_source_for_phone=True,
        )
        compile_chrono_video(cls.source, cls.bundle, profile, backend="cpu")

    @classmethod
    def tearDownClass(cls):
        cls._temporary.cleanup()

    def test_source_runtime_primes_prefetches_and_holds_last_without_overclaim(self):
        start = 10_000_000_000
        with ChronoDesktopPlayer(
            self.bundle, backend="cpu", max_vram_mib=128
        ) as player:
            first = player.start(start)
            self.assertEqual(first.ordinal, 0)
            self.assertEqual(first.rgb.shape, (16, 32, 3))
            self.assertTrue(first.logical_pts_exact)
            self.assertFalse(first.physical_display_timing_verified)
            self.assertFalse(first.late_boundary)
            self.assertEqual(
                first.rgb_sha256, hashlib.sha256(first.rgb.tobytes()).hexdigest()
            )

            second_entry = player.timeline.entries[1]
            delta = second_entry.source_pts - player.timeline.first_source_pts
            boundary_ns = math.ceil(
                delta
                * 1_000_000_000
                * player.timeline.time_base_num
                / player.timeline.time_base_den
            )
            second = player.tick(start + boundary_ns)
            self.assertEqual(second.ordinal, 1)
            self.assertFalse(second.late_boundary)
            third = player.prefetch_next()
            self.assertIsNotNone(third)
            self.assertEqual(third.ordinal, 2)

            held = player.tick(start + 100_000_000_000)
            self.assertEqual(held.ordinal, len(player.timeline.entries) - 1)
            receipt = player.receipt()
            self.assertEqual(receipt["mode"], "AUTHORITATIVE_SOURCE_LUT_Q8")
            self.assertEqual(receipt["first_frame_max_byte_difference"], 0)
            self.assertEqual(receipt["logical_pts_selection"], "EXACT_INTEGER_HALF_OPEN")
            self.assertFalse(receipt["physical_display_timing_verified"])
            self.assertFalse(receipt["video_decode_gpu_accelerated"])
            self.assertFalse(receipt["gpu_native_presentation"])
            self.assertFalse(receipt["cross_platform_color_byte_equal"])
            self.assertEqual(receipt["geometry_status"], "UNBOUNDED_UNKNOWN")
            self.assertTrue(receipt["workspace_limit_enforced_after_each_remap"])
            self.assertEqual(receipt["oracle_checked_frame_count"], 1)

    def test_compiled_project_resolves_only_through_its_hash_binding(self):
        project = Mobile3DProject.load(self.bundle / "project.json", validate=False)
        self.assertEqual(
            chrono_bundle_from_project(project, self.bundle / "project.json"),
            self.bundle.resolve(),
        )
        self.assertEqual(chrono_owner_node_id(project), "chrono_observation_root")

    def test_audit_mode_checks_every_runtime_raster_against_cpu_oracle(self):
        start = 20_000_000_000
        with ChronoDesktopPlayer(
            self.bundle,
            backend="cpu",
            max_vram_mib=128,
            verify_every_frame=True,
        ) as player:
            player.start(start)
            for expected, entry in enumerate(player.timeline.entries[1:], 1):
                delta = entry.source_pts - player.timeline.first_source_pts
                numerator = (
                    delta * 1_000_000_000 * player.timeline.time_base_num
                )
                boundary = (
                    numerator + player.timeline.time_base_den - 1
                ) // player.timeline.time_base_den
                self.assertEqual(player.tick(start + boundary).ordinal, expected)
                player.prefetch_next()
            receipt = player.receipt()
            self.assertTrue(receipt["verify_every_frame"])
            self.assertEqual(
                receipt["oracle_checked_frame_count"], len(player.timeline.entries)
            )
            self.assertEqual(receipt["oracle_max_byte_difference"], 0)


@unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 is required")
class ChronoDesktopViewportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_viewport_labels_exact_raster_separately_from_presentation(self):
        from ugts_kc3.editor.scene_view import SceneViewport

        viewport = SceneViewport()
        rgb = np.arange(8 * 16 * 3, dtype=np.uint8).reshape(8, 16, 3)
        frame = SimpleNamespace(
            ordinal=2,
            source_pts=180,
            rgb=rgb,
            rgb_sha256=hashlib.sha256(rgb.tobytes()).hexdigest(),
            backend="numpy-cpu-q8",
            logical_pts_exact=True,
            physical_display_timing_verified=False,
            late_boundary=False,
        )
        viewport.set_chrono_frame(frame)
        receipt = viewport.chrono_frame_receipt
        self.assertIsNotNone(receipt)
        self.assertEqual(receipt["ordinal"], 2)
        self.assertTrue(receipt["logical_pts_exact"])
        self.assertFalse(receipt["physical_display_timing_verified"])
        self.assertIsNone(receipt["owner_node_id"])
        chrono_items = [
            item for item in viewport.scene().items() if item.data(2) == "chrono_desktop_raster"
        ]
        self.assertEqual(len(chrono_items), 1)
        viewport.set_chrono_frame(None)
        self.assertIsNone(viewport.chrono_frame_receipt)


if __name__ == "__main__":
    unittest.main()
