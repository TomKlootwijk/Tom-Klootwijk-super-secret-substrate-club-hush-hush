from __future__ import annotations

from dataclasses import replace
import math
import unittest

from ugts_kc3.graphpack import NODE_OPCODES, compile_graph_pack_bytes
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarPose,
)
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


def _trigger_graph() -> VisualGraph:
    return VisualGraph(
        "sensor_logic",
        (
            GraphNode("enter", "event.trigger_enter"),
            GraphNode("remember_player", "action.set_state", {"key": "entered_by"}),
            GraphNode("exit", "event.trigger_exit"),
            GraphNode("remember_sensor", "action.set_state", {"key": "exited_sensor"}),
        ),
        (
            GraphLink("enter", "out", "remember_player", "in"),
            GraphLink("enter", "player", "remember_player", "value"),
            GraphLink("exit", "out", "remember_sensor", "in"),
            GraphLink("exit", "sensor", "remember_sensor", "value"),
        ),
    )


class TriggerArea3DTests(unittest.TestCase):
    def test_player_sensor_lifecycle_graph_context_and_no_impulse(self) -> None:
        project = blank_mobile3d_project()
        graph = _trigger_graph()
        project.metadata["visual_graphs"] = [graph.to_dict()]
        project.nodes = tuple(
            replace(node, metadata={**node.metadata, "visual_graph": graph.id})
            if node.id == "goal" else node
            for node in project.nodes
        )
        self.assertEqual(project.validate().metrics["trigger_sensor_count"], 1)
        self.assertEqual(NODE_OPCODES["event.trigger_enter"], 19)
        self.assertEqual(NODE_OPCODES["event.trigger_exit"], 20)
        self.assertTrue(compile_graph_pack_bytes(project))

        world = project.instantiate_world()
        player, sensor = world.require("player"), world.require("goal")
        player.position = sensor.position
        player.velocity = (0.0, 0.0, 0.0)
        first = world.step()
        enters = [event for event in first if event.kind == "trigger_enter"]
        self.assertEqual([(event.entity_a, event.entity_b) for event in enters], [("goal", "player")])
        self.assertEqual(world.state["entered_by"], "player")
        self.assertEqual(player.velocity[0], 0.0)
        self.assertEqual(player.velocity[2], 0.0)
        self.assertFalse(any(event.kind == "collision" and "goal" in (event.entity_a, event.entity_b) for event in first))

        self.assertFalse(any(event.kind == "trigger_enter" for event in world.step()))
        player.position = (12.0, 1.0, 12.0)
        player.velocity = (0.0, 0.0, 0.0)
        exits = [event for event in world.step() if event.kind == "trigger_exit"]
        self.assertEqual([(event.entity_a, event.entity_b) for event in exits], [("goal", "player")])
        self.assertEqual(world.state["exited_sensor"], "goal")

    def test_packed_polar_composition_precedes_trigger_detection(self) -> None:
        project = blank_mobile3d_project()
        profile = LogPolarProfile(r0=1.0, rho_min=-3.0, rho_max=3.0, core_radius=1.0e-5)
        motion = MotionRange(1.0, 1.0, 1.0, 1.0)
        codec = PackedKinematicCodec(profile, motion)
        component = codec.component(PolarPose(math.log(3.0), math.pi * 0.5), profile_id="orbit")
        project.metadata["packed_kinematic_profiles"] = {
            "orbit": {
                "profile": profile.to_dict(),
                "motion_range": motion.to_dict(),
                "lut_resolution": 128,
            }
        }
        project.nodes = tuple(
            replace(node, metadata={**node.metadata, "packed_kinematic": component.to_dict()})
            if node.id == "goal" else node
            for node in project.nodes
        )
        world = project.instantiate_world()
        self.assertTrue(any(event.kind == "trigger_enter" for event in world.step()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
