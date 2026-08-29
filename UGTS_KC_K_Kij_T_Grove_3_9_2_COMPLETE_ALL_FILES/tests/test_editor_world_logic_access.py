from __future__ import annotations

from dataclasses import replace
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.templates import first_steps_project
from ugts_kc3.templates3d import first_steps_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


def _ready_world_graph(
    graph_id: str, title: str, state_key: str, value: int
) -> VisualGraph:
    return VisualGraph(
        graph_id,
        (
            GraphNode("when_scene_starts", "event.ready", {}, (0, 80)),
            GraphNode("number", "value.constant", {"value": value}, (0, 230)),
            GraphNode(
                "remember_number",
                "action.set_state",
                {"key": state_key},
                (300, 80),
            ),
        ),
        (
            GraphLink("when_scene_starts", "out", "remember_number", "in"),
            GraphLink("number", "value", "remember_number", "value"),
        ),
        {"title": title, "beginner": True, "android_supported": True},
    )


def _with_2d_world_graphs():
    project = first_steps_project()
    scene = project.scenes[project.start_scene]
    morning = _ready_world_graph("world_morning", "Morning Sky", "sky", 1)
    weather = _ready_world_graph("world_weather", "Weather Rules", "weather", 2)
    rules = dict(scene.rules)
    rules["visual_graphs"] = [
        *list(rules.get("visual_graphs", ())),
        morning.to_dict(),
        weather.to_dict(),
    ]
    rules["world_graphs"] = [morning.id, weather.id]
    project.scenes[scene.id] = replace(scene, rules=rules)
    project.validate()
    return project


def _with_3d_world_graphs():
    project = first_steps_mobile3d_project()
    sunrise = _ready_world_graph("world_sunrise", "Sunrise Rules", "sun", 1)
    wind = _ready_world_graph("world_wind", "Wind Controller", "wind", 2)
    metadata = dict(project.metadata)
    metadata["visual_graphs"] = [
        *list(metadata.get("visual_graphs", ())),
        sunrise.to_dict(),
        wind.to_dict(),
    ]
    metadata["world_graphs"] = [sunrise.id, wind.id]
    project.metadata = metadata
    project.validate()
    return project


