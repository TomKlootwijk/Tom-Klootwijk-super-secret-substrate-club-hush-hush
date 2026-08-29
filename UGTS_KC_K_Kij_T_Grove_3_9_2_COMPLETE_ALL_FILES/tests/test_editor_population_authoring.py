from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem

from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow, SceneObjectsCommand
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.scatter import SCATTER_METADATA_KEY
from ugts_kc3.templates import first_steps_project
from ugts_kc3.templates3d import blank_mobile3d_project


class EditorPopulationAuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        project = blank_mobile3d_project()
        # A cube makes every generated preview item visible; the stock floor
        # plane is intentionally back-face culled from the editor camera.
        project.nodes = (replace(project.nodes[0], mesh_id="cube"),) + project.nodes[1:]
        project.validate()
        self.window.document.create(project)
        self.window.undo_stack.clear()
        self.selection = SelectionRef("node", "floor")
        self.window.document.set_selection(self.selection)
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.stop()
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

    def _shown_population_copies(self) -> int:
        return sum(
            item.data(3) == "population_copy"
            for item in self.window.viewport.scene().items()
        )

    def _scene_text(self) -> str:
        return " ".join(
            item.text()
            for item in self.window.viewport.scene().items()
            if isinstance(item, QGraphicsSimpleTextItem)
        )

    def test_gui_edit_is_atomic_compact_undoable_and_roundtrips(self) -> None:
        inspector = self.window.inspector
        self.assertTrue(inspector.population_box.isVisibleTo(inspector))
        self.assertTrue(inspector.population_enabled.isEnabled())
        self.assertFalse(inspector.population_enabled.isChecked())
        self.assertEqual(inspector.population_count.minimum(), 2)
        self.assertEqual(inspector.population_count.maximum(), 256)
        self.assertIn("36 bytes", inspector.population_cost.text())
        self.assertIn("24-byte header", inspector.population_cost.text())

        inspector.population_enabled.click()
        self.app.processEvents()

        self.assertEqual(self.window.undo_stack.count(), 1)
        self.assertIsInstance(self.window.undo_stack.command(0), SceneObjectsCommand)
        self.assertEqual(self.window.document.selection, self.selection)
        self.assertEqual(len(self.window.document.scene_objects()), 3)
        floor = self.window.document.entity(self.selection)
        self.assertEqual(floor.metadata[SCATTER_METADATA_KEY]["instance_count"], 8)
        self.assertEqual(
            self.window.status_message.text(),
            "One saved object becomes 8 display objects.",
        )

        inspector.population_count.setValue(256)
        inspector.population_count.editingFinished.emit()
        self.app.processEvents()

        self.assertEqual(self.window.undo_stack.count(), 2)
        self.assertIsInstance(self.window.undo_stack.command(1), SceneObjectsCommand)
        self.assertEqual(self.window.document.selection, self.selection)
        floor = self.window.document.entity(self.selection)
        recipe = floor.metadata[SCATTER_METADATA_KEY]
        self.assertEqual(recipe["instance_count"], 256)
        self.assertEqual(len(self.window.document.scene_objects()), 3)
        self.assertEqual(self._shown_population_copies(), 64)
        self.assertIn("255 generated · 64 shown", self._scene_text())

        category = self._resource_category("Populated Areas")
        self.assertEqual(category.text(1), "1")
        self.assertEqual(category.childCount(), 1)
        self.assertEqual(category.child(0).text(0), "Floor")
        self.assertIn("256 display objects", category.child(0).text(1))

        with tempfile.TemporaryDirectory() as temporary:
            saved_path = self.window.document.save(
                Path(temporary) / "populated_project.json"
            )
            loaded = Mobile3DProject.load(saved_path)
        loaded_floor = next(node for node in loaded.nodes if node.id == "floor")
        self.assertEqual(loaded_floor.metadata[SCATTER_METADATA_KEY], recipe)
        self.assertEqual(len(loaded.nodes), 3)

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(
            self.window.document.entity(self.selection).metadata[SCATTER_METADATA_KEY][
                "instance_count"
            ],
            8,
        )
        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertNotIn(
            SCATTER_METADATA_KEY,
            self.window.document.entity(self.selection).metadata,
        )
        self.assertEqual(self.window.document.selection, self.selection)

        self.window.undo_stack.redo()
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(
            self.window.document.entity(self.selection).metadata[SCATTER_METADATA_KEY][
                "instance_count"
            ],
            256,
        )

        inspector.population_enabled.click()
        self.app.processEvents()
        self.assertNotIn(
            SCATTER_METADATA_KEY,
            self.window.document.entity(self.selection).metadata,
        )
        self.assertEqual(
            self.window.status_message.text(), "Removed Populate Area from Floor."
        )
        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(
            self.window.document.entity(self.selection).metadata[SCATTER_METADATA_KEY][
                "instance_count"
            ],
            256,
        )

        command_count = self.window.undo_stack.count()
        self.window.play()
        self.window.play_timer.stop()
        inspector.populationEdited.emit({"enabled": False})
        self.assertEqual(self.window.undo_stack.count(), command_count)
        self.assertIn(
            SCATTER_METADATA_KEY,
            self.window.document.entity(self.selection).metadata,
        )

    def test_unsafe_and_2d_selections_cannot_create_population_commands(self) -> None:
        player_selection = SelectionRef("node", "player")
        self.window.document.set_selection(player_selection)
        self.app.processEvents()
        inspector = self.window.inspector
        self.assertTrue(inspector.population_box.isVisibleTo(inspector))
        self.assertFalse(inspector.population_enabled.isEnabled())
        self.assertIn("static", inspector.population_explanation.text())

        values = {
            "enabled": True,
            "instance_count": 8,
            "seed": 1,
            "size_x": 8.0,
            "size_y": 0.0,
            "size_z": 8.0,
            "scale_min": 0.85,
            "scale_max": 1.15,
            "random_yaw": True,
        }
        inspector.populationEdited.emit(values)
        self.app.processEvents()
        self.assertEqual(self.window.undo_stack.count(), 0)
        self.assertNotIn(
            SCATTER_METADATA_KEY,
            self.window.document.entity(player_selection).metadata,
        )
        self.assertFalse(inspector.population_enabled.isChecked())
        self.assertIn("must be static", self.window.status_message.text())

        self.window.document.create(first_steps_project())
        self.window.undo_stack.clear()
        entity_selection = SelectionRef("entity", "player", "main")
        self.window.document.set_selection(entity_selection)
        self.app.processEvents()
        self.assertTrue(inspector.population_box.isHidden())
        inspector.populationEdited.emit(values)
        self.app.processEvents()
        self.assertEqual(self.window.undo_stack.count(), 0)
        self.assertIn("mobile 3D", self.window.status_message.text())


if __name__ == "__main__":
    unittest.main()
