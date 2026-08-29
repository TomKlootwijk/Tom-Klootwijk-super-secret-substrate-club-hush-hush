from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import EditorDocument, SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow, TransformCommand
from ugts_kc3.editor.scene_view import TranslationGizmoHandle


class Editor3DTranslationGizmoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.resize(1200, 800)
        self.window.show()
        self.window.new_3d_project()
        self.app.processEvents()
        self.window.undo_stack.clear()
        self.window.document.set_dirty(False)

    def tearDown(self) -> None:
        if self.window._playing:
            self.window.stop()
        self.window.document.set_dirty(False)
        self.window.close()
        self.app.processEvents()

    def _select(self, object_id: str) -> None:
        self.window.document.set_selection(SelectionRef("node", object_id))
        self.app.processEvents()

    def _handle(self, axis: str) -> TranslationGizmoHandle:
        return next(
            handle
            for handle in self.window.viewport.gizmo_handles
            if handle.axis == axis
        )

    def _drag_points(
        self, handle: TranslationGizmoHandle, distance: float = 70.0
    ) -> tuple[QPoint, QPoint]:
        viewport = self.window.viewport
        origin = viewport.mapFromScene(handle.mapToScene(QPointF()))
        endpoint = viewport.mapFromScene(handle.mapToScene(handle.endpoint))
        start = viewport.mapFromScene(handle.mapToScene(handle.drag_point()))
        dx = float(endpoint.x() - origin.x())
        dy = float(endpoint.y() - origin.y())
        length = (dx * dx + dy * dy) ** 0.5
        self.assertGreater(length, 2.0)
        target = QPoint(
            round(start.x() + dx / length * distance),
            round(start.y() + dy / length * distance),
        )
        self.assertIs(viewport.itemAt(start), handle)
        return start, target

    @staticmethod
    def _project_bytes(document: EditorDocument) -> bytes:
        return json.dumps(
            document.serialize(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

    def test_x_drag_previews_without_mutation_then_commits_one_undoable_roundtrip(
        self,
    ) -> None:
        self._select("player")
        handle = self._handle("x")
        start, target = self._drag_points(handle)
        before = self.window.document.transform()
        self.assertIsNotNone(before)
        before_bytes = self._project_bytes(self.window.document)
        mesh = self.window.viewport._mesh_items["player"]
        mesh_centre = mesh.boundingRect().center()
        handle_origin = handle.pos()

        QTest.mousePress(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        QTest.mouseMove(self.window.viewport.viewport(), target, 15)
        self.app.processEvents()

        preview_x = self.window.inspector.x3.value()
        self.assertNotAlmostEqual(preview_x, float(before["translation"][0]))
        self.assertNotEqual(mesh.boundingRect().center(), mesh_centre)
        self.assertNotEqual(handle.pos(), handle_origin)
        self.assertEqual(self.window.document.transform(), before)
        self.assertEqual(self._project_bytes(self.window.document), before_bytes)
        self.assertFalse(self.window.document.is_dirty)
        self.assertEqual(self.window.undo_stack.count(), 0)
        self.assertIs(handle.scene(), self.window.viewport.scene())

        QTest.mouseRelease(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            target,
        )
        self.app.processEvents()
        QTest.qWait(2)
        self.app.processEvents()

        after = self.window.document.transform()
        self.assertIsNotNone(after)
        self.assertAlmostEqual(after["translation"][0], preview_x, places=3)
        self.assertEqual(after["translation"][1:], before["translation"][1:])
        self.assertEqual(self.window.undo_stack.count(), 1)
        self.assertIsInstance(self.window.undo_stack.command(0), TransformCommand)
        self.assertTrue(self.window.document.is_dirty)
        self.assertEqual(len(self.window.viewport.gizmo_handles), 3)

        self.window.undo_stack.undo()
        self.assertEqual(self.window.document.transform(), before)
        self.assertFalse(self.window.document.is_dirty)
        self.window.undo_stack.redo()
        self.assertEqual(self.window.document.transform(), after)

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "gizmo_project.json")
            reloaded = EditorDocument()
            reloaded.load(path)
            persisted = reloaded.transform(SelectionRef("node", "player"))
        self.assertEqual(persisted, after)
        self.assertTrue(reloaded.validate().passed)

    def test_selection_replaces_handles_and_packed_movement_locks_only_xz(self) -> None:
        self._select("player")
        player_handles = self.window.viewport.gizmo_handles
        self.assertEqual({handle.axis for handle in player_handles}, {"x", "y", "z"})
        for handle in player_handles:
            self.assertFalse(handle.locked)
            self.assertTrue(handle.shape().contains(handle.drag_point()))
            self.assertIs(handle.scene(), self.window.viewport.scene())

        self._select("goal")
        goal_handles = {handle.axis: handle for handle in self.window.viewport.gizmo_handles}
        self.assertEqual(set(goal_handles), {"x", "y", "z"})
        self.assertTrue(goal_handles["x"].locked)
        self.assertFalse(goal_handles["y"].locked)
        self.assertTrue(goal_handles["z"].locked)
        self.assertIn("Choose Off / Static", goal_handles["x"].toolTip())
        self.assertIn("Choose Off / Static", goal_handles["z"].toolTip())
        self.assertNotIn("Off / Static", goal_handles["y"].toolTip())
        self.assertTrue(all(handle.scene() is None for handle in player_handles))

        before = self.window.document.transform()
        before_bytes = self._project_bytes(self.window.document)
        locked_start, locked_target = self._drag_points(goal_handles["x"])
        QTest.mouseClick(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            locked_start,
        )
        self.assertIn("Off / Static", self.window.status_message.text())
        QTest.mousePress(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            locked_start,
        )
        QTest.mouseMove(self.window.viewport.viewport(), locked_target, 10)
        QTest.mouseRelease(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            locked_target,
        )
        self.app.processEvents()
        self.assertEqual(self.window.document.transform(), before)
        self.assertEqual(self._project_bytes(self.window.document), before_bytes)
        self.assertEqual(self.window.undo_stack.count(), 0)

        y_start, y_target = self._drag_points(goal_handles["y"], 45.0)
        QTest.mousePress(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            y_start,
        )
        QTest.mouseMove(self.window.viewport.viewport(), y_target, 10)
        QTest.mouseRelease(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            y_target,
        )
        self.app.processEvents()
        QTest.qWait(2)
        self.app.processEvents()
        after = self.window.document.transform()
        self.assertEqual(after["translation"][0], before["translation"][0])
        self.assertNotEqual(after["translation"][1], before["translation"][1])
        self.assertEqual(after["translation"][2], before["translation"][2])
        self.assertEqual(self.window.undo_stack.count(), 1)

        active_handles = self.window.viewport.gizmo_handles
        self.window.document.set_selection(None)
        self.app.processEvents()
        self.assertEqual(self.window.viewport.gizmo_handles, ())
        self.assertTrue(all(handle.scene() is None for handle in active_handles))

    def test_play_cancels_preview_hides_handles_and_blocks_late_move(self) -> None:
        self._select("player")
        handle = self._handle("x")
        start, target = self._drag_points(handle)
        before = self.window.document.transform()
        before_bytes = self._project_bytes(self.window.document)

        QTest.mousePress(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            start,
        )
        QTest.mouseMove(self.window.viewport.viewport(), target, 10)
        self.app.processEvents()
        self.assertNotAlmostEqual(
            self.window.inspector.x3.value(), float(before["translation"][0])
        )

        self.window.play()
        self.app.processEvents()
        self.assertTrue(self.window._playing)
        self.assertEqual(self.window.viewport.gizmo_handles, ())
        self.assertIsNone(handle.scene())
        self.assertEqual(self.window.document.transform(), before)
        self.assertEqual(self._project_bytes(self.window.document), before_bytes)
        self.assertFalse(self.window.document.is_dirty)
        self.assertEqual(self.window.undo_stack.count(), 0)
        self.assertAlmostEqual(
            self.window.inspector.x3.value(), float(before["translation"][0])
        )

        late_translation = tuple(before["translation"])
        late_translation = (late_translation[0] + 5.0, *late_translation[1:])
        self.window.viewport.entityMoved.emit(
            "player", before["translation"], late_translation
        )
        self.window.viewport.translationPreviewed.emit("player", late_translation)
        self.app.processEvents()
        self.assertEqual(self.window.document.transform(), before)
        self.assertEqual(self.window.undo_stack.count(), 0)
        self.assertAlmostEqual(
            self.window.inspector.x3.value(), float(before["translation"][0])
        )

        QTest.mouseRelease(
            self.window.viewport.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            target,
        )
        self.window.stop()
        self.app.processEvents()
        self.assertEqual(len(self.window.viewport.gizmo_handles), 3)
        self.assertEqual(self.window.document.transform(), before)


if __name__ == "__main__":
    unittest.main()
