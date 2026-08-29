from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QDoubleSpinBox

from ugts_kc3.editor.document import EditorDocument
from ugts_kc3.editor.graph import (
    GraphNode,
    NodePalette,
    NodePropertiesPanel,
    TEMPLATE_BY_KEY,
    VisualGraphScene,
)
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.visual_graph import GraphNode as DataGraphNode, VisualGraph


def _document_bytes(document: EditorDocument) -> bytes:
    return json.dumps(
        document.serialize(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class TimerEditorAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_timer_is_a_child_friendly_root_event_with_bounded_controls(self) -> None:
        template = TEMPLATE_BY_KEY["event.timer"]
        self.assertEqual(template.title, "When Timer Rings")
        self.assertEqual(template.category, "Events")
        self.assertEqual(template.color, "#5ac8fa")
        self.assertIn("saved number of seconds", template.description)
        self.assertIn("Repeat", template.description)
        self.assertEqual(template.inputs, ())
        self.assertEqual(template.outputs, ("out", "count", "remaining", "entity"))
        self.assertEqual(dict(template.default_properties), {"seconds": 1.0, "repeat": True})

        palette = NodePalette()
        timer_item = None
        for category_index in range(palette.tree.topLevelItemCount()):
            category = palette.tree.topLevelItem(category_index)
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                if child.data(0, Qt.ItemDataRole.UserRole) == "event.timer":
                    timer_item = child
                    self.assertEqual(category.text(0), "Events")
                    self.assertEqual(child.text(0), "When Timer Rings")
        self.assertIsNotNone(timer_item)

        node = GraphNode("timer", template)
        self.assertEqual(node.input_ports, {})
        self.assertIn("starts the connected blocks", node.toolTip())
        panel = NodePropertiesPanel()
        panel.set_node(node)
        self.assertEqual(panel.title.text(), "When Timer Rings")
        self.assertIn("whether it starts waiting again", panel.hint.text())
        self.assertEqual(
            [panel.values.topLevelItem(index).text(0) for index in range(2)],
            ["Seconds", "Repeat"],
        )

        seconds = panel.editor_for("seconds")
        repeat = panel.editor_for("repeat")
        self.assertIsInstance(seconds, QDoubleSpinBox)
        self.assertGreater(seconds.minimum(), 0.0)
        self.assertEqual(seconds.maximum(), 86_400.0)
        self.assertEqual(seconds.decimals(), 3)
        self.assertEqual(seconds.singleStep(), 0.25)
        self.assertEqual(seconds.suffix(), " seconds")
        self.assertIn("one day", seconds.toolTip())
        self.assertIsInstance(repeat, QCheckBox)
        self.assertEqual(repeat.text(), "Ring again and again")
        self.assertTrue(repeat.isChecked())

        seconds.setValue(2.75)
        seconds.editingFinished.emit()
        repeat.setChecked(False)
        self.assertEqual(node.properties, {"seconds": 2.75, "repeat": False})
        VisualGraph(
            "timer_editor_controls",
            (DataGraphNode("timer", "event.timer", node.properties),),
        ).validate()

    def test_timer_literal_settings_are_not_exposed_as_connectable_inputs(self) -> None:
        scene = VisualGraphScene()
        scene.load_data(
            {
                "schema": VisualGraph.SCHEMA,
                "id": "timer_literal_guard",
                "nodes": [
                    {
                        "id": "number",
                        "type": "value.constant",
                        "position": [0, 0],
                        "properties": {"value": 3.0},
                    },
                    {
                        "id": "timer",
                        "type": "event.timer",
                        "position": [240, 0],
                        "properties": {"seconds": 3.0, "repeat": True},
                    },
                ],
                "links": [
                    {
                        "source_node": "number",
                        "source_port": "value",
                        "target_node": "timer",
                        "target_port": "seconds",
                    }
                ],
            }
        )
        self.assertNotIn("seconds", scene.nodes["timer"].input_ports)
        self.assertNotIn("repeat", scene.nodes["timer"].input_ports)
        self.assertEqual(scene.connections, [])
        self.assertEqual(scene.data()["links"], [])

    def test_timer_save_load_and_undo_redo_are_byte_exact(self) -> None:
        window = EditorMainWindow()
        try:
            window.new_2d_project()
            window.graph_page.add_template("event.timer")
            self.app.processEvents()
            timer = window.graph_page.properties.node
            self.assertIsNotNone(timer)
            self.assertEqual(timer.template.key, "event.timer")
            timer_id = timer.node_id
            window.undo_stack.clear()
            before = _document_bytes(window.document)

            seconds = window.graph_page.properties.editor_for("seconds")
            self.assertIsInstance(seconds, QDoubleSpinBox)
            seconds.setValue(4.25)
            seconds.editingFinished.emit()
            self.app.processEvents()

            repeat = window.graph_page.properties.editor_for("repeat")
            self.assertIsInstance(repeat, QCheckBox)
            repeat.setChecked(False)
            self.app.processEvents()
            after = _document_bytes(window.document)
            self.assertNotEqual(after, before)
            self.assertEqual(window.undo_stack.count(), 2)
            self.assertEqual(
                window.graph_page.graph_scene.nodes[timer_id].properties,
                {"seconds": 4.25, "repeat": False},
            )

            window.undo_stack.undo()
            window.undo_stack.undo()
            self.app.processEvents()
            self.assertEqual(_document_bytes(window.document), before)

            window.undo_stack.redo()
            window.undo_stack.redo()
            self.app.processEvents()
            self.assertEqual(_document_bytes(window.document), after)
            self.assertEqual(
                window.graph_page.graph_scene.nodes[timer_id].properties,
                {"seconds": 4.25, "repeat": False},
            )

            with tempfile.TemporaryDirectory() as temporary:
                path = window.document.save(Path(temporary) / "timer-project.json")
                self.assertEqual(json.loads(path.read_text(encoding="utf-8")), window.document.serialize())
                loaded = EditorDocument()
                loaded.load(path)
                self.assertEqual(_document_bytes(loaded), after)
                self.assertTrue(loaded.validate().passed)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
