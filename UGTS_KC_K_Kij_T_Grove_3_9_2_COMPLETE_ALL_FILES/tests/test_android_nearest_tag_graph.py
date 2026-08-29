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

    def scene_node(entity_id, position=(0.0, 0.0, 0.0), tags=(), metadata=None):
        return replace(
            prototype,
            id=entity_id,
            transform=Transform3DRecord(position),
            velocity=(0.0, 0.0, 0.0),
            angular_velocity=(0.0, 0.0, 0.0),
            collider=Collider3DRecord("none"),
            dynamic=False,
            tags=tuple(tags),
            metadata=dict(metadata or {}),
        )

    project.nodes = (
        scene_node("origin", tags=("player", "goal")),
        scene_node("zeta", (1.1, 2.2, 3.3), ("goal",)),
        scene_node("alpha", (-1.1, -2.2, -3.3), ("goal",)),
        scene_node("closer_inactive", (0.1, 0.0, 0.0), ("goal",)),
        scene_node("closer_dead", (0.2, 0.0, 0.0), ("goal",)),
        scene_node("boundary", (4.2, 0.0, 0.0), ("collectible",)),
        scene_node("distance_sink"),
        scene_node("found_marker"),
        scene_node("missing_found_marker"),
        scene_node("missing_entity_null_marker"),
        scene_node("missing_distance_null_marker"),
        scene_node("boundary_marker"),
    )
    return project


def _world_graph() -> VisualGraph:
    action_ids = (
        "write_distance",
        "announce",
        "mark_found",
        "mark_missing_found",
        "mark_missing_entity_null",
        "mark_missing_distance_null",
        "mark_boundary",
    )
    return VisualGraph(
        "nearest_world",
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "nearest",
                "query.nearest_tag",
                {"origin": "origin", "tag": "goal", "radius": 10.0},
            ),
            GraphNode(
                "missing",
                "query.nearest_tag",
                {"origin": "origin", "tag": "hazard", "radius": 10.0},
            ),
            GraphNode(
                "boundary_query",
                "query.nearest_tag",
                {"origin": "origin", "tag": "collectible", "radius": 4.2},
            ),
            GraphNode("null", "value.constant", {"value": None}),
            GraphNode("missing_entity_null", "compare"),
            GraphNode("missing_distance_null", "compare"),
            GraphNode(
                "write_distance",
                "action.set_component",
                {
                    "entity": "distance_sink",
                    "component": "transform",
                    "field": "translation.y",
                },
            ),
            GraphNode(
                "announce",
                "action.emit_event",
                {"kind": "nearest_found", "source": "origin"},
            ),
            GraphNode(
                "mark_found",
                "action.set_active",
                {"entity": "found_marker"},
            ),
            GraphNode(
                "mark_missing_found",
                "action.set_active",
                {"entity": "missing_found_marker"},
            ),
            GraphNode(
                "mark_missing_entity_null",
                "action.set_active",
                {"entity": "missing_entity_null_marker"},
            ),
            GraphNode(
                "mark_missing_distance_null",
                "action.set_active",
                {"entity": "missing_distance_null_marker"},
            ),
            GraphNode(
                "mark_boundary",
                "action.set_active",
                {"entity": "boundary_marker"},
            ),
        ),
        (
            *(GraphLink("ready", "out", target, "in") for target in action_ids),
            GraphLink("nearest", "distance", "write_distance", "value"),
            GraphLink("nearest", "entity", "announce", "target"),
            GraphLink("nearest", "found", "mark_found", "active"),
            GraphLink("missing", "found", "mark_missing_found", "active"),
            GraphLink("missing", "entity", "missing_entity_null", "a"),
            GraphLink("null", "value", "missing_entity_null", "b"),
            GraphLink(
                "missing",
                "distance",
                "missing_distance_null",
                "a",
            ),
            GraphLink("null", "value", "missing_distance_null", "b"),
            GraphLink(
                "missing_entity_null",
                "result",
                "mark_missing_entity_null",
                "active",
            ),
            GraphLink(
                "missing_distance_null",
                "result",
                "mark_missing_distance_null",
                "active",
            ),
            GraphLink("boundary_query", "found", "mark_boundary", "active"),
        ),
    )


def _bound_graph() -> VisualGraph:
    return VisualGraph(
        "nearest_bound",
        (
            GraphNode("ready", "event.ready"),
            GraphNode("nearest", "query.nearest_tag", {"tag": "goal", "radius": 10.0}),
            GraphNode("announce", "action.emit_event", {"kind": "bound_nearest"}),
        ),
        (
            GraphLink("ready", "out", "announce", "in"),
            GraphLink("nearest", "entity", "announce", "target"),
        ),
    )


def _invalid_graph(port: str, value) -> VisualGraph:
    return VisualGraph(
        f"invalid_{port}",
        (
            GraphNode("ready", "event.ready"),
            GraphNode("bad", "value.constant", {"value": value}),
            GraphNode(
                "nearest",
                "query.nearest_tag",
                {"origin": "origin"},
            ),
            GraphNode(
                "mark",
                "action.set_active",
                {"entity": "found_marker"},
            ),
        ),
        (
            GraphLink("ready", "out", "mark", "in"),
            GraphLink("bad", "value", "nearest", port),
            GraphLink("nearest", "found", "mark", "active"),
        ),
    )


def _missing_origin_graph() -> VisualGraph:
    return VisualGraph(
        "missing_origin",
        (
            GraphNode("ready", "event.ready"),
            GraphNode("nearest", "query.nearest_tag"),
            GraphNode(
                "mark",
                "action.set_active",
                {"entity": "found_marker"},
            ),
        ),
        (
            GraphLink("ready", "out", "mark", "in"),
            GraphLink("nearest", "found", "mark", "active"),
        ),
    )


def _single_world_pack(graph: VisualGraph) -> bytes:
    project = _scene_project()
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.metadata["world_graphs"] = graph.id
    return compile_graph_pack_bytes(project)


class AndroidNearestTagGraphTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for the host graph-VM test")
    def test_opcode_22_matches_python_contract_in_host_cpp(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        project = _scene_project()
        world_graph = _world_graph()
        bound_graph = _bound_graph()
        project.metadata["visual_graphs"] = [
            world_graph.to_dict(),
            bound_graph.to_dict(),
        ]
        project.metadata["world_graphs"] = world_graph.id
        project.nodes = (
            replace(
                project.nodes[0],
                metadata={"visual_graph": bound_graph.id},
            ),
            *project.nodes[1:],
        )
        valid = compile_graph_pack_bytes(project)
        info = inspect_graph_pack(valid)
        self.assertEqual(info["binding_count"], 2)
        self.assertEqual(info["world_binding_count"], 1)

        fixtures = (
            ("nearest.kcvg", valid),
            ("invalid_tag.kcvg", _single_world_pack(_invalid_graph("tag", "custom"))),
            ("invalid_radius.kcvg", _single_world_pack(_invalid_graph("radius", -1.0))),
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
                    "nearest_tag_graph_vm_tests",
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
            candidates = tuple(build.rglob("nearest_tag_graph_vm_tests.exe")) or tuple(
                path
                for path in build.rglob("nearest_tag_graph_vm_tests")
                if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the nearest-tag host test")
            executed = subprocess.run(
                [str(candidates[0]), *(str(path) for path in paths)],
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
            self.assertIn("PASS nearest-tag graph VM parity", executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
