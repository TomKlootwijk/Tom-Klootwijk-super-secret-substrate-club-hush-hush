from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack
from ugts_kc3.game import GameWorld
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph, attach_graph


class Mobile3DComponentAliasTests(unittest.TestCase):
    def test_first_two_visual_graph_tick_values_match_2d(self):
        graph = VisualGraph(
            "tick_probe",
            (
                GraphNode("tick", "event.tick"),
                GraphNode("remember", "action.set_state", {"key": "observed_tick"}),
            ),
            (
                GraphLink("tick", "out", "remember", "in"),
                GraphLink("tick", "tick", "remember", "value"),
            ),
        )
        world_2d = GameWorld()
        world_3d = blank_mobile3d_project().instantiate_world()
        attach_graph(world_2d, graph)
        attach_graph(world_3d, graph)
        for expected in (0, 1):
            world_2d.step()
            world_3d.step()
            self.assertEqual(world_2d.state["observed_tick"], expected)
            self.assertEqual(world_3d.state["observed_tick"], expected)

    def test_portable_graph_can_write_whole_and_field_vector_aliases(self):
        graph = VisualGraph(
            "spin",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "whole",
                    "action.set_component",
                    {
                        "component": "angular_velocity",
                        "field": "",
                        "value": [1.0, 2.0, 3.0],
                    },
                ),
                GraphNode(
                    "field",
                    "action.set_component",
                    {
                        "component": "angular_velocity",
                        "field": "y",
                        "value": 4.0,
                    },
                ),
            ),
            (
                GraphLink("ready", "out", "whole", "in"),
                GraphLink("whole", "out", "field", "in"),
            ),
        )
        project = blank_mobile3d_project()
        project.nodes = tuple(
            replace(node, metadata={**node.metadata, "visual_graph": graph.id})
            if node.id == "player" else node
            for node in project.nodes
        )
        project.metadata["visual_graphs"] = [graph.to_dict()]
        packed = inspect_graph_pack(compile_graph_pack_bytes(project))
        self.assertEqual(packed["binding_count"], 1)

        world = project.instantiate_world()
        self.assertEqual(world.require("player").angular_velocity, (1.0, 4.0, 3.0))
        self.assertEqual(list(world.get("player", "angular_velocity")), [1.0, 4.0, 3.0])

    def test_aliases_update_compatibility_record_and_participate_in_queries(self):
        world = blank_mobile3d_project().instantiate_world()
        world.add_component("player", [4.0, 5.0, 6.0], "velocity", replace_existing=True)
        world.add_component("player", False, "active", replace_existing=True)
        player = world.require("player")
        self.assertEqual(player.velocity, (4.0, 5.0, 6.0))
        self.assertFalse(world.get("player", "active"))
        self.assertEqual(
            [item.id for item in world.query("velocity", "active", active_only=False) if item.id == "player"],
            ["player"],
        )
        with self.assertRaises(TypeError):
            world.add_component("player", 1, "alive", replace_existing=True)
        with self.assertRaises(ValueError):
            world.add_component("player", [math.nan, 0, 0], "velocity", replace_existing=True)

    def test_initial_state_is_validated_deep_copied_and_seeded(self):
        project = blank_mobile3d_project()
        project.metadata["initial_state"] = {"score": 7, "lesson": {"steps": [1, 2]}}
        report = project.validate()
        self.assertEqual(report.metrics["initial_state_key_count"], 2)
        world = project.instantiate_world()
        self.assertEqual(world.state["score"], 7)
        self.assertEqual(world.state["lesson"], {"steps": [1, 2]})
        world.state["lesson"]["steps"].append(3)
        self.assertEqual(project.metadata["initial_state"]["lesson"]["steps"], [1, 2])

        project.metadata["initial_state"] = []
        invalid = project.validate(raise_on_error=False)
        self.assertTrue(any(issue.code == "state.initial_invalid" for issue in invalid.issues))


if __name__ == "__main__":
    unittest.main()
