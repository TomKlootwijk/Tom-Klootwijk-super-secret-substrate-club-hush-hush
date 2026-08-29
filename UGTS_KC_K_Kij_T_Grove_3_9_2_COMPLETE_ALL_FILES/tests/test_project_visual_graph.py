from dataclasses import replace
import unittest

from ugts_kc3.templates import blank_vector_game_project
from ugts_kc3.game_input import InputFrame
from ugts_kc3.templates import first_steps_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


class ProjectVisualGraphTests(unittest.TestCase):
    def test_scene_graph_validates_binds_and_runs_ready(self):
        project = blank_vector_game_project("My First Graph Game", "Learner")
        scene = project.scenes[project.start_scene]
        entity = scene.entities[0]
        graph = VisualGraph(
            "hello",
            (
                GraphNode("start", "event.ready", position=(0, 0)),
                GraphNode(
                    "score", "action.set_state",
                    {"key": "score", "value": 7},
                    (220, 0),
                ),
            ),
            (GraphLink("start", "out", "score", "in"),),
        )
        scene = replace(
            scene,
            entities=(replace(entity, metadata={**entity.metadata, "visual_graph": "hello"}),),
            rules={**scene.rules, "visual_graphs": [graph.to_dict()]},
        )
        project.scenes[scene.id] = scene
        report = project.validate(raise_on_error=False)
        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual(report.metrics["visual_graph_count"], 1)
        world = project.instantiate_world()
        self.assertEqual(world.state["score"], 7)
        self.assertEqual(len(world.visual_graph_bindings), 1)

    def test_unknown_entity_binding_is_reported_in_plain_language(self):
        project = blank_vector_game_project()
        scene = project.scenes[project.start_scene]
        entity = replace(scene.entities[0], metadata={"visual_graph": "missing"})
        project.scenes[scene.id] = replace(scene, entities=(entity,))
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.code == "visual_graph.unknown" for issue in report.issues))

    def test_world_graph_string_is_one_binding_and_unknown_ids_fail_validation(self):
        project = blank_vector_game_project()
        scene = project.scenes[project.start_scene]
        graph = VisualGraph(
            "world_ready",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("mark", "action.set_state", {"key": "world_ready", "value": True}),
            ),
            (GraphLink("ready", "out", "mark", "in"),),
        )
        project.scenes[scene.id] = replace(
            scene,
            rules={
                **scene.rules,
                "visual_graphs": [graph.to_dict()],
                "world_graphs": "world_ready",
            },
        )
        self.assertTrue(project.validate(raise_on_error=False).passed)
        world = project.instantiate_world()
        self.assertTrue(world.state["world_ready"])
        self.assertEqual(len(world.visual_graph_bindings), 1)
        project.scenes[scene.id] = replace(
            project.scenes[scene.id],
            rules={**project.scenes[scene.id].rules, "world_graphs": "missing"},
        )
        self.assertFalse(project.validate(raise_on_error=False).passed)

    def test_entity_graph_stops_with_inactive_or_despawned_owner(self):
        pressed = InputFrame({"dash": 1.0}, {"dash": 0.0}, {"dash": 0.5})
        project = first_steps_project()
        scene = project.scenes[project.start_scene]
        player_id = next(entity.id for entity in scene.entities if "player" in entity.tags)

        inactive_world = project.instantiate_world()
        inactive_world.entities[player_id].active = False
        inactive_world.step(pressed)
        self.assertEqual(inactive_world.state["score"], 0)

        despawned_world = project.instantiate_world()
        despawned_world.despawn(player_id)
        despawned_world.step(pressed)
        self.assertEqual(despawned_world.state["score"], 0)

    def test_duplicate_graph_bindings_are_rejected(self):
        project = first_steps_project()
        scene = project.scenes[project.start_scene]
        project.scenes[scene.id] = replace(
            scene,
            entities=tuple(
                replace(
                    entity,
                    metadata={"visual_graph": ["dash_counter", "dash_counter"]},
                )
                if "player" in entity.tags
                else entity
                for entity in scene.entities
            ),
        )
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.code == "visual_graph.binding_type" for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
