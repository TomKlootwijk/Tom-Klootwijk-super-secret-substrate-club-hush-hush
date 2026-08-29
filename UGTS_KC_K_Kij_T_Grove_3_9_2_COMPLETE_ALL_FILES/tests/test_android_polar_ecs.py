from __future__ import annotations

import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import build_android_project
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.math3d import quat_from_axis_angle
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PackedKinematicComponent,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polarpack import (
    POLAR_PACK_ASSET,
    POLAR_PACK_MAGIC,
    PolarPackError,
    compile_polar_pack_bytes,
    inspect_polar_pack,
    collect_polar_project_spec,
    quantized_profile_lut,
)
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


def _attach_orbit(project):
    profile = LogPolarProfile(r0=2.0, rho_min=-3.0, rho_max=4.0, core_radius=1e-5)
    motion_range = MotionRange(3.0, 5.0, 7.0, 11.0)
    codec = PackedKinematicCodec(profile, motion_range)
    project.metadata["packed_kinematic_profiles"] = {
        "orbit": {
            "profile": profile.to_dict(),
            "motion_range": motion_range.to_dict(),
            "lut_resolution": 64,
        }
    }
    project.nodes[0].metadata["packed_kinematic"] = codec.component(
        PolarPose(0.35, 1.1, 17, 0.7),
        PolarMotion(0.2, -0.4, 0.05, 0.1),
        profile_id="orbit",
    ).to_dict()
    return codec


