from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QComboBox

from ugts_kc3.editor.graph import (
    GraphNode,
    NodePropertiesPanel,
    TEMPLATE_BY_KEY,
)
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.visual_graph import GraphNode as DataGraphNode, VisualGraph


class ContextualGraphPropertyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_comparison_and_boolean_choices_keep_canonical_typed_values(self) -> None:
        panel = NodePropertiesPanel()
        panel.set_project_kind("2d")
        compare = GraphNode("comparison", TEMPLATE_BY_KEY["compare"])
        panel.set_node(compare)

        operator = panel.editor_for("operator")
        self.assertIsInstance(operator, QComboBox)
        self.assertFalse(operator.isEditable())
        self.assertEqual(
            [operator.itemData(index) for index in range(operator.count())],
            ["equal", "not_equal", "less", "less_equal", "greater", "greater_equal"],
        )
        operator.setCurrentText("invalid_comparison")
        self.assertEqual(compare.properties["operator"], "equal")
        operator.setCurrentIndex(operator.findData("greater_equal"))
        self.assertEqual(compare.properties["operator"], "greater_equal")
        VisualGraph("choice", (DataGraphNode("comparison", "compare", compare.properties),)).validate()

        active = GraphNode("active", TEMPLATE_BY_KEY["action.set_active"])
        panel.set_node(active)
        enabled = panel.editor_for("active")
        self.assertIsInstance(enabled, QComboBox)
        self.assertEqual(
            [enabled.itemData(index) for index in range(enabled.count())],
            [True, False],
        )
        enabled.setCurrentIndex(enabled.findData(False))
        self.assertIs(active.properties["active"], False)
        enabled.setCurrentText("Maybe")
        self.assertIs(active.properties["active"], False)

    def test_actions_and_component_fields_follow_project_context(self) -> None:
        panel = NodePropertiesPanel()
        panel.set_project_kind("3d")
        pressed = GraphNode(
            "pressed", TEMPLATE_BY_KEY["event.input_pressed"], {"action": "dash"}
        )
        panel.set_node(pressed)
        action = panel.editor_for("action")
        self.assertIsInstance(action, QComboBox)
        self.assertGreaterEqual(action.findData("jump"), 0)
        self.assertEqual(action.findData("pause"), -1)
        action.setCurrentText("made_up_button")
        self.assertEqual(pressed.properties["action"], "dash")

        custom_pressed = GraphNode(
            "custom", TEMPLATE_BY_KEY["event.input_pressed"], {"action": "special_spell"}
        )
        panel.set_node(custom_pressed)
        custom_action = panel.editor_for("action")
        self.assertIsInstance(custom_action, QComboBox)
        self.assertGreaterEqual(custom_action.findData("special_spell"), 0)
        self.assertEqual(custom_pressed.properties["action"], "special_spell")

        component = GraphNode(
            "component",
            TEMPLATE_BY_KEY["action.set_component"],
            {"component": "transform", "field": "translation", "value": [0, 0, 0]},
        )
        panel.set_node(component)
        component_editor = panel.editor_for("component")
        field_editor = panel.editor_for("field")
        self.assertIsInstance(component_editor, QComboBox)
        self.assertIsInstance(field_editor, QComboBox)
        self.assertGreaterEqual(field_editor.findData("translation"), 0)
        self.assertEqual(component_editor.findData("health"), -1)

        component_editor.setCurrentIndex(component_editor.findData("body"))
        self.assertEqual(component.properties["component"], "body")
        self.assertEqual(component.properties["field"], "velocity")
        body_field = panel.editor_for("field")
        self.assertIsInstance(body_field, QComboBox)
        body_field.setCurrentText("not_a_body_field")
        self.assertEqual(component.properties["field"], "velocity")

        custom_component = GraphNode(
            "custom_component",
            TEMPLATE_BY_KEY["value.component"],
            {"component": "quest_stats", "field": "mana", "default": None, "entity": None},
        )
        panel.set_node(custom_component)
        custom_component_editor = panel.editor_for("component")
        self.assertIsInstance(custom_component_editor, QComboBox)
        self.assertGreaterEqual(custom_component_editor.findData("quest_stats"), 0)
        self.assertIsNone(panel.editor_for("field"))
        self.assertEqual(custom_component.properties["field"], "mana")

    def test_message_names_allow_nonempty_custom_text_but_state_keys_stay_open(self) -> None:
        panel = NodePropertiesPanel()
        panel.set_project_kind("2d")
        message = GraphNode(
            "message", TEMPLATE_BY_KEY["action.emit_event"], {"kind": "spell_cast"}
        )
        panel.set_node(message)
        event_kind = panel.editor_for("kind")
        self.assertIsInstance(event_kind, QComboBox)
        self.assertTrue(event_kind.isEditable())
        self.assertGreaterEqual(event_kind.findData("spell_cast"), 0)
        event_kind.lineEdit().editingFinished.emit()
        self.assertEqual(message.properties["kind"], "spell_cast")

        event_kind.setEditText("boss_awake")
        event_kind.lineEdit().editingFinished.emit()
        self.assertEqual(message.properties["kind"], "boss_awake")
        event_kind = panel.editor_for("kind")
        event_kind.setEditText("   ")
        event_kind.lineEdit().editingFinished.emit()
        self.assertEqual(message.properties["kind"], "boss_awake")

        state = GraphNode(
            "state", TEMPLATE_BY_KEY["value.state"], {"key": "my_custom_score", "default": 0}
        )
        panel.set_node(state)
        self.assertIsNone(panel.editor_for("key"))
        self.assertEqual(state.properties["key"], "my_custom_score")

    def test_editor_combo_change_survives_graph_undo_redo_reload(self) -> None:
        window = EditorMainWindow()
        try:
            window.new_2d_project()
            window.graph_page.add_template("compare")
            self.app.processEvents()
            selected = window.graph_page.properties.node
            self.assertIsNotNone(selected)
            self.assertEqual(selected.template.key, "compare")
            node_id = selected.node_id
            operator = window.graph_page.properties.editor_for("operator")
            self.assertIsInstance(operator, QComboBox)

            operator.setCurrentIndex(operator.findData("greater"))
            self.app.processEvents()
            self.assertEqual(
                window.graph_page.graph_scene.nodes[node_id].properties["operator"],
                "greater",
            )
            self.assertTrue(window.document.validate().passed)

            window.undo_stack.undo()
            self.app.processEvents()
            self.assertEqual(
                window.graph_page.graph_scene.nodes[node_id].properties["operator"],
                "equal",
            )
            window.undo_stack.redo()
            self.app.processEvents()
            self.assertEqual(
                window.graph_page.graph_scene.nodes[node_id].properties["operator"],
                "greater",
            )
            self.assertEqual(window.graph_page.properties.node.node_id, node_id)
            reloaded = window.graph_page.properties.editor_for("operator")
            self.assertIsInstance(reloaded, QComboBox)
            self.assertEqual(reloaded.currentData(), "greater")
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_push_block_is_available_in_mobile_3d_palette(self) -> None:
        window = EditorMainWindow()
        try:
            window.new_3d_project()
            found = None
            tree = window.graph_page.palette.tree
            for category_index in range(tree.topLevelItemCount()):
                category = tree.topLevelItem(category_index)
                for child_index in range(category.childCount()):
                    child = category.child(child_index)
                    if child.data(0, Qt.ItemDataRole.UserRole) == "action.apply_force":
                        found = child
                        self.assertFalse(category.isHidden())
                        self.assertFalse(child.isHidden())
            self.assertIsNotNone(found)
            window.graph_page.add_template("action.apply_force")
            self.app.processEvents()
            self.assertTrue(
                any(
                    node.template.key == "action.apply_force"
                    for node in window.graph_page.graph_scene.nodes.values()
                )
            )
            self.assertTrue(window.document.validate().passed)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
