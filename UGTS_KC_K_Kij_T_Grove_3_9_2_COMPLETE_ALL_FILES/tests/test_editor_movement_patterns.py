from __future__ import annotations

import copy
import math
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.mobile3d import Mobile3DProject, Node3DRecord
from ugts_kc3.packed_kinematics import (
    PackedKinematicComponent,
    packed_kinematic_codecs_from_dict,
)
from ugts_kc3.polarpack import compile_polar_pack_bytes, inspect_polar_pack
from ugts_kc3.templates3d import blank_mobile3d_project, first_steps_mobile3d_project


def _tree_text(item: QTreeWidgetItem) -> str:
    values = [item.text(0), item.text(1)]
    for index in range(item.childCount()):
        values.append(_tree_text(item.child(index)))
    return " ".join(values)


class EditorMovementPatternTests(unittest.TestCase):
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

    def _select(self, object_id: str) -> SelectionRef:
        selection = SelectionRef("node", object_id)
        self.window.document.set_selection(selection)
        self.app.processEvents()
        return selection

    def _choose(
        self,
        pattern: str,
        *,
        radius: float,
        speed: float,
        angle: float,
    ) -> None:
        inspector = self.window.inspector
        inspector.movement_radius.setValue(radius)
        inspector.movement_speed.setValue(speed)
        inspector.movement_angle.setValue(angle)
        index = inspector.movement_pattern_combo.findData(pattern)
        self.assertGreaterEqual(index, 0)
        inspector.movement_pattern_combo.setCurrentIndex(index)
        self.app.processEvents()

    def test_presets_share_profile_pack_to_two_words_and_undo_roundtrip(self) -> None:
        floor_selection = self._select("floor")
        inspector = self.window.inspector
        self.assertTrue(inspector.movement_box.isVisibleTo(inspector))
        self.assertEqual(
            [
                inspector.movement_pattern_combo.itemData(index)
                for index in range(inspector.movement_pattern_combo.count())
            ],
            ["off", "orbit", "spiral_out", "spiral_in"],
        )
        self.assertTrue(inspector.x3.isEnabled())

        self._choose("orbit", radius=4.25, speed=-0.125, angle=90.0)
        floor = self.window.document.entity(floor_selection)
        self.assertIsInstance(floor, Node3DRecord)
        raw_floor = floor.metadata["packed_kinematic"]
        self.assertEqual(set(raw_floor), {"pose", "motion", "profile"})
        self.assertEqual(len(raw_floor["pose"]), 16)
        self.assertEqual(len(raw_floor["motion"]), 16)
        self.assertEqual(raw_floor["profile"], "studio_movement")
        self.assertTrue(self.window.document.validate().passed)

        profiles = self.window.document.movement_profiles()
        codec = packed_kinematic_codecs_from_dict(profiles)[raw_floor["profile"]]
        packed_floor = PackedKinematicComponent.from_dict(raw_floor)
        pose = codec.unpack_pose(packed_floor.pose_word)
        motion = codec.unpack_motion(packed_floor.motion_word)
        self.assertAlmostEqual(codec.profile.r0 * math.exp(pose.rho), 4.25, places=3)
        self.assertAlmostEqual(math.degrees(pose.theta), 90.0, places=2)
        self.assertAlmostEqual(motion.theta_velocity / math.tau, -0.125, places=3)
        self.assertAlmostEqual(floor.transform.translation[0], 0.0, places=3)
        self.assertAlmostEqual(floor.transform.translation[2], 4.25, places=3)
        self.assertFalse(inspector.x3.isEnabled())
        self.assertFalse(inspector.z3.isEnabled())
        self.assertFalse(inspector.ry3.isEnabled())
        self.assertTrue(inspector.y3.isEnabled())
        self.assertIn("24 bytes", inspector.movement_cost.text())
        self.assertIn("shared", inspector.movement_cost.text().casefold())

        packed_one = compile_polar_pack_bytes(self.window.document.project)
        one_info = inspect_polar_pack(packed_one, node_count=3)
        self.assertEqual((one_info["profile_count"], one_info["component_count"]), (1, 1))
        self.assertLess(one_info["byte_length"], 1024)

        goal_selection = self._select("goal")
        self.assertEqual(
            self.window.document.entity(goal_selection).angular_velocity,
            (0, 0.5, 0),
        )
        self._choose("spiral_out", radius=6.0, speed=0.2, angle=180.0)
        goal = self.window.document.entity(goal_selection)
        self.assertIsInstance(goal, Node3DRecord)
        raw_goal = goal.metadata["packed_kinematic"]
        self.assertEqual(raw_goal["profile"], raw_floor["profile"])
        self.assertEqual(len(self.window.document.movement_profiles()), 1)
        self.assertEqual(
            self.window.viewport._mesh_runtime_transforms["goal"][0],
            goal.transform.translation,
        )
        goal_component = PackedKinematicComponent.from_dict(raw_goal)
        goal_motion = codec.unpack_motion(goal_component.motion_word)
        self.assertGreater(goal_motion.rho_velocity, 0.0)
        self.assertEqual(goal.angular_velocity, (0.0, 0.0, 0.0))

        packed_two = compile_polar_pack_bytes(self.window.document.project)
        two_info = inspect_polar_pack(packed_two, node_count=3)
        self.assertEqual((two_info["profile_count"], two_info["component_count"]), (1, 2))
        self.assertEqual(two_info["schema"], "ugts-kc-native-packed-kinematics-inspection-3.9.2")
        self.assertEqual(len(packed_two) - len(packed_one), 24)

        movement_category = next(
            self.window.assets_project.assets.topLevelItem(index)
            for index in range(self.window.assets_project.assets.topLevelItemCount())
            if self.window.assets_project.assets.topLevelItem(index).text(0)
            == "Movement Patterns"
        )
        self.assertEqual(movement_category.text(1), "2")

        self.window.undo_stack.undo()
        self.app.processEvents()
        undone_goal = self.window.document.entity(goal_selection)
        self.assertNotIn("packed_kinematic", undone_goal.metadata)
        self.assertEqual(undone_goal.angular_velocity, (0, 0.5, 0))
        self.assertEqual(compile_polar_pack_bytes(self.window.document.project), packed_one)
        self.window.undo_stack.redo()
        self.app.processEvents()
        self.assertEqual(
            self.window.document.entity(goal_selection).angular_velocity,
            (0.0, 0.0, 0.0),
        )
        self.assertEqual(compile_polar_pack_bytes(self.window.document.project), packed_two)

        with tempfile.TemporaryDirectory() as temporary:
            path = self.window.document.save(Path(temporary) / "movement_project.json")
            loaded = Mobile3DProject.load(path)
        self.assertEqual(compile_polar_pack_bytes(loaded), packed_two)
        self.assertTrue(loaded.validate().passed)

    def test_existing_profile_stays_canonical_and_inspector_never_shows_hex(self) -> None:
        self.window.document.create(first_steps_mobile3d_project())
        self.window.undo_stack.clear()
        selection = self._select("goal")
        goal = self.window.document.entity(selection)
        raw = copy.deepcopy(goal.metadata["packed_kinematic"])
        profiles_before = self.window.document.movement_profiles()

        inspector = self.window.inspector
        self.assertEqual(inspector.movement_pattern_combo.currentData(), "orbit")
        self.assertFalse(inspector.x3.isEnabled())
        details_text = " ".join(
            _tree_text(inspector.details.topLevelItem(index))
            for index in range(inspector.details.topLevelItemCount())
        )
        self.assertIn("Movement Pattern", details_text)
        self.assertNotIn(raw["pose"], details_text)
        self.assertNotIn(raw["motion"], details_text)

        inspector.movement_speed.editingFinished.emit()
        self.app.processEvents()
        unchanged = self.window.document.entity(selection)
        self.assertEqual(unchanged.metadata["packed_kinematic"], raw)
        self.assertEqual(self.window.undo_stack.count(), 0)

        inspector.movement_speed.setValue(0.1)
        inspector.movement_speed.editingFinished.emit()
        self.app.processEvents()
        changed = self.window.document.entity(selection)
        self.assertEqual(changed.metadata["packed_kinematic"]["profile"], "lesson_orbit")
        self.assertEqual(changed.metadata["packed_kinematic"]["pose"], raw["pose"])
        self.assertEqual(self.window.document.movement_profiles(), profiles_before)

        self.window.play()
        self.assertFalse(inspector.isEnabled())
        self.window.stop()
        self.assertTrue(inspector.isEnabled())

    def test_dynamic_node_is_guarded_and_invalid_values_are_rejected(self) -> None:
        selection = self._select("player")
        inspector = self.window.inspector
        self.assertFalse(inspector.movement_pattern_combo.isEnabled())
        self.assertIn("Dynamic", inspector.movement_pattern_combo.currentText())
        self.assertFalse(inspector.movement_radius.isEnabled())
        self.assertNotIn(
            "packed_kinematic", self.window.document.entity(selection).metadata
        )

        with self.assertRaisesRegex(ValueError, "Physics already controls"):
            self.window.document.movement_pattern_snapshot(
                selection,
                {
                    "pattern": "orbit",
                    "radius": 3.0,
                    "speed": 0.2,
                    "start_angle": 0.0,
                },
            )

        floor_selection = self._select("floor")
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            self.window.document.movement_pattern_snapshot(
                floor_selection,
                {
                    "pattern": "orbit",
                    "radius": 0.0,
                    "speed": 0.2,
                    "start_angle": 0.0,
                },
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            self.window.document.movement_pattern_snapshot(
                floor_selection,
                {
                    "pattern": "orbit",
                    "radius": 3.0,
                    "speed": math.nan,
                    "start_angle": 0.0,
                },
            )
        with self.assertRaisesRegex(ValueError, "Turn speed"):
            self.window.document.movement_pattern_snapshot(
                floor_selection,
                {
                    "pattern": "orbit",
                    "radius": 3.0,
                    "speed": 99.0,
                    "start_angle": 0.0,
                },
            )


if __name__ == "__main__":
    unittest.main()
