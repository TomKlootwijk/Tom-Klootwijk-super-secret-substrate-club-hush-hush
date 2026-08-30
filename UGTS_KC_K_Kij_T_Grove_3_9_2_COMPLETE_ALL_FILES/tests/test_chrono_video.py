import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest

import numpy as np

from ugts_kc3.chrono_video import (
    CVPTS_ALREADY_LOG_POLAR,
    CVPTS_APPLY_UGCVLUT1_Q8,
    CVPTS_LOOP,
    CVPTS_MEDIA_DERIVED_POLAR_PREVIEW,
    CVPTS_MEDIA_ORIGINAL_SOURCE,
    ChronoVideoError,
    ChronoVideoProfile,
    _CudaQ8Remapper,
    compile_chrono_video,
    generate_video_polar_lut,
    generate_video_pts_cache,
    inspect_video_polar_lut,
    inspect_chrono_profile_receipt,
    inspect_video_pts_cache,
    probe_video,
    remap_rgb_q8_numpy,
    verify_chrono_bundle,
    verify_tile_partition,
)


class ChronoVideoLutTests(unittest.TestCase):
    def setUp(self):
        self.profile = ChronoVideoProfile(
            theta_bins=32,
            rho_bins=16,
            sample_stride=1,
            tile_size=8,
            batch_size=1,
            max_vram_mib=128,
        )

    def test_cvlut_roundtrip_is_strict_and_separate_from_uglut2(self):
        payload = generate_video_polar_lut(16, 12, self.profile)
        report = inspect_video_polar_lut(payload)
        self.assertEqual(report["magic"], "UGCVLUT1")
        self.assertEqual(report["texture_format"], "RGBA16UI")
        self.assertEqual(report["source_width"], 16)
        self.assertEqual(report["source_height"], 12)
        self.assertNotEqual(payload[:6], b"UGLUT2")
        with self.assertRaisesRegex(ChronoVideoError, "payload length mismatch"):
            inspect_video_polar_lut(payload + b"\x00")
        corrupted = bytearray(payload)
        corrupted[-1] ^= 1
        with self.assertRaisesRegex(ChronoVideoError, "SHA-256 mismatch"):
            inspect_video_polar_lut(bytes(corrupted))

    def test_reference_integer_remap_is_repeatable(self):
        lut = generate_video_polar_lut(16, 12, self.profile)
        frame = np.arange(16 * 12 * 3, dtype=np.uint8).reshape(12, 16, 3)
        first = remap_rgb_q8_numpy(frame, lut)
        second = remap_rgb_q8_numpy(frame, lut)
        self.assertEqual(first.shape, (16, 32, 3))
        self.assertEqual(first.dtype, np.uint8)
        self.assertEqual(first.tobytes(), second.tobytes())
        self.assertEqual(
            hashlib.sha256(first.tobytes()).hexdigest(),
            hashlib.sha256(second.tobytes()).hexdigest(),
        )

    def test_cvlut_valid_addresses_own_the_full_bilinear_footprint(self):
        profile = ChronoVideoProfile(
            theta_bins=16,
            rho_bins=16,
            core_radius_pixels=0.01,
            sample_stride=1,
            tile_size=8,
            batch_size=1,
            max_vram_mib=128,
        )
        payload = generate_video_polar_lut(2, 2, profile)
        report = inspect_video_polar_lut(payload)
        header_bytes = len(payload) - report["payload_bytes"]
        lanes = np.frombuffer(payload, dtype="<u2", offset=header_bytes).reshape(
            report["rho_bins"], report["theta_bins"], 4
        )
        valid = lanes[..., 3] == 1
        self.assertTrue(np.all(lanes[..., 0][valid] + 1 < report["source_width"]))
        self.assertTrue(np.all(lanes[..., 1][valid] + 1 < report["source_height"]))

        malformed = bytearray(payload)
        struct.pack_into("<H", malformed, header_bytes, report["source_width"] - 1)
        struct.pack_into("<H", malformed, header_bytes + 6, 1)
        malformed[header_bytes - 32 : header_bytes] = hashlib.sha256(
            malformed[header_bytes:]
        ).digest()
        with self.assertRaisesRegex(ChronoVideoError, "bilinear footprint"):
            inspect_video_polar_lut(bytes(malformed))

    def test_source_tiles_cover_every_pixel_once(self):
        report = verify_tile_partition(17, 11, 8)
        self.assertEqual(report["covered_pixels"], 17 * 11)
        self.assertEqual(report["coverage_multiplicity"], 1)
        self.assertEqual(report["canonical_state"], "UNKNOWN")

    def test_cuda_q8_matches_cpu_byte_for_byte_when_available(self):
        try:
            import torch
        except ImportError:
            self.skipTest("PyTorch is unavailable")
        if not torch.cuda.is_available():
            self.skipTest("CUDA is unavailable")
        lut = generate_video_polar_lut(16, 12, self.profile)
        frame = np.arange(16 * 12 * 3, dtype=np.uint8).reshape(12, 16, 3)
        expected = remap_rgb_q8_numpy(frame, lut)
        actual = _CudaQ8Remapper(lut, 128).remap([frame])[0]
        self.assertEqual(expected.tobytes(), actual.tobytes())

    def test_profile_rejects_unbounded_or_odd_lut_dimensions(self):
        for profile in (
            ChronoVideoProfile(theta_bins=31, rho_bins=16),
            ChronoVideoProfile(theta_bins=32, rho_bins=15),
            ChronoVideoProfile(theta_bins=8192, rho_bins=4096),
        ):
            with self.subTest(profile=profile):
                with self.assertRaises(ValueError):
                    profile.validate()


