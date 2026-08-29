from dataclasses import replace
import unittest

from ugts_kc3.templates import blank_vector_game_project
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


if __name__ == "__main__":
    unittest.main()
