from __future__ import annotations

from dataclasses import replace
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.templates3d import first_steps_mobile3d_project


class EditorLogicTraceWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.document.create(first_steps_mobile3d_project())
        self.window.document.set_selection(SelectionRef("node", "player"))

    def tearDown(self) -> None:
        self.window.stop()
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def test_preview_keeps_logic_open_read_only_and_retains_last_run(self) -> None:
        self.window.editor_tabs.setCurrentIndex(self.window._logic_tab_index)
        self.window.play()
        self.window.play_timer.stop()

        self.assertTrue(
            self.window.editor_tabs.isTabEnabled(self.window._logic_tab_index)
        )
        self.assertTrue(self.window.graph_page.read_only)
        self.assertTrue(self.window.graph_page.graph_scene.read_only)

        self.window.viewport.pressed_keys.add("space")
        self.window._play_frame()
        self.window.viewport.pressed_keys.discard("space")

        self.assertEqual(self.window.graph_page.trace_count, 6)
        self.assertEqual(
            self.window.editor_tabs.tabText(self.window._logic_tab_index),
            "Logic Blocks • 6 ran",
        )
        self.assertEqual(self.window.graph_page.trace_list.topLevelItemCount(), 6)

        self.window.editor_tabs.setCurrentIndex(self.window._logic_tab_index)
        self.assertEqual(self.window.graph_page.trace_count, 6)

        self.window.document.set_selection(SelectionRef("node", "goal"))
        self.assertEqual(self.window.graph_page.trace_count, 0)
        self.assertEqual(
            self.window.editor_tabs.tabText(self.window._logic_tab_index),
            "Logic Blocks",
        )
        self.window.document.set_selection(SelectionRef("node", "player"))
        self.assertEqual(self.window.graph_page.trace_count, 6)
        self.window.stop()

        self.assertFalse(self.window.graph_page.read_only)
        self.assertEqual(self.window.graph_page.trace_count, 6)
        self.assertEqual(
            self.window.editor_tabs.tabText(self.window._logic_tab_index),
            "Logic Blocks • 6 ran",
        )

    def test_new_preview_clears_previous_trail(self) -> None:
        self.window.play()
        self.window.play_timer.stop()
        self.window.viewport.pressed_keys.add("space")
        self.window._play_frame()
        self.window.viewport.pressed_keys.discard("space")
        self.window.stop()
        self.assertEqual(self.window.graph_page.trace_count, 6)

        self.window.play()
        self.window.play_timer.stop()

        self.assertEqual(self.window.graph_page.trace_count, 0)
        self.assertEqual(
            self.window.editor_tabs.tabText(self.window._logic_tab_index),
            "Logic Blocks",
        )

    def test_selected_idle_owner_never_shows_another_owners_trail(self) -> None:
        project = first_steps_mobile3d_project()
        nodes = []
        for node in project.nodes:
            if node.id != "goal":
                nodes.append(node)
                continue
            metadata = dict(node.metadata)
            metadata.pop("packed_kinematic", None)
            nodes.append(
                replace(
                    node,
                    transform=replace(node.transform, translation=(0.0, 0.55, 3.0)),
                    metadata=metadata,
                )
            )
            nodes.append(
                replace(
                    node,
                    id="far_goal",
                    transform=replace(node.transform, translation=(50.0, 0.55, 50.0)),
                    metadata=metadata,
                )
            )
        project.nodes = tuple(nodes)
        project.validate()
        self.window.document.create(project)
        self.window.document.set_selection(SelectionRef("node", "goal"))
        self.window.play()
        self.window.play_timer.stop()
        self.window._play_frame()

        near = self.window.document.logic_trace("goal_area_lesson", "goal")
        self.assertIsNotNone(near)
        self.assertIsNone(
            self.window.document.logic_trace("goal_area_lesson", "far_goal")
        )
        self.assertEqual(self.window.graph_page.trace_count, 3)

        self.window.document.set_selection(SelectionRef("node", "far_goal"))
        self.assertEqual(self.window.graph_page.trace_count, 0)
        self.assertIsNone(self.window._logic_trace_snapshot)
        self.assertEqual(
            self.window.editor_tabs.tabText(self.window._logic_tab_index),
            "Logic Blocks",
        )


if __name__ == "__main__":
    unittest.main()