class ChronoVideoPtsCacheTests(unittest.TestCase):
    def setUp(self):
        self.source_hash = hashlib.sha256(b"source").hexdigest()
        self.profile_hash = hashlib.sha256(b"profile").hexdigest()
        self.media_hash = hashlib.sha256(b"media").hexdigest()
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

    def _build(
        self, *, entries=None, flags=None, time_base_num=1, time_base_den=1000
    ):
        return generate_video_pts_cache(
            entries=self.entries if entries is None else entries,
            source_frame_count=3,
            media_width=64,
            media_height=48,
            time_base_num=time_base_num,
            time_base_den=time_base_den,
            source_sha256=self.source_hash,
            profile_sha256=self.profile_hash,
            media_sha256=self.media_hash,
            flags=(
                CVPTS_MEDIA_ORIGINAL_SOURCE | CVPTS_APPLY_UGCVLUT1_Q8
                if flags is None
                else flags
            ),
        )

    def test_pts_cache_roundtrip_binds_finite_exact_source_intervals(self):
        payload = self._build()
        report = inspect_video_pts_cache(payload)
        self.assertEqual(payload[:8], b"UGCVPTS1")
        self.assertEqual(report["header_bytes"], 208)
        self.assertEqual(report["entry_bytes"], 32)
        self.assertEqual(report["entry_count"], 3)
        self.assertEqual(report["first_source_pts"], 100)
        self.assertEqual(report["end_source_pts_exclusive"], 221)
        self.assertEqual(report["source_sha256"], self.source_hash)
        self.assertEqual(report["profile_sha256"], self.profile_hash)
        self.assertEqual(report["media_sha256"], self.media_hash)
        self.assertEqual(report["media_role"], "ORIGINAL_SOURCE")
        self.assertEqual(report["raster_mode"], "APPLY_UGCVLUT1_Q8")
        self.assertEqual(report["playback_mode"], "ONCE_HOLD_LAST")
        self.assertFalse(report["flags"] & CVPTS_LOOP)

    def test_pts_cache_rejects_corruption_and_truncation(self):
        payload = self._build()
        with self.assertRaisesRegex(ChronoVideoError, "length mismatch"):
            inspect_video_pts_cache(payload[:-1])
        corrupted = bytearray(payload)
        corrupted[-1] ^= 1
        with self.assertRaisesRegex(ChronoVideoError, "content SHA-256 mismatch"):
            inspect_video_pts_cache(bytes(corrupted))

    def test_pts_cache_rejects_interval_gaps_and_contradictory_flags(self):
        gapped = [dict(item) for item in self.entries]
        gapped[1]["source_pts"] = 141
        with self.assertRaisesRegex(ChronoVideoError, "intervals must be contiguous"):
            self._build(entries=gapped)
        with self.assertRaisesRegex(ChronoVideoError, "contradictory"):
            self._build(
                flags=(
                    CVPTS_MEDIA_ORIGINAL_SOURCE
                    | CVPTS_MEDIA_DERIVED_POLAR_PREVIEW
                    | CVPTS_APPLY_UGCVLUT1_Q8
                )
            )
        with self.assertRaisesRegex(ChronoVideoError, "do not match"):
            self._build(
                flags=CVPTS_MEDIA_ORIGINAL_SOURCE | CVPTS_ALREADY_LOG_POLAR
            )

    def test_pts_cache_rejects_noncanonical_sha_text(self):
        with self.assertRaisesRegex(ChronoVideoError, "lowercase SHA-256 hex"):
            generate_video_pts_cache(
                entries=self.entries,
                source_frame_count=3,
                media_width=64,
                media_height=48,
                time_base_num=1,
                time_base_den=1000,
                source_sha256=" " + self.source_hash,
                profile_sha256=self.profile_hash,
                media_sha256=self.media_hash,
                flags=CVPTS_MEDIA_ORIGINAL_SOURCE | CVPTS_APPLY_UGCVLUT1_Q8,
            )

    def test_pts_cache_rejects_time_base_outside_native_signed_profile(self):
        with self.assertRaisesRegex(ChronoVideoError, "time-base numerator"):
            self._build(time_base_num=1 << 63)
        with self.assertRaisesRegex(ChronoVideoError, "time-base denominator"):
            self._build(time_base_den=1 << 63)


