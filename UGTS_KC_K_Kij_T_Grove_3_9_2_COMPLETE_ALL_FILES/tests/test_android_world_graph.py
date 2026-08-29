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

from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


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
            str(vswhere), "-latest", "-products", "*", "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property",
            "installationPath",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return found.returncode == 0 and bool(found.stdout.strip())


def _world_graph() -> VisualGraph:
    nodes = (
        GraphNode("ready", "event.ready"),
        GraphNode("tick", "event.tick"),
        GraphNode(
            "set_x",
            "action.set_component",
            {"entity": "player", "component": "transform", "field": "translation.x", "value": 3.5},
        ),
        GraphNode(
            "set_y",
            "action.set_component",
            {"entity": "player", "component": "transform", "field": "translation.y", "value": 7.0},
        ),
        GraphNode("push", "action.apply_force", {"entity": "player", "force": [4.0, 6.0]}),
        GraphNode("announce", "action.emit_event", {"kind": "world_ready", "payload": {}}),
        GraphNode("trigger_enter", "event.trigger_enter"),
        GraphNode("trigger_exit", "event.trigger_exit"),
        GraphNode("announce_enter", "action.emit_event", {"kind": "player_entered", "payload": {}}),
        GraphNode("announce_exit", "action.emit_event", {"kind": "player_exited", "payload": {}}),
    )
    links = (
        GraphLink("ready", "out", "set_x", "in"),
        GraphLink("set_x", "out", "push", "in"),
        GraphLink("push", "out", "announce", "in"),
        GraphLink("ready", "entity", "announce", "source"),
        GraphLink("tick", "out", "set_y", "in"),
        GraphLink("trigger_enter", "out", "announce_enter", "in"),
        GraphLink("trigger_enter", "sensor", "announce_enter", "source"),
        GraphLink("trigger_enter", "player", "announce_enter", "target"),
        GraphLink("trigger_exit", "out", "announce_exit", "in"),
        GraphLink("trigger_exit", "sensor", "announce_exit", "source"),
        GraphLink("trigger_exit", "player", "announce_exit", "target"),
    )
    return VisualGraph("world_logic", nodes, links)


def _bound_graph() -> VisualGraph:
    return VisualGraph(
        "bound_logic",
        (
            GraphNode("tick", "event.tick"),
            GraphNode(
                "set_z",
                "action.set_component",
                {"component": "transform", "field": "translation.z", "value": 9.0},
            ),
        ),
        (GraphLink("tick", "out", "set_z", "in"),),
    )


def _sensor_graph() -> VisualGraph:
    return VisualGraph(
        "sensor_logic",
        (
            GraphNode("enter", "event.trigger_enter"),
            GraphNode("exit", "event.trigger_exit"),
            GraphNode("mark_sensor", "action.set_component", {"component": "transform", "field": "translation.x", "value": 11.0}),
            GraphNode("mark_player", "action.set_component", {"component": "transform", "field": "translation.y", "value": 12.0}),
            GraphNode("clear_sensor", "action.set_component", {"component": "transform", "field": "translation.x", "value": -11.0}),
        ),
        (
            GraphLink("enter", "out", "mark_sensor", "in"),
            GraphLink("enter", "out", "mark_player", "in"),
            GraphLink("enter", "player", "mark_player", "entity"),
            GraphLink("exit", "out", "clear_sensor", "in"),
        ),
    )


class AndroidWorldGraphTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for the host graph-VM test")
    def test_world_graph_executes_in_host_cpp_and_ignores_entity_lifecycle(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        project = blank_mobile3d_project()
        world, bound, sensor = _world_graph(), _bound_graph(), _sensor_graph()
        project.metadata["visual_graphs"] = [world.to_dict(), bound.to_dict(), sensor.to_dict()]
        project.metadata["world_graphs"] = world.id
        player = next(node for node in project.nodes if node.id == "player")
        player.metadata["visual_graph"] = bound.id
        goal = next(node for node in project.nodes if node.id == "goal")
        goal.metadata["visual_graph"] = sensor.id
        packed = compile_graph_pack_bytes(project)
        info = inspect_graph_pack(packed)
        self.assertEqual(info["binding_count"], 3)
        self.assertEqual(info["world_binding_count"], 1)

        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            pack_path = temporary_path / "world_graph.kcvg"
            pack_path.write_bytes(packed)
            build = temporary_path / "build"
            configured = subprocess.run(
                ["cmake", "-S", str(HOST_TESTS), "-B", str(build)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            compiled = subprocess.run(
                ["cmake", "--build", str(build), "--config", "Release", "--target", "graph_vm_tests"],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            candidates = tuple(build.rglob("graph_vm_tests.exe")) or tuple(
                path for path in build.rglob("graph_vm_tests") if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the graph-VM test executable")
            executed = subprocess.run(
                [str(candidates[0]), str(pack_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("PASS graph VM world binding", executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
