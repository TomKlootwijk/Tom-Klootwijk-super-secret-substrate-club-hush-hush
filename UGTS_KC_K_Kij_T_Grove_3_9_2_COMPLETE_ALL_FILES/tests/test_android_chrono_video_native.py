from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ugts_kc3.androidexport import build_android_project
from ugts_kc3.chrono_video import ChronoVideoProfile, generate_video_polar_lut
from ugts_kc3.templates3d import blank_mobile3d_project


ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/ugts_kc3/android_template/project/app/src/main/cpp"
TRANSPORT_CPP = CPP / "chrono_mp4_transport.cpp"


_TRANSPORT_HARNESS = r"""
#include "chrono_mp4_transport.hpp"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <vector>

int main(int argc,char** argv) {
    if (argc!=3) return 2;
    try {
        std::ifstream input(argv[1],std::ios::binary);
        if (!input) throw std::runtime_error("input open failed");
        std::vector<std::uint8_t> source{
            std::istreambuf_iterator<char>(input),std::istreambuf_iterator<char>()};
        const auto immutableSource=source;
        const auto derived=kc::deriveIso4IsomTransport(source);
        if (source!=immutableSource) throw std::runtime_error("source mutated");
        std::vector<std::size_t> differences;
        for (std::size_t i=0;i<source.size();++i) {
            if (source[i]!=derived.bytes[i]) differences.push_back(i);
        }
        if (derived.bytes.size()!=source.size() || differences.size()!=1u ||
                differences[0]!=19u || derived.changedByteCount!=1u ||
                derived.changedByteOffset!=19u ||
                !std::equal(source.begin()+20,source.end(),derived.bytes.begin()+20))
            throw std::runtime_error("derivation boundary mismatch");
        std::ofstream output(argv[2],std::ios::binary|std::ios::trunc);
        output.write(reinterpret_cast<const char*>(derived.bytes.data()),
            static_cast<std::streamsize>(derived.bytes.size()));
        if (!output) throw std::runtime_error("output write failed");
        std::cout << "changed_offset=19 changed_count=1 source_unchanged=true "
            "payload_after_ftyp_unchanged=true\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 3;
    }
}
"""


