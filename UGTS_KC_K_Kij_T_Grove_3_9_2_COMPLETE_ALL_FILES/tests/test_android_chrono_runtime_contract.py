"""Cross-language conformance tests for the Android chrono-video runtime.

These tests deliberately keep the pure UGCVPTS1 reader free of Android mocks:
Python writes a canonical fixture, a host C++ compiler builds the exact native
reader used by the APK, and the executable validates/hash-checks/selects it.
The remaining tests inspect the Android-only integration at its source boundary.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

from ugts_kc3.chrono_video import (
    CVPTS_ALREADY_LOG_POLAR,
    CVPTS_APPLY_UGCVLUT1_Q8,
    CVPTS_LOOP,
    CVPTS_MEDIA_DERIVED_POLAR_PREVIEW,
    CVPTS_MEDIA_ORIGINAL_SOURCE,
    generate_video_pts_cache,
    inspect_video_pts_cache,
)
from ugts_kc3.chrono_desktop import decode_chrono_desktop_timeline


ROOT = Path(__file__).resolve().parents[1]
ANDROID = ROOT / "src/ugts_kc3/android_template/project/app"
CPP = ANDROID / "src/main/cpp"
SHADERS = ANDROID / "src/main/assets/shaders"
TIMELINE_CPP = CPP / "chrono_video_timeline.cpp"


_HARNESS = r"""
#include "chrono_video_timeline.hpp"

#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>

#if defined(UGTS_TEST_WINDOWS_CLANG_BUILTINS)
// Android's Clang driver links these signed-128 helpers from compiler-rt. The
// NDK's Windows-host clang-cl can compile the exact production translation
// unit but ships only Android-target runtime archives, so this host harness
// supplies the two helpers needed by selectForElapsedNanoseconds. The bitwise
// implementation contains no division and does not alter production code.
using HarnessU128 = unsigned __int128;
using HarnessI128 = __int128;

struct HarnessDivmod {
    HarnessU128 quotient;
    HarnessU128 remainder;
};

static HarnessDivmod harnessUnsignedDivmod(HarnessU128 numerator, HarnessU128 denominator) {
    HarnessDivmod result{0, 0};
    for (int bit = 127; bit >= 0; --bit) {
        result.remainder = (result.remainder << 1) | ((numerator >> bit) & 1);
        if (result.remainder >= denominator) {
            result.remainder -= denominator;
            result.quotient |= HarnessU128{1} << bit;
        }
    }
    return result;
}

static HarnessU128 harnessMagnitude(HarnessI128 value) {
    const auto bits = static_cast<HarnessU128>(value);
    return value < 0 ? (~bits + 1) : bits;
}

extern "C" HarnessI128 __divti3(HarnessI128 numerator, HarnessI128 denominator) {
    const auto magnitude = harnessUnsignedDivmod(
        harnessMagnitude(numerator), harnessMagnitude(denominator)).quotient;
    const auto signedMagnitude = static_cast<HarnessI128>(magnitude);
    return (numerator < 0) != (denominator < 0) ? -signedMagnitude : signedMagnitude;
}

extern "C" HarnessI128 __modti3(HarnessI128 numerator, HarnessI128 denominator) {
    const auto magnitude = harnessUnsignedDivmod(
        harnessMagnitude(numerator), harnessMagnitude(denominator)).remainder;
    const auto signedMagnitude = static_cast<HarnessI128>(magnitude);
    return numerator < 0 ? -signedMagnitude : signedMagnitude;
}
#endif

