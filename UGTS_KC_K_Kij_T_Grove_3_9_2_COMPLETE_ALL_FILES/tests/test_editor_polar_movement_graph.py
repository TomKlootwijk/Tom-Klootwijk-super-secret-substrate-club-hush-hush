from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox
from PySide6.QtCore import Qt

from ugts_kc3.editor.graph import GraphNode, NodePropertiesPanel, TEMPLATE_BY_KEY
from ugts_kc3.packed_kinematics import POLAR_MOVEMENT_FIELDS


class EditorPolarMovementGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_3d_beginner_choices_are_semantic_and_hide_packed_words(self) -> None:
        panel = NodePropertiesPanel()
        panel.set_project_kind("3d")
        node = GraphNode(
            "movement",
            TEMPLATE_BY_KEY["action.set_component"],
            {
                "entity": None,
                "component": "polar_movement",
                "field": "radius",
                "value": 3.0,
            },
        )
        panel.set_node(node)

        component = panel.editor_for("component")
        field = panel.editor_for("field")
        self.assertIsInstance(component, QComboBox)
        self.assertIsInstance(field, QComboBox)
        self.assertGreaterEqual(component.findData("polar_movement"), 0)
        self.assertEqual(component.findData("packed_kinematic"), -1)
        self.assertEqual(component.findData("pose_word"), -1)
        self.assertEqual(
            tuple(field.itemData(index) for index in range(field.count())),
            POLAR_MOVEMENT_FIELDS,
        )
        self.assertEqual(field.findData(""), -1)
        self.assertEqual(field.itemText(field.findData("radius")), "Distance from centre")
        turns = field.findData("turns_per_second")
        growth = field.findData("growth_per_second")
        self.assertEqual(field.itemText(turns), "Turns per second")
        self.assertEqual(field.itemText(growth), "Grow / shrink speed")
        self.assertIn(
            "negative",
            field.itemData(turns, Qt.ItemDataRole.ToolTipRole).casefold(),
        )
        self.assertIn(
            "log-radius",
            field.itemData(growth, Qt.ItemDataRole.ToolTipRole).casefold(),
        )
        self.assertIn("quantizes", field.toolTip().casefold())

    def test_dedicated_blocks_hide_component_names_and_raw_words(self) -> None:
        panel = NodePropertiesPanel()
        panel.set_project_kind("3d")
        node = GraphNode(
            "movement",
            TEMPLATE_BY_KEY["action.set_polar_movement"],
            {
                "entity": None,
                "field": "turns_per_second",
                "value": 0.25,
            },
        )
        panel.set_node(node)

        self.assertNotIn("component", node.properties)
        self.assertNotIn("component", node.template.inputs)
        self.assertNotIn("field", node.template.inputs)
        field = panel.editor_for("field")
        entity = panel.editor_for("entity")
        self.assertIsInstance(field, QComboBox)
        self.assertIsInstance(entity, QComboBox)
        self.assertEqual(
            tuple(field.itemData(index) for index in range(field.count())),
            POLAR_MOVEMENT_FIELDS,
        )
        self.assertEqual(entity.itemData(0), None)
        self.assertEqual(entity.itemText(0), "This object")
        self.assertEqual(
            panel.values.topLevelItem(1).text(0),
            "Movement number",
        )
        rendered = " ".join(
            panel.values.topLevelItem(index).text(column)
            for index in range(panel.values.topLevelItemCount())
            for column in (0, 1)
        ).casefold()
        self.assertNotIn("polar_movement", rendered)
        self.assertNotIn("pose_word", rendered)

        reader = TEMPLATE_BY_KEY["value.polar_movement"]
        self.assertNotIn("component", reader.default_properties or {})
        self.assertNotIn("field", reader.inputs)


if __name__ == "__main__":
    unittest.main()
