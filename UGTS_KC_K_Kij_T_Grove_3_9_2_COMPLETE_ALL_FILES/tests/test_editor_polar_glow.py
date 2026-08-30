# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
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

from PySide6.QtWidgets import QApplication, QLabel

from ugts_kc3.editor.document import EditorDocument, SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.editor.scene_view import SceneViewport, _PerspectiveProjector
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import (
    POLAR_POPULATION_PRESETS,
    collect_polar_population_project_spec,
    polar_population_glow_sample,
    polar_population_instance,
    polar_population_preset,
)
from ugts_kc3.templates3d import blank_mobile3d_project


def _project(
    preset: str = "ring",
    *,
    glow: dict[str, float | bool] | None = None,
) -> Mobile3DProject:
    project = blank_mobile3d_project("Distance Glow Editor", "Test")
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
        profile_id="glow_test",
    )
    project.metadata["packed_kinematic_profiles"] = {
        "glow_test": {
            "profile": profile.to_dict(),
            "motion_range": motion.to_dict(),
            "lut_resolution": 64,
        }
    }
    recipe = polar_population_preset(preset, instance_count=16, seed=29).to_dict()
    if glow is not None:
        recipe["glow_by_distance"] = dict(glow)
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


class EditorPolarGlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_optional_section_roundtrips_and_survives_every_make_many_preset(
        self,
    ) -> None:
        window = EditorMainWindow()
        try:
            window.document.create(_project())
            window.undo_stack.clear()
            window.document.set_selection(SelectionRef("node", "goal"))
            self.app.processEvents()
            inspector = window.inspector

            self.assertEqual(inspector.polar_population_glow_box.title(), "Glow by distance")
            self.assertTrue(inspector.polar_population_glow_box.isVisibleTo(inspector))
            self.assertFalse(inspector.polar_population_glow_enabled.isChecked())
            self.assertFalse(inspector.polar_population_glow_start_distance.isEnabled())
            self.assertEqual(inspector.polar_population_glow_start_distance.value(), 0.0)
            self.assertEqual(inspector.polar_population_glow_end_distance.value(), 4.0)
            self.assertEqual(inspector.polar_population_glow_strength.value(), 1.0)
            self.assertAlmostEqual(
                inspector.polar_population_glow_end_distance.maximum(), 8.0, places=5
            )
            labels = tuple(
                label.text()
                for field in (
                    inspector.polar_population_glow_start_distance,
                    inspector.polar_population_glow_end_distance,
                    inspector.polar_population_glow_strength,
                )
                if isinstance(
                    label := inspector.polar_population_glow_form.labelForField(field),
                    QLabel,
                )
            )
            self.assertEqual(
                labels, ("Start distance", "End distance", "Glow strength")
            )
            explanation = inspector.polar_population_glow_explanation.text()
            self.assertIn("compact polar distance", explanation)
            self.assertIn("repeatable World number", explanation)
            self.assertIn("Bayer is still the final screen finish", explanation)
            self.assertNotIn(
                "glow_by_distance",
                window.document.entity().metadata["polar_population"],
            )

            inspector.polar_population_glow_start_distance.setValue(0.5)
            inspector.polar_population_glow_end_distance.setValue(6.0)
            inspector.polar_population_glow_strength.setValue(1.25)
            inspector.polar_population_glow_enabled.setChecked(True)
            self.app.processEvents()

            expected = {
                "start_distance": 0.5,
                "end_distance": 6.0,
                "strength": 1.25,
            }
            recipe = window.document.entity().metadata["polar_population"]
            self.assertEqual(recipe["glow_by_distance"], expected)
            self.assertEqual(set(recipe["glow_by_distance"]), set(expected))
            self.assertEqual(window.undo_stack.count(), 1)
            self.assertTrue(inspector.polar_population_glow_start_distance.isEnabled())

            for preset in ("spiral", "polar_field", "burst", "ring"):
                with self.subTest(preset=preset):
                    inspector.polar_population_preset.setCurrentIndex(
                        inspector.polar_population_preset.findData(preset)
                    )
                    self.app.processEvents()
                    recipe = window.document.entity().metadata["polar_population"]
                    self.assertEqual(recipe["preset"], preset)
                    self.assertEqual(recipe["glow_by_distance"], expected)
                    self.assertTrue(
                        inspector.polar_population_glow_box.isVisibleTo(inspector)
                    )
                    copies = tuple(
                        item
                        for item in window.viewport.scene().items()
                        if item.data(3) == "polar_population_copy"
                    )
                    self.assertTrue(copies)
                    self.assertTrue(
                        all(isinstance(item.data(6), float) for item in copies)
                    )
                    self.assertTrue(any(item.data(6) > 0.0 for item in copies))

            inspector.polar_population_glow_enabled.setChecked(False)
            self.app.processEvents()
            self.assertNotIn(
                "glow_by_distance",
                window.document.entity().metadata["polar_population"],
            )
            window.undo_stack.undo()
            self.app.processEvents()
            self.assertEqual(
                window.document.entity().metadata["polar_population"][
                    "glow_by_distance"
                ],
                expected,
            )
            self.assertTrue(inspector.polar_population_glow_enabled.isChecked())

            inspector.polar_population_preset.setCurrentIndex(
                inspector.polar_population_preset.findData("off")
            )
            self.app.processEvents()
            self.assertNotIn("polar_population", window.document.entity().metadata)
            self.assertFalse(inspector.polar_population_glow_box.isVisibleTo(inspector))
            window.undo_stack.undo()
            self.app.processEvents()
            self.assertEqual(
                window.document.entity().metadata["polar_population"][
                    "glow_by_distance"
                ],
                expected,
            )

            with tempfile.TemporaryDirectory() as temporary:
                saved = window.document.save(Path(temporary) / "distance_glow.json")
                loaded = Mobile3DProject.load(saved)
            loaded_goal = next(node for node in loaded.nodes if node.id == "goal")
            self.assertEqual(
                loaded_goal.metadata["polar_population"]["glow_by_distance"],
                expected,
            )
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_document_rejects_invalid_or_out_of_profile_glow_atomically(self) -> None:
        document = EditorDocument()
        document.create(_project())
        selection = SelectionRef("node", "goal")
        before = document.entity(selection).to_dict()

        invalid = (
            (
                {"start_distance": 2.0, "end_distance": 2.0, "strength": 1.0},
                "greater than its start",
            ),
            (
                {"start_distance": 0.0, "end_distance": 4.0, "strength": 4.1},
                "between 0 and 4",
            ),
            (
                {"start_distance": 0.0, "end_distance": 9.0, "strength": 1.0},
                "profile maximum",
            ),
            (
                {"start_distance": 0.125, "end_distance": 4.0, "strength": 1.0},
                "profile core",
            ),
        )
        for glow, message in invalid:
            with self.subTest(glow=glow):
                with self.assertRaisesRegex(ValueError, message):
                    document.record_with_polar_population(
                        selection,
                        {"preset": "ring", "glow_by_distance": glow},
                    )
                self.assertEqual(document.entity(selection).to_dict(), before)

        with self.assertRaisesRegex(ValueError, "missing field"):
            document.record_with_polar_population(
                selection,
                {
                    "preset": "ring",
                    "glow_by_distance": {
                        "start_distance": 0.0,
                        "end_distance": 4.0,
                    },
                },
            )

    def test_grow_glowing_copies_is_child_facing_strict_and_undoable(self) -> None:
        window = EditorMainWindow()
        try:
            window.document.create(
                _project(
                    glow={
                        "start_distance": 0.0,
                        "end_distance": 4.0,
                        "strength": 1.25,
                    }
                )
            )
            window.document.set_selection(SelectionRef("node", "goal"))
            window.undo_stack.clear()
            self.app.processEvents()
            checkbox = window.inspector.polar_population_glow_grow_copies

            self.assertEqual(checkbox.text(), "Grow glowing copies")
            self.assertTrue(checkbox.isEnabled())
            self.assertFalse(checkbox.isChecked())
            tooltip = checkbox.toolTip()
            self.assertIn("Generated display copies only", tooltip)
            self.assertIn("real object and its collider stay unchanged", tooltip)
            self.assertIn("1x..5x", tooltip)
            self.assertNotIn(
                "grow_copies",
                window.document.entity().metadata["polar_population"][
                    "glow_by_distance"
                ],
            )

            checkbox.setChecked(True)
            self.app.processEvents()
            expected = {
                "start_distance": 0.0,
                "end_distance": 4.0,
                "strength": 1.25,
                "grow_copies": True,
            }
            self.assertEqual(
                window.document.entity().metadata["polar_population"][
                    "glow_by_distance"
                ],
                expected,
            )
            self.assertEqual(window.undo_stack.count(), 1)

            window.undo_stack.undo()
            self.app.processEvents()
            self.assertFalse(checkbox.isChecked())
            self.assertNotIn(
                "grow_copies",
                window.document.entity().metadata["polar_population"][
                    "glow_by_distance"
                ],
            )
            window.undo_stack.redo()
            self.app.processEvents()
            self.assertTrue(checkbox.isChecked())

            window.inspector.polar_population_preset.setCurrentIndex(
                window.inspector.polar_population_preset.findData("burst")
            )
            self.app.processEvents()
            self.assertEqual(
                window.document.entity().metadata["polar_population"][
                    "glow_by_distance"
                ],
                expected,
            )

            with tempfile.TemporaryDirectory() as temporary:
                saved = window.document.save(Path(temporary) / "grow_glow.json")
                loaded = Mobile3DProject.load(saved)
            loaded_goal = next(node for node in loaded.nodes if node.id == "goal")
            self.assertEqual(
                loaded_goal.metadata["polar_population"]["glow_by_distance"],
                expected,
            )

            selection = SelectionRef("node", "goal")
            before = window.document.entity(selection).to_dict()
            with self.assertRaisesRegex(ValueError, "true or false"):
                window.document.record_with_polar_population(
                    selection,
                    {
                        "preset": "burst",
                        "glow_by_distance": expected | {"grow_copies": 1},
                    },
                )
            self.assertEqual(window.document.entity(selection).to_dict(), before)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_disabled_defaults_have_no_key_and_selection_clears_stale_controls(
        self,
    ) -> None:
        for preset in POLAR_POPULATION_PRESETS:
            with self.subTest(preset=preset):
                self.assertNotIn(
                    "glow_by_distance", polar_population_preset(preset).to_dict()
                )

        window = EditorMainWindow()
        try:
            window.document.create(
                _project(
                    "burst",
                    glow={
                        "start_distance": 0.0,
                        "end_distance": 4.0,
                        "strength": 2.0,
                    },
                )
            )
            window.document.set_selection(SelectionRef("node", "goal"))
            self.app.processEvents()
            self.assertTrue(window.inspector.polar_population_glow_enabled.isChecked())

            window.document.set_selection(SelectionRef("node", "floor"))
            self.app.processEvents()
            self.assertFalse(window.inspector.polar_population_glow_enabled.isChecked())
            self.assertEqual(
                window.inspector.polar_population_glow_start_distance.value(), 0.0
            )
            self.assertEqual(
                window.inspector.polar_population_glow_end_distance.value(), 4.0
            )
            self.assertEqual(window.inspector.polar_population_glow_strength.value(), 1.0)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_stopped_and_play_previews_use_exact_shared_glow_on_retained_items(
        self,
    ) -> None:
        project = _project(
            "burst",
            glow={
                "start_distance": 0.0,
                "end_distance": 8.0,
                "strength": 4.0,
                "grow_copies": True,
            },
        )
        goal = next(node for node in project.nodes if node.id == "goal")
        project.materials[goal.material_id] = replace(
            project.materials[goal.material_id],
            base_color=(0.12, 0.2, 0.3, 1.0),
            emissive=(0.0, 0.0, 0.0),
        )
        project.validate()
        document = EditorDocument()
        document.create(project)
        samples: list[tuple[int, object]] = []

        def tracked_glow(*args, **kwargs):
            sample = polar_population_glow_sample(*args, **kwargs)
            samples.append((int(kwargs["index"]), sample))
            return sample

        with (
            patch(
                "ugts_kc3.polar_population.polar_population_glow_sample",
                side_effect=tracked_glow,
            ),
            patch(
                "ugts_kc3.editor.scene_view.polar_population_glow_sample",
                side_effect=tracked_glow,
            ),
        ):
            viewport = SceneViewport()
            viewport.set_document(document)
            self.app.processEvents()
        try:
            retained = tuple(viewport._polar_population_previews)
            retained_items = tuple(preview.item for preview in retained)
            prototype_samples = tuple(
                sample for index, sample in samples if index == 0
            )
            copy_samples = tuple(
                sample for index, sample in samples if index != 0
            )
            self.assertTrue(retained)
            self.assertEqual(len(prototype_samples), 1)
            self.assertEqual(len(copy_samples), len(retained))
            self.assertTrue(all(sample is not None for sample in copy_samples))
            prototype_sample = prototype_samples[0]
            assert prototype_sample is not None
            prototype_item = viewport._mesh_items["goal"]
            self.assertAlmostEqual(
                prototype_item.data(6), prototype_sample.glow, places=7
            )
            self.assertEqual(prototype_item.data(7), 1.0)
            for preview, sample in zip(retained, copy_samples):
                assert sample is not None
                self.assertAlmostEqual(preview.item.data(6), sample.glow, places=7)
                self.assertAlmostEqual(
                    preview.item.data(7), sample.display_scale_multiplier, places=7
                )
                self.assertGreaterEqual(sample.display_scale_multiplier, 1.0)
                self.assertLessEqual(sample.display_scale_multiplier, 5.0)
                self.assertIn("exact compact preview", preview.item.toolTip())

            target_index = max(
                range(len(copy_samples)),
                key=lambda index: (
                    0.0
                    if copy_samples[index] is None
                    else copy_samples[index].glow
                ),
            )
            target_preview = retained[target_index]
            target_sample = copy_samples[target_index]
            assert target_sample is not None
            self.assertGreater(target_sample.glow, 0.0)
            self.assertGreater(target_sample.display_scale_multiplier, 1.0)
            instance = polar_population_instance(
                target_preview.prototype,
                target_preview.group,
                target_preview.index,
                lut=target_preview.lut,
            )
            base_project = _project(
                "burst",
                glow={
                    "start_distance": 0.0,
                    "end_distance": 8.0,
                    "strength": 4.0,
                },
            )
            base_goal = next(node for node in base_project.nodes if node.id == "goal")
            base_project.materials[base_goal.material_id] = replace(
                base_project.materials[base_goal.material_id],
                base_color=(0.12, 0.2, 0.3, 1.0),
                emissive=(0.0, 0.0, 0.0),
            )
            base_project.validate()
            base_group = collect_polar_population_project_spec(base_project).groups[0]
            base_prototype = base_project.nodes[base_group.prototype_node_index]
            base_instance = polar_population_instance(
                base_prototype,
                base_group,
                target_preview.index,
                lut=target_preview.lut,
            )
            self.assertEqual(instance.translation, base_instance.translation)
            for grown, base in zip(instance.scale, base_instance.scale):
                self.assertAlmostEqual(
                    grown,
                    base * target_sample.display_scale_multiplier,
                    places=5,
                )
            self.assertEqual(
                viewport._mesh_runtime_transforms["goal"][2],
                goal.transform.scale,
            )
            runtime = {
                "translation": instance.translation,
                "rotation": instance.rotation,
                "scale": instance.scale,
            }
            projector = _PerspectiveProjector(project, 1280.0, 720.0)
            base_faces = sorted(
                viewport._project_node_faces(
                    project,
                    target_preview.prototype,
                    projector,
                    runtime,
                ),
                key=lambda face: face[0],
                reverse=True,
            )
            glowing_faces = target_preview.item.faces
            self.assertEqual(len(glowing_faces), len(base_faces))
            self.assertTrue(
                any(
                    glow_color.redF() > base_color.redF()
                    or glow_color.greenF() > base_color.greenF()
                    or glow_color.blueF() > base_color.blueF()
                    for (_, _, glow_color), (_, _, base_color) in zip(
                        glowing_faces, base_faces
                    )
                )
            )

            document.begin_play()
            runtime_world = document._runtime_world
            self.assertIsNotNone(runtime_world)
            assert runtime_world is not None
            viewport.set_playing(True)
            for _ in range(3):
                state, _events = document.step_play(set())
            runtime_samples: list[tuple[int, object]] = []

            def tracked_runtime_glow(*args, **kwargs):
                sample = polar_population_glow_sample(*args, **kwargs)
                runtime_samples.append((int(kwargs["index"]), sample))
                return sample

            with (
                patch(
                    "ugts_kc3.polar_population.polar_population_glow_sample",
                    side_effect=tracked_runtime_glow,
                ),
                patch(
                    "ugts_kc3.editor.scene_view.polar_population_glow_sample",
                    side_effect=tracked_runtime_glow,
                ),
            ):
                viewport.set_runtime_state(state)
            self.app.processEvents()
            runtime_prototype_samples = tuple(
                sample for index, sample in runtime_samples if index == 0
            )
            runtime_copy_samples = tuple(
                sample for index, sample in runtime_samples if index != 0
            )
            self.assertEqual(len(runtime_prototype_samples), 1)
            self.assertEqual(len(runtime_copy_samples), len(retained))
            self.assertEqual(
                tuple(preview.item for preview in viewport._polar_population_previews),
                retained_items,
            )
            runtime_prototype_sample = runtime_prototype_samples[0]
            assert runtime_prototype_sample is not None
            self.assertAlmostEqual(
                viewport._mesh_items["goal"].data(6),
                runtime_prototype_sample.glow,
                places=7,
            )
            self.assertEqual(viewport._mesh_items["goal"].data(7), 1.0)
            for preview, sample in zip(retained, runtime_copy_samples):
                assert sample is not None
                self.assertAlmostEqual(preview.item.data(6), sample.glow, places=7)
                self.assertAlmostEqual(
                    preview.item.data(7), sample.display_scale_multiplier, places=7
                )
            self.assertEqual(
                viewport._mesh_runtime_transforms["goal"][2],
                goal.transform.scale,
            )
            self.assertEqual(len(runtime_world.entities), len(project.nodes))
        finally:
            document.stop_play()
            viewport.close()
            self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
