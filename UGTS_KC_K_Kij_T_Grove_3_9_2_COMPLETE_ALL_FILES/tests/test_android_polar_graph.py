from __future__ import annotations

from dataclasses import replace
import math
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

from ugts_kc3.graphpack import compile_graph_pack_bytes  # noqa: E402
from ugts_kc3.packed_kinematics import (  # noqa: E402
    POLAR_MOVEMENT_FIELDS,
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polarpack import compile_polar_pack_bytes  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402


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
            str(vswhere), "-latest", "-products", "*", "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property", "installationPath",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return found.returncode == 0 and bool(found.stdout.strip())


def _project_with_polar_graph():
    project = blank_mobile3d_project("Native Polar Graph", "UGTS")
    # Force UGLUT2 radius scaling above one with a non-binary32-exact source
    # value, while retaining a range broad enough for the semantic writes.
    profile = LogPolarProfile(r0=10_000.0, rho_min=-10.0, rho_max=3.0)
    ranges = MotionRange(2.0, 8.0, 6.0, 16.0)
    codec = PackedKinematicCodec(profile, ranges)
    project.metadata["packed_kinematic_profiles"] = {
        "friendly": {
            "profile": profile.to_dict(),
            "motion_range": ranges.to_dict(),
            "lut_resolution": 1024,
        }
    }
    packed = codec.component(
        PolarPose(math.log(1.5), math.radians(25.0), 321, math.radians(70.0)),
        PolarMotion(0.25, math.tau * 0.2, 0.5, math.tau * -0.1),
        profile_id="friendly",
    )

    values = {
        "radius": 4.0,
        "angle_degrees": 450.0,
        "facing_degrees": -90.0,
        "turns_per_second": 0.5,
        "growth_per_second": -0.4,
        "turn_acceleration": 0.3,
        "growth_acceleration": -0.7,
    }
    graph_nodes = [GraphNode("ready", "event.ready")]
    graph_links = []
    previous = "ready"
    for index, field in enumerate(POLAR_MOVEMENT_FIELDS):
        node_id = f"write_{index}"
        graph_nodes.append(
            GraphNode(
                node_id,
                "action.set_polar_movement",
                {"field": field, "value": values[field]},
            )
        )
        graph_links.append(GraphLink(previous, "out", node_id, "in"))
        previous = node_id
    graph_nodes.extend(
        (
            GraphNode(
                "read_radius",
                "value.polar_movement",
                {"field": "radius", "default": -1.0},
            ),
            GraphNode(
                "copy_radius", "action.set_component",
                {"entity": "floor", "component": "transform", "field": "translation.y"},
            ),
        )
    )
    graph_links.extend(
        (
            GraphLink(previous, "out", "copy_radius", "in"),
            GraphLink("read_radius", "value", "copy_radius", "value"),
        )
    )
    graph = VisualGraph("native_polar_access", tuple(graph_nodes), tuple(graph_links))
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.nodes = tuple(
        replace(
            node,
            angular_velocity=(0.0, 0.0, 0.0),
            metadata={
                **node.metadata,
                "packed_kinematic": packed.to_dict(),
                "visual_graph": graph.id,
            },
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    return project


def _project_with_polar_transform_conflict(project):
    conflict = VisualGraph(
        "native_polar_transform_conflict",
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "write_owned_x",
                "action.set_component",
                # Compile a valid Y write, then mutate its equal-length field
                # token below. Project validation now rejects owned X/Z before
                # KCVG compilation, while the native VM still needs a malformed
                # cross-asset defense fixture.
                {"component": "transform", "field": "translation.y", "value": 99.0},
            ),
        ),
        (GraphLink("ready", "out", "write_owned_x", "in"),),
    )
    result = replace(
        project,
        metadata={**project.metadata, "visual_graphs": [conflict.to_dict()]},
    )
    result.nodes = tuple(
        replace(node, metadata={**node.metadata, "visual_graph": conflict.id})
        if node.id == "goal"
        else node
        for node in result.nodes
    )
    return result


class AndroidPolarGraphTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for the native polar test")
    def test_semantic_polar_component_executes_in_host_cpp(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        project = _project_with_polar_graph()
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            polar_pack = temporary_path / "packed_kinematics.kcpk"
            graph_pack = temporary_path / "visual_graphs.kcvg"
            conflict_pack = temporary_path / "polar_transform_conflict.kcvg"
            player_pack = temporary_path / "player_packed_kinematics.kcpk"
            polar_pack.write_bytes(compile_polar_pack_bytes(project))
            graph_pack.write_bytes(compile_graph_pack_bytes(project))
            conflict_bytes = compile_graph_pack_bytes(
                _project_with_polar_transform_conflict(project)
            )
            self.assertEqual(conflict_bytes.count(b"translation.y"), 1)
            conflict_pack.write_bytes(
                conflict_bytes.replace(b"translation.y", b"translation.0")
            )
            player_bytes = bytearray(polar_pack.read_bytes())
            # One canonical 24-byte component sits at the end of this fixture.
            # Rebind it to the static form of the Player node in the host test.
            struct.pack_into("<I", player_bytes, len(player_bytes) - 24, 1)
            player_pack.write_bytes(player_bytes)
            build = temporary_path / "build"
            configured = subprocess.run(
                ["cmake", "-S", str(HOST_TESTS), "-B", str(build)],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            compiled = subprocess.run(
                [
                    "cmake", "--build", str(build), "--config", "Release",
                    "--target", "polar_graph_vm_tests",
                ],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            candidates = tuple(build.rglob("polar_graph_vm_tests.exe")) or tuple(
                path for path in build.rglob("polar_graph_vm_tests") if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce the polar graph host test")
            executed = subprocess.run(
                [
                    str(candidates[0]), str(polar_pack), str(graph_pack),
                    str(conflict_pack), str(player_pack),
                ],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("PASS polar graph component bridge", executed.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