int main(int argc, char** argv) {
    try {
        if (argc < 2) throw std::runtime_error("usage: harness CACHE [ELAPSED_NS ...]");
        std::ifstream input(argv[1], std::ios::binary);
        if (!input) throw std::runtime_error("could not open cache");
        std::vector<std::uint8_t> bytes{
            std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
        kc::ChronoVideoTimeline timeline;
        timeline.load(bytes);
        std::cout << "role="
                  << (timeline.originalSource() ? "source" : "preview")
                  << " raster=" << (timeline.applyLut() ? "lut" : "polar")
                  << " playback=" << (timeline.loop() ? "loop" : "once")
                  << " entries=" << timeline.entries.size()
                  << " first=" << timeline.firstSourcePts
                  << " end=" << timeline.endSourcePtsExclusive << "\n";
        std::cout << "media_us=";
        for (std::size_t index = 0; index < timeline.entries.size(); ++index) {
            if (index) std::cout << ',';
            std::cout << timeline.exactMediaTimeUs(timeline.entries[index].sourcePts);
        }
        std::cout << "\nselect=";
        for (int index = 2; index < argc; ++index) {
            if (index != 2) std::cout << ',';
            const auto elapsed = static_cast<std::uint64_t>(std::stoull(argv[index]));
            std::cout << timeline.selectForElapsedNanoseconds(elapsed);
        }
        std::cout << "\nsha256_abc=";
        const std::vector<std::uint8_t> abc{'a', 'b', 'c'};
        for (const auto value : kc::chronoSha256(abc))
            std::cout << std::hex << std::setw(2) << std::setfill('0')
                      << static_cast<unsigned>(value);
        std::cout << "\n";
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << "\n";
        return 3;
    }
}
"""


def _fixture(*, loop: bool = False, time_base_num: int = 1, time_base_den: int = 1000) -> bytes:
    flags = CVPTS_MEDIA_ORIGINAL_SOURCE | CVPTS_APPLY_UGCVLUT1_Q8
    if loop:
        flags |= CVPTS_LOOP
    return generate_video_pts_cache(
        entries=[
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
        ],
        source_frame_count=3,
        media_width=64,
        media_height=48,
        time_base_num=time_base_num,
        time_base_den=time_base_den,
        source_sha256=hashlib.sha256(b"source").hexdigest(),
        profile_sha256=hashlib.sha256(b"profile").hexdigest(),
        media_sha256=hashlib.sha256(b"media").hexdigest(),
        flags=flags,
    )


def _windows_clang_cl() -> tuple[Path, Path] | None:
    """Return clang-cl and vcvars64; clang-cl supports the reader's __int128."""
    candidates: list[Path] = []
    command = shutil.which("clang-cl")
    if command:
        candidates.append(Path(command))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        ndk_root = Path(local_app_data) / "Android/Sdk/ndk"
        if ndk_root.is_dir():
            candidates.extend(
                sorted(
                    ndk_root.glob(
                        "*/toolchains/llvm/prebuilt/windows-x86_64/bin/clang-cl.exe"
                    ),
                    reverse=True,
                )
            )
    program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    vcvars_candidates = [
        Path(program_files_x86)
        / "Microsoft Visual Studio/2022/BuildTools/VC/Auxiliary/Build/vcvars64.bat",
        Path(program_files)
        / "Microsoft Visual Studio/2022/Community/VC/Auxiliary/Build/vcvars64.bat",
    ]
    vcvars_candidates.extend(
        Path(program_files_x86).glob(
            "Microsoft Visual Studio/*/*/VC/Auxiliary/Build/vcvars64.bat"
        )
    )
    vcvars_candidates.extend(
        Path(program_files).glob(
            "Microsoft Visual Studio/*/*/VC/Auxiliary/Build/vcvars64.bat"
        )
    )
    compiler = next((path for path in candidates if path.is_file()), None)
    vcvars = next((path for path in vcvars_candidates if path.is_file()), None)
    if compiler and vcvars:
        return compiler, vcvars
    return None


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


def _wsl_has_gxx() -> bool:
    if os.name != "nt" or shutil.which("wsl.exe") is None:
        return False
    result = subprocess.run(
        ["wsl.exe", "--exec", "sh", "-lc", "command -v g++ >/dev/null"],
        text=True,
        capture_output=True,
        timeout=30,
    )
    return result.returncode == 0


def _build_harness(directory: Path) -> tuple[Path, bool] | None:
    source = directory / "chrono_timeline_harness.cpp"
    source.write_text(_HARNESS, encoding="utf-8")
    if os.name == "nt":
        if _wsl_has_gxx():
            executable = directory / "chrono_timeline_harness"
            result = subprocess.run(
                [
                    "wsl.exe",
                    "--exec",
                    "g++",
                    "-std=c++20",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    f"-I{_as_wsl_path(CPP)}",
                    _as_wsl_path(source),
                    _as_wsl_path(TIMELINE_CPP),
                    "-o",
                    _as_wsl_path(executable),
                ],
                text=True,
                capture_output=True,
                timeout=120,
            )
            if result.returncode:
                raise AssertionError(
                    "WSL host compilation of the production UGCVPTS1 reader failed\n"
                    f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
                )
            return executable, True
        toolchain = _windows_clang_cl()
        if toolchain is None:
            return None
        compiler, vcvars = toolchain
        executable = directory / "chrono_timeline_harness.exe"
        # vcvars supplies Microsoft's standard-library headers and linker; the
        # NDK-bundled clang-cl supplies C++20 plus __int128 on this Windows host.
        compile_batch = directory / "build_chrono_harness.bat"
        harness_object = directory / "chrono_timeline_harness.obj"
        timeline_object = directory / "chrono_video_timeline.obj"
        builtins_candidates = sorted(
            (vcvars.parents[2] / "Tools/MSVC").glob(
                "*/lib/x64/clang_rt.builtins-x86_64.lib"
            ),
            reverse=True,
        )
        builtins_argument = (
            f' "{builtins_candidates[0]}"' if builtins_candidates else ""
        )
        compile_batch.write_text(
            "@echo off\n"
            f'call "{vcvars}" >nul\n'
            "if errorlevel 1 exit /b %errorlevel%\n"
            f'"{compiler}" /nologo /std:c++20 /EHsc '
            f'/DUGTS_TEST_WINDOWS_CLANG_BUILTINS /I"{CPP}" '
            f'/c "{source}" /Fo:"{harness_object}"\n'
            "if errorlevel 1 exit /b %errorlevel%\n"
            f'"{compiler}" /nologo /std:c++20 /EHsc /I"{CPP}" '
            f'/c "{TIMELINE_CPP}" /Fo:"{timeline_object}"\n'
            "if errorlevel 1 exit /b %errorlevel%\n"
            f'link /nologo "{harness_object}" "{timeline_object}"{builtins_argument} '
            f'/OUT:"{executable}"\n',
            encoding="ascii",
        )
        result = subprocess.run(
            ["cmd.exe", "/d", "/c", str(compile_batch)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=120,
        )
    else:
        compiler_name = shutil.which("clang++") or shutil.which("g++") or shutil.which("c++")
        if compiler_name is None:
            return None
        executable = directory / "chrono_timeline_harness"
        result = subprocess.run(
            [
                compiler_name,
                "-std=c++20",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{CPP}",
                str(source),
                str(TIMELINE_CPP),
                "-o",
                str(executable),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=120,
        )
    if result.returncode:
        raise AssertionError(
            "host compilation of the production UGCVPTS1 reader failed\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return executable, False


class NativeUgcvpts1ConformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary = tempfile.TemporaryDirectory()
        cls.directory = Path(cls._temporary.name)
        built = _build_harness(cls.directory)
        cls.executable = built[0] if built else None
        cls.run_with_wsl = built[1] if built else False

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary.cleanup()

    def _require_compiler(self) -> Path:
        if self.executable is None:
            self.skipTest("no C++20 host compiler with a usable standard library is available")
        return self.executable

    def _run(self, payload: bytes, *elapsed_nanoseconds: int) -> subprocess.CompletedProcess[str]:
        executable = self._require_compiler()
        cache = self.directory / (
            hashlib.sha256(payload + repr(elapsed_nanoseconds).encode("ascii")).hexdigest()
            + ".ugcvpts1"
        )
        cache.write_bytes(payload)
        command = [str(executable), str(cache), *(str(value) for value in elapsed_nanoseconds)]
        if self.run_with_wsl:
            command = [
                "wsl.exe",
                "--exec",
                _as_wsl_path(executable),
                _as_wsl_path(cache),
                *(str(value) for value in elapsed_nanoseconds),
            ]
        return subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
        )

    def test_python_writer_is_accepted_by_native_reader_and_sha256_matches_standard(self):
        payload = _fixture()
        self.assertEqual(inspect_video_pts_cache(payload)["playback_mode"], "ONCE_HOLD_LAST")
        result = self._run(payload, 0)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("role=source raster=lut playback=once entries=3 first=100 end=221", result.stdout)
        self.assertIn("media_us=100000,140000,180000", result.stdout)
        self.assertIn(
            "sha256_abc=" + hashlib.sha256(b"abc").hexdigest(),
            result.stdout,
        )

    def test_native_selection_uses_exact_half_open_boundaries_and_holds_last(self):
        # With time_base 1/1000, the three exact source-clock intervals after
        # first PTS are [0,40ms), [40ms,80ms), [80ms,121ms).
        elapsed = (
            0,
            39_999_999,
            40_000_000,
            79_999_999,
            80_000_000,
            120_999_999,
            121_000_000,
            10_000_000_000,
        )
        result = self._run(_fixture(), *elapsed)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("select=0,0,1,1,2,2,2,2", result.stdout)
        desktop = decode_chrono_desktop_timeline(_fixture())
        self.assertEqual(
            [desktop.select_for_elapsed_nanoseconds(value) for value in elapsed],
            [0, 0, 1, 1, 2, 2, 2, 2],
        )

    def test_native_selection_loops_only_when_the_explicit_flag_is_present(self):
        result = self._run(
            _fixture(loop=True),
            120_999_999,
            121_000_000,
            160_999_999,
            161_000_000,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("playback=loop", result.stdout)
        self.assertIn("select=2,0,0,1", result.stdout)

    def test_native_reader_rejects_payload_corruption_and_trailing_data(self):
        corrupted = bytearray(_fixture())
        corrupted[-1] ^= 0x01
        result = self._run(bytes(corrupted))
        self.assertEqual(result.returncode, 3)
        self.assertIn("content SHA-256 mismatch", result.stderr)

        result = self._run(_fixture() + b"not-canonical")
        self.assertEqual(result.returncode, 3)
        self.assertIn("length mismatch", result.stderr)

    def test_native_reader_rejects_canonically_rehashed_contradictory_roles(self):
        corrupted = bytearray(_fixture())
        flags_offset = 8 + 2 + 2 + 4 + 4
        contradictory = (
            CVPTS_MEDIA_ORIGINAL_SOURCE
            | CVPTS_MEDIA_DERIVED_POLAR_PREVIEW
            | CVPTS_APPLY_UGCVLUT1_Q8
        )
        struct.pack_into("<I", corrupted, flags_offset, contradictory)
        corrupted[172:204] = bytes(32)
        corrupted[172:204] = hashlib.sha256(corrupted).digest()
        result = self._run(bytes(corrupted))
        self.assertEqual(result.returncode, 3)
        self.assertIn("role flags are contradictory", result.stderr)

    def test_native_reader_rejects_rehashed_noncontiguous_half_open_intervals(self):
        corrupted = bytearray(_fixture())
        first_entry_display_until_offset = 208 + 4 + 4 + 8
        struct.pack_into("<q", corrupted, first_entry_display_until_offset, 141)
        corrupted[172:204] = bytes(32)
        corrupted[172:204] = hashlib.sha256(corrupted).digest()
        result = self._run(bytes(corrupted))
        self.assertEqual(result.returncode, 3)
        self.assertIn("half-open intervals are not contiguous", result.stderr)

    def test_native_exact_media_clock_rejects_nonrepresentable_pts(self):
        payload = _fixture(time_base_num=1, time_base_den=90_000)
        result = self._run(payload)
        self.assertEqual(result.returncode, 3)
        self.assertIn("not exactly representable", result.stderr)

    def test_exact_media_clock_uses_cancellation_and_checked_multiplication(self):
        timeline = TIMELINE_CPP.read_text(encoding="utf-8")
        self.assertIn("std::gcd(factor,denominator)", timeline)
        self.assertIn("cancel(source); cancel(base); cancel(micros);", timeline)
        self.assertIn("denominator==1u", timeline)
        self.assertIn("value<=limit/factor", timeline)


class AndroidChronoSourceContractTests(unittest.TestCase):
    def test_runtime_roles_are_explicit_and_preview_cannot_be_promoted(self):
        header = (CPP / "chrono_video_player.hpp").read_text(encoding="utf-8")
        player = (CPP / "chrono_video_player.cpp").read_text(encoding="utf-8")
        self.assertIn("AuthoritativeSourceLut", header)
        self.assertIn("DerivedPolarPreview", header)
        self.assertIn('return "AUTHORITATIVE_SOURCE_LUT"', player)
        self.assertIn('return "DERIVED_POLAR_PREVIEW"', player)
        self.assertRegex(
            player,
            r"timeline_\.originalSource\(\)\s*&&\s*timeline_\.applyLut\(\)[\s\S]*?"
            r"!timeline_\.derivedPreview\(\)\s*&&\s*!timeline_\.alreadyLogPolar\(\)",
        )
        self.assertRegex(
            player,
            r"timeline_\.derivedPreview\(\)\s*&&\s*timeline_\.alreadyLogPolar\(\)[\s\S]*?"
            r"!timeline_\.originalSource\(\)\s*&&\s*!timeline_\.applyLut\(\)",
        )
        self.assertIn("preview_promotion=false", player)

    def test_source_shader_implements_the_declared_q8_four_neighbor_math(self):
        source = (SHADERS / "chrono_video_source.frag").read_text(encoding="utf-8")
        lut_reader = (CPP / "chrono_video_lut.cpp").read_text(encoding="utf-8")
        self.assertIn("samplerExternalOES uVideo", source)
        self.assertIn("usampler2D uLut", source)
        self.assertRegex(source, r"uint\s+fx\s*=\s*address\.z\s*&\s*255u")
        self.assertRegex(source, r"uint\s+fy\s*=\s*\(address\.z\s*>>\s*8u\)\s*&\s*255u")
        for term in ("ix*iy", "fx*iy", "ix*fy", "fx*fy"):
            self.assertIn(term, source)
        self.assertRegex(source, r"sum\s*\+\s*uvec4\(32768u\)\)\s*>>\s*16u")
        self.assertIn("address.w==0u", source)
        self.assertIn('require(valid<=1u,"UGCVLUT1 valid lane is not boolean")', lut_reader)
        self.assertRegex(
            lut_reader,
            r"if\s*\(valid\)\s*require\([\s\S]*?x0\)\+1u<sourceWidth[\s\S]*?"
            r"y0\)\+1u<sourceHeight",
        )
        self.assertIn("valid bilinear footprint exceeds the source raster", lut_reader)

    def test_preview_has_a_separate_copy_shader_with_no_lut_interface(self):
        preview = (SHADERS / "chrono_video_preview.frag").read_text(encoding="utf-8")
        player = (CPP / "chrono_video_player.cpp").read_text(encoding="utf-8")
        self.assertIn("samplerExternalOES uVideo", preview)
        self.assertNotIn("uLut", preview)
        self.assertNotIn("texelFetch", preview)
        self.assertIn('"shaders/chrono_video_source.frag":"shaders/chrono_video_preview.frag"', player)
        self.assertRegex(
            player,
            r"if\s*\(mode_==ChronoVideoRuntimeMode::AuthoritativeSourceLut\)\s*\{\s*"
            r"glActiveTexture\(GL_TEXTURE1\)[\s\S]*?"
            r"glBindTexture\(GL_TEXTURE_2D,lutTexture_\)",
        )
        preview_flags = CVPTS_MEDIA_DERIVED_POLAR_PREVIEW | CVPTS_ALREADY_LOG_POLAR
        report = inspect_video_pts_cache(
            generate_video_pts_cache(
                entries=[
                    {
                        "media_index": 0,
                        "source_frame_index": 0,
                        "source_pts": 0,
                        "display_until_source_pts": 1,
                    }
                ],
                source_frame_count=1,
                media_width=16,
                media_height=8,
                time_base_num=1,
                time_base_den=1000,
                source_sha256=hashlib.sha256(b"source").hexdigest(),
                profile_sha256=hashlib.sha256(b"profile").hexdigest(),
                media_sha256=hashlib.sha256(b"preview").hexdigest(),
                flags=preview_flags,
            )
        )
        self.assertEqual(report["media_role"], "DERIVED_POLAR_PREVIEW")
        self.assertEqual(report["raster_mode"], "ALREADY_LOG_POLAR")

    def test_android_build_keeps_mp4_fd_addressable_and_links_native_media(self):
        gradle = (ANDROID / "build.gradle").read_text(encoding="utf-8")
        cmake = (CPP / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertRegex(gradle, r"noCompress\s*(?:\+=|=).*['\"]mp4['\"]")
        self.assertIn("chrono_video_timeline.cpp", cmake)
        self.assertIn("chrono_video_player.cpp", cmake)
        self.assertRegex(cmake, r"target_link_libraries\s*\([^)]*\bmediandk\b")

    def test_android16_rejection_retries_only_bounded_ftyp_transport(self):
        gradle = (ANDROID / "build.gradle").read_text(encoding="utf-8")
        player = (CPP / "chrono_video_player.cpp").read_text(encoding="utf-8")
        transport = (CPP / "chrono_mp4_transport.cpp").read_text(encoding="utf-8")
        cmake = (CPP / "CMakeLists.txt").read_text(encoding="utf-8")

        # Preserve the direct, uncompressed APK range as the normal transport,
        # and retain its AAsset owner until MediaExtractor has duplicated the fd.
        first_set = player.index("const auto apkStatus=AMediaExtractor_setDataSourceFd")
        asset_close = player.index("mediaAsset.reset()", first_set)
        retry_branch = player.index("if (apkStatus==AMEDIA_OK)", asset_close)
        self.assertLess(first_set, asset_close)
        self.assertLess(asset_close, retry_branch)

        # A rejected source gets a fresh extractor and an offset-zero seekable
        # fd derived only after the original mediaBytes_ passed its SHA binding.
        self.assertRegex(
            player,
            r"if \(apkStatus==AMEDIA_OK\)[\s\S]*?else \{[\s\S]*?"
            r"AMediaExtractor_delete\(extractor_\);[\s\S]*?"
            r"deriveIso4IsomTransport\(mediaBytes_\);[\s\S]*?"
            r"createPrivateMediaDescriptor\(activity_,derived\.bytes\);[\s\S]*?"
            r"extractor_=AMediaExtractor_new\(\);[\s\S]*?"
            r"AMediaExtractor_setDataSourceFd\(\s*"
            r"extractor_,mediaFileDescriptor_,0,privateLength\)",
        )
        for receipt in (
            "actual_changed_byte_count=%zu",
            "encoded_payload_unchanged=true",
            "pts_atoms_unchanged=true",
            "authoritative_source_sha_verified=true",
            "source_sha256=%s",
            "transport_sha256=%s",
            "transport_bytes_source_identical=false",
            "preview_promotion=false",
        ):
            self.assertIn(receipt, player)
        self.assertEqual(player.count("source_bytes_sha_bound=true"), 1)
        self.assertIn("sourceSha==timeline_.mediaSha256", player)
        self.assertIn("sourceSha==timeline_.sourceSha256", player)

        # The pure derivation accepts only the evidenced 20-byte layout with
        # major iso4 and sole compatible iso4, and verifies its full-vector diff.
        self.assertIn("constexpr std::size_t FtypBytes=20u", transport)
        self.assertIn("constexpr std::size_t CompatibleBrandOffset=16u", transport)
        self.assertIn("constexpr std::array<std::uint8_t,4> Iso4{'i','s','o','4'}", transport)
        self.assertIn("constexpr std::array<std::uint8_t,4> Isom{'i','s','o','m'}", transport)
        self.assertIn("result.changedByteCount!=1u", transport)
        self.assertIn("result.changedByteOffset!=CompatibleBrandOffset+3u", transport)
        self.assertIn("sourceBytes.begin()+FtypBytes", transport)
        self.assertIn("chrono_mp4_transport.cpp", cmake)

        # The private copy is constrained to internalDataPath, mode 0600,
        # unlinked before writing, exact-length checked, and handles short/EINTR
        # writes. These calls are available at the unchanged API-26 floor.
        self.assertIn("activity->internalDataPath", player)
        self.assertIn('path.append(".ugts-chrono-media-XXXXXX")', player)
        self.assertIn("S_IRUSR|S_IWUSR", player)
        self.assertIn("unlink(path.c_str())", player)
        descriptor_created = player.index("OwnedFileDescriptor descriptor(mkstemp")
        descriptor_unlinked = player.index("unlinkResult=unlink", descriptor_created)
        descriptor_written = player.index(
            "while (written<transportBytes.size())", descriptor_unlinked
        )
        self.assertLess(descriptor_created, descriptor_unlinked)
        self.assertLess(descriptor_unlinked, descriptor_written)
        self.assertRegex(
            player,
            r"while \(written<transportBytes\.size\(\)\)[\s\S]*?"
            r"if \(result<0 && errno==EINTR\) continue;[\s\S]*?"
            r"written\+=static_cast<std::size_t>\(result\)",
        )
        self.assertIn("descriptorStat.st_size==", player)
        self.assertRegex(gradle, r"\bminSdk\s+26\b")
        self.assertNotIn("AMediaExtractor_setDataSourceCustom", player)

    def test_extractor_and_codec_initialization_stay_in_a_visible_jni_scope(self):
        player = (CPP / "chrono_video_player.cpp").read_text(encoding="utf-8")
        open_decoder = re.search(
            r"bool ChronoVideoPlayer::openDecoder\(\) \{([\s\S]*?)\n\}\n\n"
            r"bool ChronoVideoPlayer::initialize",
            player,
        )
        self.assertIsNotNone(open_decoder)
        body = open_decoder.group(1)
        scope = body.index("JniEnvironment mediaJni(activity_);")
        visibility_check = body.index("activity_->vm->GetEnv", scope)
        receipt = body.index("entry_point_contract=NDK_WITH_JVM", visibility_check)
        first_extractor = body.index("AMediaExtractor_new()", receipt)
        retry_extractor = body.index("AMediaExtractor_new()", first_extractor + 1)
        codec = body.index("AMediaCodec_createDecoderByType", retry_extractor)
        self.assertLess(scope, visibility_check)
        self.assertLess(visibility_check, receipt)
        self.assertLess(receipt, first_extractor)
        self.assertLess(first_extractor, retry_extractor)
        self.assertLess(retry_extractor, codec)
        self.assertIn("jni_env_visible=true", body)
        self.assertIn("attachedCurrentThread()", body)

    def test_once_mode_is_finite_and_holds_the_last_observed_raster(self):
        timeline = TIMELINE_CPP.read_text(encoding="utf-8")
        player = (CPP / "chrono_video_player.cpp").read_text(encoding="utf-8")
        self.assertRegex(
            timeline,
            r"if\s*\(loop\(\)\)\s*offset\s*%=\s*duration\s*;\s*"
            r"else if\s*\(offset>=duration\)\s*return entries\.size\(\)-1u",
        )
        self.assertIn('timeline_.loop()?"LOOP_EXPLICIT":"ONCE_HOLD_LAST"', player)
        self.assertIn("loop reset requested for ONCE_HOLD_LAST", player)

    def test_media_decoder_is_pts_bound_and_surface_frames_are_gl_thread_consumed(self):
        player = (CPP / "chrono_video_player.cpp").read_text(encoding="utf-8")
        activity = (
            ANDROID / "src/main/java/org/ugts/runtime/UgtsNativeActivity.java"
        ).read_text(encoding="utf-8")
        self.assertIn("AMediaExtractor_setDataSourceFd", player)
        self.assertIn("AMediaCodec_configure", player)
        self.assertIn("AMediaCodec_releaseOutputBuffer", player)
        self.assertIn("sample PTS disagrees with exact UGCVPTS1 ordinal PTS", player)
        self.assertIn("info.presentationTimeUs==expected", player)
        self.assertIn("SurfaceTexture.OnFrameAvailableListener", activity)
        self.assertIn("updateTexImage()", activity)
        self.assertIn("getTransformMatrix", activity)
        self.assertNotIn("updateTexImage()", re.sub(r"consumeVideoFrame[\s\S]*", "", activity))

    def test_owned_dual_staging_primes_zero_and_prefetches_one_ordinal(self):
        header = (CPP / "chrono_video_player.hpp").read_text(encoding="utf-8")
        player = (CPP / "chrono_video_player.cpp").read_text(encoding="utf-8")
        self.assertRegex(header, r"std::array<GLuint,2>\s+stagingTextures_")
        self.assertRegex(header, r"std::array<std::size_t,2>\s+stagingOrdinals_")
        self.assertIn("GL_RGBA8", player)
        self.assertIn("prefetch=exactly_one_verified_ordinal", player)
        self.assertRegex(
            player,
            r"require\(publishForTarget\(0u\)[\s\S]*?"
            r"playbackStartNs_=steadyNowNanoseconds;[\s\S]*?"
            r"playbackClockStarted_=true",
        )
        self.assertRegex(
            player,
            r"if\s*\(targetOrdinal\+1u<timeline_\.entries\.size\(\)[\s\S]*?"
            r"return targetOrdinal\+1u",
        )

    def test_late_boundary_and_runtime_failure_are_explicit_and_fail_closed(self):
        player = (CPP / "chrono_video_player.cpp").read_text(encoding="utf-8")
        renderer = (CPP / "renderer_gles3.cpp").read_text(encoding="utf-8")
        self.assertIn("++lateBoundaryCount_", player)
        self.assertIn("physical_exact_timing=false", player)
        self.assertIn("chrono once completion receipt", player)
        self.assertIn("late_boundaries=%llu selector_boundaries_met=%s", player)
        self.assertIn("photon_time_claim=false color_byte_authoritative=false", player)
        self.assertRegex(
            player,
            r"void ChronoVideoPlayer::fail\(const char\* message\)[\s\S]*?"
            r"mode_=ChronoVideoRuntimeMode::Failed;[\s\S]*?closeDecoder\(\);",
        )
        self.assertIn("preview_promotion=false", renderer)
        self.assertIn("ordinary_editable_scene_continues=true", renderer)


if __name__ == "__main__":
    unittest.main()
