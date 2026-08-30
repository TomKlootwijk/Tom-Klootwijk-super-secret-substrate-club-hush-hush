from __future__ import annotations

import copy
from dataclasses import replace
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from ugts_kc3.editor.document import EditorDocument, SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.saved_scene import materialize_saved_scenes
from ugts_kc3.templates3d import first_steps_mobile3d_project


def _plain_group_project() -> Mobile3DProject:
    project = first_steps_mobile3d_project()
    project.nodes = tuple(
        replace(node, metadata={}, angular_velocity=(0.0, 0.0, 0.0))
        if node.id in {"goal", "crystal_garden"}
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _tree_items(tree) -> tuple[object, ...]:
    items: list[object] = []
    iterator = QTreeWidgetItemIterator(tree)
    while iterator.value():
        items.append(iterator.value())
        iterator += 1
    return tuple(items)


def _selection_item(tree, selection: SelectionRef):
    return next(
        item
        for item in _tree_items(tree)
        if item.data(0, Qt.ItemDataRole.UserRole) == selection
    )


class SavedSceneDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = _plain_group_project()
        self.document = EditorDocument()
        self.document.create(self.project)
        self.document.set_selection(SelectionRef("node", "goal"))

    def test_definition_place_transform_and_bake_stay_compact_until_unlink(self) -> None:
        authored_before = copy.deepcopy(self.project.nodes)
        metadata, definition = self.document.saved_scene_metadata_snapshot(
            "Goal Gate",
            ("crystal_garden", "goal"),
            root_id="goal",
        )

        self.assertEqual(definition.id, "goal_gate")
        self.assertEqual(definition.root_id, "goal")
        self.assertEqual(
            [value.node.id for value in definition.nodes],
            ["goal", "crystal_garden"],
        )
        root = next(value for value in definition.nodes if value.node.id == "goal")
        child = next(
            value for value in definition.nodes if value.node.id == "crystal_garden"
        )
        self.assertIsNone(root.parent_id)
        self.assertEqual(child.parent_id, "goal")
        self.assertEqual(root.node.transform.translation, (0.0, 0.0, 0.0))
        self.assertEqual(self.project.nodes, authored_before)

        self.document.replace_saved_scenes(
            self.project.nodes,
            metadata,
            self.document.selection,
        )
        placed_metadata, instance = self.document.instantiate_saved_scene_snapshot(
            definition.id
        )
        self.document.replace_saved_scenes(
            self.project.nodes,
            placed_metadata,
            SelectionRef("saved_scene_instance", instance.id),
        )
        self.assertEqual(self.project.nodes, authored_before)
        self.assertEqual(len(self.document.saved_scene_instances()), 1)

        materialized = materialize_saved_scenes(self.project)
        materialized_ids = {node.id for node in materialized.nodes}
        self.assertIn(instance.id, materialized_ids)
        self.assertIn(f"{instance.id}__crystal_garden", materialized_ids)
        self.assertEqual(len(materialized.nodes), len(authored_before) + 2)

        before_transform = self.document.transform()
        assert before_transform is not None
        moved_transform = dict(before_transform)
        moved_transform["translation"] = (12.0, 2.0, -4.0)
        self.document.set_transform(self.document.selection, moved_transform)  # type: ignore[arg-type]
        self.assertEqual(
            self.document.saved_scene_instances()[0].transform.translation,
            (12.0, 2.0, -4.0),
        )

        baked_nodes, baked_metadata, baked_instance = (
            self.document.bake_saved_scene_instance_snapshot(instance.id)
        )
        self.assertEqual(baked_instance.id, instance.id)
        self.document.replace_saved_scenes(
            baked_nodes,
            baked_metadata,
            SelectionRef("node", instance.id),
        )
        self.assertEqual(self.document.saved_scene_instances(), ())
        self.assertEqual(len(self.project.nodes), len(authored_before) + 2)
        self.assertEqual(len(self.document.saved_scenes()), 1)
        self.assertIsNotNone(self.document.entity())

    def test_save_requires_two_unique_authored_nodes(self) -> None:
        with self.assertRaisesRegex(ValueError, "at least two"):
            self.document.saved_scene_metadata_snapshot(
                "Too Small", ("floor",), root_id="floor"
            )
        with self.assertRaisesRegex(ValueError, "no longer"):
            self.document.saved_scene_metadata_snapshot(
                "Missing", ("goal", "not_here"), root_id="goal"
            )


class SavedSceneEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.document.create(_plain_group_project())
        self.window.undo_stack.clear()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def _select_goal_and_crystal(self) -> None:
        tree = self.window.hierarchy.tree
        goal = _selection_item(tree, SelectionRef("node", "goal"))
        crystal = _selection_item(tree, SelectionRef("node", "crystal_garden"))
        tree.clearSelection()
        tree.setCurrentItem(goal)
        goal.setSelected(True)
        crystal.setSelected(True)
        self.app.processEvents()

    def _save_group(self) -> None:
        self._select_goal_and_crystal()
        self.assertEqual(
            self.window.hierarchy.selected_node_ids(), ("goal", "crystal_garden")
        )
        self.assertTrue(self.window.hierarchy.save_scene_button.isEnabled())
        with patch(
            "ugts_kc3.editor.main_window.QInputDialog.getText",
            return_value=("Goal Gate", True),
        ):
            self.window.hierarchy.save_scene_button.click()
        self.app.processEvents()

    def _place_group(self) -> str:
        with patch(
            "ugts_kc3.editor.main_window.QInputDialog.getItem",
            return_value=("Goal Gate", True),
        ):
            self.window.hierarchy.add_saved_scene_button.click()
        self.app.processEvents()
        selection = self.window.document.selection
        assert selection is not None
        self.assertEqual(selection.kind, "saved_scene_instance")
        return selection.object_id

    def test_save_place_preview_and_unlink_are_atomic_and_child_friendly(self) -> None:
        authored_count = len(self.window.document.project.nodes)
        self._save_group()

        self.assertEqual(self.window.undo_stack.count(), 1)
        self.assertEqual(len(self.window.document.saved_scenes()), 1)
        self.assertEqual(len(self.window.document.project.nodes), authored_count)
        self.assertTrue(self.window.hierarchy.add_saved_scene_button.isEnabled())
        resources = {(item.text(0), item.text(1)) for item in _tree_items(self.window.assets_project.assets)}
        self.assertIn(("Saved Scenes", "1"), resources)
        self.assertIn(("Goal Gate", "0 linked · 2 objects"), resources)

        instance_id = self._place_group()
        self.assertEqual(self.window.undo_stack.count(), 2)
        self.assertEqual(len(self.window.document.project.nodes), authored_count)
        self.assertEqual(len(self.window.document.saved_scene_instances()), 1)
        linked_root = next(
            item
            for item in _tree_items(self.window.hierarchy.tree)
            if item.text(1) == "Linked Saved Scene"
        )
        self.assertEqual(linked_root.text(0), "Goal Gate")
        self.assertEqual(linked_root.childCount(), 2)
        self.assertTrue(
            all(
                linked_root.child(index).text(1) == "Linked Child"
                for index in range(linked_root.childCount())
            )
        )
        group_selection = SelectionRef("saved_scene_instance", instance_id)
        self.assertTrue(
            all(
                linked_root.child(index).data(0, Qt.ItemDataRole.UserRole)
                == group_selection
                for index in range(linked_root.childCount())
            )
        )

        preview_ids = set(self.window.viewport._mesh_items)
        self.assertIn(instance_id, preview_ids)
        self.assertIn(f"{instance_id}__crystal_garden", preview_ids)
        self.assertEqual(
            self.window.viewport._mesh_items[
                f"{instance_id}__crystal_garden"
            ].data(0),
            instance_id,
        )
        self.window.document.set_selection(None)
        self.window.viewport.scene().clearSelection()
        self.window.viewport._mesh_items[
            f"{instance_id}__crystal_garden"
        ].setSelected(True)
        self.app.processEvents()
        self.assertEqual(self.window.document.selection, group_selection)
        self.assertTrue(self.window.hierarchy.unlink_saved_scene_button.isEnabled())

        self.window.hierarchy.unlink_saved_scene_button.click()
        self.app.processEvents()
        self.assertEqual(self.window.undo_stack.count(), 3)
        self.assertEqual(self.window.document.saved_scene_instances(), ())
        self.assertEqual(len(self.window.document.project.nodes), authored_count + 2)
        self.assertEqual(
            self.window.document.selection, SelectionRef("node", instance_id)
        )

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(len(self.window.document.project.nodes), authored_count)
        self.assertEqual(len(self.window.document.saved_scene_instances()), 1)
        self.assertEqual(self.window.document.selection, group_selection)
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(self.window.document.saved_scene_instances(), ())
        self.assertEqual(len(self.window.document.project.nodes), authored_count + 2)

    def test_saved_scene_controls_are_contextual_and_3d_only(self) -> None:
        hierarchy = self.window.hierarchy
        self.assertTrue(hierarchy.save_scene_button.isHidden())
        self.assertTrue(hierarchy.add_saved_scene_button.isHidden())
        self.assertTrue(hierarchy.unlink_saved_scene_button.isHidden())

        self._select_goal_and_crystal()
        self.assertFalse(hierarchy.save_scene_button.isHidden())
        self.assertTrue(hierarchy.add_saved_scene_button.isHidden())
        self.assertTrue(hierarchy.unlink_saved_scene_button.isHidden())
        self.assertTrue(hierarchy.duplicate_button.isHidden())
        self.assertTrue(hierarchy.delete_button.isHidden())
        self.assertTrue(hierarchy.save_reusable_button.isHidden())

        self._save_group()
        self.assertFalse(hierarchy.add_saved_scene_button.isHidden())
        self.assertTrue(hierarchy.unlink_saved_scene_button.isHidden())

        instance_id = self._place_group()
        self.assertFalse(hierarchy.add_saved_scene_button.isHidden())
        self.assertFalse(hierarchy.unlink_saved_scene_button.isHidden())
        self.assertTrue(hierarchy.save_scene_button.isHidden())
        self.assertTrue(hierarchy.duplicate_button.isHidden())
        self.assertTrue(hierarchy.delete_button.isHidden())
        self.assertTrue(hierarchy.save_reusable_button.isHidden())
        self.assertEqual(
            self.window.document.selection,
            SelectionRef("saved_scene_instance", instance_id),
        )

        tree = hierarchy.tree
        goal = _selection_item(tree, SelectionRef("node", "goal"))
        crystal = _selection_item(tree, SelectionRef("node", "crystal_garden"))
        linked = _selection_item(
            tree, SelectionRef("saved_scene_instance", instance_id)
        )
        tree.clearSelection()
        tree.setCurrentItem(goal)
        goal.setSelected(True)
        crystal.setSelected(True)
        linked.setSelected(True)
        self.app.processEvents()
        self.assertTrue(hierarchy.save_scene_button.isHidden())

        tree.clearSelection()
        tree.setCurrentItem(linked)
        linked.setSelected(True)
        self.app.processEvents()
        self.assertFalse(hierarchy.unlink_saved_scene_button.isHidden())

        hierarchy.set_authoring_enabled(False)
        self.assertFalse(hierarchy.add_button.isHidden())
        self.assertTrue(hierarchy.add_saved_scene_button.isHidden())
        self.assertTrue(hierarchy.unlink_saved_scene_button.isHidden())
        hierarchy.set_authoring_enabled(True)
        self.assertFalse(hierarchy.unlink_saved_scene_button.isHidden())

        self.window.document.set_dirty(False)
        self.window.new_2d_project()
        self.app.processEvents()
        self.assertTrue(self.window.hierarchy.save_scene_button.isHidden())
        self.assertTrue(self.window.hierarchy.add_saved_scene_button.isHidden())
        self.assertTrue(self.window.hierarchy.unlink_saved_scene_button.isHidden())


if __name__ == "__main__":
    unittest.main()
