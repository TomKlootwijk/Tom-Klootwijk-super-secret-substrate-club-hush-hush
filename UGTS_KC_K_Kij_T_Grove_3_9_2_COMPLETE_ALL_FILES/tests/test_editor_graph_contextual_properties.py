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
    VisualGraphScene,
)
from ugts_kc3.editor.document import SelectionRef
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

    def test_repeatable_random_number_template_roundtrips_all_settings(self) -> None:
        template = TEMPLATE_BY_KEY["value.seeded_number"]
        self.assertEqual(template.title, "Repeatable Random Number")
        self.assertEqual(template.category, "Values")
        self.assertEqual(
            dict(template.default_properties),
            {"world_number": 1, "pick_number": 0, "smallest": 0.0, "largest": 1.0},
        )
        scene = VisualGraphScene()
        scene.load_data(
            {
                "schema": VisualGraph.SCHEMA,
                "id": "repeatable_editor",
                "nodes": [
                    {
                        "id": "number",
                        "type": "value.seeded_number",
                        "position": [12, 34],
                        "properties": {
                            "world_number": 392,
                            "pick_number": 7,
                            "smallest": -10.0,
                            "largest": 10.0,
                        },
                    }
                ],
                "links": [],
            }
        )
        saved = scene.data()
        restored = VisualGraph.from_dict(saved)
        self.assertEqual(restored.nodes[0].type, "value.seeded_number")
        self.assertEqual(
            dict(restored.nodes[0].properties),
            {"world_number": 392, "pick_number": 7, "smallest": -10.0, "largest": 10.0},
        )

    def test_find_nearby_object_has_child_safe_sensing_choices(self) -> None:
        template = TEMPLATE_BY_KEY["query.nearest_tag"]
        self.assertEqual(template.title, "Find Nearby Object")
        self.assertEqual(template.category, "Sensing")
        panel = NodePropertiesPanel()
        panel.set_project_kind("3d")
        nearby = GraphNode("nearby", template)
        panel.set_node(nearby)

        origin = panel.editor_for("origin")
        tag = panel.editor_for("tag")
        self.assertIsInstance(origin, QComboBox)
        self.assertTrue(origin.isEditable())
        self.assertIsNone(origin.itemData(0))
        self.assertEqual(origin.itemText(0), "This object")
        self.assertIsInstance(tag, QComboBox)
        self.assertFalse(tag.isEditable())
        self.assertEqual(
            [tag.itemData(index) for index in range(tag.count())],
            ["player", "collectible", "goal", "decorative", "hazard"],
        )

        tag.setCurrentIndex(tag.findData("hazard"))
        self.assertEqual(nearby.properties["tag"], "hazard")
        origin.setEditText("player")
        origin.lineEdit().editingFinished.emit()
        self.assertEqual(nearby.properties["origin"], "player")
        origin = panel.editor_for("origin")
        origin.setEditText("")
        origin.lineEdit().editingFinished.emit()
        self.assertIsNone(nearby.properties["origin"])
        self.assertIsNone(panel.editor_for("radius"))

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

        sender_choices = {
            event_kind.itemData(index) for index in range(event_kind.count())
        }
        self.assertIn("collision_enter", sender_choices)

        receiver = GraphNode(
            "receiver",
            TEMPLATE_BY_KEY["event.message"],
            {"message": "player.dashed"},
        )
        panel.set_node(receiver)
        received_message = panel.editor_for("message")
        self.assertIsInstance(received_message, QComboBox)
        receiver_choices = {
            received_message.itemData(index)
            for index in range(received_message.count())
        }
        self.assertEqual(receiver_choices, {"graph_event", "player.dashed"})
        self.assertNotIn("collision_enter", receiver_choices)

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

    def test_animation_blocks_use_contextual_editable_object_and_clip_choices(self) -> None:
        panel = NodePropertiesPanel()
        panel.set_project_kind("3d")
        panel.set_entity_context("floor", (("floor", "Floor"), ("cone", "Cone")))
        panel.set_animation_context((("main", "Main"), ("wave", "Wave")))
        play = GraphNode(
            "play",
            TEMPLATE_BY_KEY["action.play_animation"],
            {"entity": None, "clip": "wave", "restart": True},
        )
        panel.set_node(play)

        entity = panel.editor_for("entity")
        clip = panel.editor_for("clip")
        restart = panel.editor_for("restart")
        self.assertIsInstance(entity, QComboBox)
        self.assertIsInstance(clip, QComboBox)
        self.assertIsInstance(restart, QComboBox)
        self.assertTrue(entity.isEditable())
        self.assertTrue(clip.isEditable())
        self.assertEqual(entity.itemData(0), None)
        self.assertGreaterEqual(entity.findData("cone"), 0)
        self.assertEqual(
            [clip.itemData(index) for index in range(clip.count())],
            ["main", "wave"],
        )
        clip.setEditText("other_object_clip")
        clip.lineEdit().editingFinished.emit()
        self.assertEqual(play.properties["clip"], "other_object_clip")

        stop = GraphNode(
            "stop",
            TEMPLATE_BY_KEY["action.stop_animation"],
            {"entity": None, "reset": True},
        )
        panel.set_node(stop)
        self.assertIsInstance(panel.editor_for("entity"), QComboBox)
        self.assertIsInstance(panel.editor_for("reset"), QComboBox)

    def test_animation_blocks_are_visible_only_in_the_3d_palette(self) -> None:
        def hidden(window: EditorMainWindow, key: str) -> bool:
            tree = window.graph_page.palette.tree
            for category_index in range(tree.topLevelItemCount()):
                category = tree.topLevelItem(category_index)
                for child_index in range(category.childCount()):
                    child = category.child(child_index)
                    if child.data(0, Qt.ItemDataRole.UserRole) == key:
                        return child.isHidden()
            self.fail(f"missing palette block {key}")

        window = EditorMainWindow()
        try:
            window.new_2d_project()
            self.assertTrue(hidden(window, "action.play_animation"))
            self.assertTrue(hidden(window, "action.stop_animation"))
            window.document.set_dirty(False)
            window.new_3d_project()
            self.assertFalse(hidden(window, "action.play_animation"))
            self.assertFalse(hidden(window, "action.stop_animation"))
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_world_sensing_uses_explicit_scene_object_picker_and_safe_default(self) -> None:
        window = EditorMainWindow()
        try:
            window.new_3d_project()
            window.document.set_selection(
                SelectionRef("world_graph", "find_goal_lesson")
            )
            self.app.processEvents()
            nearby = next(
                node
                for node in window.graph_page.graph_scene.nodes.values()
                if node.template.key == "query.nearest_tag"
            )
            window.graph_page.graph_scene.clearSelection()
            nearby.setSelected(True)
            self.app.processEvents()
            origin = window.graph_page.properties.editor_for("origin")
            self.assertIsInstance(origin, QComboBox)
            self.assertEqual(origin.findData(None), -1)
            self.assertGreaterEqual(origin.findData("player"), 0)
            self.assertEqual(origin.currentData(), "player")

            existing = set(window.graph_page.graph_scene.nodes)
            window.graph_page.add_template("query.nearest_tag")
            self.app.processEvents()
            added = next(
                node
                for node_id, node in window.graph_page.graph_scene.nodes.items()
                if node_id not in existing
            )
            self.assertEqual(added.properties["origin"], "player")
            self.assertTrue(window.document.validate().passed)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
