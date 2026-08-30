# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
import json
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QGraphicsSimpleTextItem

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import build_android_project
from ugts_kc3.editor.document import EditorDocument, SelectionRef
from ugts_kc3.editor.main_window import EditorMainWindow
from ugts_kc3.editor.scene_view import SceneViewport
from ugts_kc3.mobile3d import Mobile3DProject, Transform3DRecord
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PackedKinematicComponent,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import (
    MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE,
    POLAR_POPULATION_MATH_SCHEDULE,
    POLAR_POPULATION_PRESETS,
    PolarDisplayInstance,
    PolarPopulationError,
    PolarPopulationRecipe,
    collect_polar_population_project_spec,
    polar_population_instance,
    polar_population_instances,
    polar_population_preset,
)
from ugts_kc3.polar_population_pack import (
    POLAR_POPULATION_HEADER_BYTES,
    POLAR_POPULATION_OPERATOR_BYTES,
    POLAR_POPULATION_PACK_ASSET,
    POLAR_POPULATION_PACK_MAGIC,
    POLAR_POPULATION_RECIPE_BYTES,
    PolarPopulationPackError,
    compile_polar_population_pack_bytes,
    inspect_polar_population_pack,
)
from ugts_kc3.polarpack import quantized_profile_lut
from ugts_kc3.templates3d import blank_mobile3d_project


def _project(
    *,
    count: int = 64,
    preset: str = "ring",
    root_seed: int = 17,
    recipe_seed: int = 23,
) -> Mobile3DProject:
    project = blank_mobile3d_project("Polar Population", "Test")
    profile = LogPolarProfile(r0=2.0, rho_min=-5.0, rho_max=5.0)
    motion_range = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    component = codec.component(
        PolarPose(math.log(3.0 / profile.r0), math.radians(15), 321, math.radians(35)),
        PolarMotion(0.15, math.tau * 0.1, 0.05, math.tau * -0.02),
        profile_id="display",
    )
    recipe = polar_population_preset(
        preset, instance_count=count, seed=recipe_seed
    ).to_dict()
    project.metadata["packed_kinematic_profiles"] = {
        "display": {
            "profile": profile.to_dict(),
            "motion_range": motion_range.to_dict(),
            "lut_resolution": 64,
        }
    }
    project.metadata["substrate_render"] = {
        "polar_mode": "lut",
        "bayer_mode": "subtle",
        "seed": root_seed,
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
                "polar_population": recipe,
            },
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _bits(instance: PolarDisplayInstance) -> tuple[object, ...]:
    floats = (*instance.translation, *instance.rotation, *instance.scale, *instance.velocity)
    return (
        instance.index,
        instance.lineage,
        instance.pose_word,
        instance.motion_word,
        struct.pack("<13f", *floats),
    )


class PolarPopulationRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_child_facing_presets_are_explicit_and_bounded(self) -> None:
        self.assertEqual(
            POLAR_POPULATION_PRESETS,
            ("ring", "spiral", "polar_field", "burst"),
        )
        for preset in POLAR_POPULATION_PRESETS[:3]:
            with self.subTest(preset=preset):
                recipe = polar_population_preset(
                    preset, instance_count=1024, seed=2**64 - 1
                )
                self.assertEqual(recipe.preset, preset)
                self.assertEqual(set(recipe.to_dict()), {
                    "preset", "instance_count", "seed", "radius_min", "radius_max",
                    "radial_rate", "angle_step_turns", "angle_jitter_turns",
                    "height_spread", "scale_min", "scale_max",
                })
                recipe.validate()

        with self.assertRaisesRegex(PolarPopulationError, "unknown field"):
            PolarPopulationRecipe.from_mapping({"preset": "ring", "magic": 1})
        with self.assertRaisesRegex(PolarPopulationError, "between 2"):
            PolarPopulationRecipe.from_mapping({"instance_count": 1})
        with self.assertRaisesRegex(PolarPopulationError, "Spiral growth rate"):
            PolarPopulationRecipe.from_mapping(
                {"preset": "ring", "radial_rate": 0.1}
            )
        with self.assertRaisesRegex(PolarPopulationError, "Radius multipliers"):
            PolarPopulationRecipe.from_mapping(
                {"radius_min": 2.0, "radius_max": 1.0}
            )
        with self.assertRaisesRegex(PolarPopulationError, "between 2"):
            polar_population_preset(
                "ring",
                instance_count=MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE + 1,
            )

    def test_64_256_1024_have_distinct_content_but_one_exact_prefix(self) -> None:
        groups = [collect_polar_population_project_spec(_project(count=count)).groups[0]
                  for count in (64, 256, 1024)]
        self.assertEqual(len({group.content_address for group in groups}), 3)
        self.assertEqual(len({group.lineage_namespace for group in groups}), 1)
        self.assertEqual(len({group.profile_address for group in groups}), 1)
        self.assertEqual(len({group.prototype_address for group in groups}), 1)

        generated: list[tuple[tuple[object, ...], ...]] = []
        for count, group in zip((64, 256, 1024), groups):
            project = _project(count=count)
            node = project.nodes[group.prototype_node_index]
            instances = polar_population_instances(node, group)
            self.assertEqual(len(instances), count - 1)
            generated.append(tuple(_bits(instance) for instance in instances))
        self.assertEqual(generated[0], generated[1][:63])
        self.assertEqual(generated[0], generated[2][:63])
        self.assertEqual(generated[1], generated[2][:255])

    def test_direct_recipe_object_is_canonical_f32_even_at_index_4095(self) -> None:
        direct = PolarPopulationRecipe(
            preset="ring",
            instance_count=4096,
            seed=23,
            angle_step_turns=0.1234567890123,
        )
        canonical_step = struct.unpack(
            "<f", struct.pack("<f", 0.1234567890123)
        )[0]
        self.assertEqual(direct.angle_step_turns, canonical_step)

        direct_project = _project(count=4096)
        direct_project.nodes = tuple(
            replace(
                node,
                metadata={**node.metadata, "polar_population": direct},
            )
            if node.id == "goal"
            else node
            for node in direct_project.nodes
        )
        mapping_project = Mobile3DProject.from_dict(direct_project.to_dict())
        mapping_project.nodes = tuple(
            replace(
                node,
                metadata={**node.metadata, "polar_population": direct.to_dict()},
            )
            if node.id == "goal"
            else node
            for node in mapping_project.nodes
        )
        direct_group = collect_polar_population_project_spec(direct_project).groups[0]
        mapping_group = collect_polar_population_project_spec(mapping_project).groups[0]
        self.assertEqual(direct_group.content_address, mapping_group.content_address)
        self.assertEqual(direct_group.lineage_namespace, mapping_group.lineage_namespace)
        direct_last = polar_population_instance(
            direct_project.nodes[direct_group.prototype_node_index],
            direct_group,
            4095,
        )
        mapping_last = polar_population_instance(
            mapping_project.nodes[mapping_group.prototype_node_index],
            mapping_group,
            4095,
        )
        self.assertEqual(_bits(direct_last), _bits(mapping_last))
        self.assertEqual(
            compile_polar_population_pack_bytes(direct_project),
            compile_polar_population_pack_bytes(mapping_project),
        )

    def test_negative_zero_has_the_one_canonical_positive_zero_encoding(self) -> None:
        positive = _project()
        negative = Mobile3DProject.from_dict(positive.to_dict())
        negative.nodes = tuple(
            replace(
                node,
                metadata={
                    **node.metadata,
                    "polar_population": {
                        **node.metadata["polar_population"],
                        "radial_rate": -0.0,
                        "angle_jitter_turns": -0.0,
                        "height_spread": -0.0,
                    },
                },
            )
            if node.id == "goal"
            else node
            for node in negative.nodes
        )
        recipe = collect_polar_population_project_spec(negative).groups[0].recipe
        self.assertEqual(struct.pack("<f", recipe.radial_rate), bytes(4))
        self.assertEqual(struct.pack("<f", recipe.angle_jitter_turns), bytes(4))
        self.assertEqual(struct.pack("<f", recipe.height_spread), bytes(4))
        self.assertEqual(
            compile_polar_population_pack_bytes(negative),
            compile_polar_population_pack_bytes(positive),
        )

    def test_staged_binary32_generation_vectors_are_locked(self) -> None:
        fixtures = {
            "ring": {
                "content": "acc333c041382a0a521bb3b542441f9f",
                "namespace": "55164c7442cc1d7b4a2ab54ff3f78e4a",
                1: (
                    "d6c8b84c98cfff4f",
                    "8a61428a2814136d",
                    "bd87d03f0000a03f56692140",
                    "0000403f0000a03f0000003f",
                    "9d96abbf000000001f7bb33f",
                ),
                4095: (
                    "d3e8ad15af3712e6",
                    "8a614ed7a8141fbb",
                    "2ca42c400000a03f2cc2a8bf",
                    "0000403f0000a03f0000003f",
                    "44db9d3f0000000074abbf3f",
                ),
            },
            "spiral": {
                "content": "a6e0e5e497adbc7090371f34e0738c63",
                "namespace": "29724fc5fd4cfe78600efdc28a580aff",
                1: (
                    "2e56e2adceaf6a26",
                    "8ae83d28f4141e0c",
                    "e7d1ac3faf98a83f8c6030c0",
                    "74cc2a3f0b558e3f45bbe33e",
                    "a59cf73f000000007dbbde3e",
                ),
                4095: (
                    "840e1b42102b485f",
                    "be583b2bc8141c0f",
                    "1720eac0e87a813fe66fadc1",
                    "5088423f421ca23f35b0013f",
                    "046d4841000000002737fbc0",
                ),
            },
            "polar_field": {
                "content": "0bdd8f1ef4f657fc6c7f0850f6532888",
                "namespace": "5edbe04fafff7af7fb47599259bedc86",
                1: (
                    "32c2422ea512bc3d",
                    "c22591b85014129b",
                    "b3c0a541f27a863f1cc88441",
                    "7e4e7a3fbf96d03fffde263f",
                    "144feac0000000002c2c7841",
                ),
                4095: (
                    "3ec4e6a3151c5eca",
                    "71aa12d0a81413b4",
                    "2348033f48efb83fcfb7823f",
                    "0860103f0ea0703f0b80c03e",
                    "9b9910bf000000005f73f33e",
                ),
            },
        }
        for preset, expected in fixtures.items():
            with self.subTest(preset=preset):
                project = _project(count=4096, preset=preset)
                group = collect_polar_population_project_spec(project).groups[0]
                node = project.nodes[group.prototype_node_index]
                self.assertEqual(group.content_address.hex(), expected["content"])
                self.assertEqual(group.lineage_namespace.hex(), expected["namespace"])
                self.assertEqual(group.component.motion_word, 0x099A0A0E019AFEFF)
                for index in (1, 4095):
                    instance = polar_population_instance(node, group, index)
                    actual = (
                        f"{instance.lineage:016x}",
                        f"{instance.pose_word:016x}",
                        struct.pack("<3f", *instance.translation).hex(),
                        struct.pack("<3f", *instance.scale).hex(),
                        struct.pack("<3f", *instance.velocity).hex(),
                    )
                    self.assertEqual(actual, expected[index])

    def test_content_identity_tracks_only_consumed_anchor_and_render_inputs(self) -> None:
        project = _project()
        base = collect_polar_population_project_spec(project).groups[0]

        ignored = Mobile3DProject.from_dict(project.to_dict())
        ignored.nodes = tuple(
            replace(
                node,
                transform=replace(
                    node.transform,
                    translation=(99.0, node.transform.translation[1], -77.0),
                    rotation=(0.0, 0.0, 1.0, 0.0),
                ),
            )
            if node.id == "goal"
            else node
            for node in ignored.nodes
        )
        ignored_group = collect_polar_population_project_spec(ignored).groups[0]
        self.assertEqual(base.prototype_address, ignored_group.prototype_address)
        self.assertEqual(base.content_address, ignored_group.content_address)
        self.assertEqual(base.lineage_namespace, ignored_group.lineage_namespace)

        mutations = {}
        y_project = Mobile3DProject.from_dict(project.to_dict())
        y_project.nodes = tuple(
            replace(
                node,
                transform=replace(node.transform, translation=(0.0, 2.0, 0.0)),
            )
            if node.id == "goal"
            else node
            for node in y_project.nodes
        )
        mutations["anchor_y"] = y_project
        velocity_project = Mobile3DProject.from_dict(project.to_dict())
        velocity_project.nodes = tuple(
            replace(node, velocity=(node.velocity[0], 3.0, node.velocity[2]))
            if node.id == "goal"
            else node
            for node in velocity_project.nodes
        )
        mutations["velocity_y"] = velocity_project
        scale_project = Mobile3DProject.from_dict(project.to_dict())
        scale_project.nodes = tuple(
            replace(node, transform=replace(node.transform, scale=(0.8, 1.25, 0.5)))
            if node.id == "goal"
            else node
            for node in scale_project.nodes
        )
        mutations["scale"] = scale_project
        mesh_project = Mobile3DProject.from_dict(project.to_dict())
        goal = next(node for node in mesh_project.nodes if node.id == "goal")
        mesh = mesh_project.meshes[goal.mesh_id]
        changed_first_vertex = tuple(
            value + (0.125 if axis == 0 else 0.0)
            for axis, value in enumerate(mesh.vertices[0])
        )
        changed_vertices = (changed_first_vertex,) + mesh.vertices[1:]
        mesh_project.meshes[goal.mesh_id] = replace(mesh, vertices=changed_vertices)
        mutations["mesh_content"] = mesh_project
        material_project = Mobile3DProject.from_dict(project.to_dict())
        goal = next(node for node in material_project.nodes if node.id == "goal")
        material = material_project.materials[goal.material_id]
        material_project.materials[goal.material_id] = replace(
            material, roughness=min(1.0, material.roughness + 0.125)
        )
        mutations["material_content"] = material_project

        for label, changed in mutations.items():
            with self.subTest(label=label):
                changed.validate()
                group = collect_polar_population_project_spec(changed).groups[0]
                self.assertNotEqual(base.prototype_address, group.prototype_address)
                self.assertNotEqual(base.content_address, group.content_address)
                self.assertNotEqual(base.lineage_namespace, group.lineage_namespace)

    def test_dependency_identity_matches_only_deployed_f32_render_semantics(self) -> None:
        project = _project()
        base = collect_polar_population_project_spec(project).groups[0]

        below_f32 = Mobile3DProject.from_dict(project.to_dict())
        goal = next(node for node in below_f32.nodes if node.id == "goal")
        mesh = below_f32.meshes[goal.mesh_id]
        first = mesh.vertices[0]
        below_f32.meshes[goal.mesh_id] = replace(
            mesh,
            vertices=((first[0] + 1.0e-12, first[1], first[2]),) + mesh.vertices[1:],
        )
        material = below_f32.materials[goal.material_id]
        below_f32.materials[goal.material_id] = replace(
            material, roughness=material.roughness + 1.0e-12
        )
        below_f32.validate()
        rounded = collect_polar_population_project_spec(below_f32).groups[0]
        self.assertEqual(base.prototype_address, rounded.prototype_address)
        self.assertEqual(base.content_address, rounded.content_address)

        negative_zero = Mobile3DProject.from_dict(project.to_dict())
        goal = next(node for node in negative_zero.nodes if node.id == "goal")
        mesh = negative_zero.meshes[goal.mesh_id]
        normal = mesh.normals[0]
        negative_zero.meshes[goal.mesh_id] = replace(
            mesh,
            normals=((-0.0, normal[1], normal[2]),) + mesh.normals[1:],
        )
        negative_zero.nodes = tuple(
            replace(node, velocity=(node.velocity[0], -0.0, node.velocity[2]))
            if node.id == "goal"
            else node
            for node in negative_zero.nodes
        )
        negative_zero.validate()
        normalized = collect_polar_population_project_spec(negative_zero).groups[0]
        self.assertEqual(base.prototype_address, normalized.prototype_address)
        self.assertEqual(base.content_address, normalized.content_address)

    def test_malformed_polar_dependency_is_reported_without_validation_leak(self) -> None:
        project = _project()
        project.nodes = tuple(
            replace(
                node,
                metadata={
                    **node.metadata,
                    "packed_kinematic": {
                        **node.metadata["packed_kinematic"],
                        "profile": "missing",
                    },
                },
            )
            if node.id == "goal"
            else node
            for node in project.nodes
        )
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertIn("packed_kinematic.invalid", {issue.code for issue in report.issues})
        self.assertIn("polar_population.invalid", {issue.code for issue in report.issues})

    def test_root_seed_is_consumed_separately_from_recipe_seed(self) -> None:
        first_project = _project(root_seed=1, recipe_seed=9)
        second_project = _project(root_seed=2, recipe_seed=9)
        first_group = collect_polar_population_project_spec(first_project).groups[0]
        second_group = collect_polar_population_project_spec(second_project).groups[0]
        self.assertNotEqual(first_group.lineage_namespace, second_group.lineage_namespace)
        self.assertNotEqual(first_group.content_address, second_group.content_address)
        first = polar_population_instances(
            first_project.nodes[first_group.prototype_node_index], first_group
        )[0]
        second = polar_population_instances(
            second_project.nodes[second_group.prototype_node_index], second_group
        )[0]
        self.assertNotEqual(first.lineage, second.lineage)
        self.assertNotEqual(first.translation, second.translation)
        self.assertEqual(
            inspect_polar_population_pack(
                compile_polar_population_pack_bytes(second_project)
            )["root_seed"],
            2,
        )

    def test_generated_pose_uses_referenced_quantized_lut_and_inherits_motion(self) -> None:
        project = _project(preset="polar_field")
        group = collect_polar_population_project_spec(project).groups[0]
        node = project.nodes[group.prototype_node_index]
        instance = polar_population_instances(node, group)[7]
        component = PackedKinematicComponent(
            instance.pose_word, instance.motion_word, instance.profile_id
        )
        expected = group.profile.codec.cartesian_state(
            component, quantized_profile_lut(group.profile)
        )
        self.assertEqual(instance.translation[0], struct.unpack("<f", struct.pack("<f", expected["position"][0]))[0])
        self.assertEqual(instance.translation[2], struct.unpack("<f", struct.pack("<f", expected["position"][1]))[0])
        self.assertEqual(instance.motion_word, group.component.motion_word)
        self.assertEqual(instance.profile_id, group.component.profile_id)

    def test_rho_outside_profile_is_intentionally_clamped_before_lut_decode(self) -> None:
        for multiplier, expected_rho in ((256.0, 5.0), (1.0 / 256.0, -5.0)):
            with self.subTest(multiplier=multiplier):
                project = _project(count=2)
                project.nodes = tuple(
                    replace(
                        node,
                        metadata={
                            **node.metadata,
                            "polar_population": {
                                **node.metadata["polar_population"],
                                "radius_min": multiplier,
                                "radius_max": multiplier,
                            },
                        },
                    )
                    if node.id == "goal"
                    else node
                    for node in project.nodes
                )
                project.validate()
                group = collect_polar_population_project_spec(project).groups[0]
                instance = polar_population_instances(
                    project.nodes[group.prototype_node_index], group
                )[0]
                decoded = group.profile.codec.unpack_pose(instance.pose_word)
                self.assertEqual(decoded.rho, expected_rho)
                radius = math.hypot(instance.translation[0], instance.translation[2])
                expected_radius = group.profile.codec.profile.r0 * math.exp(expected_rho)
                self.assertAlmostEqual(radius, expected_radius, delta=expected_radius * 0.002)

    def test_compact_pack_is_canonical_content_addressed_and_strict(self) -> None:
        project = _project(count=64, preset="ring")
        packed = compile_polar_population_pack_bytes(project)
        clone = Mobile3DProject.from_dict(project.to_dict())
        self.assertEqual(compile_polar_population_pack_bytes(clone), packed)
        self.assertEqual(packed[:8], POLAR_POPULATION_PACK_MAGIC)
        self.assertEqual(
            len(packed),
            POLAR_POPULATION_HEADER_BYTES
            + 5 * POLAR_POPULATION_OPERATOR_BYTES
            + POLAR_POPULATION_RECIPE_BYTES,
        )
        info = inspect_polar_population_pack(packed, node_count=len(project.nodes))
        self.assertEqual(info["recipe_count"], 1)
        self.assertEqual(info["total_instances"], 64)
        self.assertEqual(info["generated_copy_count"], 63)
        self.assertEqual(info["ecs_prototype_count"], 1)
        self.assertFalse(info["generated_members_are_ecs_entities"])
        self.assertTrue(info["native_consumer_wired"])
        self.assertEqual(info["native_consumer"], "android-kcpr392-v1")
        self.assertEqual(info["native_modes"], ["cpu", "direct", "lut"])
        self.assertEqual(info["math_schedule"], POLAR_POPULATION_MATH_SCHEDULE)
        self.assertEqual(info["recipes"][0]["preset_label"], "Ring")
        self.assertEqual(len(info["recipes"][0]["content_address"]), 32)
        self.assertEqual(len(info["recipes"][0]["lineage_namespace"]), 32)
        self.assertEqual(
            info["recipes"][0]["operator_parameters"]["radius_min_log_offset"],
            0.0,
        )

        with self.assertRaisesRegex(PolarPopulationPackError, "truncated"):
            inspect_polar_population_pack(packed[:-1])
        with self.assertRaisesRegex(PolarPopulationPackError, "trailing"):
            inspect_polar_population_pack(packed + b"x")
        corrupt_meaning = bytearray(packed)
        corrupt_meaning[40] ^= 1
        with self.assertRaisesRegex(PolarPopulationPackError, "meaning mismatch"):
            inspect_polar_population_pack(corrupt_meaning)
        corrupt_content = bytearray(packed)
        recipe_offset = POLAR_POPULATION_HEADER_BYTES + 5 * POLAR_POPULATION_OPERATOR_BYTES
        corrupt_content[recipe_offset + 20] ^= 1
        with self.assertRaisesRegex(PolarPopulationPackError, "content address mismatch"):
            inspect_polar_population_pack(corrupt_content)
        negative_zero_parameter = bytearray(packed)
        negative_zero_parameter[recipe_offset + 84:recipe_offset + 88] = struct.pack(
            "<f", -0.0
        )
        with self.assertRaisesRegex(PolarPopulationPackError, "not canonical"):
            inspect_polar_population_pack(negative_zero_parameter)

    def test_spiral_operator_table_adds_only_its_stable_curve_meaning(self) -> None:
        info = inspect_polar_population_pack(
            compile_polar_population_pack_bytes(_project(preset="spiral"))
        )
        self.assertEqual(info["operator_count"], 6)
        self.assertEqual(
            [operator["name"] for operator in info["operators"]],
            [
                "splitmix64_lineage",
                "log_radius_multiplier",
                "saturating_spiral",
                "periodic_angle",
                "seeded_height",
                "uniform_scale",
            ],
        )

    def test_reference_preset_pack_hashes_lock_the_kcpr392_meanings(self) -> None:
        fixtures = {
            "ring": (
                240,
                "019c33dc2cdb7278540b4e69509eb062ce1ded7183629481db3c374d7c10f568",
            ),
            "spiral": (
                256,
                "6b5358dcc568e7f23561c1f52b949ce5c753b5332a58329e3e1c9ddccaebee55",
            ),
            "polar_field": (
                240,
                "ffcf6ca9a2a49f95f895bb5ee7616de07662ca95f1bb0d2fb6d65e6ad9bcad59",
            ),
        }
        for preset, (byte_length, sha256) in fixtures.items():
            with self.subTest(preset=preset):
                packed = compile_polar_population_pack_bytes(
                    _project(count=64, preset=preset)
                )
                inspection = inspect_polar_population_pack(packed)
                self.assertEqual(len(packed), byte_length)
                self.assertEqual(inspection["sha256"], sha256)
    def test_android_export_reports_the_wired_native_recipe_modes(self) -> None:
        project = _project(count=1024, preset="polar_field")
        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNotNone(built.polar_pack)
            self.assertIsNotNone(built.polar_population_pack)
            assert built.polar_population_pack is not None
            self.assertEqual(built.polar_population_pack.name, POLAR_POPULATION_PACK_ASSET)
            self.assertLess(built.polar_population_pack.stat().st_size, 300)
            report = json.loads(built.build_report.read_text("utf-8"))
            recipe = report["polar_population_recipe_asset"]
            self.assertEqual(recipe["total_instances"], 1024)
            self.assertTrue(recipe["native_consumer_wired"])
            self.assertEqual(recipe["native_modes"], ["cpu", "direct", "lut"])
            self.assertFalse(recipe["generated_members_are_ecs_entities"])

    def test_world_keeps_exactly_the_authored_ecs_entities(self) -> None:
        project = _project(count=1024)
        world = project.instantiate_world()
        group = collect_polar_population_project_spec(project).groups[0]
        copies = polar_population_instances(project.nodes[group.prototype_node_index], group)
        self.assertEqual(len(world.entities), len(project.nodes))
        self.assertEqual(len(copies), 1023)
        self.assertTrue(all(instance.display_id not in world.entities for instance in copies))

    def test_editor_viewport_shows_a_bounded_display_only_preview(self) -> None:
        document = EditorDocument()
        document.create(_project(count=1024, preset="polar_field"))
        with patch(
            "ugts_kc3.editor.scene_view.polar_population_instance",
            wraps=polar_population_instance,
        ) as generated:
            viewport = SceneViewport()
            viewport.set_document(document)
            self.app.processEvents()
            self.assertLessEqual(generated.call_count, 64)
        shown = sum(
            item.data(3) == "polar_population_copy"
            for item in viewport.scene().items()
        )
        scene_text = " ".join(
            item.text()
            for item in viewport.scene().items()
            if isinstance(item, QGraphicsSimpleTextItem)
        )
        self.assertGreater(shown, 0)
        self.assertLessEqual(shown, 64)
        self.assertIn(f"1023 generated · {shown} shown", scene_text)
        self.assertEqual(len(document.scene_objects()), 3)
        viewport.close()

    def test_editor_viewport_uses_one_global_64_copy_polar_budget(self) -> None:
        project = _project(count=1024, preset="polar_field")
        prototype = next(node for node in project.nodes if node.id == "goal")
        second = replace(
            prototype,
            id="goal_two",
            transform=replace(prototype.transform, translation=(2.0, 1.25, 0.0)),
        )
        project.nodes = (*project.nodes, second)
        project.validate()
        document = EditorDocument()
        document.create(project)
        with patch(
            "ugts_kc3.editor.scene_view.polar_population_instance",
            wraps=polar_population_instance,
        ) as generated:
            viewport = SceneViewport()
            viewport.set_document(document)
            self.app.processEvents()
            self.assertLessEqual(generated.call_count, 64)
        shown = sum(
            item.data(3) == "polar_population_copy"
            for item in viewport.scene().items()
        )
        self.assertGreater(shown, 0)
        self.assertLessEqual(shown, 64)
        viewport.close()

    def test_make_many_off_ignores_invalid_recipe_only_text(self) -> None:
        window = EditorMainWindow()
        try:
            window.document.create(_project(count=64))
            window.undo_stack.clear()
            window.document.set_selection(SelectionRef("node", "goal"))
            self.app.processEvents()
            inspector = window.inspector
            inspector.polar_population_seed.setText("not-a-number")
            inspector.polar_population_preset.setCurrentIndex(
                inspector.polar_population_preset.findData("off")
            )
            self.app.processEvents()
            self.assertEqual(inspector.polar_population_preset.currentData(), "off")
            self.assertNotIn("polar_population", window.document.entity().metadata)
            self.assertEqual(window.undo_stack.count(), 1)
            window.undo_stack.undo()
            self.app.processEvents()
            self.assertIn("polar_population", window.document.entity().metadata)
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_make_many_inspector_enable_edit_remove_undo_and_roundtrip(self) -> None:
        window = EditorMainWindow()
        try:
            window.document.create(blank_mobile3d_project())
            window.undo_stack.clear()
            window.document.set_selection(SelectionRef("node", "goal"))
            self.app.processEvents()
            inspector = window.inspector
            self.assertTrue(
                inspector.polar_population_box.isVisibleTo(inspector)
            )
            self.assertFalse(inspector.polar_population_preset.isEnabled())
            self.assertIn(
                "Movement Pattern", inspector.polar_population_explanation.text()
            )
            self.assertEqual(
                window.document.entity().angular_velocity, (0.0, 0.5, 0.0)
            )

            inspector.movement_radius.setValue(4.0)
            inspector.movement_speed.setValue(0.125)
            inspector.movement_angle.setValue(30.0)
            inspector.movement_pattern_combo.setCurrentIndex(
                inspector.movement_pattern_combo.findData("orbit")
            )
            self.app.processEvents()
            self.assertEqual(
                window.document.entity().angular_velocity, (0.0, 0.0, 0.0)
            )
            self.assertTrue(inspector.polar_population_preset.isEnabled())

            inspector.polar_population_count.setValue(256)
            inspector.polar_population_seed.setText("18446744073709551615")
            inspector.polar_population_preset.setCurrentIndex(
                inspector.polar_population_preset.findData("spiral")
            )
            self.app.processEvents()
            goal = window.document.entity()
            recipe = goal.metadata["polar_population"]
            self.assertEqual(recipe["preset"], "spiral")
            self.assertEqual(recipe["instance_count"], 256)
            self.assertEqual(recipe["seed"], (1 << 64) - 1)
            self.assertEqual(len(window.document.scene_objects()), 3)
            self.assertEqual(window.document.selection.object_id, "goal")
            self.assertIn("1 ECS prototype", inspector.polar_population_cost.text())
            self.assertIn("255 display copies", inspector.polar_population_cost.text())
            packed = compile_polar_population_pack_bytes(window.document.project)
            info = inspect_polar_population_pack(packed)
            self.assertEqual(info["total_instances"], 256)
            self.assertIn(
                f"exact KCPR file {len(packed)} bytes",
                inspector.polar_population_cost.text(),
            )
            self.assertIn(
                info["recipes"][0]["content_address"],
                inspector.polar_population_cost.text(),
            )
            inspector.polar_population_advanced_button.setChecked(True)
            self.assertIn("theta18", inspector.polar_population_math.text())

            inspector.polar_population_height.setValue(1.75)
            inspector.polar_population_height.editingFinished.emit()
            self.app.processEvents()
            self.assertEqual(
                window.document.entity().metadata["polar_population"]["height_spread"],
                1.75,
            )
            inspector.polar_population_preset.setCurrentIndex(
                inspector.polar_population_preset.findData("off")
            )
            self.app.processEvents()
            self.assertNotIn("polar_population", window.document.entity().metadata)
            self.assertIn("packed_kinematic", window.document.entity().metadata)

            window.undo_stack.undo()
            self.app.processEvents()
            self.assertEqual(
                window.document.entity().metadata["polar_population"]["height_spread"],
                1.75,
            )
            window.undo_stack.undo()
            self.app.processEvents()
            self.assertEqual(
                window.document.entity().metadata["polar_population"]["height_spread"],
                0.5,
            )
            window.undo_stack.undo()
            self.app.processEvents()
            self.assertNotIn("polar_population", window.document.entity().metadata)
            window.undo_stack.undo()
            self.app.processEvents()
            self.assertNotIn("packed_kinematic", window.document.entity().metadata)
            self.assertEqual(
                window.document.entity().angular_velocity, (0.0, 0.5, 0.0)
            )

            for _ in range(3):
                window.undo_stack.redo()
                self.app.processEvents()
            self.assertIn("polar_population", window.document.entity().metadata)
            generated = [
                item
                for item in window.viewport.scene().items()
                if item.data(3) == "polar_population_copy"
            ]
            self.assertLessEqual(len(generated), 64)
            self.assertTrue(generated)
            self.assertTrue(all(item.data(0) == "goal" for item in generated))
            with tempfile.TemporaryDirectory() as tmp:
                saved = window.document.save(Path(tmp) / "make_many.json")
                loaded = Mobile3DProject.load(saved)
            self.assertEqual(
                compile_polar_population_pack_bytes(loaded),
                compile_polar_population_pack_bytes(window.document.project),
            )
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_make_many_inspector_explains_player_controller_conflict(self) -> None:
        window = EditorMainWindow()
        try:
            window.document.create(blank_mobile3d_project())
            window.document.set_selection(SelectionRef("node", "player"))
            self.app.processEvents()
            inspector = window.inspector
            self.assertFalse(inspector.polar_population_preset.isEnabled())
            self.assertIn(
                "Player controller", inspector.polar_population_explanation.text()
            )
        finally:
            window.document.set_dirty(False)
            window.close()
            self.app.processEvents()

    def test_recipe_requires_a_real_packed_kinematic_prototype(self) -> None:
        project = blank_mobile3d_project()
        project.nodes = tuple(
            replace(
                node,
                metadata={
                    **node.metadata,
                    "polar_population": polar_population_preset("ring").to_dict(),
                },
            )
            if node.id == "goal"
            else node
            for node in project.nodes
        )
        report = project.validate(raise_on_error=False)
        issue = next(issue for issue in report.issues if issue.code == "polar_population.invalid")
        self.assertIn("needs a Movement Pattern", issue.message)
        with self.assertRaisesRegex(ValueError, "needs a Movement Pattern"):
            project.validate()


if __name__ == "__main__":
    unittest.main()