class AndroidPolarEcsTests(unittest.TestCase):
    def test_native_graph_tick_counter_starts_at_zero_after_ready(self):
        cpp = ROOT / "src/ugts_kc3/android_template/project/app/src/main/cpp"
        engine = (cpp / "engine.cpp").read_text("utf-8")
        tick_call = "graphVm_.tick(dt,fixedTick_"
        self.assertIn(tick_call, engine)
        self.assertNotIn("graphVm_.tick(dt,++fixedTick_", engine)
        self.assertLess(engine.index(tick_call), engine.index("++fixedTick_;", engine.index(tick_call)))
        graph_vm = (cpp / "graph_vm.cpp").read_text("utf-8")
        self.assertIn("dispatchBinding(binding,Dispatch::Ready,0.0f,0,input", graph_vm)

    def test_non_polar_project_has_no_asset_or_sparse_records(self):
        project = blank_mobile3d_project()
        self.assertEqual(compile_polar_pack_bytes(project), b"")
        report = project.validate()
        self.assertEqual(report.metrics["packed_kinematic_component_count"], 0)
        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNone(built.polar_pack)
            self.assertFalse(
                (built.output_dir / "app/src/main/assets" / POLAR_PACK_ASSET).exists()
            )
            build_report = json.loads(built.build_report.read_text("utf-8"))
            self.assertIsNone(build_report["packed_kinematic_runtime"])

    def test_named_profile_is_deterministic_shared_and_sparse(self):
        project = blank_mobile3d_project()
        _attach_orbit(project)
        validation = project.validate()
        self.assertEqual(validation.metrics["packed_kinematic_profile_count"], 1)
        self.assertEqual(validation.metrics["packed_kinematic_component_count"], 1)

        packed = compile_polar_pack_bytes(project)
        self.assertEqual(packed[:8], POLAR_PACK_MAGIC)
        clone = Mobile3DProject.from_dict(project.to_dict())
        self.assertEqual(compile_polar_pack_bytes(clone), packed)
        info = inspect_polar_pack(packed, node_count=len(project.nodes))
        self.assertEqual(info["profile_count"], 1)
        self.assertEqual(info["component_count"], 1)
        self.assertEqual(info["profiles"][0]["id"], "orbit")
        self.assertEqual(info["profiles"][0]["lut_resolution"], 64)
        self.assertEqual(info["components"][0]["node_index"], 0)
        self.assertEqual(info["components"][0]["profile"], "orbit")
        self.assertLess(info["byte_length"], 1024)

        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNotNone(built.polar_pack)
            self.assertEqual(built.polar_pack.read_bytes(), packed)
            report = json.loads(built.build_report.read_text("utf-8"))
            self.assertEqual(report["packed_kinematic_runtime"]["component_count"], 1)

    def test_desktop_preview_matches_quantized_codec_and_preserves_y(self):
        project = blank_mobile3d_project()
        codec = _attach_orbit(project)
        authored_y = project.nodes[0].transform.translation[1]
        original = PackedKinematicComponent.from_dict(
            project.nodes[0].metadata["packed_kinematic"]
        )
        profile_spec = collect_polar_project_spec(project).profiles[0]
        lut = quantized_profile_lut(profile_spec)
        initial = codec.cartesian_state(original, lut)
        ready_graph = VisualGraph(
            "observe_polar_ready",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "position",
                    "value.component",
                    {"component": "transform", "field": "position"},
                ),
                GraphNode("remember", "action.set_state", {"key": "ready_position"}),
            ),
            (
                GraphLink("ready", "out", "remember", "in"),
                GraphLink("position", "value", "remember", "value"),
            ),
        )
        project.metadata["visual_graphs"] = [ready_graph.to_dict()]
        project.nodes[0].metadata["visual_graph"] = ready_graph.id

        world = project.instantiate_world()
        entity = world.require(project.nodes[0].id)
        self.assertEqual(world.get(entity.id, "packed_kinematic").pose_word, original.pose_word)
        self.assertAlmostEqual(entity.position[0], initial["position"][0], places=12)
        self.assertEqual(entity.position[1], authored_y)
        self.assertAlmostEqual(entity.position[2], initial["position"][1], places=12)
        self.assertEqual(tuple(world.state["ready_position"]), entity.position)
        expected_rotation = quat_from_axis_angle((0, 1, 0), initial["pose"].heading)
        for actual, expected in zip(entity.rotation, expected_rotation):
            self.assertAlmostEqual(actual, expected, places=12)

        world.step()
        advanced = codec.advance(original, project.world.fixed_dt)
        expected = codec.cartesian_state(advanced, lut)
        actual_component = world.get(entity.id, "packed_kinematic")
        self.assertEqual(actual_component.pose_word, advanced.pose_word)
        self.assertEqual(actual_component.motion_word, advanced.motion_word)
        self.assertAlmostEqual(entity.position[0], expected["position"][0], places=12)
        self.assertEqual(entity.position[1], authored_y)
        self.assertAlmostEqual(entity.position[2], expected["position"][1], places=12)
        expected_rotation = quat_from_axis_angle((0, 1, 0), expected["pose"].heading)
        for actual, expected_value in zip(entity.rotation, expected_rotation):
            self.assertAlmostEqual(actual, expected_value, places=12)
        # Packed runtime state remains snapshot/hash-safe.
        self.assertIn("packed_kinematic", world.snapshot()["entities"][0]["extra_components"])
        self.assertEqual(len(world.state_hash()), 64)

    def test_dynamic_nodes_are_rejected_as_conflicting_transform_authority(self):
        project = blank_mobile3d_project()
        codec = PackedKinematicCodec()
        player = next(node for node in project.nodes if node.dynamic)
        player.metadata["packed_kinematic"] = codec.component(PolarPose(0, 0)).to_dict()
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertTrue(
            any(issue.code == "packed_kinematic.dynamic_conflict" for issue in report.issues)
        )

    def test_unknown_profile_and_malformed_words_fail_project_validation(self):
        project = blank_mobile3d_project()
        project.nodes[0].metadata["packed_kinematic"] = {
            "pose": "0",
            "motion": "0",
            "profile": "missing",
        }
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertIn("unknown packed kinematic profile", report.issues[0].message)

        project.nodes[0].metadata["packed_kinematic"] = {
            "pose": "10000000000000000",
            "motion": "0",
            "profile": "default",
        }
        with self.assertRaisesRegex(ValueError, "unsigned 64-bit"):
            project.validate()

        project.nodes[0].metadata["packed_kinematic"] = {
            "pose": "0",
            "motion": "8000000000000000",
            "profile": "default",
        }
        with self.assertRaisesRegex(ValueError, "reserved signed code"):
            project.validate()

    def test_binary_reader_rejects_reference_corruption_and_trailing_bytes(self):
        project = blank_mobile3d_project()
        _attach_orbit(project)
        packed = compile_polar_pack_bytes(project)
        with self.assertRaisesRegex(PolarPackError, "trailing bytes"):
            inspect_polar_pack(packed + b"x", node_count=len(project.nodes))

        corrupt = bytearray(packed)
        # The final sparse record is exactly 24 bytes; profile index follows
        # its u32 scene-node index.
        struct.pack_into("<H", corrupt, len(corrupt) - 20, 0xFFFF)
        with self.assertRaisesRegex(PolarPackError, "profile index"):
            inspect_polar_pack(bytes(corrupt), node_count=len(project.nodes))

        with self.assertRaisesRegex(PolarPackError, "scene node index"):
            inspect_polar_pack(packed, node_count=0)


if __name__ == "__main__":
    unittest.main()
