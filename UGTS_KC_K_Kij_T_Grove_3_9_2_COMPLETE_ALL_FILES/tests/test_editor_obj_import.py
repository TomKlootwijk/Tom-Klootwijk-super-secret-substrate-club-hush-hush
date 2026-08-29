from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.androidexport import compile_scene_pack_bytes, inspect_scene_pack
from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.mobile3d import Mobile3DProject, Node3DRecord


class EditorObjImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def test_import_refreshes_editor_is_collision_free_undoable_and_deployable(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        self.assertTrue(self.window.import_3d_shape_action.isEnabled())
        selection = SelectionRef("node", "player")
        self.window.document.set_selection(selection)
        structure_changes: list[bool] = []
        self.window.document.structureChanged.connect(lambda: structure_changes.append(True))

        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            seed_path = self.window.document.save(folder / "project.json")
            self.window.undo_stack.setClean()
            source = folder / "My Shape.obj"
            source.write_text(
                "v -1 0 0\nv 1 0 0\nv 0 2 0\nf 1 2 3\n",
                encoding="utf-8",
            )
            initial_mesh_count = len(project.meshes)

            self.assertTrue(self.window.import_3d_shape(source))
            self.app.processEvents()
            self.assertIn("my_shape", project.meshes)
            self.assertEqual(len(project.meshes), initial_mesh_count + 1)
            self.assertTrue(self.window.document.is_dirty)
            self.assertGreaterEqual(self.window.inspector.mesh_combo.findData("my_shape"), 0)
            self.assertTrue(structure_changes)
            self.assertIn("player", self.window.viewport._mesh_items)
            mesh_category = self.window.assets_project.assets.topLevelItem(0)
            self.assertEqual(mesh_category.text(0), "3D Meshes")
            resources = {
                mesh_category.child(index).text(0): mesh_category.child(index).text(1)
                for index in range(mesh_category.childCount())
            }
            self.assertEqual(resources["My Shape"], "1 triangles")

            self.window.undo_stack.undo()
            self.app.processEvents()
            self.assertNotIn("my_shape", project.meshes)
            self.assertFalse(self.window.document.is_dirty)
            self.assertEqual(self.window.inspector.mesh_combo.findData("my_shape"), -1)
            self.window.undo_stack.redo()
            self.app.processEvents()
            self.assertIn("my_shape", project.meshes)

            self.assertTrue(self.window.import_3d_shape(source))
            self.assertIn("my_shape_2", project.meshes)
            combo = self.window.inspector.mesh_combo
            combo.setCurrentIndex(combo.findData("my_shape"))
            self.app.processEvents()
            player = self.window.document.entity(selection)
            self.assertIsInstance(player, Node3DRecord)
            self.assertEqual(player.mesh_id, "my_shape")
            self.assertIn("player", self.window.viewport._mesh_items)

            saved = self.window.document.save(seed_path)
            loaded = Mobile3DProject.load(saved)

        self.assertIn("my_shape", loaded.meshes)
        self.assertIn("my_shape_2", loaded.meshes)
        loaded_player = next(node for node in loaded.nodes if node.id == "player")
        self.assertEqual(loaded_player.mesh_id, "my_shape")
        packed = inspect_scene_pack(compile_scene_pack_bytes(loaded))
        self.assertIn("my_shape", {mesh["id"] for mesh in packed["meshes"]})

    def test_action_is_3d_only_and_is_disabled_during_preview(self) -> None:
        self.window.new_3d_project()
        self.assertTrue(self.window.import_3d_shape_action.isEnabled())
        self.window.play()
        self.assertFalse(self.window.import_3d_shape_action.isEnabled())
        self.window.stop()
        self.assertTrue(self.window.import_3d_shape_action.isEnabled())
        self.window.document.set_dirty(False)
        self.window.new_2d_project()
        self.assertFalse(self.window.import_3d_shape_action.isEnabled())


if __name__ == "__main__":
    unittest.main()
