from __future__ import annotations

from dataclasses import replace
import math
import struct
import unittest

from ugts_kc3.graphpack import NODE_OPCODES, compile_graph_pack_bytes, inspect_graph_pack
from ugts_kc3.mobile3d import Collider3DRecord, Transform3DRecord
from ugts_kc3.packed_kinematics import (
    POLAR_MOVEMENT_FIELDS,
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PackedKinematicComponent,
    PolarMotion,
    PolarMovementComponent3D,
    PolarPose,
)
from ugts_kc3.polarpack import (
    collect_polar_project_spec,
    compile_polar_pack_bytes,
    quantized_profile_lut,
)
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _polar_project():
    project = blank_mobile3d_project("Friendly Polar ECS", "Learner")
    profile = LogPolarProfile(r0=2.0, rho_min=-2.0, rho_max=3.0)
    motion_range = MotionRange(2.0, 8.0, 6.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    project.metadata["packed_kinematic_profiles"] = {
        "friendly": {
            "profile": profile.to_dict(),
            "motion_range": motion_range.to_dict(),
            "lut_resolution": 64,
        }
    }
    packed = codec.component(
        PolarPose(math.log(3.0 / profile.r0), math.radians(25.0), 321, math.radians(70.0)),
        PolarMotion(0.25, math.tau * 0.2, 0.5, math.tau * -0.1),
        profile_id="friendly",
    )
    project.nodes = tuple(
        replace(
            node,
            angular_velocity=(0.0, 0.0, 0.0),
            metadata={**node.metadata, "packed_kinematic": packed.to_dict()},
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    return project, codec, packed


class PolarMovementComponentTests(unittest.TestCase):
    def test_compose_publishes_horizontal_velocity_without_owning_y(self) -> None:
        project, codec, _packed = _polar_project()
        project.nodes = tuple(
            replace(node, velocity=(11.0, 2.5, -9.0)) if node.id == "goal" else node
            for node in project.nodes
        )
        world = project.instantiate_world()
        entity = world.require("goal")
        packed = world.require("goal", "packed_kinematic")
        profile = next(
            item
            for item in collect_polar_project_spec(project).profiles
            if item.id == "friendly"
        )
        expected = codec.cartesian_state(packed, quantized_profile_lut(profile))

        self.assertAlmostEqual(entity.velocity[0], expected["velocity"][0], places=12)
        self.assertEqual(entity.velocity[1], 2.5)
        self.assertAlmostEqual(entity.velocity[2], expected["velocity"][1], places=12)

    def test_virtual_component_reads_queries_and_snapshots_without_duplication(self) -> None:
        project, _codec, packed = _polar_project()
        world = project.instantiate_world()
        movement = world.require("goal", "polar_movement")

        self.assertIsInstance(movement, PolarMovementComponent3D)
        self.assertEqual(tuple(movement.to_dict()), POLAR_MOVEMENT_FIELDS)
        self.assertEqual(
            [entity.id for entity in world.query("polar_movement")], ["goal"]
        )
        self.assertEqual(
            [entity.id for entity in world.query(PolarMovementComponent3D)],
            ["goal"],
        )
        self.assertEqual(
            world.require("goal", "packed_kinematic").profile_id, "friendly"
        )
        snapshot = next(
            item for item in world.snapshot()["entities"] if item["id"] == "goal"
        )
        self.assertIn("packed_kinematic", snapshot["extra_components"])
        self.assertNotIn("polar_movement", snapshot["extra_components"])
        self.assertEqual(
            PackedKinematicComponent.from_dict(
                project.nodes[[node.id for node in project.nodes].index("goal")]
                .metadata["packed_kinematic"]
            ).pose_word,
            packed.pose_word,
        )

    def test_one_field_write_preserves_other_bits_and_composes_immediately(self) -> None:
        project, codec, _packed = _polar_project()
        world = project.instantiate_world()
        entity = world.require("goal")
        before = world.require("goal", "packed_kinematic")
        movement = world.require("goal", "polar_movement")
        movement.radius = 5.12500017
        world.add_component(
            "goal", movement, "polar_movement", replace_existing=True
        )

        after = world.require("goal", "packed_kinematic")
        self.assertEqual(after.pose_word & ((1 << 44) - 1), before.pose_word & ((1 << 44) - 1))
        self.assertEqual(after.motion_word, before.motion_word)
        self.assertEqual((after.pose_word >> 12) & 0x3FFF, 321)
        decoded = world.require("goal", "polar_movement")
        self.assertEqual(decoded.radius, _f32(decoded.radius))
        profile_spec = next(
            item
            for item in collect_polar_project_spec(project).profiles
            if item.id == "friendly"
        )
        lut = quantized_profile_lut(profile_spec)
        expected = codec.cartesian_state(after, lut)
        self.assertAlmostEqual(entity.position[0], expected["position"][0], places=12)
        self.assertAlmostEqual(entity.position[2], expected["position"][1], places=12)

    def test_invalid_write_is_atomic_and_reports_profile_bound(self) -> None:
        project, _codec, _packed = _polar_project()
        world = project.instantiate_world()
        entity = world.require("goal")
        before_component = world.require("goal", "packed_kinematic").to_dict()
        before_pose = (entity.position, entity.rotation)
        movement = world.require("goal", "polar_movement")
        movement.radius = 1.0e20
        with self.assertRaisesRegex(ValueError, "radius must stay between"):
            world.add_component(
                "goal", movement, "polar_movement", replace_existing=True
            )
        self.assertEqual(
            world.require("goal", "packed_kinematic").to_dict(), before_component
        )
        self.assertEqual((entity.position, entity.rotation), before_pose)

        raw_leak = world.require("goal", "polar_movement").to_dict()
        raw_leak["pose_word"] = 0
        with self.assertRaisesRegex(ValueError, "unknown fields: pose_word"):
            world.add_component(
                "goal", raw_leak, "polar_movement", replace_existing=True
            )
        self.assertEqual(
            world.require("goal", "packed_kinematic").to_dict(), before_component
        )

    def test_all_seven_fields_roundtrip_through_profile_quantization(self) -> None:
        project, _codec, _packed = _polar_project()
        world = project.instantiate_world()
        before = world.require("goal", "packed_kinematic")
        values = world.require("goal", "polar_movement").to_dict()
        values.update(
            {
                "radius": 4.0,
                "angle_degrees": 450.0,
                "facing_degrees": -90.0,
                "turns_per_second": 0.5,
                "growth_per_second": -0.4,
                "turn_acceleration": 0.3,
                "growth_acceleration": -0.7,
            }
        )
        world.add_component(
            "goal", values, "polar_movement", replace_existing=True
        )
        after = world.require("goal", "packed_kinematic")
        decoded = world.require("goal", "polar_movement")

        self.assertEqual((after.pose_word >> 12) & 0x3FFF, 321)
        self.assertNotEqual(after.pose_word, before.pose_word)
        self.assertNotEqual(after.motion_word, before.motion_word)
        self.assertAlmostEqual(decoded.radius, 4.0, delta=0.01)
        self.assertAlmostEqual(decoded.angle_degrees, 90.0, delta=0.002)
        self.assertAlmostEqual(decoded.facing_degrees, 270.0, delta=0.09)
        self.assertAlmostEqual(decoded.turns_per_second, 0.5, delta=2.0e-5)
        self.assertAlmostEqual(decoded.growth_per_second, -0.4, delta=1.0e-4)
        self.assertAlmostEqual(decoded.turn_acceleration, 0.3, delta=8.0e-5)
        self.assertAlmostEqual(decoded.growth_acceleration, -0.7, delta=2.0e-4)

    def test_generic_logic_blocks_change_and_read_quantized_movement(self) -> None:
        project, _codec, _packed = _polar_project()
        polar_before = compile_polar_pack_bytes(project)
        graph = VisualGraph(
            "friendly_polar_logic",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "change_turn",
                    "action.set_component",
                    {
                        "component": "polar_movement",
                        "field": "turns_per_second",
                        "value": 0.37500001,
                    },
                ),
                GraphNode(
                    "read_turn",
                    "value.component",
                    {
                        "component": "polar_movement",
                        "field": "turns_per_second",
                        "default": -1.0,
                    },
                ),
                GraphNode(
                    "remember",
                    "action.set_state",
                    {"key": "quantized_turn_speed"},
                ),
            ),
            (
                GraphLink("ready", "out", "change_turn", "in"),
                GraphLink("change_turn", "out", "remember", "in"),
                GraphLink("read_turn", "value", "remember", "value"),
            ),
        )
        project.metadata["visual_graphs"] = [graph.to_dict()]
        project.nodes = tuple(
            replace(
                node,
                metadata={**node.metadata, "visual_graph": graph.id},
            )
            if node.id == "goal"
            else node
            for node in project.nodes
        )
        self.assertEqual(compile_polar_pack_bytes(project), polar_before)
        packed_graph = compile_graph_pack_bytes(project)
        self.assertEqual(inspect_graph_pack(packed_graph)["node_count"], 4)

        world = project.instantiate_world()
        movement = world.require("goal", "polar_movement")
        self.assertEqual(world.state["quantized_turn_speed"], movement.turns_per_second)
        self.assertNotEqual(movement.turns_per_second, -1.0)

    def test_dedicated_movement_blocks_are_smaller_and_keep_desktop_parity(self) -> None:
        self.assertEqual(NODE_OPCODES["value.polar_movement"], 28)
        self.assertEqual(NODE_OPCODES["action.set_polar_movement"], 29)
        project, _codec, _packed = _polar_project()
        generic = VisualGraph(
            "movement_logic",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "change",
                    "action.set_component",
                    {
                        "component": "polar_movement",
                        "field": "turns_per_second",
                        "value": 0.37500001,
                    },
                ),
                GraphNode(
                    "read",
                    "value.component",
                    {
                        "component": "polar_movement",
                        "field": "turns_per_second",
                        "default": -1.0,
                    },
                ),
                GraphNode("remember", "action.set_state", {"key": "turn_speed"}),
            ),
            (
                GraphLink("ready", "out", "change", "in"),
                GraphLink("change", "out", "remember", "in"),
                GraphLink("read", "value", "remember", "value"),
            ),
        )
        dedicated = VisualGraph(
            "movement_logic",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "change",
                    "action.set_polar_movement",
                    {"field": "turns_per_second", "value": 0.37500001},
                ),
                GraphNode(
                    "read",
                    "value.polar_movement",
                    {"field": "turns_per_second", "default": -1.0},
                ),
                GraphNode("remember", "action.set_state", {"key": "turn_speed"}),
            ),
            generic.links,
        )

        def bind(graph: VisualGraph):
            result = replace(
                project,
                metadata={**project.metadata, "visual_graphs": [graph.to_dict()]},
            )
            result.nodes = tuple(
                replace(node, metadata={**node.metadata, "visual_graph": graph.id})
                if node.id == "goal"
                else node
                for node in result.nodes
            )
            return result

        generic_pack = compile_graph_pack_bytes(bind(generic))
        dedicated_project = bind(dedicated)
        dedicated_pack = compile_graph_pack_bytes(dedicated_project)
        dedicated_info = inspect_graph_pack(dedicated_pack)
        self.assertEqual(len(generic_pack), 268)
        self.assertEqual(len(dedicated_pack), 239)
        self.assertEqual(len(generic_pack) - len(dedicated_pack), 29)
        self.assertEqual(dedicated_info["input_count"], 8)
        self.assertNotIn(b"polar_movement", dedicated_pack)

        world = dedicated_project.instantiate_world()
        movement = world.require("goal", "polar_movement")
        self.assertEqual(world.state["turn_speed"], movement.turns_per_second)
        self.assertNotEqual(movement.turns_per_second, -1.0)

        invalid = VisualGraph(
            "invalid_movement_logic",
            (
                GraphNode(
                    "change",
                    "action.set_polar_movement",
                    {"entity": "goal", "field": "pose_word", "value": 1.0},
                ),
            ),
        )
        with self.assertRaisesRegex(ValueError, "Movement number"):
            compile_graph_pack_bytes(bind(invalid))

        invalid_default = VisualGraph(
            "invalid_movement_default",
            (
                GraphNode(
                    "read",
                    "value.polar_movement",
                    {"entity": "goal", "field": "radius", "default": "missing"},
                ),
            ),
        )
        with self.assertRaisesRegex(
            ValueError,
            r"(?:Fallback value|property 'default').*number",
        ):
            compile_graph_pack_bytes(bind(invalid_default))

    def test_graphpack_accepts_every_numeric_field_and_rejects_whole_view(self) -> None:
        project, _codec, _packed = _polar_project()
        nodes = [GraphNode("ready", "event.ready")]
        links = []
        safe_values = {
            "radius": 3.0,
            "angle_degrees": 45.0,
            "facing_degrees": 90.0,
            "turns_per_second": 0.25,
            "growth_per_second": 0.1,
            "turn_acceleration": 0.1,
            "growth_acceleration": 0.1,
        }
        for index, field in enumerate(POLAR_MOVEMENT_FIELDS):
            node_id = f"set_{index}"
            nodes.append(
                GraphNode(
                    node_id,
                    "action.set_component",
                    {
                        "entity": "goal",
                        "component": "polar_movement",
                        "field": field,
                        "value": safe_values[field],
                    },
                )
            )
            links.append(GraphLink("ready", "out", node_id, "in"))
        graph = VisualGraph("all_polar_fields", tuple(nodes), tuple(links))
        project.metadata["visual_graphs"] = [graph.to_dict()]
        project.metadata["world_graphs"] = graph.id
        info = inspect_graph_pack(compile_graph_pack_bytes(project))
        self.assertEqual(info["node_count"], 1 + len(POLAR_MOVEMENT_FIELDS))

        broken = VisualGraph(
            "whole_polar",
            (
                GraphNode(
                    "read",
                    "value.component",
                    {
                        "entity": "goal",
                        "component": "polar_movement",
                        "field": "",
                        "default": 0,
                    },
                ),
            ),
        )
        project.metadata["visual_graphs"] = [broken.to_dict()]
        project.metadata["world_graphs"] = broken.id
        with self.assertRaisesRegex(ValueError, "polar_movement"):
            compile_graph_pack_bytes(project)

    def test_polar_parent_carries_child_after_ready_graph_write(self) -> None:
        project, _codec, _packed = _polar_project()
        goal = next(node for node in project.nodes if node.id == "goal")
        child = replace(
            goal,
            id="goal_marker",
            transform=Transform3DRecord((1.0, 0.0, 0.0)),
            collider=Collider3DRecord(),
            angular_velocity=(0.0, 0.0, 0.0),
            tags=(),
            metadata={},
            parent_id="goal",
        )
        graph = VisualGraph(
            "turn_parent",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "face",
                    "action.set_component",
                    {
                        "component": "polar_movement",
                        "field": "facing_degrees",
                        "value": 90.0,
                    },
                ),
            ),
            (GraphLink("ready", "out", "face", "in"),),
        )
        project.nodes = tuple(
            replace(
                node,
                transform=replace(node.transform, scale=(1.0, 1.0, 1.0)),
                metadata={**node.metadata, "visual_graph": graph.id},
            )
            if node.id == "goal"
            else node
            for node in project.nodes
        ) + (child,)
        project.metadata["visual_graphs"] = [graph.to_dict()]
        world = project.instantiate_world()
        parent = world.require("goal")
        marker = world.require("goal_marker")
        self.assertAlmostEqual(marker.position[0], parent.position[0], places=4)
        self.assertAlmostEqual(marker.position[2], parent.position[2] - 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
