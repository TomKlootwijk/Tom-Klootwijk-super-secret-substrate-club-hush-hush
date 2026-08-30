# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
import json
import math
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import EditorDocument
from ugts_kc3.editor.scene_view import SceneViewport
from ugts_kc3.mobile3d import InputFrame3D, Transform3DRecord
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import polar_population_instance, polar_population_preset
from ugts_kc3.polar_population_pack import compile_polar_population_pack_bytes
from ugts_kc3.templates3d import blank_mobile3d_project


def _project(*, count: int = 128):
    project = blank_mobile3d_project("Moving Make Many", "Test")
    profile = LogPolarProfile(r0=2.0, rho_min=-5.0, rho_max=5.0)
    motion_range = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    component = codec.component(
        PolarPose(math.log(3.0 / profile.r0), math.radians(15), 321, math.radians(35)),
        PolarMotion(0.15, math.tau * 0.5, 0.05, math.tau * -0.02),
        profile_id="display",
    )
    project.metadata["packed_kinematic_profiles"] = {
        "display": {
            "profile": profile.to_dict(),
            "motion_range": motion_range.to_dict(),
            "lut_resolution": 64,
        }
    }
    project.nodes = tuple(
        replace(
            node,
            angular_velocity=(0.0, 0.0, 0.0),
            transform=Transform3DRecord(
                (node.transform.translation[0], 1.25, node.transform.translation[2]),
                node.transform.rotation,
                (0.75, 1.25, 0.5),
            ),
            metadata={
                **node.metadata,
                "packed_kinematic": component.to_dict(),
                "polar_population": polar_population_preset(
                    "ring", instance_count=count, seed=23
                ).to_dict(),
            },
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _copies(viewport: SceneViewport):
    return {
        str(item.data(5)): item
        for item in viewport.scene().items()
        if item.data(3) == "polar_population_copy"
    }


def _face_signature(item) -> tuple[tuple[float, float], ...]:
    return tuple(
        (point.x(), point.y())
        for _, polygon, _ in item.faces
        for point in polygon
    )


class EditorPolarPopulationPlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.project = _project()
        self.document = EditorDocument()
        self.document.create(self.project)
        self.viewport = SceneViewport()
        self.viewport.set_document(self.document)
        self.viewport.set_selected_id("goal")
        self.app.processEvents()

    def tearDown(self) -> None:
        self.document.stop_play()
        self.viewport.close()
        self.app.processEvents()

    def test_play_advances_only_retained_items_from_transient_runtime_words(self) -> None:
        authored_project = self.project.to_dict()
        authored_pack = compile_polar_population_pack_bytes(self.project)
        authored_items = _copies(self.viewport)
        self.assertGreater(len(authored_items), 0)
        self.assertLessEqual(len(authored_items), 64)
        display_id, retained_item = next(iter(authored_items.items()))
        authored_faces = _face_signature(retained_item)
        authored_tooltip = retained_item.toolTip()

        self.document.begin_play()
        runtime_world = self.document._runtime_world
        self.assertIsNotNone(runtime_world)
        assert runtime_world is not None
        control_world = self.project.instantiate_world()
        previous = runtime_world.require("goal").extra_components[
            "packed_kinematic"
        ].pose_word

        state, _ = self.document.step_play(set())
        control_world.step(InputFrame3D())
        packed_state = state["goal"]["packed_kinematic"]
        current = runtime_world.require("goal").extra_components["packed_kinematic"]
        self.assertEqual(packed_state["previous_pose_word"], previous)
        self.assertEqual(packed_state["pose_word"], current.pose_word)
        self.assertEqual(packed_state["motion_word"], current.motion_word)
        self.assertEqual(packed_state["profile_id"], current.profile_id)
        self.assertNotIn("alpha", packed_state)
        self.assertNotIn("alpha", state)

        for world in (runtime_world, control_world):
            entity = world.require("goal")
            entity.position = (entity.position[0], 3.25, entity.position[2])
            entity.scale = (1.1, 0.9, 1.3)
            entity.velocity = (entity.velocity[0], 1.75, entity.velocity[2])
        for _ in range(7):
            state, _ = self.document.step_play(set())
            control_world.step(InputFrame3D())
        self.assertEqual(runtime_world.state_hash(), control_world.state_hash())

        retained_preview = next(
            preview
            for preview in self.viewport._polar_population_previews
            if preview.item is retained_item
        )
        self.viewport.set_playing(True)
        with patch(
            "ugts_kc3.editor.scene_view.polar_population_instance",
            wraps=polar_population_instance,
        ) as generated:
            self.viewport.set_runtime_state(state)
        self.app.processEvents()

        self.assertEqual(generated.call_count, len(authored_items))
        self.assertLessEqual(generated.call_count, 64)
        first_call = generated.call_args_list[0]
        runtime_prototype = first_call.args[0]
        self.assertIs(first_call.args[1], retained_preview.group)
        self.assertIs(first_call.kwargs["lut"], retained_preview.lut)
        self.assertEqual(first_call.kwargs["component"].pose_word, state["goal"]["packed_kinematic"]["pose_word"])
        self.assertEqual(runtime_prototype.transform.translation[1], 3.25)
        self.assertEqual(runtime_prototype.transform.scale, (1.1, 0.9, 1.3))
        self.assertEqual(runtime_prototype.velocity[1], 1.75)

        updated_items = _copies(self.viewport)
        self.assertIs(updated_items[display_id], retained_item)
        self.assertNotEqual(_face_signature(retained_item), authored_faces)
        self.assertEqual(retained_item.data(0), "goal")
        self.assertEqual(retained_item.data(3), "polar_population_copy")
        self.assertEqual(retained_item.data(5), display_id)
        self.assertEqual(retained_item.toolTip(), authored_tooltip)
        self.assertTrue(retained_item.isSelected())
        self.assertEqual(len(runtime_world.entities), len(self.project.nodes))
        self.assertFalse(
            any("__polar_display_" in entity_id for entity_id in runtime_world.entities)
        )
        self.assertNotIn("previous_pose_word", json.dumps(runtime_world.snapshot()))
        self.assertEqual(self.project.to_dict(), authored_project)
        self.assertEqual(compile_polar_population_pack_bytes(self.project), authored_pack)

    def test_visibility_reappears_and_stop_restores_authored_preview(self) -> None:
        authored_items = _copies(self.viewport)
        display_id, retained_item = next(iter(authored_items.items()))
        authored_faces = _face_signature(retained_item)
        authored_tooltip = retained_item.toolTip()
        self.document.begin_play()
        runtime_world = self.document._runtime_world
        self.assertIsNotNone(runtime_world)
        assert runtime_world is not None
        self.viewport.set_playing(True)

        state, _ = self.document.step_play(set())
        self.viewport.set_runtime_state(state)
        goal = runtime_world.require("goal")
        goal.active = False
        state, _ = self.document.step_play(set())
        self.viewport.set_runtime_state(state)
        self.assertFalse(retained_item.isVisible())
        self.assertIs(retained_item.scene(), self.viewport.scene())
        self.assertNotIn("goal", self.viewport._mesh_items)

        goal.active = True
        state, _ = self.document.step_play(set())
        self.viewport.set_runtime_state(state)
        self.assertTrue(retained_item.isVisible())
        self.assertIs(_copies(self.viewport)[display_id], retained_item)
        self.assertIn("goal", self.viewport._mesh_items)

        goal.alive = False
        state, _ = self.document.step_play(set())
        self.assertNotIn("goal", state)
        self.viewport.set_runtime_state(state)
        self.assertFalse(retained_item.isVisible())
        self.assertIs(retained_item.scene(), self.viewport.scene())
        self.assertNotIn("goal", self.viewport._mesh_items)

        goal.alive = True
        state, _ = self.document.step_play(set())
        self.viewport.set_runtime_state(state)
        self.assertTrue(retained_item.isVisible())
        self.assertIs(_copies(self.viewport)[display_id], retained_item)
        self.assertEqual(retained_item.data(0), "goal")
        self.assertEqual(retained_item.data(3), "polar_population_copy")
        self.assertEqual(retained_item.toolTip(), authored_tooltip)
        self.assertTrue(retained_item.isSelected())
        self.assertIn("goal", self.viewport._mesh_items)

        valid_goal_state = dict(state["goal"])
        valid_packed_state = dict(valid_goal_state["packed_kinematic"])
        malformed_states = (
            {
                **valid_goal_state,
                "packed_kinematic": {**valid_packed_state, "pose_word": -1},
            },
            {
                **valid_goal_state,
                "packed_kinematic": {
                    **valid_packed_state,
                    "profile_id": "wrong_profile",
                },
            },
            {**valid_goal_state, "scale": (1.0,)},
        )
        for malformed_goal_state in malformed_states:
            with self.subTest(malformed_goal_state=malformed_goal_state):
                self.viewport.set_runtime_state(
                    {**state, "goal": malformed_goal_state}
                )
                self.assertFalse(retained_item.isVisible())
                self.viewport.set_runtime_state(state)
                self.assertTrue(retained_item.isVisible())
                self.assertIs(_copies(self.viewport)[display_id], retained_item)

        self.document.stop_play()
        self.viewport.set_playing(False)
        self.viewport.set_runtime_state(None)
        self.app.processEvents()
        restored_item = _copies(self.viewport)[display_id]
        self.assertIsNot(restored_item, retained_item)
        self.assertEqual(_face_signature(restored_item), authored_faces)
        self.assertEqual(restored_item.data(0), "goal")
        self.assertEqual(restored_item.data(3), "polar_population_copy")
        self.assertEqual(restored_item.toolTip(), authored_tooltip)
        self.assertTrue(restored_item.isSelected())
        self.assertEqual(len(self.viewport.gizmo_handles), 3)


if __name__ == "__main__":
    unittest.main()