def _as_wsl_path(path: Path) -> str:
    result = subprocess.run(
        ["wsl.exe", "--exec", "wslpath", "-a", str(path.resolve())],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode or not result.stdout.strip():
        raise AssertionError(f"wslpath failed for {path}: {result.stderr}")
    return result.stdout.strip()


def _build_transport_harness(directory: Path) -> tuple[Path, bool] | None:
    source = directory / "chrono_mp4_transport_harness.cpp"
    source.write_text(_TRANSPORT_HARNESS, encoding="utf-8")
    if os.name == "nt" and shutil.which("wsl.exe"):
        available = subprocess.run(
            ["wsl.exe", "--exec", "sh", "-lc", "command -v g++ >/dev/null"],
            timeout=30,
        )
        if available.returncode == 0:
            executable = directory / "chrono_mp4_transport_harness"
            command = [
                "wsl.exe",
                "--exec",
                "g++",
                "-std=c++20",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{_as_wsl_path(CPP)}",
                _as_wsl_path(source),
                _as_wsl_path(TRANSPORT_CPP),
                "-o",
                _as_wsl_path(executable),
            ]
            result = subprocess.run(command, text=True, capture_output=True, timeout=120)
            if result.returncode:
                raise AssertionError(
                    "host compilation of MP4 transport helper failed\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            return executable, True
    compiler = shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
    if compiler is None:
        return None
    executable = directory / (
        "chrono_mp4_transport_harness.exe" if os.name == "nt" else "chrono_mp4_transport_harness"
    )
    result = subprocess.run(
        [
            compiler,
            "-std=c++20",
            "-Wall",
            "-Wextra",
            "-Werror",
            f"-I{CPP}",
            str(source),
            str(TRANSPORT_CPP),
            "-o",
            str(executable),
        ],
        text=True,
        capture_output=True,
        timeout=120,
    )
    if result.returncode:
        raise AssertionError(
            "host compilation of MP4 transport helper failed\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return executable, False


def _iso4_transport_fixture() -> bytes:
    ftyp = (
        (20).to_bytes(4, "big")
        + b"ftyp"
        + b"iso4"
        + b"\x00\x00\x02\x00"
        + b"iso4"
    )
    encoded_payload_atom = (16).to_bytes(4, "big") + b"mdat" + b"PAYLOAD!"
    return ftyp + encoded_payload_atom


class AndroidChronoVideoNativeTests(unittest.TestCase):
    def test_compiled_transport_helper_changes_only_iso4_compatible_brand_byte(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            built = _build_transport_harness(directory)
            if built is None:
                self.skipTest("no C++20 host compiler is available")
            executable, run_with_wsl = built

            def run(payload: bytes, label: str) -> tuple[subprocess.CompletedProcess[str], Path]:
                source = directory / f"{label}.mp4"
                output = directory / f"{label}-derived.mp4"
                source.write_bytes(payload)
                command = [str(executable), str(source), str(output)]
                if run_with_wsl:
                    command = [
                        "wsl.exe",
                        "--exec",
                        _as_wsl_path(executable),
                        _as_wsl_path(source),
                        _as_wsl_path(output),
                    ]
                return (
                    subprocess.run(
                        command,
                        text=True,
                        capture_output=True,
                        timeout=30,
                    ),
                    output,
                )

            source = _iso4_transport_fixture()
            source_digest = hashlib.sha256(source).hexdigest()
            result, derived_path = run(source, "exact-iso4")
            self.assertEqual(result.returncode, 0, result.stderr)
            derived = derived_path.read_bytes()
            immutable_source_path = directory / "exact-iso4.mp4"
            self.assertEqual(immutable_source_path.stat().st_size, len(source))
            self.assertEqual(
                hashlib.sha256(immutable_source_path.read_bytes()).hexdigest(),
                source_digest,
            )
            self.assertEqual(len(derived), len(source))
            self.assertNotEqual(hashlib.sha256(derived).hexdigest(), source_digest)
            self.assertEqual(
                [index for index, pair in enumerate(zip(source, derived)) if pair[0] != pair[1]],
                [19],
            )
            self.assertEqual(source[16:20], b"iso4")
            self.assertEqual(derived[16:20], b"isom")
            self.assertEqual(derived[:19], source[:19])
            self.assertEqual(derived[20:], source[20:])
            self.assertIn(
                "changed_offset=19 changed_count=1 source_unchanged=true "
                "payload_after_ftyp_unchanged=true",
                result.stdout,
            )

            malformed = {}
            wrong_size = bytearray(source)
            wrong_size[3] = 24
            malformed["wrong-size"] = (bytes(wrong_size), "not exactly 20 bytes")
            wrong_type = bytearray(source)
            wrong_type[4:8] = b"free"
            malformed["wrong-type"] = (bytes(wrong_type), "leading atom is not ftyp")
            wrong_major = bytearray(source)
            wrong_major[8:12] = b"isom"
            malformed["wrong-major"] = (bytes(wrong_major), "major brand is not")
            already_supported = bytearray(source)
            already_supported[16:20] = b"isom"
            malformed["supported-compatible"] = (
                bytes(already_supported),
                "sole compatible brand is not",
            )
            for label, (payload, reason) in malformed.items():
                with self.subTest(label=label):
                    immutable_digest = hashlib.sha256(payload).hexdigest()
                    rejected, _ = run(payload, label)
                    self.assertEqual(rejected.returncode, 3)
                    self.assertIn(reason, rejected.stderr)
                    self.assertEqual(hashlib.sha256(payload).hexdigest(), immutable_digest)

    def test_native_reader_verifies_and_uploads_separate_integer_lut(self):
        parser = (CPP / "chrono_video_lut.cpp").read_text(encoding="utf-8")
        renderer = (CPP / "renderer_gles3.cpp").read_text(encoding="utf-8")
        engine = (CPP / "engine.cpp").read_text(encoding="utf-8")
        cmake = (CPP / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn('std::memcmp(magic,"UGCVLUT1",8)', parser)
        self.assertIn("payload SHA-256 mismatch", parser)
        self.assertIn("GL_RGBA16UI", renderer)
        self.assertIn("GL_RGBA_INTEGER", renderer)
        self.assertIn('readAsset("chrono/polar_lut.ugcv1")', engine)
        self.assertIn("chrono_video_lut.cpp", cmake)
        self.assertNotIn('std::memcmp(magic,"UGLUT2",6)', parser)

    def test_android_export_copies_only_hash_verified_declared_assets(self):
        profile = ChronoVideoProfile(
            theta_bins=32,
            rho_bins=16,
            sample_stride=1,
            tile_size=8,
            batch_size=1,
            max_vram_mib=128,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lut = root / "polar_lut.ugcv1"
            lut.write_bytes(generate_video_polar_lut(16, 12, profile))
            digest = hashlib.sha256(lut.read_bytes()).hexdigest()
            manifest = root / "manifest.json"
            manifest.write_text('{"schema":"chrono-test"}\n', encoding="utf-8")
            manifest_digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            project = blank_mobile3d_project("Chrono package test")
            metadata = dict(project.metadata)
            metadata["chrono_scene_observation"] = {
                "schema": "ugts-chrono-video-observation-manifest-0.1",
                "manifest": manifest.name,
                "manifest_sha256": manifest_digest,
                "runtime_assets": [
                    {"path": lut.name, "bytes": lut.stat().st_size, "sha256": digest},
                    {
                        "path": manifest.name,
                        "bytes": manifest.stat().st_size,
                        "sha256": manifest_digest,
                    },
                ],
            }
            project = replace(project, metadata=metadata)
            result = build_android_project(
                project,
                root / "android",
                clean=True,
                asset_source_root=root,
            )
            packaged = result.output_dir / "app/src/main/assets/chrono/polar_lut.ugcv1"
            self.assertEqual(packaged.read_bytes(), lut.read_bytes())
            report = json.loads(result.build_report.read_text(encoding="utf-8"))
            self.assertEqual(report["chrono_video_assets"][0]["sha256"], digest)
            binding = (
                result.output_dir
                / "app/src/main/cpp/chrono_runtime_binding.hpp"
            ).read_text(encoding="utf-8")
            self.assertIn('"chrono/polar_lut.ugcv1"', binding)
            self.assertIn(manifest_digest, binding)
            self.assertEqual(
                report["files_scope"], "exported source inputs before Gradle build"
            )
            volatile_parts = {".cxx", ".gradle", ".idea", "build"}
            self.assertFalse(
                any(
                    volatile_parts.intersection(Path(item["path"]).parts)
                    or Path(item["path"]).name == "local.properties"
                    for item in report["files"]
                )
            )
            self.assertFalse((result.output_dir / ".gradle").exists())
            self.assertFalse((result.output_dir / "app/.cxx").exists())
            self.assertFalse((result.output_dir / "app/build").exists())
            self.assertFalse((result.output_dir / "build").exists())


if __name__ == "__main__":
    unittest.main()
