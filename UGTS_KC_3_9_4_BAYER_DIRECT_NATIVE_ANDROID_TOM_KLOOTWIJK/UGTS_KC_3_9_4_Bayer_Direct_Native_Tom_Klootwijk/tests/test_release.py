from __future__ import annotations

import json
import re
import struct
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APK = ROOT / "dist" / "UGTS_KC_Bayer_Direct_3_9_4_arm64-v8a.apk"
SO = ROOT / "validation" / "freestanding_build" / "libugts_kc_bayer.so"
HOST = ROOT / "tools" / "host_preview"
CORE = ROOT / "app" / "src" / "main" / "cpp" / "bayer_core.c"


class BayerCoreTests(unittest.TestCase):
    def test_01_bayer_matrix_is_exact_permutation(self) -> None:
        text = CORE.read_text(encoding="utf-8")
        match = re.search(r"matrix\[64\]\s*=\s*\{([^}]+)\}", text, re.S)
        self.assertIsNotNone(match)
        values = [int(v) for v in re.findall(r"\d+", match.group(1))]
        self.assertEqual(len(values), 64)
        self.assertEqual(sorted(values), list(range(64)))

    def test_02_four_deterministic_mode_crcs(self) -> None:
        expected = ["270e3825", "163378fd", "3e678cdb", "67f2e213"]
        with tempfile.TemporaryDirectory() as td:
            for mode, crc in enumerate(expected):
                out = Path(td) / f"m{mode}.ppm"
                run = subprocess.run(
                    [str(HOST), "160", "72", "1", str(out), str(mode)],
                    check=True,
                    text=True,
                    capture_output=True,
                )
                self.assertIn(f"crc32={crc}", run.stdout)
                self.assertTrue(out.exists())

    def test_03_no_floating_point_in_hot_core(self) -> None:
        text = CORE.read_text(encoding="utf-8")
        self.assertNotRegex(text, r"\b(float|double|sinf|cosf|sqrtf|powf)\b")


class NativeBinaryTests(unittest.TestCase):
    def test_04_arm64_shared_object_is_tiny(self) -> None:
        self.assertTrue(SO.exists())
        self.assertLessEqual(SO.stat().st_size, 8192)
        output = subprocess.check_output(["file", str(SO)], text=True)
        self.assertIn("ARM aarch64", output)

    def test_05_only_android_and_libc_are_needed(self) -> None:
        output = subprocess.check_output(["readelf", "-d", str(SO)], text=True)
        needed = re.findall(r"Shared library: \[([^]]+)\]", output)
        self.assertEqual(needed, ["libandroid.so", "libc.so"])
        self.assertNotRegex(output.lower(), r"gles|egl|vulkan")

    def test_06_native_activity_entry_is_exported(self) -> None:
        output = subprocess.check_output(["readelf", "-Ws", str(SO)], text=True)
        exports = [line for line in output.splitlines() if "GLOBAL" in line and "DEFAULT" in line and "UND" not in line]
        self.assertTrue(any("ANativeActivity_onCreate" in line for line in exports))


class ApkTests(unittest.TestCase):
    def test_07_apk_size_budget(self) -> None:
        self.assertTrue(APK.exists())
        self.assertLessEqual(APK.stat().st_size, 16 * 1024)

    def test_08_apk_contains_no_assets_dex_or_shaders(self) -> None:
        with zipfile.ZipFile(APK) as zf:
            names = zf.namelist()
        self.assertIn("lib/arm64-v8a/libugts_kc_bayer.so", names)
        self.assertNotIn("classes.dex", names)
        self.assertFalse(any(n.startswith("assets/") for n in names))
        self.assertFalse(any(n.endswith((".frag", ".vert", ".spv", ".glsl")) for n in names))

    def test_09_manifest_identity_and_no_feature_elements(self) -> None:
        with zipfile.ZipFile(APK) as zf:
            manifest = zf.read("AndroidManifest.xml")
        self.assertIn("3.9.4-bayer-direct-v001".encode("utf-16le"), manifest)
        self.assertIn("nl.tomklootwijk.ugtskc.bayer.poco".encode("utf-16le"), manifest)
        self.assertIn("ugts_kc_bayer".encode("utf-16le"), manifest)
        offset = 8
        uses_feature_starts = 0
        while offset < len(manifest):
            chunk_type, header_size, chunk_size = struct.unpack_from("<HHI", manifest, offset)
            if chunk_type == 0x0102 and struct.unpack_from("<I", manifest, offset + 20)[0] == 45:
                uses_feature_starts += 1
            offset += chunk_size
        self.assertEqual(uses_feature_starts, 0)
        self.assertEqual(struct.unpack_from("<I", manifest, 2028)[0], 394)

    def test_10_v1_jar_signature_verifies(self) -> None:
        run = subprocess.run(["jarsigner", "-verify", str(APK)], text=True, capture_output=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("jar verified", run.stdout.lower())

    def test_11_v2_signature_verifies(self) -> None:
        run = subprocess.run(
            ["python", str(ROOT / "tools" / "apk_v2_verify.py"), str(APK)],
            check=True,
            text=True,
            capture_output=True,
        )
        self.assertIn("content_digest=", run.stdout)
        self.assertIn("subject=C=NL", run.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
