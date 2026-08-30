from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import struct
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
from ugts_kc3.hierarchypack import (  # noqa: E402
    HIERARCHY_PACK_ASSET,
    HIERARCHY_PACK_MAGIC,
    HierarchyPackError,
    compile_hierarchy_pack_bytes,
    inspect_hierarchy_pack,
)
from ugts_kc3.mobile3d import Transform3DRecord  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402


def _hierarchy_project():
    project = blank_mobile3d_project()
    base = project.nodes[0]
    root = replace(
        base,
        id="hierarchy_root",
        transform=Transform3DRecord(),
        parent_id=None,
    )
    level1 = replace(
        base,
        id="hierarchy_level_1",
        transform=Transform3DRecord(
            (1.0, 0.0, 0.0),
            (0.7071067811865476, 0.0, 0.7071067811865475, 0.0),
            (0.5, 0.5, 0.5),
        ),
        parent_id=root.id,
    )
    level2 = replace(
        base,
        id="hierarchy_level_2",
        transform=Transform3DRecord(
            (0.0, 1.0, 0.0),
            (0.7071067811865476, 0.7071067811865475, 0.0, 0.0),
            (2.0, 2.0, 2.0),
        ),
        parent_id=level1.id,
    )
    level3 = replace(
        base,
        id="hierarchy_level_3",
        transform=Transform3DRecord(
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0, 0.0),
            (1.0, 2.0, 3.0),
        ),
        parent_id=level2.id,
    )
    # Parent indices intentionally do not precede every child. KCHI records
    # remain child-index canonical while native composition must be depth-first.
    project.nodes = (level3, root, level2, level1)
    project.validate()
    return project


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


class AndroidTransformHierarchyTests(unittest.TestCase):
    def test_unused_hierarchy_has_no_asset_or_runtime_record(self) -> None:
        project = blank_mobile3d_project()
        self.assertEqual(compile_hierarchy_pack_bytes(project), b"")
        with tempfile.TemporaryDirectory() as temporary:
            built = build_android_project(project, Path(temporary) / "android")
            self.assertIsNone(built.hierarchy_pack)
            self.assertFalse(
                (built.output_dir / "app/src/main/assets" / HIERARCHY_PACK_ASSET).exists()
            )
            report = json.loads(built.build_report.read_text("utf-8"))
            self.assertIsNone(report["transform_hierarchy_runtime"])

    def test_sparse_pack_is_fixed_canonical_and_strict(self) -> None:
        project = _hierarchy_project()
        packed = compile_hierarchy_pack_bytes(project)
        self.assertEqual(packed[:8], HIERARCHY_PACK_MAGIC)
        self.assertEqual(len(packed), 24 + 3 * 8)
        info = inspect_hierarchy_pack(packed, node_count=len(project.nodes))
        self.assertEqual(info["link_count"], 3)
        self.assertEqual(info["max_depth"], 3)
        self.assertEqual(
            [(link["child_index"], link["parent_index"]) for link in info["links"]],
            [(0, 2), (2, 3), (3, 1)],
        )
        self.assertEqual(info["topological_child_indices"], [3, 2, 0])

        with self.assertRaisesRegex(HierarchyPackError, "trailing bytes"):
            inspect_hierarchy_pack(packed + b"x", node_count=len(project.nodes))
        corrupt = bytearray(packed)
        struct.pack_into("<I", corrupt, 28, 99)
        with self.assertRaisesRegex(HierarchyPackError, "missing scene node"):
            inspect_hierarchy_pack(bytes(corrupt), node_count=len(project.nodes))
        corrupt = bytearray(packed)
        struct.pack_into("<I", corrupt, 36, 0)
        with self.assertRaisesRegex(HierarchyPackError, "cycle"):
            inspect_hierarchy_pack(bytes(corrupt), node_count=len(project.nodes))

        deep = b"".join(
            (
                HIERARCHY_PACK_MAGIC,
                struct.pack("<IIII", 0x01020304, 1, 9, 0),
                *(struct.pack("<II", child, child - 1) for child in range(1, 10)),
            )
        )
        with self.assertRaisesRegex(HierarchyPackError, "depth exceeds 8"):
            inspect_hierarchy_pack(deep, node_count=10)

    @unittest.skipUnless(
        shutil.which("cmake"), "CMake is required for the native hierarchy test"
    )
    def test_generated_kc3d_kchi_executes_in_host_cpp(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            project = _hierarchy_project()
            built = build_android_project(project, temporary_path / "android")
            self.assertIsNotNone(built.hierarchy_pack)
            assets = built.output_dir / "app/src/main/assets"
            scene_pack = assets / "signature_scene.kc3d"
            hierarchy_pack = assets / HIERARCHY_PACK_ASSET
            self.assertEqual(hierarchy_pack.read_bytes(), compile_hierarchy_pack_bytes(project))
            report = json.loads(built.build_report.read_text("utf-8"))
            self.assertEqual(report["transform_hierarchy_runtime"]["max_depth"], 3)

            generated_cpp = built.output_dir / "app/src/main/cpp"
            self.assertTrue((generated_cpp / "transform_hierarchy.hpp").is_file())
            self.assertTrue((generated_cpp / "transform_hierarchy.cpp").is_file())
            self.assertIn(
                "transform_hierarchy.cpp",
                (generated_cpp / "CMakeLists.txt").read_text("utf-8"),
            )
            engine = (generated_cpp / "engine.cpp").read_text("utf-8")
            self.assertIn('readAsset("hierarchies.kchi")', engine)
            self.assertGreaterEqual(engine.count("transformHierarchy_.compose(nodes_)"), 4)

            native_build = temporary_path / "native-build"
            configured = subprocess.run(
                [
                    "cmake",
                    "-S",
                    str(HOST_TESTS),
                    "-B",
                    str(native_build),
                    f"-DUGTS_ANDROID_CPP_DIR={generated_cpp}",
                ],
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
                    str(native_build),
                    "--config",
                    "Release",
                    "--target",
                    "transform_hierarchy_tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            candidates = tuple(native_build.rglob("transform_hierarchy_tests.exe")) or tuple(
                path
                for path in native_build.rglob("transform_hierarchy_tests")
                if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the hierarchy test")
            executed = subprocess.run(
                [str(candidates[0]), str(scene_pack), str(hierarchy_pack)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("PASS generated KC3D+KCHI transform hierarchy", executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
