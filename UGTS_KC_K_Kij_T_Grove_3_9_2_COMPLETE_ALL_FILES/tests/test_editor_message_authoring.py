from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

from ugts_kc3.editor.graph import (
    GraphNode,
    NodePalette,
    NodePropertiesPanel,
    TEMPLATE_BY_KEY,
    VisualGraphScene,
)
from ugts_kc3.visual_graph import GraphNode as DataGraphNode, VisualGraph


class MessageEditorAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_receiver_is_a_literal_child_friendly_event(self) -> None:
        template = TEMPLATE_BY_KEY["event.message"]
        self.assertEqual(template.title, "When Message Heard")
        self.assertEqual(template.category, "Events")
        self.assertEqual(template.color, "#5ac8fa")
        self.assertIn("wait their turn", template.description)
        self.assertEqual(template.inputs, ())
        self.assertEqual(template.outputs, ("out", "source", "target", "entity"))
        self.assertEqual(dict(template.default_properties), {"message": "graph_event"})

        palette = NodePalette()
        matches = []
        for category_index in range(palette.tree.topLevelItemCount()):
            category = palette.tree.topLevelItem(category_index)
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                if child.data(0, Qt.ItemDataRole.UserRole) == "event.message":
                    matches.append((category.text(0), child.text(0)))
        self.assertEqual(matches, [("Events", "When Message Heard")])

        node = GraphNode("heard", template)
        self.assertNotIn("message", node.input_ports)
        panel = NodePropertiesPanel()
        panel.set_project_kind("3d")
        panel.set_node(node)
        self.assertIn("exact same name", panel.hint.text())
        editor = panel.editor_for("message")
        self.assertIsInstance(editor, QComboBox)
        self.assertTrue(editor.isEditable())
        self.assertEqual(editor.lineEdit().maxLength(), 64)

        editor.setEditText("player.dashed")
        editor.lineEdit().editingFinished.emit()
        self.assertEqual(node.properties["message"], "player.dashed")
        editor = panel.editor_for("message")
        editor.setEditText("Player Dashed")
        editor.lineEdit().editingFinished.emit()
        self.assertEqual(node.properties["message"], "player.dashed")

        VisualGraph(
            "message_editor",
            (DataGraphNode("heard", "event.message", node.properties),),
        ).validate()

    def test_receiver_message_cannot_be_linked(self) -> None:
        scene = VisualGraphScene()
        scene.load_data(
            {
                "schema": VisualGraph.SCHEMA,
                "id": "message_literal_guard",
                "nodes": [
                    {
                        "id": "name",
                        "type": "value.constant",
                        "position": [0, 0],
                        "properties": {"value": "player.dashed"},
                    },
                    {
                        "id": "heard",
                        "type": "event.message",
                        "position": [240, 0],
                        "properties": {"message": "player.dashed"},
                    },
                ],
                "links": [
                    {
                        "source_node": "name",
                        "source_port": "value",
                        "target_node": "heard",
                        "target_port": "message",
                    }
                ],
            }
        )
        self.assertNotIn("message", scene.nodes["heard"].input_ports)
        self.assertEqual(scene.connections, [])
        self.assertEqual(scene.data()["links"], [])


if __name__ == "__main__":
    unittest.main()
