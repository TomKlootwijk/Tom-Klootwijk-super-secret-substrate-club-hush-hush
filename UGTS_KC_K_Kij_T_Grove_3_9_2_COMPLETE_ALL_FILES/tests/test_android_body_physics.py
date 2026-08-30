from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
HOST_TESTS = ROOT / "native" / "host_tests"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import build_android_project  # noqa: E402
from ugts_kc3.mobile3d import Mobile3DProject  # noqa: E402


EXAMPLE = ROOT / "examples" / "dynamic_crate_parity_3d" / "project.json"
GAMEPLAY_EXAMPLE = ROOT / "examples" / "tom_signature_arena_3d" / "project.json"


def _host_cpp_toolchain_available() -> bool:
    if os.name != "nt":
        return any(shutil.which(name) for name in ("c++", "g++", "clang++"))
    if shutil.which("cl") or shutil.which("clang++") or shutil.which("g++"):
        return True
    vswhere = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not vswhere.exists():
        return False
    found = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return found.returncode == 0 and bool(found.stdout.strip())


class AndroidBodyPhysicsTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("cmake"), "CMake is required for the native body test"
    )
    def test_generic_dynamic_body_parity_executes_in_host_cpp(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            generated = build_android_project(
                Mobile3DProject.load(EXAMPLE), temporary_path / "android"
            )
            generated_cpp = (
                generated.output_dir / "app" / "src" / "main" / "cpp"
            )
            self.assertTrue((generated_cpp / "body_physics.hpp").is_file())
            self.assertTrue((generated_cpp / "body_physics.cpp").is_file())
            self.assertIn(
                "body_physics.cpp",
                (generated_cpp / "CMakeLists.txt").read_text("utf-8"),
            )
            self.assertIn(
                "integrateDynamicBodies",
                (generated_cpp / "engine.cpp").read_text("utf-8"),
            )
            assets = generated.output_dir / "app" / "src" / "main" / "assets"
            scene_pack = assets / "signature_scene.kc3d"
            graph_pack = assets / "visual_graphs.kcvg"
            self.assertTrue(scene_pack.is_file())
            self.assertTrue(graph_pack.is_file())
            gameplay_generated = build_android_project(
                Mobile3DProject.load(GAMEPLAY_EXAMPLE),
                temporary_path / "gameplay-android",
            )
            gameplay_scene_pack = (
                gameplay_generated.output_dir
                / "app"
                / "src"
                / "main"
                / "assets"
                / "signature_scene.kc3d"
            )
            self.assertTrue(gameplay_scene_pack.is_file())
            build = temporary_path / "build"
            configured = subprocess.run(
                ["cmake", "-S", str(HOST_TESTS), "-B", str(build)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                configured.returncode, 0, configured.stdout + configured.stderr
            )
            compiled = subprocess.run(
                [
                    "cmake",
                    "--build",
                    str(build),
                    "--config",
                    "Release",
                    "--target",
                    "body_physics_tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            candidates = tuple(build.rglob("body_physics_tests.exe")) or tuple(
                path for path in build.rglob("body_physics_tests") if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the body-physics test")
            executed = subprocess.run(
                [
                    str(candidates[0]),
                    str(scene_pack),
                    str(graph_pack),
                    str(gameplay_scene_pack),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("PASS generic dynamic body physics", executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
