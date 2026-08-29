from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import MATERIAL_LOOK_CHOICES, SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.mobile3d import Mobile3DProject


class EditorMaterialLookTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.new_3d_project()
        self.project = self.window.document.project
        self.assertIsInstance(self.project, Mobile3DProject)

    def tearDown(self) -> None:
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def _select(self, object_id: str) -> SelectionRef:
        selection = SelectionRef("node", object_id)
        self.window.document.set_selection(selection)
        self.app.processEvents()
        return selection

    def _apply(self, look: str) -> None:
        combo = self.window.inspector.material_look_combo
        index = combo.findData(look)
        self.assertGreaterEqual(index, 0)
        combo.setCurrentIndex(index)
        self.app.processEvents()

    def _bytes(self) -> bytes:
        return json.dumps(
            self.window.document.serialize(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def test_combo_classifies_values_and_custom_never_mutates(self) -> None:
        selection = self._select("player")
        combo = self.window.inspector.material_look_combo
        self.assertEqual(
            [(combo.itemText(index), combo.itemData(index)) for index in range(combo.count())],
            list(MATERIAL_LOOK_CHOICES),
        )
        self.assertIn("keeps this object's colour", combo.toolTip())
        source = self.project.materials["player"]
        cases = {
            "matte": (0.0, 0.875, (0.0, 0.0, 0.0)),
            "toy_plastic": (0.0, 0.3125, (0.0, 0.0, 0.0)),
            "metal": (1.0, 0.21875, (0.0, 0.0, 0.0)),
            "crystal_glow": (
                0.125,
                0.1875,
                tuple(float(channel) * 0.25 for channel in source.base_color[:3]),
            ),
        }
        for look, (metallic, roughness, emissive) in cases.items():
            self.project.materials["player"] = replace(
                source,
                metallic=metallic,
                roughness=roughness,
                emissive=emissive,
            )
            self.window.inspector.set_selection(self.window.document, selection)
            self.assertEqual(combo.currentData(), look)

        before = self._bytes()
        undo_count = self.window.undo_stack.count()
        self._apply("custom")
        self.assertEqual(self._bytes(), before)
        self.assertEqual(self.window.undo_stack.count(), undo_count)
        self.assertEqual(combo.currentData(), "crystal_glow")

    def test_shared_material_clones_and_keeps_population_prototype_together(self) -> None:
        selection = self._select("crystal_garden")
        before = self._bytes()
        before_materials = dict(self.project.materials)
        source = before_materials["accent"]
        self.assertTrue(
            any(
                node.id != "crystal_garden" and node.material_id == "accent"
                for node in self.project.nodes
            )
        )
        undo_count = self.window.undo_stack.count()

        self._apply("crystal_glow")

        selected = self.window.document.entity(selection)
        self.assertEqual(selected.material_id, "accent_crystal_glow")
        self.assertIn("scatter_population", selected.metadata)
        self.assertEqual(
            next(node for node in self.project.nodes if node.id == "goal").material_id,
            "accent",
        )
        self.assertEqual(self.project.materials["accent"], source)
        clone = self.project.materials["accent_crystal_glow"]
        self.assertEqual(clone.base_color, source.base_color)
        self.assertEqual(clone.double_sided, source.double_sided)
        self.assertEqual((clone.metallic, clone.roughness), (0.125, 0.1875))
        self.assertEqual(
            clone.emissive,
            tuple(float(channel) * 0.25 for channel in source.base_color[:3]),
        )
        self.assertEqual(len(self.project.materials), len(before_materials) + 1)
        self.assertEqual(self.window.undo_stack.count(), undo_count + 1)
        after = self._bytes()

        self.window.undo_stack.undo()
        self.assertEqual(self._bytes(), before)
        self.window.undo_stack.redo()
        self.assertEqual(self._bytes(), after)
        self.assertEqual(
            self.window.document.entity(selection).material_id,
            "accent_crystal_glow",
        )

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "material_look.json")
            raw = json.loads(path.read_text(encoding="utf-8"))
            loaded = Mobile3DProject.load(path)
        self.assertEqual(loaded.to_dict(), self.project.to_dict())
        self.assertTrue(all("preset" not in material for material in raw["materials"]))

    def test_unshared_material_updates_in_place_and_preserves_colour_flags(self) -> None:
        selection = self._select("player")
        source = self.project.materials["player"]
        self.assertEqual(
            sum(node.material_id == "player" for node in self.project.nodes),
            1,
        )
        material_ids = set(self.project.materials)
        node_ids = tuple((node.id, node.material_id) for node in self.project.nodes)

        self._apply("toy_plastic")

        updated = self.project.materials["player"]
        self.assertEqual(self.window.document.entity(selection).material_id, "player")
        self.assertEqual(set(self.project.materials), material_ids)
        self.assertEqual(
            tuple((node.id, node.material_id) for node in self.project.nodes),
            node_ids,
        )
        self.assertEqual(updated.base_color, source.base_color)
        self.assertEqual(updated.double_sided, source.double_sided)
        self.assertEqual((updated.metallic, updated.roughness), (0.0, 0.3125))
        self.assertEqual(updated.emissive, (0.0, 0.0, 0.0))
        self.assertEqual(self.window.inspector.material_look_combo.currentData(), "toy_plastic")

    def test_clone_id_uses_deterministic_collision_suffix(self) -> None:
        source = self.project.materials["accent"]
        self.project.materials["accent_crystal_glow"] = replace(
            source, id="accent_crystal_glow"
        )
        self.project.materials["accent_crystal_glow_2"] = replace(
            source, id="accent_crystal_glow_2"
        )
        self.assertTrue(self.project.validate().passed)
        selection = self._select("crystal_garden")
        self.assertEqual(
            self.window.document.collision_free_material_id("accent_crystal_glow"),
            "accent_crystal_glow_3",
        )

        self._apply("crystal_glow")

        self.assertEqual(
            self.window.document.entity(selection).material_id,
            "accent_crystal_glow_3",
        )
        self.window.undo_stack.undo()
        self.window.undo_stack.redo()
        self.assertEqual(
            self.window.document.entity(selection).material_id,
            "accent_crystal_glow_3",
        )


if __name__ == "__main__":
    unittest.main()
