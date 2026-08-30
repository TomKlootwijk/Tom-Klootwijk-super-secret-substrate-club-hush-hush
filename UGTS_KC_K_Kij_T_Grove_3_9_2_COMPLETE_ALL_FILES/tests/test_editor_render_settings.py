from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.renderpack import (
    compile_render_substrate_pack_bytes,
    inspect_render_substrate_pack,
)
from ugts_kc3.templates3d import blank_mobile3d_project


class EditorRenderSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.document.create(blank_mobile3d_project())
        self.window.undo_stack.clear()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def test_child_facing_choices_write_exact_compact_recipe_and_undo(self) -> None:
        panel = self.window.assets_project
        self.assertTrue(panel.isTabVisible(panel.render_tab_index))
        self.assertEqual(panel.polar_render_mode.currentData(), "cpu")
        self.assertEqual(panel.bayer_output_mode.currentData(), "off")
        self.assertIn("no extra asset", panel.render_recipe_summary.text())
        self.assertNotIn("substrate_render", self.window.document.project.metadata)

        panel.polar_render_mode.setCurrentIndex(
            panel.polar_render_mode.findData("auto")
        )
        self.app.processEvents()
        panel.bayer_output_mode.setCurrentIndex(
            panel.bayer_output_mode.findData("subtle")
        )
        self.app.processEvents()

        project = self.window.document.project
        raw = project.metadata["substrate_render"]
        self.assertEqual(raw["polar_mode"], "auto")
        self.assertEqual(raw["bayer_mode"], "subtle")
        self.assertEqual(raw["seed"], 0)
        packed = compile_render_substrate_pack_bytes(project)
        self.assertEqual(len(packed), 32)
        info = inspect_render_substrate_pack(packed)
        self.assertEqual((info["polar_mode"], info["bayer_mode"]), ("auto", "subtle"))
        self.assertIn("32 bytes", panel.render_recipe_summary.text())

        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertEqual(
            self.window.document.project.metadata["substrate_render"]["bayer_mode"],
            "off",
        )
        self.window.undo_stack.undo()
        self.app.processEvents()
        self.assertNotIn("substrate_render", self.window.document.project.metadata)
        self.assertEqual(compile_render_substrate_pack_bytes(self.window.document.project), b"")

        self.window.undo_stack.redo()
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(
            inspect_render_substrate_pack(
                compile_render_substrate_pack_bytes(self.window.document.project)
            )["bayer_mode"],
            "subtle",
        )

    def test_existing_custom_values_are_preserved_until_a_preset_is_chosen(self) -> None:
        project = blank_mobile3d_project()
        project.metadata["substrate_render"] = {
            "polar_mode": "lut",
            "bayer_mode": "custom",
            "levels": 12,
            "strength": 0.625,
            "seed": 392,
        }
        self.window.document.create(project)
        self.window.undo_stack.clear()
        self.app.processEvents()
        panel = self.window.assets_project
        self.assertEqual(panel.bayer_output_mode.currentData(), "custom")

        panel.polar_render_mode.setCurrentIndex(
            panel.polar_render_mode.findData("direct")
        )
        self.app.processEvents()
        raw = self.window.document.project.metadata["substrate_render"]
        self.assertEqual((raw["levels"], raw["strength"], raw["seed"]), (12, 0.625, 392))

        panel.bayer_output_mode.setCurrentIndex(
            panel.bayer_output_mode.findData("retro")
        )
        self.app.processEvents()
        raw = self.window.document.project.metadata["substrate_render"]
        self.assertNotIn("levels", raw)
        self.assertNotIn("strength", raw)
        self.assertEqual(raw["seed"], 392)


if __name__ == "__main__":
    unittest.main()
