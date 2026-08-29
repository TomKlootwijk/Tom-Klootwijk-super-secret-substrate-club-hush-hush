from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTreeWidgetItemIterator

from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.mobile3d import Mobile3DProject, Node3DRecord


class EditorTriggerAreaAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def _resource_category(self, name: str):
        tree = self.window.assets_project.assets
        return next(
            tree.topLevelItem(index)
            for index in range(tree.topLevelItemCount())
            if tree.topLevelItem(index).text(0) == name
        )

    def _hierarchy_item(self, selection: SelectionRef):
        iterator = QTreeWidgetItemIterator(self.window.hierarchy.tree)
        while iterator.value():
            item = iterator.value()
            if item.data(0, Qt.ItemDataRole.UserRole) == selection:
                return item
            iterator += 1
        self.fail(f"No hierarchy item for {selection.object_id}")

    def test_3d_only_preset_is_unique_undoable_visible_and_roundtrips(self) -> None:
        self.window.new_2d_project()
        self.app.processEvents()
        self.assertTrue(self.window.hierarchy.add_trigger_button.isHidden())

        self.window.document.set_dirty(False)
        self.window.new_3d_project()
        self.app.processEvents()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        existing_trigger_count = sum(
            node.collider.sensor and node.collider.shape != "none"
            for node in project.nodes
        )
        original_count = len(project.nodes)
        self.assertFalse(self.window.hierarchy.add_trigger_button.isHidden())
        self.assertTrue(self.window.hierarchy.add_trigger_button.isEnabled())

        self.window.hierarchy.add_trigger_button.click()
        self.app.processEvents()
        selection = self.window.document.selection
        self.assertEqual(selection, SelectionRef("node", "trigger_area"))
        added = self.window.document.entity(selection)
        self.assertIsInstance(added, Node3DRecord)
        self.assertFalse(added.dynamic)
        self.assertTrue(added.collider.sensor)
        self.assertEqual(added.collider.shape, "sphere")
        self.assertEqual(added.collider.radius, 1.5)
        self.assertIn(added.mesh_id, project.meshes)
        self.assertIn(added.material_id, project.materials)
        self.assertEqual(self._hierarchy_item(selection).text(1), "Trigger Area")
        self.assertIn(added.id, self.window.viewport._mesh_runtime_transforms)
        self.assertEqual(
            self._resource_category("Trigger Areas").text(1),
            str(existing_trigger_count + 1),
        )
        self.assertTrue(self.window.document.validate().passed)

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(len(self.window.document.scene_objects()), original_count)
        self.assertIsNone(self.window.document.entity(selection))
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(self.window.document.selection, selection)
        self.assertIsNotNone(self.window.document.entity(selection))

        self.window.hierarchy.add_trigger_button.click()
        self.app.processEvents()
        second_selection = self.window.document.selection
        self.assertEqual(second_selection.object_id, "trigger_area_2")
        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertIsNone(self.window.document.entity(second_selection))

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "trigger_project.json")
            loaded = Mobile3DProject.load(path)
        loaded_area = next(node for node in loaded.nodes if node.id == "trigger_area")
        self.assertFalse(loaded_area.dynamic)
        self.assertEqual(loaded_area.collider.to_dict(), added.collider.to_dict())

        self.window.play()
        self.assertFalse(self.window.hierarchy.add_trigger_button.isEnabled())
        self.assertFalse(self.window.inspector.isEnabled())
        self.window.stop()
        self.assertTrue(self.window.hierarchy.add_trigger_button.isEnabled())

    def test_inspector_edits_sphere_and_box_without_collision_push(self) -> None:
        self.window.new_3d_project()
        selection = SelectionRef("node", "floor")
        self.window.document.set_selection(selection)
        self.app.processEvents()
        inspector = self.window.inspector
        self.assertTrue(inspector.trigger_box.isVisibleTo(inspector))
        self.assertFalse(inspector.trigger_enabled.isChecked())
        self.assertEqual(inspector.trigger_shape.currentData(), "sphere")
        self.assertIn("Logic Blocks", inspector.trigger_explanation.text())

        inspector.trigger_radius.setValue(2.25)
        inspector.trigger_enabled.click()
        self.app.processEvents()
        sphere = self.window.document.entity(selection)
        self.assertTrue(sphere.collider.sensor)
        self.assertEqual(sphere.collider.shape, "sphere")
        self.assertEqual(sphere.collider.radius, 2.25)
        self.assertIn("never pushes", inspector.trigger_explanation.text())
        self.assertEqual(self._hierarchy_item(selection).text(1), "Trigger Area")

        self.window.undo_stack.undo()
        self.app.processEvents()
        restored = self.window.document.entity(selection)
        self.assertFalse(restored.collider.sensor)
        self.assertEqual(restored.collider.shape, "none")
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertTrue(self.window.document.entity(selection).collider.sensor)

        inspector.trigger_size_x.setValue(4.0)
        inspector.trigger_size_y.setValue(6.0)
        inspector.trigger_size_z.setValue(8.0)
        inspector.trigger_shape.setCurrentIndex(
            inspector.trigger_shape.findData("box")
        )
        self.app.processEvents()
        boxed = self.window.document.entity(selection)
        self.assertTrue(boxed.collider.sensor)
        self.assertEqual(boxed.collider.shape, "box")
        self.assertEqual(boxed.collider.half_extents, (2.0, 3.0, 4.0))
        self.assertTrue(inspector.trigger_radius.isHidden())
        self.assertFalse(inspector.trigger_size_x.isHidden())

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(self.window.document.entity(selection).collider.shape, "sphere")
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(
            self.window.document.entity(selection).collider.half_extents,
            (2.0, 3.0, 4.0),
        )

        inspector.trigger_enabled.click()
        self.app.processEvents()
        disabled = self.window.document.entity(selection)
        self.assertFalse(disabled.collider.sensor)
        self.assertEqual(disabled.collider.shape, "box")
        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertTrue(self.window.document.entity(selection).collider.sensor)

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "edited_trigger.json")
            loaded = Mobile3DProject.load(path)
        loaded_floor = next(node for node in loaded.nodes if node.id == "floor")
        self.assertTrue(loaded_floor.collider.sensor)
        self.assertEqual(loaded_floor.collider.half_extents, (2.0, 3.0, 4.0))

        with self.assertRaisesRegex(ValueError, "Sphere or Box"):
            self.window.document.record_with_trigger_area(
                selection,
                {
                    "enabled": True,
                    "shape": "capsule",
                    "radius": 1.0,
                    "size_x": 1.0,
                    "size_y": 1.0,
                    "size_z": 1.0,
                },
            )
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            self.window.document.record_with_trigger_area(
                selection,
                {
                    "enabled": True,
                    "shape": "box",
                    "radius": 1.0,
                    "size_x": 0.0,
                    "size_y": 1.0,
                    "size_z": 1.0,
                },
            )


if __name__ == "__main__":
    unittest.main()