class EditorWorldLogicAccessTests(unittest.TestCase):
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

    def _tree_item(self, selection: SelectionRef):
        iterator = QTreeWidgetItemIterator(self.window.hierarchy.tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, Qt.ItemDataRole.UserRole) == selection:
                return item
            iterator += 1
        self.fail(f"Scene Tree has no item for {selection!r}")

    def _click(self, selection: SelectionRef):
        item = self._tree_item(selection)
        self.window.hierarchy.tree.setCurrentItem(item)
        self.app.processEvents()
        self.assertEqual(self.window.document.selection, selection)
        return item

    @staticmethod
    def _graph(project, graph_id: str) -> dict[str, object]:
        if hasattr(project, "scenes"):
            scene = project.scenes[project.start_scene]
            values = scene.rules["visual_graphs"]
        else:
            values = project.metadata["visual_graphs"]
        return next(item for item in values if item["id"] == graph_id)

    def _clear_with_project_item(self) -> None:
        root = self.window.hierarchy.tree.topLevelItem(0)
        self.window.hierarchy.tree.setCurrentItem(root)
        self.app.processEvents()
        self.assertIsNone(self.window.document.selection)
        self.assertIsNone(self.window._logic_trace_snapshot)
        self.assertEqual(self.window.graph_page.trace_count, 0)

    def _exercise_world_logic(
        self,
        *,
        project,
        world_ids: tuple[str, str],
        world_titles: tuple[str, str],
        object_selection: SelectionRef,
        object_graph_id: str,
    ) -> None:
        self.window.document.create(project)
        first = SelectionRef("world_graph", world_ids[0], object_selection.scene_id)
        second = SelectionRef("world_graph", world_ids[1], object_selection.scene_id)

        first_item = self._tree_item(first)
        second_item = self._tree_item(second)
        self.assertEqual(first_item.text(0), world_titles[0])
        self.assertEqual(second_item.text(0), world_titles[1])

        self._click(second)
        self.assertEqual(
            self.window.graph_page.graph_scene.property("graph_id"), world_ids[1]
        )
        self.assertEqual(self.window.inspector.title.text(), "World Logic")
        self.assertIn("whole scene", self.window.inspector.subtitle.text())
        self.assertIn("World Logic:", self.window.status_message.text())
        self.assertIsNone(self.window.viewport._selected_id)
        self.assertFalse(self.window.hierarchy.duplicate_button.isEnabled())
        self.assertFalse(self.window.hierarchy.delete_button.isEnabled())

        edited = self.window.graph_page.graph_scene.data()
        edited["metadata"] = {**dict(edited.get("metadata", {})), "edited": True}
        undo_count = self.window.undo_stack.count()
        self.window._graph_edited(edited)
        self.app.processEvents()
        self.assertEqual(self.window.undo_stack.count(), undo_count + 1)
        self.assertTrue(self._graph(project, world_ids[1])["metadata"]["edited"])
        self.assertNotIn("edited", self._graph(project, world_ids[0])["metadata"])

        # Clear the UI context before undoing: the command must still target
        # the selected world graph, never the first/object graph fallback.
        self._clear_with_project_item()
        self.window.undo_stack.undo()
        self.assertNotIn("edited", self._graph(project, world_ids[1])["metadata"])
        self.window.undo_stack.redo()
        self.assertTrue(self._graph(project, world_ids[1])["metadata"]["edited"])
        self.assertNotIn("edited", self._graph(project, object_graph_id)["metadata"])

        self._click(second)
        self.window.play()
        self.window.play_timer.stop()
        world_snapshot = self.window.document.logic_trace(world_ids[1], None)
        self.assertIsNotNone(world_snapshot)
        self.assertIs(self.window._logic_trace_snapshot, world_snapshot)
        self.assertEqual(self.window._logic_trace_snapshot.key, (world_ids[1], None))
        self.assertEqual(self.window.graph_page.trace_count, 3)

        # Produce an object-owned run while World Logic stays selected. The
        # newer object trail must not replace the exact owner=None trail.
        self.window.viewport.pressed_keys.add("space")
        self.window._play_frame()
        self.window.viewport.pressed_keys.discard("space")
        self.assertEqual(self.window._logic_trace_snapshot.key, (world_ids[1], None))

        self._click(object_selection)
        object_snapshot = self.window.document.logic_trace(
            object_graph_id, object_selection.object_id
        )
        self.assertIsNotNone(object_snapshot)
        self.assertIs(self.window._logic_trace_snapshot, object_snapshot)
        self.assertEqual(
            self.window._logic_trace_snapshot.key,
            (object_graph_id, object_selection.object_id),
        )

        self._click(second)
        self.assertIs(self.window._logic_trace_snapshot, world_snapshot)
        self._clear_with_project_item()
        self.assertIsNone(self.window.viewport._selected_id)

    def test_2d_scene_tree_world_logic_is_exact_and_owner_safe(self) -> None:
        self._exercise_world_logic(
            project=_with_2d_world_graphs(),
            world_ids=("world_morning", "world_weather"),
            world_titles=("Morning Sky", "Weather Rules"),
            object_selection=SelectionRef("entity", "player", "main"),
            object_graph_id="dash_counter",
        )

    def test_3d_scene_tree_world_logic_is_exact_and_owner_safe(self) -> None:
        self._exercise_world_logic(
            project=_with_3d_world_graphs(),
            world_ids=("world_sunrise", "world_wind"),
            world_titles=("Sunrise Rules", "Wind Controller"),
            object_selection=SelectionRef("node", "player"),
            object_graph_id="dash_lesson",
        )

    def test_missing_world_graph_binding_opens_its_own_blank_context(self) -> None:
        project = first_steps_mobile3d_project()
        metadata = dict(project.metadata)
        metadata["world_graphs"] = ["missing_world_graph"]
        project.metadata = metadata
        self.window.document.create(project)

        selection = SelectionRef("world_graph", "missing_world_graph")
        self._click(selection)
        data = self.window.document.graph_data()
        self.assertEqual(data["id"], "missing_world_graph")
        self.assertEqual(data["nodes"], [])
        self.assertEqual(
            self.window.graph_page.graph_scene.property("graph_id"),
            "missing_world_graph",
        )
        self.assertNotEqual(data["id"], "dash_lesson")

    def test_2d_world_logic_click_activates_its_scene_for_preview(self) -> None:
        project = first_steps_project()
        main = project.scenes[project.start_scene]
        bonus_graph = _ready_world_graph(
            "bonus_world_logic", "Bonus World Rules", "bonus", 9
        )
        bonus_rules = dict(main.rules)
        bonus_rules["visual_graphs"] = [
            *list(bonus_rules.get("visual_graphs", ())),
            bonus_graph.to_dict(),
        ]
        bonus_rules["world_graphs"] = [bonus_graph.id]
        project.scenes["bonus"] = replace(main, id="bonus", rules=bonus_rules)
        project.validate()
        self.window.document.create(project)

        selection = SelectionRef("world_graph", bonus_graph.id, "bonus")
        self._click(selection)
        self.assertEqual(self.window.document.current_scene_id, "bonus")
        self.assertEqual(
            self.window.graph_page.graph_scene.property("graph_id"), bonus_graph.id
        )

        self.window.play()
        self.window.play_timer.stop()
        snapshot = self.window.document.logic_trace(bonus_graph.id, None)
        self.assertIsNotNone(snapshot)
        self.assertIs(self.window._logic_trace_snapshot, snapshot)


if __name__ == "__main__":
    unittest.main()
