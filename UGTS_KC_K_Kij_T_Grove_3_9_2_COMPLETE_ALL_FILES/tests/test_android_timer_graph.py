from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402


HOST_TESTS = ROOT / "native" / "host_tests"


def _host_cpp_toolchain_available() -> bool:
    if os.name != "nt":
        return any(shutil.which(name) for name in ("c++", "g++", "clang++"))
    if shutil.which("cl") or shutil.which("clang++") or shutil.which("g++"):
        return True
    vswhere = Path(
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    ) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
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


def _timer_project():
    project = blank_mobile3d_project()
    world_repeat = VisualGraph(
        "world_repeat",
        (
            GraphNode("a_timer", "event.timer", {"seconds": 0.5}),
            GraphNode("z_tick", "event.tick"),
            GraphNode(
                "write_count",
                "action.set_component",
                {
                    "entity": "floor",
                    "component": "transform",
                    "field": "translation.x",
                },
            ),
            GraphNode(
                "write_remaining",
                "action.set_component",
                {
                    "entity": "floor",
                    "component": "transform",
                    "field": "translation.y",
                },
            ),
            GraphNode(
                "announce",
                "action.emit_event",
                {"kind": "world_repeat"},
            ),
        ),
        (
            GraphLink("a_timer", "out", "write_count", "in"),
            GraphLink("a_timer", "count", "write_count", "value"),
            GraphLink("a_timer", "out", "announce", "in"),
            GraphLink("z_tick", "out", "write_remaining", "in"),
            GraphLink("a_timer", "remaining", "write_remaining", "value"),
        ),
    )
    world_once = VisualGraph(
        "world_once",
        (
            GraphNode(
                "timer",
                "event.timer",
                {"seconds": 0.5, "repeat": False},
            ),
            GraphNode(
                "announce",
                "action.emit_event",
                {"kind": "world_once"},
            ),
        ),
        (GraphLink("timer", "out", "announce", "in"),),
    )
    bound_repeat = VisualGraph(
        "bound_repeat",
        (
            GraphNode("timer", "event.timer", {"seconds": 0.5}),
            GraphNode(
                "write_count",
                "action.set_component",
                {
                    "entity": "goal",
                    "component": "transform",
                    "field": "translation.x",
                },
            ),
            GraphNode(
                "announce",
                "action.emit_event",
                {"kind": "bound_repeat"},
            ),
        ),
        (
            GraphLink("timer", "out", "write_count", "in"),
            GraphLink("timer", "count", "write_count", "value"),
            GraphLink("timer", "out", "announce", "in"),
        ),
    )
    project.metadata["visual_graphs"] = [
        world_repeat.to_dict(),
        world_once.to_dict(),
        bound_repeat.to_dict(),
    ]
    project.metadata["world_graphs"] = [world_repeat.id, world_once.id]
    project.nodes = tuple(
        replace(node, metadata={"visual_graph": bound_repeat.id})
        if node.id == "player"
        else node
        for node in project.nodes
    )
    return project


class AndroidTimerGraphTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for the host graph-VM test")
    def test_opcode_23_matches_active_step_contract_in_host_cpp(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        packed = compile_graph_pack_bytes(_timer_project())
        info = inspect_graph_pack(packed)
        self.assertEqual(info["binding_count"], 3)
        self.assertEqual(info["world_binding_count"], 2)

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            fixture = temporary_path / "timer.kcvg"
            fixture.write_bytes(packed)
            build = temporary_path / "build"
            configured = subprocess.run(
                ["cmake", "-S", str(HOST_TESTS), "-B", str(build)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                configured.returncode,
                0,
                configured.stdout + configured.stderr,
            )
            compiled = subprocess.run(
                [
                    "cmake",
                    "--build",
                    str(build),
                    "--config",
                    "Release",
                    "--target",
                    "timer_graph_vm_tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                compiled.returncode,
                0,
                compiled.stdout + compiled.stderr,
            )
            candidates = tuple(build.rglob("timer_graph_vm_tests.exe")) or tuple(
                path
                for path in build.rglob("timer_graph_vm_tests")
                if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the timer host test")
            executed = subprocess.run(
                [str(candidates[0]), str(fixture)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                executed.returncode,
                0,
                executed.stdout + executed.stderr,
            )
            self.assertIn("PASS timer graph VM parity", executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
