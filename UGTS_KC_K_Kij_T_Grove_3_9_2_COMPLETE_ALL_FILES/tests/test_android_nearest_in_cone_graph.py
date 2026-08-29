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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack  # noqa: E402
from ugts_kc3.mobile3d import Collider3DRecord, Transform3DRecord  # noqa: E402
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


def _scene_project():
    project = blank_mobile3d_project()
    prototype = next(node for node in project.nodes if node.id == "goal")

    def scene_node(entity_id, position=(0.0, 0.0, 0.0), tags=()):
        return replace(
            prototype,
            id=entity_id,
            transform=Transform3DRecord(position),
            velocity=(0.0, 0.0, 0.0),
            angular_velocity=(0.0, 0.0, 0.0),
            collider=Collider3DRecord("none"),
            dynamic=False,
            tags=tuple(tags),
            metadata={},
        )

    project.nodes = (
        scene_node("origin", tags=("player", "goal")),
        scene_node("zeta", (1.1, 2.2, 3.3), ("goal",)),
        scene_node("alpha", (1.1, -2.2, -3.3), ("goal",)),
        scene_node("inactive_closer", (0.1, 0.0, 0.0), ("goal",)),
        scene_node("dead_closer", (0.2, 0.0, 0.0), ("goal",)),
        scene_node("cone_boundary", (3.0, 4.0, 0.0), ("collectible",)),
        scene_node("closer_outside", (0.0, 1.0, 0.0), ("collectible",)),
        scene_node("coincident", (0.0, 0.0, 0.0), ("hazard",)),
        scene_node("distance_sink"),
        scene_node("tie_found_marker"),
        scene_node("boundary_marker"),
        scene_node("coincident_zero_marker"),
        scene_node("coincident_positive_marker"),
    )
    return project


def _world_graph() -> VisualGraph:
    action_ids = (
        "write_distance",
        "announce_tie",
        "mark_tie",
        "announce_boundary",
        "mark_boundary",
        "announce_coincident",
        "mark_coincident_zero",
        "mark_coincident_positive",
    )
    return VisualGraph(
        "cone_world",
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "tie",
                "query.nearest_in_cone",
                {"origin": "origin", "tag": "goal", "radius": 10.0, "cone": [1, 0, 0, 0]},
            ),
            GraphNode(
                "boundary",
                "query.nearest_in_cone",
                {"origin": "origin", "tag": "collectible", "radius": 5.0, "cone": [1, 0, 0, 0.6]},
            ),
            GraphNode(
                "coincident_zero",
                "query.nearest_in_cone",
                {"origin": "origin", "tag": "hazard", "radius": 0.0, "cone": [2, 3, 4, 0]},
            ),
            GraphNode(
                "coincident_positive",
                "query.nearest_in_cone",
                {"origin": "origin", "tag": "hazard", "radius": 0.0, "cone": [2, 3, 4, 0.0001]},
            ),
            GraphNode(
                "write_distance",
                "action.set_component",
                {"entity": "distance_sink", "component": "transform", "field": "translation.y"},
            ),
            GraphNode("announce_tie", "action.emit_event", {"kind": "cone_tie", "source": "origin"}),
            GraphNode("mark_tie", "action.set_active", {"entity": "tie_found_marker"}),
            GraphNode("announce_boundary", "action.emit_event", {"kind": "cone_boundary", "source": "origin"}),
            GraphNode("mark_boundary", "action.set_active", {"entity": "boundary_marker"}),
            GraphNode("announce_coincident", "action.emit_event", {"kind": "cone_coincident", "source": "origin"}),
            GraphNode("mark_coincident_zero", "action.set_active", {"entity": "coincident_zero_marker"}),
            GraphNode("mark_coincident_positive", "action.set_active", {"entity": "coincident_positive_marker"}),
        ),
        (
            *(GraphLink("ready", "out", target, "in") for target in action_ids),
            GraphLink("tie", "distance", "write_distance", "value"),
            GraphLink("tie", "entity", "announce_tie", "target"),
            GraphLink("tie", "found", "mark_tie", "active"),
            GraphLink("boundary", "entity", "announce_boundary", "target"),
            GraphLink("boundary", "found", "mark_boundary", "active"),
            GraphLink("coincident_zero", "entity", "announce_coincident", "target"),
            GraphLink("coincident_zero", "found", "mark_coincident_zero", "active"),
            GraphLink("coincident_positive", "found", "mark_coincident_positive", "active"),
        ),
    )


def _invalid_cone_graph() -> VisualGraph:
    return VisualGraph(
        "invalid_cone",
        (
            GraphNode("ready", "event.ready"),
            GraphNode("bad", "value.constant", {"value": [0, 0, 0, 0]}),
            GraphNode(
                "query",
                "query.nearest_in_cone",
                {"origin": "origin", "tag": "goal", "radius": 10.0},
            ),
            GraphNode("mark", "action.set_active", {"entity": "tie_found_marker"}),
        ),
        (
            GraphLink("ready", "out", "mark", "in"),
            GraphLink("bad", "value", "query", "cone"),
            GraphLink("query", "found", "mark", "active"),
        ),
    )


def _missing_origin_graph() -> VisualGraph:
    return VisualGraph(
        "missing_origin",
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "query",
                "query.nearest_in_cone",
                {"tag": "goal", "radius": 10.0, "cone": [1, 0, 0, 0]},
            ),
            GraphNode("mark", "action.set_active", {"entity": "tie_found_marker"}),
        ),
        (
            GraphLink("ready", "out", "mark", "in"),
            GraphLink("query", "found", "mark", "active"),
        ),
    )


def _single_world_pack(graph: VisualGraph) -> bytes:
    project = _scene_project()
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.metadata["world_graphs"] = graph.id
    return compile_graph_pack_bytes(project)


class AndroidNearestInConeGraphTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for the host graph-VM test")
    def test_opcode_24_matches_python_web_and_native_contract(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        valid = _single_world_pack(_world_graph())
        info = inspect_graph_pack(valid)
        self.assertEqual(info["binding_count"], 1)
        self.assertEqual(info["world_binding_count"], 1)

        fixtures = (
            ("cone.kcvg", valid),
            ("invalid_cone.kcvg", _single_world_pack(_invalid_cone_graph())),
            ("missing_origin.kcvg", _single_world_pack(_missing_origin_graph())),
        )
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            paths = []
            for name, data in fixtures:
                path = temporary_path / name
                path.write_bytes(data)
                paths.append(path)
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
                [
                    "cmake",
                    "--build",
                    str(build),
                    "--config",
                    "Release",
                    "--target",
                    "nearest_in_cone_graph_vm_tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            candidates = tuple(build.rglob("nearest_in_cone_graph_vm_tests.exe")) or tuple(
                path
                for path in build.rglob("nearest_in_cone_graph_vm_tests")
                if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the cone-query host test")
            executed = subprocess.run(
                [str(candidates[0]), *(str(path) for path in paths)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("PASS nearest-in-cone graph VM parity", executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
