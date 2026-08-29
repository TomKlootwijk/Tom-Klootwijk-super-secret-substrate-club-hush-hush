import unittest

from ugts_kc3.game_input import InputFrame
from ugts_kc3.templates import blank_vector_game_project, first_steps_project


class FirstStepsTests(unittest.TestCase):
    def test_unicode_child_name_gets_a_valid_ascii_project_id(self):
        project = blank_vector_game_project("Zoë haar spel")
        self.assertEqual(project.metadata.id, "game.zoe-haar-spel")
        self.assertTrue(project.validate(raise_on_error=False).passed)

    def test_starter_is_valid_and_space_graph_counts_dash_edges(self):
        project = first_steps_project("Lina's First Game", "Lina")
        report = project.validate(raise_on_error=False)
        self.assertTrue(report.passed, report.to_dict())
        self.assertEqual(report.metrics["visual_graph_count"], 1)
        world = project.instantiate_world()
        released = InputFrame({"dash": 0.0}, {"dash": 0.0}, {"dash": 0.5})
        pressed = InputFrame({"dash": 1.0}, {"dash": 0.0}, {"dash": 0.5})
        world.step(released)
        world.step(pressed)
        self.assertEqual(world.state["score"], 1)


if __name__ == "__main__":
    unittest.main()
