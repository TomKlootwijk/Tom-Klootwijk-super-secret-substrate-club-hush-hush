# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
import math
import os
from pathlib import Path
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from PySide6.QtWidgets import QApplication

from ugts_kc3.editor.document import SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import (
    collect_polar_population_project_spec,
    polar_burst_phase,
    polar_population_glow_sample,
    polar_population_instance,
    polar_population_preset,
)
from ugts_kc3.polar_population_pack import compile_polar_population_pack_bytes
from ugts_kc3.polarpack import quantized_profile_lut
from ugts_kc3.templates3d import blank_mobile3d_project


def _project(
    preset: str = "polar_field",
    *,
    instance_count: int = 96,
    seed: int = 29,
    glow: bool = True,
    grow: bool = True,
) -> Mobile3DProject:
    project = blank_mobile3d_project("Polar Field Meter", "Test")
    profile = LogPolarProfile(
        r0=1.0,
        rho_min=math.log(0.25),
        rho_max=math.log(8.0),
        core_radius=0.25,
    )
    motion = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion)
    component = codec.component(
        PolarPose(math.log(2.0), math.radians(20.0), 7, math.radians(35.0)),
        PolarMotion(0.0, math.tau * 0.2, 0.0, 0.0),
        profile_id="field_meter",
    )
    project.metadata["packed_kinematic_profiles"] = {
        "field_meter": {
            "profile": profile.to_dict(),
            "motion_range": motion.to_dict(),
            "lut_resolution": 64,
        }
    }
    recipe = polar_population_preset(
        preset,
        instance_count=instance_count,
        seed=seed,
    ).to_dict()
    if glow:
        recipe["glow_by_distance"] = {
            "start_distance": 0.0,
            "end_distance": 8.0,
            "strength": 4.0,
            **({"grow_copies": True} if grow else {}),
        }
    project.nodes = tuple(
        replace(
            node,
            angular_velocity=(0.0, 0.0, 0.0),
            metadata={
                **node.metadata,
                "packed_kinematic": component.to_dict(),
                "polar_population": recipe,
            },
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _expected_samples(
    project: Mobile3DProject,
    *,
    fixed_tick: int | None = None,
) -> tuple[object, tuple[object, ...]]:
    group = collect_polar_population_project_spec(project).groups[0]
    prototype = project.nodes[group.prototype_node_index]
    lut = quantized_profile_lut(group.profile)
    prototype_sample = polar_population_glow_sample(
        group,
        index=0,
        pose_word=group.component.pose_word,
        lut=lut,
    )
    assert prototype_sample is not None
    samples = []
    for index in range(1, min(64, group.recipe.instance_count - 1) + 1):
        instance = polar_population_instance(
            prototype,
            group,
            index,
            lut=lut,
            fixed_tick=fixed_tick,
        )
        sample = instance.glow_sample or polar_population_glow_sample(
            group,
            index=instance.index,
            pose_word=instance.pose_word,
            lut=lut,
        )
        assert sample is not None
        samples.append(sample)
    return prototype_sample, tuple(samples)


class EditorPolarFieldMeterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_state_matches_core_and_uses_count_stable_64_sample_prefix(self) -> None:
        project = _project(instance_count=96)
        window = EditorMainWindow()
        try:
            window.document.create(project)
            window.undo_stack.clear()
            before_json = window.document.project.to_dict()
            before_pack = compile_polar_population_pack_bytes(window.document.project)
            selection = SelectionRef("node", "goal")
            state = window.document.polar_population_state(selection)
            self.assertIsNotNone(state)
            assert state is not None
            field = state["field_preview"]
            self.assertIsNotNone(field)
            assert field is not None
            prototype, copies = _expected_samples(project)
            self.assertEqual(field["preview_label"], "Stopped preview")
            self.assertEqual(field["distance_label"], "Movement distance")
            self.assertEqual(field["prototype_glow"], prototype.glow)
            self.assertEqual(field["prototype_scale_multiplier"], 1.0)
            self.assertEqual(field["copy_glow_min"], min(item.glow for item in copies))
            self.assertEqual(field["copy_glow_max"], max(item.glow for item in copies))
            self.assertEqual(
                field["copy_scale_multiplier_min"],
                min(item.display_scale_multiplier for item in copies),
            )
            self.assertEqual(
                field["copy_scale_multiplier_max"],
                max(item.display_scale_multiplier for item in copies),
            )
            self.assertEqual(field["sampled_copies"], 64)
            self.assertEqual(field["total_copies"], 95)
            self.assertEqual(
                window.document.polar_population_state(selection)["field_preview"],
                field,
            )
            self.assertEqual(window.undo_stack.count(), 0)
            self.assertEqual(window.document.project.to_dict(), before_json)
            self.assertEqual(
                compile_polar_population_pack_bytes(window.document.project),
                before_pack,
            )

            longer = _project(instance_count=120)
            longer_window = EditorMainWindow()
            try:
                longer_window.document.create(longer)
                longer_field = longer_window.document.polar_population_state(
                    selection
                )["field_preview"]
                assert longer_field is not None
                for key in field.keys() - {"total_copies"}:
                    self.assertEqual(longer_field[key], field[key])
                self.assertEqual(longer_field["total_copies"], 119)
            finally:
                longer_window.document.set_dirty(False)
                longer_window.close()
                self.app.processEvents()

            other_seed = _project(instance_count=96, seed=30)
            other_window = EditorMainWindow()
            try:
                other_window.document.create(other_seed)
                other_field = other_window.document.polar_population_state(
                    selection
                )["field_preview"]
                assert other_field is not None
                self.assertNotEqual(
                    (
                        other_field["copy_glow_min"],
                        other_field["copy_glow_max"],
                    ),
                    (field["copy_glow_min"], field["copy_glow_max"]),
                )
            finally:
                other_window.document.set_dirty(False)
                other_window.close()
                self.app.processEvents()
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_meter_is_text_complete_read_only_and_clears_stale_state(self) -> None:
        window = EditorMainWindow()
        try:
            window.document.create(_project())
            window.undo_stack.clear()
            before_json = window.document.project.to_dict()
            before_pack = compile_polar_population_pack_bytes(window.document.project)
            window.document.set_selection(SelectionRef("node", "goal"))
            self.app.processEvents()
            meter = window.inspector.polar_population_field_meter
            self.assertTrue(meter.isVisibleTo(window.inspector))
            self.assertEqual(meter.preview_label.text(), "Stopped preview")
            self.assertIn("Movement distance", meter.distance_label.text())
            self.assertIn("Real object · Glow", meter.prototype_label.text())
            self.assertIn("visible size stays 1x", meter.prototype_label.text())
            self.assertIn("Generated copies · Glow", meter.copies_label.text())
            self.assertIn("field size", meter.copies_label.text())
            self.assertEqual(
                meter.count_label.text(),
                "64 of 95 generated copies sampled in this meter",
            )
            self.assertEqual(
                meter.count_label.accessibleName(), "Generated copies sampled"
            )
            self.assertIn(meter.prototype_label.text(), meter.accessibleDescription())
            self.assertIn(meter.copies_label.text(), meter.accessibleDescription())
            self.assertIn(meter.count_label.text(), meter.accessibleDescription())
            window.inspector.set_selection(
                window.document,
                SelectionRef("node", "goal"),
            )
            self.assertEqual(window.undo_stack.count(), 0)
            self.assertEqual(window.document.project.to_dict(), before_json)
            self.assertEqual(
                compile_polar_population_pack_bytes(window.document.project),
                before_pack,
            )

            window.document.set_selection(SelectionRef("node", "floor"))
            self.app.processEvents()
            self.assertTrue(meter.isHidden())
            self.assertEqual(meter.prototype_label.text(), "")
            self.assertEqual(meter.copies_label.text(), "")
            self.assertEqual(meter.accessibleDescription(), "")
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_burst_uses_stopped_midpoint_and_real_object_never_grows(self) -> None:
        project = _project("burst", instance_count=16)
        window = EditorMainWindow()
        try:
            window.document.create(project)
            selection = SelectionRef("node", "goal")
            state = window.document.polar_population_state(selection)
            self.assertIsNotNone(state)
            assert state is not None
            field = state["field_preview"]
            self.assertIsNotNone(field)
            assert field is not None
            group = collect_polar_population_project_spec(project).groups[0]
            midpoint = polar_burst_phase(group)
            prototype, copies = _expected_samples(
                project,
                fixed_tick=midpoint.fixed_tick,
            )
            self.assertEqual(
                field["distance_label"],
                "Local Burst distance for copies; Movement distance for real object",
            )
            self.assertEqual(field["prototype_glow"], prototype.glow)
            self.assertEqual(field["prototype_scale_multiplier"], 1.0)
            self.assertEqual(field["copy_glow_min"], min(item.glow for item in copies))
            self.assertEqual(field["copy_glow_max"], max(item.glow for item in copies))
            self.assertEqual(
                field["copy_scale_multiplier_max"],
                max(item.display_scale_multiplier for item in copies),
            )
            self.assertGreater(field["copy_scale_multiplier_max"], 1.0)
            self.assertEqual(field["sampled_copies"], 15)
            self.assertEqual(field["total_copies"], 15)

            window.document.set_selection(selection)
            self.app.processEvents()
            meter = window.inspector.polar_population_field_meter
            self.assertTrue(meter.isVisibleTo(window.inspector))
            self.assertIn("Local Burst distance", meter.distance_label.text())
            self.assertIn("Movement distance for real object", meter.distance_label.text())

            no_glow = EditorMainWindow()
            try:
                no_glow.document.create(_project(glow=False))
                no_glow.document.set_selection(selection)
                self.app.processEvents()
                no_glow_state = no_glow.document.polar_population_state(selection)
                assert no_glow_state is not None
                self.assertIsNone(no_glow_state["field_preview"])
                self.assertTrue(
                    no_glow.inspector.polar_population_field_meter.isHidden()
                )
            finally:
                no_glow.document.set_dirty(False)
                no_glow.close()
                self.app.processEvents()
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_authored_changes_refresh_or_hide_the_meter_after_the_undoable_edit(
        self,
    ) -> None:
        window = EditorMainWindow()
        try:
            window.document.create(_project())
            window.undo_stack.clear()
            selection = SelectionRef("node", "goal")
            window.document.set_selection(selection)
            self.app.processEvents()
            inspector = window.inspector
            meter = inspector.polar_population_field_meter
            initial_copies = meter.copies_label.text()

            inspector.polar_population_count.setValue(80)
            inspector.polar_population_count.editingFinished.emit()
            self.app.processEvents()
            self.assertEqual(
                meter.count_label.text(),
                "64 of 79 generated copies sampled in this meter",
            )

            inspector.polar_population_seed.setText("30")
            inspector.polar_population_seed.editingFinished.emit()
            self.app.processEvents()
            self.assertNotEqual(meter.copies_label.text(), initial_copies)

            inspector.polar_population_glow_grow_copies.setChecked(False)
            self.app.processEvents()
            self.assertTrue(meter.isVisibleTo(inspector))
            self.assertIn("field size 1x .. 1x", meter.copies_label.text())

            burst_index = inspector.polar_population_preset.findData("burst")
            inspector.polar_population_preset.setCurrentIndex(burst_index)
            self.app.processEvents()
            self.assertTrue(meter.isVisibleTo(inspector))
            self.assertIn("Local Burst distance", meter.distance_label.text())

            inspector.polar_population_glow_enabled.setChecked(False)
            self.app.processEvents()
            self.assertTrue(meter.isHidden())
            self.assertEqual(meter.copies_label.text(), "")
            self.assertEqual(window.undo_stack.count(), 5)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_multi_group_meter_samples_selected_recipe_independent_of_viewport_budget(
        self,
    ) -> None:
        project = _project(instance_count=96)
        goal = next(node for node in project.nodes if node.id == "goal")
        first = replace(
            goal,
            id="a_first",
            tags=(),
            transform=replace(goal.transform, translation=(3.0, 1.0, 3.0)),
        )
        project.nodes = (first, *project.nodes)
        project.validate()

        window = EditorMainWindow()
        try:
            window.document.create(project)
            selection = SelectionRef("node", "goal")
            window.document.set_selection(selection)
            self.app.processEvents()

            state = window.document.polar_population_state(selection)
            assert state is not None
            field = state["field_preview"]
            assert field is not None
            self.assertEqual(field["sampled_copies"], 64)
            self.assertEqual(field["total_copies"], 95)
            self.assertEqual(
                window.inspector.polar_population_field_meter.count_label.text(),
                "64 of 95 generated copies sampled in this meter",
            )

            viewport_counts: dict[str, int] = {}
            for preview in window.viewport._polar_population_previews:
                prototype_id = preview.prototype.id
                viewport_counts[prototype_id] = viewport_counts.get(prototype_id, 0) + 1
            self.assertEqual(viewport_counts.get("a_first", 0), 64)
            self.assertEqual(viewport_counts.get("goal", 0), 0)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
