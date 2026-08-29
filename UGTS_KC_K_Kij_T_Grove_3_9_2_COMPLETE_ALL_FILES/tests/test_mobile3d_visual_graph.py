from dataclasses import replace
import unittest

from ugts_kc3.mobile3d import InputFrame3D, TransformComponent3D
from ugts_kc3.templates import first_steps_project
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


class Mobile3DVisualGraphTests(unittest.TestCase):
    @staticmethod
    def project_with_dash_graph():
        source = first_steps_project()
        source_scene = source.scenes[source.start_scene]
        graph = source_scene.rules["visual_graphs"][0]
        project = blank_mobile3d_project("My First 3D Graph", "Learner")
        nodes = tuple(
            replace(
                node,
                metadata={**node.metadata, "visual_graph": "dash_counter"},
            )
            if node.id == "player"
            else node
            for node in project.nodes
        )
        project.nodes = nodes
        project.metadata = {**project.metadata, "visual_graphs": [graph]}
        return project

    def test_mobile_project_validates_binds_and_runs_shared_graph(self):
        project = self.project_with_dash_graph()
        report = project.validate(raise_on_error=False)
        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual(report.metrics["visual_graph_count"], 1)
        self.assertEqual(report.metrics["visual_graph_binding_count"], 1)
        world = project.instantiate_world()
        self.assertEqual(len(world.visual_graph_bindings), 1)
        held = InputFrame3D(action=True)
        world.step(held)
        self.assertEqual(world.state["score"], 1)
        world.step(held)
        self.assertEqual(world.state["score"], 1)
        world.step(InputFrame3D())
        world.step(held)
        self.assertEqual(world.state["score"], 2)

    def test_mobile_input_edges_cover_movement_axes(self):
        pressed = InputFrame3D(move_x=-1.0).with_previous(InputFrame3D())
        held = InputFrame3D(move_x=-1.0).with_previous(InputFrame3D(move_x=-1.0))
        self.assertTrue(pressed.pressed("move_left"))
        self.assertFalse(held.pressed("move_left"))

    def test_3d_world_exposes_composable_component_queries(self):
        world = blank_mobile3d_project().instantiate_world()
        player = world.require("player")
        transform = world.require("player", "transform")
        self.assertIsInstance(transform, TransformComponent3D)
        transform.position = (2.0, 3.0, 4.0)
        world.add_component("player", transform, "transform", replace_existing=True)
        self.assertEqual(player.position, (2.0, 3.0, 4.0))
        self.assertEqual([entity.id for entity in world.query("body", tags=("player",))], ["player"])
        before = player.velocity
        world.apply_force("player", (2.0, -1.0))
        self.assertNotEqual(player.velocity, before)

    def test_unknown_mobile_graph_binding_is_reported(self):
        project = blank_mobile3d_project()
        project.nodes = tuple(
            replace(node, metadata={"visual_graph": "missing"})
            if node.id == "player"
            else node
            for node in project.nodes
        )
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.code == "graph.binding_unknown" for issue in report.issues))

    def test_ready_graph_can_edit_a_3d_transform_component(self):
        graph = VisualGraph(
            "place_player",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "place",
                    "action.set_component",
                    {
                        "component": "transform",
                        "field": "position",
                        "value": [3.0, 2.0, 1.0],
                    },
                ),
            ),
            (GraphLink("ready", "out", "place", "in"),),
        )
        project = blank_mobile3d_project()
        project.nodes = tuple(
            replace(node, metadata={"visual_graph": graph.id})
            if node.id == "player"
            else node
            for node in project.nodes
        )
        project.metadata = {"visual_graphs": [graph.to_dict()]}
        world = project.instantiate_world()
        self.assertEqual(world.require("player").position, (3.0, 2.0, 1.0))


if __name__ == "__main__":
    unittest.main()
