from __future__ import annotations

from dataclasses import replace
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMenu, QTreeWidgetItem, QTreeWidgetItemIterator

from ugts_kc3.editor.document import SelectionRef, euler_degrees_to_quaternion
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.hierarchy3d import world_trs_by_id
from ugts_kc3.mobile3d import Node3DRecord, Transform3DRecord
from ugts_kc3.saved_scene import (
    instantiate_saved_scene,
    make_saved_scene,
    metadata_with_saved_scene_instances,
    metadata_with_saved_scenes,
)


def _tree_items(tree) -> list[QTreeWidgetItem]:
    result: list[QTreeWidgetItem] = []
    iterator = QTreeWidgetItemIterator(tree)
    while iterator.value():
        result.append(iterator.value())
        iterator += 1
    return result


def _selection_item(window: EditorMainWindow, object_id: str) -> QTreeWidgetItem:
    selection = SelectionRef("node", object_id)
    return next(
        item
        for item in _tree_items(window.hierarchy.tree)
        if item.data(0, Qt.ItemDataRole.UserRole) == selection
    )


def _assert_trs_close(
    case: unittest.TestCase, left: object, right: object, places: int = 7
) -> None:
    for field in ("translation", "rotation", "scale"):
        before = tuple(getattr(left, field))
        after = tuple(getattr(right, field))
        case.assertEqual(len(before), len(after))
        for first, second in zip(before, after):
            case.assertAlmostEqual(first, second, places=places)


class EditorNodeHierarchyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.new_3d_project()
        self.project = self.window.document.project

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def _node(
        self,
        node_id: str,
        translation=(0.0, 0.0, 0.0),
        *,
        rotation=(1.0, 0.0, 0.0, 0.0),
        scale=(1.0, 1.0, 1.0),
        parent_id: str | None = None,
    ) -> Node3DRecord:
        return Node3DRecord(
            node_id,
            "cube",
            "accent",
            Transform3DRecord(translation, rotation, scale),
            parent_id=parent_id,
        )

    def _set_nodes(self, *nodes: Node3DRecord) -> None:
        self.project.nodes = tuple(nodes)
        self.project.validate()
        self.window.document.set_selection(None)
        self.window.hierarchy.set_document(self.window.document)
        self.window.viewport.refresh(keep_view=False)
        self.app.processEvents()

    def test_context_attach_nests_tree_preserves_world_pose_and_undoes(self) -> None:
        parent = self._node(
            "parent",
            (4.0, 1.0, -2.0),
            rotation=euler_degrees_to_quaternion((0.0, 35.0, 0.0)),
            scale=(2.0, 2.0, 2.0),
        )
        child = self._node("child", (1.0, 3.0, 5.0), scale=(0.5, 0.5, 0.5))
        self._set_nodes(parent, child)
        before_world = world_trs_by_id(self.project.nodes)["child"]

        child_item = _selection_item(self.window, "child")
        menu = self.window.hierarchy.node_context_menu(child_item)
        attach_menu = next(
            action.menu()
            for action in menu.actions()
            if action.text() == "Attach to…"
        )
        self.assertIsInstance(attach_menu, QMenu)
        attach_action = next(
            action for action in attach_menu.actions() if action.data() == "parent"
        )
        self.assertTrue(attach_action.isEnabled())
        attach_action.trigger()
        self.app.processEvents()

        attached = next(node for node in self.project.nodes if node.id == "child")
        self.assertEqual(attached.parent_id, "parent")
        self.assertNotEqual(attached.transform.translation, child.transform.translation)
        _assert_trs_close(
            self, before_world, world_trs_by_id(self.project.nodes)["child"]
        )
        child_item = _selection_item(self.window, "child")
        self.assertEqual(
            child_item.parent().data(0, Qt.ItemDataRole.UserRole),
            SelectionRef("node", "parent"),
        )
        self.assertIn("attached to Parent", self.window.inspector.subtitle.text())
        self.assertEqual(self.window.undo_stack.count(), 1)

        attached_menu = self.window.hierarchy.node_context_menu(child_item)
        self.assertIn("Detach", [action.text() for action in attached_menu.actions()])
        self.window.undo_stack.undo()
        self.app.processEvents()
        restored = next(node for node in self.project.nodes if node.id == "child")
        self.assertIsNone(restored.parent_id)
        self.assertEqual(restored.transform, child.transform)
        self.window.undo_stack.redo()
        _assert_trs_close(
            self, before_world, world_trs_by_id(self.project.nodes)["child"]
        )

    def test_context_disables_cycle_and_unsafe_child_choices_with_explanations(self) -> None:
        root = self._node("root")
        child = self._node("child", (1.0, 0.0, 0.0), parent_id="root")
        unsafe = replace(self._node("unsafe"), tags=("gameplay",))
        linked_owned = replace(
            self._node("linked_owned"),
            metadata={
                "saved_scene_runtime": {"instance_root_id": "linked_group"}
            },
        )
        self._set_nodes(root, child, unsafe, linked_owned)

        root_menu = self.window.hierarchy.node_context_menu(
            _selection_item(self.window, "root")
        )
        attach_menu = root_menu.actions()[0].menu()
        child_action = next(
            action for action in attach_menu.actions() if action.data() == "child"
        )
        self.assertFalse(child_action.isEnabled())
        self.assertIn("loop", child_action.text())
        self.assertIn("own parents", child_action.toolTip())

        unsafe_menu = self.window.hierarchy.node_context_menu(
            _selection_item(self.window, "unsafe")
        )
        unsafe_attach = unsafe_menu.actions()[0].menu()
        self.assertTrue(
            all(
                not action.isEnabled()
                for action in unsafe_attach.actions()
                if action.data() in {"root", "child"}
            )
        )
        self.assertTrue(
            any("No safe parent yet" in action.text() for action in unsafe_attach.actions())
        )
        with self.assertRaisesRegex(ValueError, "gameplay tag"):
            self.window.document.reparent_node_snapshot("unsafe", "root")
        with self.assertRaisesRegex(ValueError, "linked Saved Scene"):
            self.window.document.reparent_node_snapshot("linked_owned", "root")

    def test_too_deep_attachment_is_disabled_with_child_readable_reason(self) -> None:
        chain = tuple(
            self._node(
                f"level_{index}",
                parent_id=None if index == 0 else f"level_{index - 1}",
            )
            for index in range(8)
        )
        branch = self._node("branch")
        leaf = self._node("leaf", parent_id="branch")
        self._set_nodes(*chain, branch, leaf)

        with self.assertRaisesRegex(ValueError, "too deep"):
            self.window.document.reparent_node_snapshot("branch", "level_7")
        menu = self.window.hierarchy.node_context_menu(
            _selection_item(self.window, "branch")
        )
        attach_menu = menu.actions()[0].menu()
        too_deep = next(
            action for action in attach_menu.actions() if action.data() == "level_7"
        )
        self.assertFalse(too_deep.isEnabled())
        self.assertIn("too deep", too_deep.text())
        self.assertIn("8 levels", too_deep.toolTip())

    def test_delete_parent_promotes_children_in_place_and_undo_restores_branch(self) -> None:
        grandparent = self._node(
            "grandparent", (2.0, 0.0, -1.0), scale=(2.0, 2.0, 2.0)
        )
        parent = self._node("parent", (1.0, 1.0, 0.0), parent_id="grandparent")
        child = self._node("child", (0.0, 2.0, 1.0), parent_id="parent")
        self._set_nodes(grandparent, parent, child)
        child_world = world_trs_by_id(self.project.nodes)["child"]
        self.window.document.set_selection(SelectionRef("node", "parent"))

        self.window._delete_scene_object()
        self.app.processEvents()
        self.assertNotIn("parent", {node.id for node in self.project.nodes})
        promoted = next(node for node in self.project.nodes if node.id == "child")
        self.assertEqual(promoted.parent_id, "grandparent")
        _assert_trs_close(
            self, child_world, world_trs_by_id(self.project.nodes)["child"]
        )
        self.window.undo_stack.undo()
        self.app.processEvents()
        restored = {node.id: node for node in self.project.nodes}
        self.assertEqual(restored["child"].parent_id, "parent")
        self.assertEqual(restored["parent"].parent_id, "grandparent")
        _assert_trs_close(
            self, child_world, world_trs_by_id(self.project.nodes)["child"]
        )

    def test_viewport_is_world_space_but_gizmo_commit_is_parent_local(self) -> None:
        parent = self._node(
            "parent",
            (5.0, 1.0, 2.0),
            rotation=euler_degrees_to_quaternion((0.0, 40.0, 0.0)),
            scale=(2.0, 2.0, 2.0),
        )
        child = self._node("child", (1.0, 2.0, 3.0), parent_id="parent")
        self._set_nodes(parent, child)
        world_before = world_trs_by_id(self.project.nodes)["child"]
        preview_child = next(
            node
            for node in self.window.viewport._preview_3d_project().nodes
            if node.id == "child"
        )
        self.assertIsNone(preview_child.parent_id)
        self.assertEqual(preview_child.transform.translation, world_before.translation)
        self.assertEqual(preview_child.transform.rotation, world_before.rotation)
        self.assertEqual(preview_child.transform.scale, world_before.scale)

        moved_parent = (8.0, 2.0, 4.0)
        expected_preview = self.window.document.preview_world_trs_after_translation(
            "parent", moved_parent
        )
        self.window.viewport._apply_translation_preview("parent", moved_parent)
        child_signature = self.window.viewport._mesh_runtime_transforms["child"]
        self.assertEqual(
            child_signature,
            (
                expected_preview["child"].translation,
                expected_preview["child"].rotation,
                expected_preview["child"].scale,
            ),
        )
        self.window.viewport.refresh(keep_view=True)

        self.window.document.set_selection(SelectionRef("node", "child"))
        moved_world = (
            world_before.translation[0] + 3.0,
            world_before.translation[1],
            world_before.translation[2],
        )
        self.window._viewport_moved("child", world_before.translation, moved_world)
        moved = next(node for node in self.project.nodes if node.id == "child")
        self.assertEqual(moved.parent_id, "parent")
        self.assertNotEqual(moved.transform.translation, moved_world)
        for actual, expected in zip(
            world_trs_by_id(self.project.nodes)["child"].translation, moved_world
        ):
            self.assertAlmostEqual(actual, expected, places=7)
        self.window.undo_stack.undo()
        _assert_trs_close(
            self, world_before, world_trs_by_id(self.project.nodes)["child"]
        )

    def test_linked_saved_scene_row_stays_separate_from_ordinary_hierarchy(self) -> None:
        parent = self._node("parent")
        child = self._node("child", (1.0, 0.0, 0.0), parent_id="parent")
        definition = make_saved_scene(
            "pair", "Linked Pair", (self._node("piece_a"), self._node("piece_b")), "piece_a"
        )
        instance = instantiate_saved_scene(definition, "linked_pair")
        metadata = metadata_with_saved_scenes(self.project.metadata, (definition,))
        self.project.metadata = metadata_with_saved_scene_instances(metadata, (instance,))
        self._set_nodes(parent, child)

        child_item = _selection_item(self.window, "child")
        self.assertEqual(
            child_item.parent().data(0, Qt.ItemDataRole.UserRole),
            SelectionRef("node", "parent"),
        )
        linked = next(
            item
            for item in _tree_items(self.window.hierarchy.tree)
            if item.text(1) == "Linked Saved Scene"
        )
        self.assertEqual(linked.text(0), "Linked Pair")
        self.assertEqual(linked.childCount(), 2)
        self.assertEqual(linked.parent().text(0), "Main 3D Scene")


if __name__ == "__main__":
    unittest.main()
