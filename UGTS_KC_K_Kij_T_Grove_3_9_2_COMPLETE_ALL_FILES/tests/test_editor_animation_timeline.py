from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication, QInputDialog  # noqa: E402

from ugts_kc3.editor.document import EditorDocument, SelectionRef  # noqa: E402
from ugts_kc3.editor.main_window import EditorMainWindow  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402


class EditorAnimationTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.window = EditorMainWindow()
        self.window.document.create(blank_mobile3d_project())
        self.window.document.set_dirty(False)
        self.window.undo_stack.clear()
        self.selection = SelectionRef("node", "floor")
        self.window.document.set_selection(self.selection)

    def tearDown(self) -> None:
        self.window._animation_preview_stop()
        self.window.stop()
        self.window.document.set_dirty(False)
        self.window.deleteLater()
        self.app.processEvents()

    def _create(self) -> None:
        self.assertTrue(self.window.animation_timeline.create_button.isEnabled())
        self.window.animation_timeline.create_button.click()
        self.assertIsNotNone(self.window.document.transform_animation())

    def _add_key(self, time_value: float = 1.0) -> None:
        panel = self.window.animation_timeline
        panel.set_playhead(time_value)
        panel.set_pose(
            {
                "translation": [2.0, 1.0, -3.0],
                "rotation": [0.0, 90.0, 0.0],
                "scale": [1.5, 0.75, 2.0],
            }
        )
        panel.key_button.click()

    def test_guidance_create_and_conflict_reason_are_child_readable(self) -> None:
        panel = self.window.animation_timeline
        self.assertIs(panel.pages.currentWidget(), panel.guidance_page)
        self.assertIn("Create", panel.guidance_label.text())
        self.assertFalse(panel.create_button.isHidden())

        self.window.document.set_selection(SelectionRef("node", "player"))
        self.assertFalse(panel.create_button.isEnabled())
        self.assertIn("Physics", panel.guidance_label.text())

    def test_create_add_key_and_delete_are_atomic_undo_commands(self) -> None:
        self._create()
        self.assertEqual(self.window.undo_stack.count(), 1)
        self.assertTrue(self.window.document.is_dirty)
        self.assertEqual(len(self.window.document.transform_animation().keys), 1)

        self._add_key()
        self.assertEqual(self.window.undo_stack.count(), 2)
        self.assertEqual(len(self.window.document.transform_animation().keys), 2)

        self.window.undo_stack.undo()
        self.assertEqual(len(self.window.document.transform_animation().keys), 1)
        self.window.undo_stack.undo()
        self.assertIsNone(self.window.document.transform_animation())
        self.assertFalse(self.window.document.is_dirty)
        self.window.undo_stack.redo()
        self.window.undo_stack.redo()
        self.assertEqual(len(self.window.document.transform_animation().keys), 2)

        self.window.animation_timeline.delete_button.click()
        self.assertIsNone(self.window.document.transform_animation())
        self.window.undo_stack.undo()
        self.assertEqual(len(self.window.document.transform_animation().keys), 2)

    def test_scrubbing_changes_only_complete_viewport_overlay(self) -> None:
        self._create()
        self._add_key()
        before_json = copy.deepcopy(self.window.document.serialize())
        undo_count = self.window.undo_stack.count()
        dirty = self.window.document.is_dirty

        panel = self.window.animation_timeline
        panel.time.setValue(0.5)
        self.app.processEvents()
        state = self.window.viewport._runtime_state
        self.assertIsNotNone(state)
        self.assertEqual(set(state), {node.id for node in self.window.document.project.nodes})
        self.assertNotEqual(state["floor"]["translation"], (0.0, 0.0, 0.0))
        self.assertEqual(self.window.document.serialize(), before_json)
        self.assertEqual(self.window.undo_stack.count(), undo_count)
        self.assertEqual(self.window.document.is_dirty, dirty)

        self.window._animation_preview_stop()
        self.assertIsNone(self.window.viewport._runtime_state)
        self.assertEqual(panel.time.value(), 0.0)

    def test_duration_repeat_arrival_and_remove_key_persist_with_undo(self) -> None:
        self._create()
        self._add_key()
        panel = self.window.animation_timeline

        panel.duration.setValue(3.0)
        panel.loop_mode.setCurrentIndex(panel.loop_mode.findData("pingpong"))
        key_index = panel.key_selector.findData(1.0)
        panel.key_selector.setCurrentIndex(key_index)
        panel.easing.setCurrentIndex(panel.easing.findData("step"))
        animation = self.window.document.transform_animation()
        self.assertEqual(animation.duration, 3.0)
        self.assertEqual(animation.loop_mode, "pingpong")
        self.assertEqual(animation.keys[1].easing, "step")

        panel.remove_key_button.click()
        self.assertEqual(len(self.window.document.transform_animation().keys), 1)
        self.window.undo_stack.undo()
        self.assertEqual(len(self.window.document.transform_animation().keys), 2)

    def test_all_runtime_arrivals_are_previewable_and_persist(self) -> None:
        self._create()
        self._add_key()
        panel = self.window.animation_timeline
        key_index = panel.key_selector.findData(1.0)
        panel.key_selector.setCurrentIndex(key_index)
        expected = {
            "linear",
            "step",
            "ease_in",
            "ease_out",
            "ease_in_out",
            "smoothstep",
            "smootherstep",
            "back_out",
            "elastic_out",
        }
        self.assertEqual(
            {str(panel.easing.itemData(index)) for index in range(panel.easing.count())},
            expected,
        )
        for easing in expected:
            with self.subTest(easing=easing):
                panel.easing.setCurrentIndex(panel.easing.findData(easing))
                self.assertEqual(
                    self.window.document.transform_animation().keys[1].easing,
                    easing,
                )
                pose = panel.pose_at(0.5)
                self.assertTrue(
                    all(math.isfinite(value) for value in pose["translation"])
                )

    def test_save_reopen_and_project_play_use_the_same_animation(self) -> None:
        self._create()
        self._add_key()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.json"
            self.window.document.save(path)
            reopened = EditorDocument()
            reopened.load(path)
            reopened.set_selection(self.selection)
            self.assertEqual(
                reopened.transform_animation_data(),
                self.window.document.transform_animation_data(),
            )
            self.assertEqual(
                reopened.transform_animation_library_data(),
                self.window.document.transform_animation_library_data(),
            )

        self.window.animation_timeline.play_button.click()
        self.assertTrue(self.window._animation_previewing)
        self.window.play()
        self.assertFalse(self.window._animation_previewing)
        self.assertTrue(self.window._playing)
        for _ in range(60):
            self.window._play_frame()
        state = self.window.viewport._runtime_state
        self.assertGreater(state["floor"]["translation"][0], 0.0)
        self.window.stop()
        self.assertTrue(self.window.animation_timeline.isEnabled())

    def test_clip_workflow_is_named_stable_atomic_and_undoable(self) -> None:
        self._create()
        panel = self.window.animation_timeline
        created_count = self.window.undo_stack.count()

        with patch.object(QInputDialog, "getText", return_value=("Wave", True)):
            panel.new_clip_button.click()
        library = self.window.document.transform_animation_library()
        self.assertEqual([(clip.id, clip.label) for clip in library.clips], [
            ("main", "Main"),
            ("wave", "Wave"),
        ])
        self.assertEqual(panel.selected_clip_id(), "wave")

        with patch.object(QInputDialog, "getText", return_value=("Wave Copy", True)):
            panel.duplicate_clip_button.click()
        duplicate = self.window.document.transform_animation_library().clip("wave_copy")
        self.assertEqual(
            duplicate.animation,
            self.window.document.transform_animation_library().clip("wave").animation,
        )

        with patch.object(QInputDialog, "getText", return_value=("Jump", True)):
            panel.rename_clip_button.click()
        renamed = self.window.document.transform_animation_library().clip("wave_copy")
        self.assertEqual(renamed.label, "Jump")
        self.assertEqual(renamed.id, "wave_copy")
        self.assertEqual(
            self.window.document.graph_authoring_context().animation_choices,
            (("main", "Main"), ("wave", "Wave"), ("wave_copy", "Jump")),
        )

        before_choice_count = self.window.undo_stack.count()
        before_choice_dirty = self.window.document.is_dirty
        panel.set_playhead(0.75)
        panel.clip_selector.setCurrentIndex(panel.clip_selector.findData("main"))
        panel.set_playhead(0.25)
        panel.clip_selector.setCurrentIndex(panel.clip_selector.findData("wave_copy"))
        self.assertAlmostEqual(panel.time.value(), 0.75)
        self.assertEqual(self.window.undo_stack.count(), before_choice_count)
        self.assertEqual(self.window.document.is_dirty, before_choice_dirty)

        panel.autoplay_checkbox.setChecked(True)
        self.assertEqual(
            self.window.document.transform_animation_library().autoplay,
            "wave_copy",
        )
        panel.delete_clip_button.click()
        self.assertEqual(
            [clip.id for clip in self.window.document.transform_animation_library().clips],
            ["main", "wave"],
        )
        self.assertIsNone(self.window.document.transform_animation_library().autoplay)
        self.window.undo_stack.undo()
        self.assertEqual(
            self.window.document.transform_animation_library().clip("wave_copy").label,
            "Jump",
        )
        self.assertEqual(
            self.window.document.transform_animation_library().autoplay,
            "wave_copy",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi_clip_project.json"
            expected = self.window.document.transform_animation_library_data()
            self.window.document.save(path)
            reopened = EditorDocument()
            reopened.load(path)
            reopened.set_selection(self.selection)
            self.assertEqual(reopened.transform_animation_library_data(), expected)
        while self.window.undo_stack.index() > created_count:
            self.window.undo_stack.undo()
        self.assertEqual(
            [clip.id for clip in self.window.document.transform_animation_library().clips],
            ["main"],
        )


if __name__ == "__main__":
    unittest.main()
