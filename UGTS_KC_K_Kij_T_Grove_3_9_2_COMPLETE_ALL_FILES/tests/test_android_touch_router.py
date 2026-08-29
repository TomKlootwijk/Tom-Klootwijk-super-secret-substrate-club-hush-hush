from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import build_android_project
from ugts_kc3.templates3d import first_steps_mobile3d_project


HOST_TESTS = ROOT / "native" / "host_tests"
TEMPLATE_CPP = (
    ROOT
    / "src"
    / "ugts_kc3"
    / "android_template"
    / "project"
    / "app"
    / "src"
    / "main"
    / "cpp"
)
CHECKED_ANDROID = ROOT / "android" / "UGTSKCKKijTGrove"
CHECKED_CPP = CHECKED_ANDROID / "app" / "src" / "main" / "cpp"


def _host_cpp_toolchain_available() -> bool:
    if os.name != "nt":
        return any(shutil.which(name) for name in ("c++", "g++", "clang++"))
    if shutil.which("cl") or shutil.which("clang++") or shutil.which("g++"):
        return True
    vswhere = Path(
        os.environ.get(
            "ProgramFiles(x86)", r"C:\Program Files (x86)"
        )
    ) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    if not vswhere.exists():
        return False
    found = subprocess.run(
        [
            str(vswhere), "-latest", "-products", "*", "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property",
            "installationPath",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return found.returncode == 0 and bool(found.stdout.strip())


class AndroidTouchRouterTests(unittest.TestCase):
    def test_checked_in_signature_project_uses_the_same_router(self) -> None:
        for filename in ("touch_router.hpp", "touch_router.cpp"):
            self.assertEqual(
                (CHECKED_CPP / filename).read_bytes(),
                (TEMPLATE_CPP / filename).read_bytes(),
                f"checked-in {filename} drifted from the packaged router",
            )
        cmake = (CHECKED_CPP / "CMakeLists.txt").read_text("utf-8")
        self.assertIn("touch_router.cpp", cmake)
        self.assertNotIn("graph_vm.cpp", cmake)
        self.assertNotIn("polar_kinematics.cpp", cmake)
        engine = (CHECKED_CPP / "engine.cpp").read_text("utf-8")
        self.assertIn("AMOTION_EVENT_ACTION_POINTER_DOWN", engine)
        self.assertIn("AMOTION_EVENT_ACTION_POINTER_UP", engine)
        self.assertIn("AMotionEvent_getPointerId", engine)
        self.assertIn("if (density<72 || density>1000)", engine)
        self.assertIn("{ jump_=true; dash_=true; }", engine)
        controls = (CHECKED_ANDROID / "README.md").read_text("utf-8")
        self.assertIn("Pointer-ID tracking", controls)

    def test_router_is_packaged_into_generated_android_project(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            generated = build_android_project(
                first_steps_mobile3d_project(), Path(temporary) / "android"
            )
            cpp = generated.output_dir / "app" / "src" / "main" / "cpp"
            self.assertTrue((cpp / "touch_router.hpp").is_file())
            self.assertTrue((cpp / "touch_router.cpp").is_file())
            self.assertIn(
                "touch_router.cpp", (cpp / "CMakeLists.txt").read_text("utf-8")
            )
            engine = (cpp / "engine.cpp").read_text("utf-8")
            self.assertIn("AMOTION_EVENT_ACTION_POINTER_DOWN", engine)
            self.assertIn("AMOTION_EVENT_ACTION_POINTER_UP", engine)
            self.assertIn("AMotionEvent_getPointerId", engine)
            self.assertIn("if (density<72 || density>1000)", engine)
            self.assertIn("{ jump_=true; dash_=true; }", engine)

    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for the host touch test")
    def test_pointer_id_gestures_execute_in_host_cpp(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary) / "build"
            configured = subprocess.run(
                ["cmake", "-S", str(HOST_TESTS), "-B", str(build)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            compiled = subprocess.run(
                ["cmake", "--build", str(build), "--config", "Release"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            candidates = tuple(build.rglob("touch_router_tests.exe")) or tuple(
                path for path in build.rglob("touch_router_tests") if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the touch-router test executable")
            executed = subprocess.run(
                [str(candidates[0])],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("PASS touch router pointer-ID gestures", executed.stdout)


if __name__ == "__main__":
    unittest.main()