@unittest.skipUnless(
    shutil.which("ffmpeg")
    and shutil.which("ffprobe")
    and importlib.util.find_spec("av")
    and importlib.util.find_spec("cv2"),
    "ffmpeg, ffprobe, PyAV, and OpenCV are required",
)
class ChronoVideoCompileContractTests(unittest.TestCase):
    def test_compile_embeds_byte_identical_source_and_verifies_phone_timelines(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            output = root / "bundle"
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
                    str(source),
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
                target_kind="human",
                embed_source_for_phone=True,
            )
            result = compile_chrono_video(source, output, profile, backend="cpu")
            report = verify_chrono_bundle(output)

            self.assertTrue(report["passed"])
            self.assertTrue(report["embedded_source_verified"])
            self.assertEqual(
                (output / "source_media.mp4").read_bytes(), source.read_bytes()
            )
            self.assertEqual(
                report["source_pts_cache"]["entry_count"], result.decoded_frames
            )
            self.assertEqual(
                report["preview_pts_cache"]["raster_mode"], "ALREADY_LOG_POLAR"
            )
            self.assertEqual(
                report["source_pts_cache"]["raster_mode"], "APPLY_UGCVLUT1_Q8"
            )
            self.assertEqual(
                report["preview_pts_cache"]["playback_mode"], "ONCE_HOLD_LAST"
            )
            preview_probe = probe_video(output / "polar_preview.mp4")
            self.assertIn(
                preview_probe["stream"]["profile"],
                {"Baseline", "Constrained Baseline"},
            )
            self.assertEqual(int(preview_probe["stream"]["has_b_frames"]), 0)
            self.assertEqual(preview_probe["stream"]["color_range"], "tv")
            self.assertEqual(preview_probe["stream"]["color_space"], "bt709")
            self.assertEqual(preview_probe["stream"]["color_transfer"], "bt709")
            self.assertEqual(preview_probe["stream"]["color_primaries"], "bt709")
            manifest = json.loads((output / "manifest.json").read_text("utf-8"))
            profile_receipt = json.loads(
                (output / "profile.json").read_text(encoding="utf-8")
            )
            inspected_profile = inspect_chrono_profile_receipt(profile_receipt)
            canonical_profile_bytes = json.dumps(
                profile_receipt["canonical_profile"],
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
            self.assertEqual(manifest["profile_asset"], "profile.json")
            self.assertEqual(
                manifest["profile_sha256"],
                hashlib.sha256(canonical_profile_bytes).hexdigest(),
            )
            self.assertEqual(
                report["profile_sha256"], inspected_profile["profile_sha256"]
            )
            self.assertIn(
                "profile.json", {item["path"] for item in manifest["assets"]}
            )
            implementation = profile_receipt["implementation"]
            self.assertEqual(
                implementation["selected"]["compute_backend"], "numpy-cpu-q8"
            )
            self.assertEqual(
                implementation["selected"]["decode_backend"],
                "pyav-cpu-exact-pts",
            )
            self.assertIsNone(implementation["dependencies"]["torch"])
            self.assertIsNone(
                implementation["dependencies"]["torch_cuda_runtime"]
            )
            for field in ("numpy", "pyav", "opencv"):
                self.assertTrue(implementation["dependencies"][field])
            self.assertTrue(implementation["ugts_kc3"]["version"])
            module_spec = importlib.util.find_spec("ugts_kc3.chrono_video")
            self.assertIsNotNone(module_spec)
            self.assertIsNotNone(module_spec.origin)
            self.assertEqual(
                implementation["ugts_kc3"]["chrono_video_module_sha256"],
                hashlib.sha256(Path(module_spec.origin).read_bytes()).hexdigest(),
            )
            self.assertRegex(
                implementation["ugts_kc3"]["chrono_video_module_sha256"],
                r"^[0-9a-f]{64}$",
            )
            self.assertTrue(
                implementation["executables"]["ffmpeg"].startswith(
                    "ffmpeg version "
                )
            )
            self.assertTrue(
                implementation["executables"]["ffprobe"].startswith(
                    "ffprobe version "
                )
            )
            self.assertEqual(
                manifest["phone_profile"]["source_media_mode"],
                "EMBEDDED_BYTE_IDENTICAL",
            )
            self.assertEqual(
                manifest["phone_profile"]["playback_mode"], "ONCE_HOLD_LAST"
            )
            self.assertEqual(
                manifest["phone_profile"]["physical_device_verification"],
                "EXTERNAL_PHYSICAL_RECEIPT_REQUIRED",
            )
            joint = json.loads(
                (output / "joint_hypotheses.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )["human_specialization"]
            self.assertEqual(joint["persistent_object"], "UNESTABLISHED")
            self.assertEqual(joint["cross_time_identity"], "UNKNOWN")
            self.assertEqual(
                joint["human_specialization_status"],
                "DECLARED_TARGET_ONLY_NO_ACCEPTED_HCO",
            )

            # Even if an attacker updates the full-file asset receipt, the
            # verifier recomputes the semantic digest from the canonical
            # profile preimage and rejects a copied/stale digest.
            tampered_profile = json.loads(json.dumps(profile_receipt))
            tampered_profile["canonical_profile"]["sample_stride"] = 2
            new_profile_sha = hashlib.sha256(
                json.dumps(
                    tampered_profile["canonical_profile"],
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
            ).hexdigest()
            tampered_profile["profile_sha256"] = new_profile_sha
            profile_path = output / "profile.json"
            profile_path.write_text(
                json.dumps(tampered_profile, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            for asset in manifest["assets"]:
                if asset["path"] == "profile.json":
                    asset["bytes"] = profile_path.stat().st_size
                    asset["sha256"] = hashlib.sha256(
                        profile_path.read_bytes()
                    ).hexdigest()
            (output / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                ChronoVideoError, "manifest/profile receipt SHA-256 mismatch"
            ):
                verify_chrono_bundle(output)


if __name__ == "__main__":
    unittest.main()
