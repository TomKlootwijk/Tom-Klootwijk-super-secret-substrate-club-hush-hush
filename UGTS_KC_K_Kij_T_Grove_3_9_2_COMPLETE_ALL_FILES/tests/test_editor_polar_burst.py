# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
import json
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

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import EditorDocument, SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.editor.scene_view import SceneViewport
from ugts_kc3.mobile3d import Mobile3DProject, Transform3DRecord
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import (
    POLAR_BURST_MATH_SCHEDULE,
    collect_polar_population_project_spec,
    polar_burst_phase,
    polar_population_instance,
    polar_population_preset,
)
from ugts_kc3.polar_population_pack import compile_polar_population_pack_bytes
from ugts_kc3.templates3d import blank_mobile3d_project


BURST_KEYS = {
    "preset",
    "instance_count",
    "seed",
    "start_distance",
    "end_distance",
    "duration_seconds",
    "angle_step_turns",
    "angle_jitter_turns",
    "height_arc",
    "scale_min",
    "scale_max",
}


def _project(*, burst: bool, count: int = 96) -> Mobile3DProject:
    project = blank_mobile3d_project("Radial Burst Editor", "Test")
    profile = LogPolarProfile(r0=2.0, rho_min=-5.0, rho_max=5.0)
    motion_range = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    component = codec.component(
        PolarPose(
            math.log(3.0 / profile.r0),
            math.radians(15.0),
            321,
            math.radians(35.0),
        ),
        PolarMotion(0.15, math.tau * 0.25, 0.05, math.tau * -0.02),
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
                **(
                    {
                        "polar_population": polar_population_preset(
                            "burst", instance_count=count, seed=23
                        ).to_dict()
                    }
                    if burst
                    else {}
                ),
            },
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _copy_items(viewport: SceneViewport):
    return tuple(
        item
        for item in viewport.scene().items()
        if item.data(3) == "polar_population_copy"
    )


class EditorPolarBurstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_inspector_uses_discriminated_rows_and_atomic_burst_metadata(self) -> None:
        window = EditorMainWindow()
        try:
            window.document.create(_project(burst=False))
            window.undo_stack.clear()
            window.document.set_selection(SelectionRef("node", "goal"))
            self.app.processEvents()
            inspector = window.inspector

            burst_index = inspector.polar_population_preset.findData("burst")
            self.assertGreaterEqual(burst_index, 0)
            self.assertEqual(
                inspector.polar_population_preset.itemText(burst_index),
                "Radial Burst (loops)",
            )
            inspector.polar_population_preset.setCurrentIndex(burst_index)
            self.app.processEvents()

            self.assertEqual(inspector.polar_population_count.maximum(), 512)
            self.assertEqual(inspector.polar_population_count.value(), 32)
            self.assertEqual(
                inspector.polar_population_form.labelForField(
                    inspector.polar_population_count
                ).text(),
                "Objects in burst",
            )
            self.assertEqual(
                inspector.polar_population_form.labelForField(
                    inspector.polar_population_start_distance
                ).text(),
                "Start distance (0 = core)",
            )
            self.assertEqual(
                inspector.polar_population_form.labelForField(
                    inspector.polar_population_duration
                ).text(),
                "Loop time (seconds)",
            )
            self.assertTrue(
                inspector.polar_population_form.isRowVisible(
                    inspector.polar_population_start_distance
                )
            )
            self.assertTrue(
                inspector.polar_population_form.isRowVisible(
                    inspector.polar_population_end_distance
                )
            )
            self.assertTrue(
                inspector.polar_population_form.isRowVisible(
                    inspector.polar_population_duration
                )
            )
            self.assertTrue(
                inspector.polar_population_form.isRowVisible(
                    inspector.polar_population_height_arc
                )
            )
            self.assertFalse(
                inspector.polar_population_form.isRowVisible(
                    inspector.polar_population_radius_min
                )
            )
            self.assertFalse(
                inspector.polar_population_form.isRowVisible(
                    inspector.polar_population_height
                )
            )
            self.assertFalse(
                inspector.polar_population_advanced_form.isRowVisible(
                    inspector.polar_population_radial_rate
                )
            )
            self.assertEqual(inspector.polar_population_math.text(), POLAR_BURST_MATH_SCHEDULE)
            self.assertIn(
                "halfway through", inspector.polar_population_explanation.text()
            )

            created = dict(window.document.entity().metadata["polar_population"])
            self.assertEqual(set(created), BURST_KEYS)
            self.assertEqual(created["preset"], "burst")
            self.assertEqual(created["instance_count"], 32)
            self.assertEqual(window.undo_stack.count(), 1)
            self.assertIn("Radial Burst (loops)", window.undo_stack.command(0).text())
            made_many = next(
                inspector_item
                for inspector_item in (
                    window.assets_project.assets.topLevelItem(index)
                    for index in range(
                        window.assets_project.assets.topLevelItemCount()
                    )
                )
                if inspector_item.text(0) == "Made Many"
            )
            self.assertIn("Radial Burst (loops)", made_many.child(0).text(1))
            compile_polar_population_pack_bytes(window.document.project)

            window.undo_stack.undo()
            self.app.processEvents()
            self.assertNotIn("polar_population", window.document.entity().metadata)
            window.undo_stack.redo()
            self.app.processEvents()
            self.assertEqual(
                window.document.entity().metadata["polar_population"], created
            )

            command_count = window.undo_stack.count()
            inspector.polar_population_start_distance.setValue(8.0)
            inspector.polar_population_start_distance.editingFinished.emit()
            self.app.processEvents()
            self.assertEqual(window.undo_stack.count(), command_count)
            self.assertEqual(
                window.document.entity().metadata["polar_population"], created
            )
            self.assertIn("greater than its start", window.status_message.text())

            with tempfile.TemporaryDirectory() as temporary:
                saved = window.document.save(Path(temporary) / "burst.json")
                loaded = Mobile3DProject.load(saved)
            loaded_goal = next(node for node in loaded.nodes if node.id == "goal")
            self.assertEqual(loaded_goal.metadata["polar_population"], created)

            ring_index = inspector.polar_population_preset.findData("ring")
            inspector.polar_population_preset.setCurrentIndex(ring_index)
            self.app.processEvents()
            self.assertEqual(inspector.polar_population_count.maximum(), 4096)
            self.assertEqual(
                inspector.polar_population_form.labelForField(
                    inspector.polar_population_count
                ).text(),
                "Objects in group",
            )
            self.assertTrue(
                inspector.polar_population_form.isRowVisible(
                    inspector.polar_population_radius_min
                )
            )
            self.assertFalse(
                inspector.polar_population_form.isRowVisible(
                    inspector.polar_population_start_distance
                )
            )
            ring = window.document.entity().metadata["polar_population"]
            self.assertEqual(ring["preset"], "ring")
            self.assertIn("radius_min", ring)
            self.assertNotIn("start_distance", ring)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_stopped_midpoint_and_play_use_retained_items_with_real_fixed_tick(self) -> None:
        project = _project(burst=True)
        authored_json = project.to_dict()
        authored_pack = compile_polar_population_pack_bytes(project)
        document = EditorDocument()
        document.create(project)
        generated: list[tuple[dict[str, object], object]] = []

        def tracked_instance(*args, **kwargs):
            instance = polar_population_instance(*args, **kwargs)
            generated.append((dict(kwargs), instance))
            return instance

        with patch(
            "ugts_kc3.editor.scene_view.polar_population_instance",
            side_effect=tracked_instance,
        ):
            viewport = SceneViewport()
            viewport.set_document(document)
            viewport.set_selected_id("goal")
            self.app.processEvents()
        try:
            retained = tuple(viewport._polar_population_previews)
            retained_items = tuple(preview.item for preview in retained)
            self.assertGreater(len(retained), 0)
            self.assertLessEqual(len(retained), 64)
            self.assertEqual(len(generated), len(retained))
            group = collect_polar_population_project_spec(project).groups[0]
            midpoint = polar_burst_phase(group)
            self.assertEqual(midpoint.fixed_tick, midpoint.duration_ticks // 2)
            self.assertTrue(all("fixed_tick" not in kwargs for kwargs, _ in generated))
            self.assertTrue(
                all(instance.fixed_tick == midpoint.fixed_tick for _, instance in generated)
            )

            document.begin_play()
            runtime_world = document._runtime_world
            self.assertIsNotNone(runtime_world)
            assert runtime_world is not None
            viewport.set_playing(True)
            for _ in range(9):
                state, _ = document.step_play(set())

            self.assertEqual(
                state["goal"]["make_many_fixed_tick"], runtime_world.tick
            )
            self.assertNotIn("make_many_fixed_tick", state["floor"])
            self.assertNotIn("make_many_fixed_tick", state["player"])
            self.assertNotIn("make_many_fixed_tick", runtime_world.state)
            self.assertNotIn(
                "make_many_fixed_tick", json.dumps(runtime_world.snapshot())
            )
            self.assertNotIn("alpha", state["goal"])
            self.assertNotIn("alpha", state["goal"]["packed_kinematic"])

            with patch(
                "ugts_kc3.editor.scene_view.polar_population_instance",
                wraps=polar_population_instance,
            ) as runtime_instances:
                viewport.set_runtime_state(state)
            self.app.processEvents()
            self.assertEqual(runtime_instances.call_count, len(retained))
            self.assertTrue(
                all(
                    call.kwargs["fixed_tick"] == runtime_world.tick
                    for call in runtime_instances.call_args_list
                )
            )
            self.assertEqual(
                tuple(preview.item for preview in viewport._polar_population_previews),
                retained_items,
            )
            self.assertTrue(
                all(item.data(3) == "polar_population_copy" for item in retained_items)
            )
            self.assertTrue(all(item.data(0) == "goal" for item in retained_items))
            self.assertTrue(all(item.data(5) for item in retained_items))
            self.assertTrue(all(item.toolTip() for item in retained_items))
            self.assertTrue(all(item.isSelected() for item in retained_items))
            self.assertEqual(len(runtime_world.entities), len(project.nodes))
            self.assertFalse(
                any("__polar_display_" in entity_id for entity_id in runtime_world.entities)
            )

            runtime_world.polar_population_runtime.set_copies_visible("goal", False)
            hidden_state, _ = document.step_play(set())
            viewport.set_runtime_state(hidden_state)
            self.assertTrue(all(not item.isVisible() for item in retained_items))
            self.assertIn("goal", viewport._mesh_items)
            runtime_world.polar_population_runtime.set_copies_visible("goal", True)
            visible_state, _ = document.step_play(set())
            viewport.set_runtime_state(visible_state)
            self.assertTrue(any(item.isVisible() for item in retained_items))
            self.assertIn("goal", viewport._mesh_items)

            document.stop_play()
            viewport.set_playing(False)
            stopped_calls: list[dict[str, object]] = []

            def tracked_stopped(*args, **kwargs):
                stopped_calls.append(dict(kwargs))
                return polar_population_instance(*args, **kwargs)

            with patch(
                "ugts_kc3.editor.scene_view.polar_population_instance",
                side_effect=tracked_stopped,
            ):
                viewport.set_runtime_state(None)
            self.app.processEvents()
            self.assertTrue(stopped_calls)
            self.assertTrue(
                all("fixed_tick" not in kwargs for kwargs in stopped_calls)
            )
            self.assertEqual(project.to_dict(), authored_json)
            self.assertEqual(compile_polar_population_pack_bytes(project), authored_pack)
        finally:
            document.stop_play()
            viewport.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
