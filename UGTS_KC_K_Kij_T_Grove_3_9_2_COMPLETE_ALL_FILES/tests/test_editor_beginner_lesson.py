from __future__ import annotations

from dataclasses import replace
import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.graphpack import compile_graph_pack_bytes
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.templates import blank_vector_game_project, first_steps_project
from ugts_kc3.templates3d import (
    blank_mobile3d_project,
    first_steps_mobile3d_project,
)


def _project_bytes(project) -> bytes:
    return json.dumps(
        project.to_dict(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _rendered_steps(window: EditorMainWindow) -> tuple[str, ...]:
    text = window.assets_project.lesson_steps.text()
    return tuple(part.split(". ", 1)[1] for part in text.split("\n\n") if part)


class EditorBeginnerLessonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()

    def tearDown(self) -> None:
        self.window.stop()
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def _assert_lesson_is_read_only(self) -> None:
        project = self.window.document.project
        self.assertIsNotNone(project)
        authoring_before = _project_bytes(project)
        graphpack_before = (
            compile_graph_pack_bytes(project)
            if isinstance(project, Mobile3DProject)
            else None
        )
        undo_before = self.window.undo_stack.count()

        self.window.assets_project.setCurrentIndex(0)
        self.assertTrue(self.window.assets_project.show_lesson())
        self.window.assets_project.refresh_lesson(self.window.document)
        self.app.processEvents()

        self.assertEqual(_project_bytes(project), authoring_before)
        if graphpack_before is not None:
            self.assertEqual(compile_graph_pack_bytes(project), graphpack_before)
        self.assertEqual(self.window.undo_stack.count(), undo_before)

    def test_new_2d_template_opens_exact_first_steps_without_writes(self) -> None:
        expected_authoring = _project_bytes(first_steps_project())
        self.window.new_2d_project()
        self.app.processEvents()

        panel = self.window.assets_project
        project = self.window.document.project
        self.assertEqual(_project_bytes(project), expected_authoring)
        scene = project.scenes[project.start_scene]
        lesson = scene.rules["lesson"]
        self.assertEqual(panel.currentIndex(), panel.lesson_tab_index)
        self.assertTrue(panel.isTabVisible(panel.lesson_tab_index))
        self.assertEqual(panel.lesson_title.text(), lesson["title"])
        self.assertEqual(_rendered_steps(self.window), tuple(lesson["steps"]))
        self.assertEqual(len(_rendered_steps(self.window)), 4)
        self.assertEqual(self.window.undo_stack.count(), 0)
        self._assert_lesson_is_read_only()

    def test_new_mobile_template_opens_all_first_steps_without_writes(self) -> None:
        expected_project = first_steps_mobile3d_project()
        expected_authoring = _project_bytes(expected_project)
        expected_graphpack = compile_graph_pack_bytes(expected_project)
        self.window.new_3d_project()
        self.app.processEvents()

        panel = self.window.assets_project
        project = self.window.document.project
        self.assertEqual(_project_bytes(project), expected_authoring)
        self.assertEqual(compile_graph_pack_bytes(project), expected_graphpack)
        lesson = project.metadata["lesson"]
        steps = _rendered_steps(self.window)
        self.assertEqual(panel.currentIndex(), panel.lesson_tab_index)
        self.assertTrue(panel.isTabVisible(panel.lesson_tab_index))
        self.assertEqual(panel.lesson_title.text(), lesson["title"])
        self.assertEqual(steps, tuple(lesson["steps"]))
        self.assertEqual(len(steps), 12)
        self.assertTrue(any("Find the Goal Ahead" in step for step in steps))
        self.assertTrue(any("Deploy to Phone" in step for step in steps))
        self.assertEqual(self.window.undo_stack.count(), 0)
        self._assert_lesson_is_read_only()

    def test_2d_scene_change_refreshes_then_clears_the_lesson(self) -> None:
        project = first_steps_project()
        main = project.scenes[project.start_scene]
        bonus_lesson = {
            "title": "Bonus first steps",
            "steps": ["Find the bonus.", "Press Play again."],
        }
        project.scenes["bonus"] = replace(
            main,
            id="bonus",
            rules={**main.rules, "lesson": bonus_lesson},
        )
        project.scenes["sandbox"] = replace(
            main,
            id="sandbox",
            rules={key: value for key, value in main.rules.items() if key != "lesson"},
        )
        self.window.document.create(project)

        self.window.document.set_current_scene("bonus")
        self.app.processEvents()
        panel = self.window.assets_project
        self.assertEqual(panel.lesson_title.text(), bonus_lesson["title"])
        self.assertEqual(_rendered_steps(self.window), tuple(bonus_lesson["steps"]))

        panel.show_lesson()
        self.window.document.set_current_scene("sandbox")
        self.app.processEvents()
        self.assertFalse(panel.isTabVisible(panel.lesson_tab_index))
        self.assertEqual(panel.lesson_title.text(), "")
        self.assertEqual(panel.lesson_steps.text(), "")
        self.assertEqual(panel.currentIndex(), 0)

    def test_nonlesson_and_malformed_lesson_never_show_stale_content(self) -> None:
        self.window.new_3d_project()
        panel = self.window.assets_project
        self.assertTrue(panel.lesson_title.text())

        self.window.document.create(blank_vector_game_project())
        self.assertFalse(panel.isTabVisible(panel.lesson_tab_index))
        self.assertFalse(panel.show_lesson())
        self.assertEqual(panel.lesson_title.text(), "")
        self.assertEqual(panel.lesson_steps.text(), "")

        malformed = blank_mobile3d_project()
        malformed.metadata["lesson"] = {
            "title": "Broken lesson",
            "steps": "This must be a list, not one string.",
        }
        self.window.document.create(malformed)
        self.assertFalse(panel.isTabVisible(panel.lesson_tab_index))
        self.assertEqual(panel.lesson_title.text(), "")
        self.assertEqual(panel.lesson_steps.text(), "")


if __name__ == "__main__":
    unittest.main()
