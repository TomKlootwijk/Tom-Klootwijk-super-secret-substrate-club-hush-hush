from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.mobile3d import Mobile3DProject, Node3DRecord
from ugts_kc3.project import EntitySpec, GameProject


class EditorAppearanceAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def test_2d_picture_combo_is_validated_undoable_and_roundtrips(self) -> None:
        self.window.new_2d_project()
        project = self.window.document.project
        self.assertIsInstance(project, GameProject)
        selection = SelectionRef("entity", "player", "main")
        self.window.document.set_selection(selection)
        self.app.processEvents()

        combo = self.window.inspector.vector_asset_combo
        self.assertTrue(self.window.inspector.appearance_box.isVisibleTo(self.window.inspector))
        self.assertEqual(
            {combo.itemData(index) for index in range(combo.count())},
            set(project.vector_assets.assets),
        )
        self.assertEqual(combo.currentData(), "player_ship")
        combo.setCurrentIndex(combo.findData("crystal"))
        self.app.processEvents()

        changed = self.window.document.entity(selection)
        self.assertIsInstance(changed, EntitySpec)
        self.assertEqual(changed.components["vector_renderer"]["asset_id"], "crystal")
        self.assertTrue(self.window.document.validate().passed)
        with self.assertRaisesRegex(ValueError, "not in this project"):
            self.window.document.record_with_resource(
                selection, "vector_asset", "missing_picture"
            )

        self.window.undo_stack.undo()
        restored = self.window.document.entity(selection)
        self.assertEqual(restored.components["vector_renderer"]["asset_id"], "player_ship")
        self.window.undo_stack.redo()
        redone = self.window.document.entity(selection)
        self.assertEqual(redone.components["vector_renderer"]["asset_id"], "crystal")

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "picture_project.json")
            loaded = GameProject.load(path)
        loaded_player = next(
            entity for entity in loaded.scenes["main"].entities if entity.id == "player"
        )
        self.assertEqual(
            loaded_player.components["vector_renderer"]["asset_id"], "crystal"
        )

    def test_3d_shape_and_material_combos_undo_redo_and_roundtrip(self) -> None:
        self.window.new_3d_project()
        project = self.window.document.project
        self.assertIsInstance(project, Mobile3DProject)
        selection = SelectionRef("node", "player")
        self.window.document.set_selection(selection)
        self.app.processEvents()

        mesh_combo = self.window.inspector.mesh_combo
        material_combo = self.window.inspector.material_combo
        self.assertTrue(self.window.inspector.appearance_box.isVisibleTo(self.window.inspector))
        self.assertEqual(
            {mesh_combo.itemData(index) for index in range(mesh_combo.count())},
            set(project.meshes),
        )
        self.assertEqual(
            {material_combo.itemData(index) for index in range(material_combo.count())},
            set(project.materials),
        )
        self.assertEqual((mesh_combo.currentData(), material_combo.currentData()), ("sphere", "player"))

        mesh_combo.setCurrentIndex(mesh_combo.findData("cube"))
        self.app.processEvents()
        material_combo.setCurrentIndex(material_combo.findData("accent"))
        self.app.processEvents()
        changed = self.window.document.entity(selection)
        self.assertIsInstance(changed, Node3DRecord)
        self.assertEqual((changed.mesh_id, changed.material_id), ("cube", "accent"))
        self.assertTrue(self.window.document.validate().passed)
        with self.assertRaisesRegex(ValueError, "not in this project"):
            self.window.document.record_with_resource(selection, "mesh", "missing_mesh")
        with self.assertRaisesRegex(ValueError, "not in this project"):
            self.window.document.record_with_resource(
                selection, "material", "missing_material"
            )

        self.window.undo_stack.undo()
        material_undone = self.window.document.entity(selection)
        self.assertEqual((material_undone.mesh_id, material_undone.material_id), ("cube", "player"))
        self.window.undo_stack.undo()
        shape_undone = self.window.document.entity(selection)
        self.assertEqual((shape_undone.mesh_id, shape_undone.material_id), ("sphere", "player"))
        self.window.undo_stack.redo()
        self.window.undo_stack.redo()
        redone = self.window.document.entity(selection)
        self.assertEqual((redone.mesh_id, redone.material_id), ("cube", "accent"))

        self.window.play()
        self.assertFalse(self.window.inspector.isEnabled())
        self.window.stop()
        self.assertTrue(self.window.inspector.isEnabled())

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "mobile_project.json")
            loaded = Mobile3DProject.load(path)
        loaded_player = next(node for node in loaded.nodes if node.id == "player")
        self.assertEqual(
            (loaded_player.mesh_id, loaded_player.material_id), ("cube", "accent")
        )


if __name__ == "__main__":
    unittest.main()
