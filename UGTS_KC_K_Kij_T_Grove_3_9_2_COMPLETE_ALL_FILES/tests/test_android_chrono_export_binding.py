from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from ugts_kc3.androidexport import build_android_project
from ugts_kc3.chrono_video import (
    CHRONO_MANIFEST_SCHEMA,
    CHRONO_PROFILE,
    CHRONO_PROFILE_RECEIPT_SCHEMA,
    ChronoVideoProfile,
)
from ugts_kc3.templates3d import blank_mobile3d_project


def _receipt(path: Path, *, byte_count: int | None = None) -> dict[str, object]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size if byte_count is None else byte_count,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _bound_project(root: Path, receipts: list[dict[str, object]]):
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps({"schema": "chrono-export-binding-test"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest_receipt = _receipt(manifest)
    project = blank_mobile3d_project("Chrono runtime binding test")
    metadata = dict(project.metadata)
    metadata["chrono_scene_observation"] = {
        "schema": "ugts-chrono-video-observation-manifest-0.1",
        "manifest": "manifest.json",
        "manifest_sha256": manifest_receipt["sha256"],
        "runtime_assets": [*receipts, manifest_receipt],
    }
    return replace(project, metadata=metadata)


def _profile_receipt(profile: ChronoVideoProfile) -> dict[str, object]:
    canonical = profile.to_dict()
    profile_sha256 = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "schema": CHRONO_PROFILE_RECEIPT_SCHEMA,
        "canonical_profile": canonical,
        "profile_sha256": profile_sha256,
        "implementation": {
            "schema": "ugts-chrono-video-implementation-receipt-0.1",
            "ugts_kc3": {
                "version": "test-fixture",
                "chrono_video_module_sha256": "a" * 64,
            },
            "python": {"implementation": "test", "version": "test"},
            "dependencies": {
                "numpy": "test",
                "pyav": "test",
                "opencv": "test",
                "torch": None,
                "torch_cuda_runtime": None,
            },
            "executables": {
                "ffmpeg": "ffmpeg version test",
                "ffprobe": "ffprobe version test",
            },
            "selected": {
                "compute_backend": "numpy-cpu-q8",
                "decode_backend": "pyav-cpu-exact-pts",
                "preview_encoder": "ffmpeg-libx264",
            },
        },
    }


def _real_bound_project(
    root: Path,
    receipt: dict[str, object],
    *,
    manifest_profile_sha256: str | None = None,
):
    profile_path = root / "profile.json"
    profile_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    profile_asset_receipt = _receipt(profile_path)
    manifest = root / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": CHRONO_MANIFEST_SCHEMA,
                "profile": CHRONO_PROFILE,
                "profile_asset": "profile.json",
                "profile_sha256": (
                    receipt["profile_sha256"]
                    if manifest_profile_sha256 is None
                    else manifest_profile_sha256
                ),
                "assets": [profile_asset_receipt],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest_receipt = _receipt(manifest)
    project = blank_mobile3d_project("Chrono profile binding test")
    metadata = dict(project.metadata)
    metadata["chrono_scene_observation"] = {
        "schema": CHRONO_MANIFEST_SCHEMA,
        "manifest": "manifest.json",
        "manifest_sha256": manifest_receipt["sha256"],
        "runtime_assets": [profile_asset_receipt, manifest_receipt],
    }
    return replace(project, metadata=metadata)


class AndroidChronoExportBindingTests(unittest.TestCase):
    def test_real_manifest_recomputes_and_exports_profile_semantic_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = ChronoVideoProfile(
                theta_bins=32,
                rho_bins=16,
                tile_size=8,
                batch_size=1,
                max_vram_mib=128,
            )
            receipt = _profile_receipt(profile)
            project = _real_bound_project(root, receipt)
            result = build_android_project(
                project, root / "android", asset_source_root=root
            )

            header = (
                result.output_dir / "app/src/main/cpp/chrono_runtime_binding.hpp"
            ).read_text(encoding="utf-8")
            self.assertIn(
                'kProfileAssetPath{"chrono/profile.json"}', header
            )
            self.assertIn(
                f'kProfileSha256Hex{{"{receipt["profile_sha256"]}"}}', header
            )
            report = json.loads(result.build_report.read_text(encoding="utf-8"))
            self.assertEqual(
                report["chrono_runtime_binding"]["profile_asset_path"],
                "chrono/profile.json",
            )
            self.assertEqual(
                report["chrono_runtime_binding"]["profile_sha256"],
                receipt["profile_sha256"],
            )

            stale_hash = str(receipt["profile_sha256"])
            tampered = json.loads(json.dumps(receipt))
            tampered["canonical_profile"]["sample_stride"] = 2
            tampered["profile_sha256"] = hashlib.sha256(
                json.dumps(
                    tampered["canonical_profile"],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            tampered_project = _real_bound_project(
                root, tampered, manifest_profile_sha256=stale_hash
            )
            with self.assertRaisesRegex(
                ValueError, "does not match recomputed profile"
            ):
                build_android_project(
                    tampered_project,
                    root / "tampered-android",
                    asset_source_root=root,
                )

    def test_generated_header_binds_every_declared_phone_runtime_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "source_media.mp4"
            media.write_bytes(b"byte-identical-source-media")
            timeline = root / "source_timeline.ugcvpts1"
            timeline.write_bytes(b"UGCVPTS1" + bytes(range(64)))
            project = _bound_project(root, [_receipt(media), _receipt(timeline)])

            result = build_android_project(
                project,
                root / "android",
                asset_source_root=root,
            )

            header = (
                result.output_dir
                / "app/src/main/cpp/chrono_runtime_binding.hpp"
            ).read_text(encoding="utf-8")
            self.assertIn("inline constexpr bool kPresent = true;", header)
            self.assertIn('"chrono/source_media.mp4"', header)
            self.assertIn('"chrono/source_timeline.ugcvpts1"', header)
            self.assertIn('"chrono/manifest.json"', header)
            self.assertIn("std::uint64_t{27}", header)
            media_hash = hashlib.sha256(media.read_bytes()).hexdigest()
            self.assertIn(
                ", ".join(
                    f"0x{media_hash[index:index + 2]}u"
                    for index in range(0, len(media_hash), 2)
                ),
                header,
            )

            report = json.loads(result.build_report.read_text(encoding="utf-8"))
            receipts = {item["path"]: item for item in report["chrono_video_assets"]}
            self.assertEqual(
                set(receipts),
                {
                    "chrono/source_media.mp4",
                    "chrono/source_timeline.ugcvpts1",
                    "chrono/manifest.json",
                },
            )
            self.assertEqual(receipts["chrono/source_media.mp4"]["bytes"], media.stat().st_size)
            self.assertEqual(
                report["chrono_runtime_binding"]["manifest_sha256"],
                hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest(),
            )

    def test_declared_byte_count_is_verified_before_export_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "source_media.mp4"
            media.write_bytes(b"source")
            project = _bound_project(
                root,
                [_receipt(media, byte_count=media.stat().st_size + 1)],
            )
            output = root / "android"

            with self.assertRaisesRegex(ValueError, "byte-count mismatch"):
                build_android_project(project, output, asset_source_root=root)
            self.assertFalse(output.exists())

    def test_duplicate_paths_are_rejected_case_insensitively(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "Media.mp4"
            media.write_bytes(b"source")
            first = _receipt(media)
            second = dict(first, path="media.mp4")
            project = _bound_project(root, [first, second])

            with self.assertRaisesRegex(ValueError, "duplicate or case-collision"):
                build_android_project(project, root / "android", asset_source_root=root)

    def test_manifest_metadata_must_match_declared_manifest_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = _bound_project(root, [])
            metadata = dict(project.metadata)
            chrono = dict(metadata["chrono_scene_observation"])
            chrono["manifest_sha256"] = "0" * 64
            metadata["chrono_scene_observation"] = chrono
            project = replace(project, metadata=metadata)

            with self.assertRaisesRegex(ValueError, "manifest metadata SHA-256"):
                build_android_project(project, root / "android", asset_source_root=root)

    def test_copied_target_is_rehashed_and_resized(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            media = root / "source_media.mp4"
            media.write_bytes(b"source")
            project = _bound_project(root, [_receipt(media)])
            real_copy2 = shutil.copy2

            def corrupt_runtime_copy(source, target, *args, **kwargs):
                result = real_copy2(source, target, *args, **kwargs)
                if Path(source).name == "source_media.mp4":
                    Path(target).write_bytes(b"corrupt")
                return result

            with mock.patch(
                "ugts_kc3.androidexport.shutil.copy2",
                side_effect=corrupt_runtime_copy,
            ):
                with self.assertRaisesRegex(ValueError, "failed byte/SHA verification"):
                    build_android_project(
                        project,
                        root / "android",
                        asset_source_root=root,
                    )


if __name__ == "__main__":
    unittest.main()
