from __future__ import annotations

import json
import os
import struct
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

from ugts_kc3.editor.graph import (
    GraphNode,
    NodePalette,
    NodePropertiesPanel,
    TEMPLATE_BY_KEY,
)
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.visual_graph import GraphNode as DataGraphNode, VisualGraph


def _f32_bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _document_bytes(window: EditorMainWindow) -> bytes:
    return json.dumps(
        window.document.serialize(),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


class NearestInConeEditorAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_child_facing_template_and_exact_composite_presets(self) -> None:
        template = TEMPLATE_BY_KEY["query.nearest_in_cone"]
        self.assertEqual(template.title, "Find Object Ahead")
        self.assertEqual(template.category, "Sensing")
        self.assertEqual(template.color, "#64d8cb")
        self.assertEqual(template.inputs, ("origin", "tag", "radius", "cone"))
        self.assertEqual(template.outputs, ("found", "entity", "distance"))

        palette = NodePalette()
        matches = []
        for category_index in range(palette.tree.topLevelItemCount()):
            category = palette.tree.topLevelItem(category_index)
            for child_index in range(category.childCount()):
                child = category.child(child_index)
                if child.data(0, Qt.ItemDataRole.UserRole) == "query.nearest_in_cone":
                    matches.append((category.text(0), child.text(0)))
        self.assertEqual(matches, [("Sensing", "Find Object Ahead")])

        node = GraphNode("ahead", template)
        panel = NodePropertiesPanel()
        panel.set_project_kind("3d")
        panel.set_entity_context(None, (("player", "Player"), ("goal", "Goal")))
        panel.set_node(node)
        self.assertIn("Facing and View width", panel.hint.text())
        self.assertEqual(
            [panel.values.topLevelItem(index).text(0) for index in range(4)],
            ["Search from", "Object kind", "Search distance", "Facing + view"],
        )
        origin = panel.editor_for("origin")
        tag = panel.editor_for("tag")
        self.assertIsInstance(origin, QComboBox)
        self.assertIsInstance(tag, QComboBox)
        self.assertEqual(
            [tag.itemData(index) for index in range(tag.count())],
            ["player", "collectible", "goal", "decorative", "hazard"],
        )

        cone = panel.editor_for("cone")
        direction = cone.findChild(QComboBox, "GraphProperty_cone_direction")
        width = cone.findChild(QComboBox, "GraphProperty_cone_width")
        self.assertIsNotNone(direction)
        self.assertIsNotNone(width)
        self.assertEqual(direction.currentData(), [0.0, 0.0, -1.0])
        self.assertEqual(_f32_bits(width.currentData()), 0x3F3504F3)

        width.setCurrentIndex(width.findData(0.8660253882408142))
        cone = panel.editor_for("cone")
        direction = cone.findChild(QComboBox, "GraphProperty_cone_direction")
        direction.setCurrentIndex(direction.findData([1.0, 0.0, 0.0]))
        self.assertEqual(node.properties["cone"][:3], [1.0, 0.0, 0.0])
        self.assertEqual(_f32_bits(node.properties["cone"][3]), 0x3F5DB3D7)
        VisualGraph(
            "editor_cone",
            (DataGraphNode("ahead", "query.nearest_in_cone", node.properties),),
        ).validate()

    def test_contextual_defaults_and_undo_redo_are_byte_exact(self) -> None:
        window = EditorMainWindow()
        try:
            window.new_2d_project()
            window.graph_page.add_template("query.nearest_in_cone")
            self.app.processEvents()
            node = window.graph_page.properties.node
            self.assertIsNotNone(node)
            self.assertEqual(node.properties["cone"], [1.0, 0.0, 0.0, 0.7071067690849304])
            node_id = node.node_id
            before = _document_bytes(window)
            window.undo_stack.clear()

            cone = window.graph_page.properties.editor_for("cone")
            direction = cone.findChild(QComboBox, "GraphProperty_cone_direction")
            direction.setCurrentIndex(direction.findData([0.0, 1.0, 0.0]))
            self.app.processEvents()
            after = _document_bytes(window)
            self.assertNotEqual(after, before)
            self.assertEqual(
                window.graph_page.graph_scene.nodes[node_id].properties["cone"],
                [0.0, 1.0, 0.0, 0.7071067690849304],
            )
            window.undo_stack.undo()
            self.app.processEvents()
            self.assertEqual(_document_bytes(window), before)
            window.undo_stack.redo()
            self.app.processEvents()
            self.assertEqual(_document_bytes(window), after)

            window.document.set_dirty(False)
            window.new_3d_project()
            window.graph_page.add_template("query.nearest_in_cone")
            self.app.processEvents()
            self.assertEqual(
                window.graph_page.properties.node.properties["cone"],
                [0.0, 0.0, -1.0, 0.7071067690849304],
            )
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
