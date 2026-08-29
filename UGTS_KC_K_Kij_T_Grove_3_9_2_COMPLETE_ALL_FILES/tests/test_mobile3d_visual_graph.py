from dataclasses import replace
import struct
import unittest

from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack
from ugts_kc3.mobile3d import InputFrame3D, TransformComponent3D
from ugts_kc3.polarpack import compile_polar_pack_bytes, inspect_polar_pack
from ugts_kc3.templates import first_steps_project
from ugts_kc3.templates3d import blank_mobile3d_project, first_steps_mobile3d_project
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

    def test_fixed_senders_use_scene_graph_then_world_order(self):
        def sender(graph_id, message):
            return VisualGraph(
                graph_id,
                (
                    GraphNode("tick", "event.tick"),
                    GraphNode("send", "action.emit_event", {"kind": message}),
                ),
                (GraphLink("tick", "out", "send", "in"),),
            )

        graphs = (
            sender("z_floor", "floor_z"),
            sender("a_floor", "floor_a"),
            sender("m_player", "player_m"),
            sender("m_world", "world_m"),
        )
        project = blank_mobile3d_project()
        project.nodes = tuple(
            replace(node, metadata={**node.metadata, "visual_graph": ["z_floor", "a_floor"]})
            if node.id == "floor"
            else replace(node, metadata={**node.metadata, "visual_graph": "m_player"})
            if node.id == "player"
            else node
            for node in project.nodes
        )
        project.metadata = {
            **project.metadata,
            "visual_graphs": [graph.to_dict() for graph in reversed(graphs)],
            "world_graphs": ["m_world"],
        }

        world = project.instantiate_world()
        world.step()
        markers = {"floor_a", "floor_z", "player_m", "world_m"}
        self.assertEqual(
            [event.kind for event in world.events if event.kind in markers],
            ["floor_a", "floor_z", "player_m", "world_m"],
        )

    def test_phone_first_steps_template_runs_visible_beginner_graph(self):
        project = first_steps_mobile3d_project("A Child's First Phone Game", "Learner")
        report = project.validate(raise_on_error=False)
        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual(project.metadata["template"], "first-steps-mobile-3d")
        world = project.instantiate_world()
        self.assertEqual(
            struct.unpack("<I", struct.pack("<f", world.state["repeatable_number"]))[0],
            0xC0F72CB8,
        )
        self.assertIs(world.state["nearby_goal"], True)
        self.assertIs(world.state["goal_ahead"], True)
        timer_world = project.instantiate_world()
        for _ in range(119):
            timer_world.step()
        self.assertEqual(timer_world.state["timer_rings"], 0)
        timer_world.step()
        self.assertEqual(timer_world.state["timer_rings"], 1)
        goal_before = world.require("goal").position
        world.step(InputFrame3D(action=True))
        self.assertEqual(world.state["score"], 1)
        self.assertIs(world.state["heard_message"], True)
        self.assertEqual(world.require("player").scale, (1.35, 1.35, 1.35))
        self.assertNotEqual(world.require("goal").position, goal_before)
        player = world.require("player")
        player.position = world.require("goal").position
        player.velocity = (0.0, 0.0, 0.0)
        world.step()
        self.assertTrue(world.state["inside_goal"])
        player.position = (12.0, 1.0, 12.0)
        player.velocity = (0.0, 0.0, 0.0)
        world.step()
        self.assertFalse(world.state["inside_goal"])
        packed = inspect_graph_pack(compile_graph_pack_bytes(project))
        self.assertEqual(
            packed["graphs"],
            [
                {"id": "dash_lesson", "node_count": 7, "max_steps": 1024},
                {"id": "find_goal_ahead_lesson", "node_count": 3, "max_steps": 1024},
                {"id": "find_goal_lesson", "node_count": 3, "max_steps": 1024},
                {"id": "goal_area_lesson", "node_count": 6, "max_steps": 1024},
                {"id": "message_lesson", "node_count": 3, "max_steps": 1024},
                {"id": "repeatable_number_lesson", "node_count": 3, "max_steps": 1024},
                {"id": "timer_lesson", "node_count": 2, "max_steps": 1024},
            ],
        )
        self.assertEqual(packed["binding_count"], 7)
        self.assertEqual(packed["world_binding_count"], 4)
        polar = inspect_polar_pack(
            compile_polar_pack_bytes(project), node_count=len(project.nodes)
        )
        self.assertEqual(polar["profile_count"], 1)
        self.assertEqual(polar["component_count"], 1)
        self.assertLess(polar["byte_length"], 1024)

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

    def test_duplicate_mobile_graph_bindings_are_rejected(self):
        project = self.project_with_dash_graph()
        project.nodes = tuple(
            replace(
                node,
                metadata={"visual_graph": ["dash_counter", "dash_counter"]},
            )
            if node.id == "player"
            else node
            for node in project.nodes
        )
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.code == "graph.binding_type" for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
