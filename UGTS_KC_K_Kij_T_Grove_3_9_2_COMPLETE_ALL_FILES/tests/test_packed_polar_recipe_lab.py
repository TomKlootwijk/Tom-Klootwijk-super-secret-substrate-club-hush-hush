from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
GENERATOR = (
    ROOT / "examples" / "packed_polar_gpu_lab_3d" / "generate_recipe_variants.py"
)
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.polar_population import (  # noqa: E402
    collect_polar_population_project_spec,
    polar_population_glow_sample,
    polar_population_instance,
    polar_population_instances,
)
from ugts_kc3.polar_population_pack import (  # noqa: E402
    compile_polar_population_pack_bytes,
    inspect_polar_population_pack,
)
from ugts_kc3.polarpack import compile_polar_pack_bytes  # noqa: E402


def _load_generator():
    spec = importlib.util.spec_from_file_location("_ugts_recipe_lab", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load polar recipe lab generator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class PackedPolarRecipeLabTests(unittest.TestCase):
    def test_one_ecs_prototype_generates_prefix_stable_compact_workloads(self) -> None:
        generator = _load_generator()
        projects = tuple(
            generator.build_project(count, preset="ring") for count in (64, 256, 1024)
        )
        self.assertEqual({len(project.nodes) for project in projects}, {6})
        self.assertEqual(
            len({compile_polar_pack_bytes(project) for project in projects}), 1
        )

        inspections = tuple(
            inspect_polar_population_pack(compile_polar_population_pack_bytes(project))
            for project in projects
        )
        self.assertEqual(
            [item["total_instances"] for item in inspections], [64, 256, 1024]
        )
        self.assertEqual(len({item["byte_length"] for item in inspections}), 1)
        self.assertEqual(
            len({item["recipes"][0]["content_address"] for item in inspections}),
            3,
        )
        self.assertEqual(
            len({item["recipes"][0]["lineage_namespace"] for item in inspections}),
            1,
        )

        generated = []
        for project in projects:
            group = collect_polar_population_project_spec(project).groups[0]
            node = project.nodes[group.prototype_node_index]
            generated.append(
                tuple(
                    (item.lineage, item.pose_word, item.motion_word)
                    for item in polar_population_instances(node, group)
                )
            )
        self.assertEqual(generated[0], generated[1][:63])
        self.assertEqual(generated[1], generated[2][:255])

    def test_radial_burst_matrix_workloads_are_v2_and_prefix_stable(self) -> None:
        generator = _load_generator()
        projects = tuple(
            generator.build_project(count, preset="burst") for count in (32, 128, 384)
        )
        inspections = tuple(
            inspect_polar_population_pack(compile_polar_population_pack_bytes(project))
            for project in projects
        )
        self.assertEqual([item["format_version"] for item in inspections], [2, 2, 2])
        self.assertEqual(
            [item["total_instances"] for item in inspections], [32, 128, 384]
        )
        self.assertEqual({item["byte_length"] for item in inspections}, {240})
        self.assertEqual(
            len({item["recipes"][0]["lineage_namespace"] for item in inspections}),
            1,
        )

        generated = []
        for project in projects:
            group = collect_polar_population_project_spec(project).groups[0]
            node = project.nodes[group.prototype_node_index]
            generated.append(
                tuple(
                    (
                        item.lineage,
                        item.previous_pose_word,
                        item.pose_word,
                        item.translation,
                        item.scale,
                    )
                    for item in polar_population_instances(node, group, fixed_tick=17)
                )
            )
        self.assertEqual(generated[0], generated[1][:31])
        self.assertEqual(generated[1], generated[2][:127])

    def test_glow_lab_opts_into_v3_without_changing_spatial_lineage(self) -> None:
        generator = _load_generator()
        plain = generator.build_project(128, preset="burst")
        glowing = generator.build_project(
            128,
            preset="burst",
            glow_by_distance=True,
            glow_start_distance=0.0,
            glow_end_distance=4.0,
            glow_strength=1.25,
        )
        plain_group = collect_polar_population_project_spec(plain).groups[0]
        glow_group = collect_polar_population_project_spec(glowing).groups[0]
        plain_info = inspect_polar_population_pack(
            compile_polar_population_pack_bytes(plain)
        )
        glow_pack = compile_polar_population_pack_bytes(glowing)
        glow_info = inspect_polar_population_pack(glow_pack)

        self.assertEqual(plain_info["format_version"], 2)
        self.assertEqual(glow_info["format_version"], 3)
        self.assertEqual(plain_info["byte_length"], 240)
        self.assertEqual(glow_info["byte_length"], 288)
        self.assertEqual(glow_info["operator_count"], 8)
        self.assertEqual(plain_group.lineage_namespace, glow_group.lineage_namespace)
        self.assertNotEqual(plain_group.content_address, glow_group.content_address)
        self.assertEqual(
            glow_group.recipe.to_dict()["glow_by_distance"],
            {"start_distance": 0.0, "end_distance": 4.0, "strength": 1.25},
        )
        self.assertIsNotNone(glow_group.glow_parameters)

        node = glowing.nodes[glow_group.prototype_node_index]
        display = polar_population_instance(node, glow_group, 1, fixed_tick=3)
        sample = polar_population_glow_sample(
            glow_group,
            index=1,
            pose_word=display.pose_word,
        )
        self.assertIsNotNone(sample)
        assert sample is not None
        self.assertGreaterEqual(sample.phase12, 0)
        self.assertLess(sample.phase12, 4096)
        self.assertGreaterEqual(sample.glow, 0.0)
        self.assertLessEqual(sample.glow, 4.0)
        self.assertEqual(glow_pack, compile_polar_population_pack_bytes(glowing))

    def test_grow_lab_opts_into_v4_without_growing_the_ecs_prototype(self) -> None:
        generator = _load_generator()
        glowing = generator.build_project(
            128,
            preset="burst",
            glow_by_distance=True,
            glow_start_distance=0.0,
            glow_end_distance=4.0,
            glow_strength=1.25,
        )
        growing = generator.build_project(
            128,
            preset="burst",
            glow_by_distance=True,
            grow_glowing_copies=True,
            glow_start_distance=0.0,
            glow_end_distance=4.0,
            glow_strength=1.25,
        )
        glow_group = collect_polar_population_project_spec(glowing).groups[0]
        grow_group = collect_polar_population_project_spec(growing).groups[0]
        inspection = inspect_polar_population_pack(
            compile_polar_population_pack_bytes(growing)
        )

        self.assertEqual(len(growing.nodes), 6)
        self.assertEqual(inspection["format_version"], 4)
        self.assertEqual(inspection["operator_count"], 9)
        self.assertEqual(inspection["byte_length"], 304)
        self.assertEqual(glow_group.lineage_namespace, grow_group.lineage_namespace)
        self.assertNotEqual(glow_group.content_address, grow_group.content_address)
        self.assertEqual(
            grow_group.recipe.to_dict()["glow_by_distance"],
            {
                "start_distance": 0.0,
                "end_distance": 4.0,
                "strength": 1.25,
                "grow_copies": True,
            },
        )
        self.assertEqual(
            growing.metadata["polar_recipe_lab"]["glow_by_distance"][
                "grow_copies"
            ],
            True,
        )

        glow_node = glowing.nodes[glow_group.prototype_node_index]
        grow_node = growing.nodes[grow_group.prototype_node_index]
        self.assertEqual(glow_node.transform.scale, grow_node.transform.scale)
        multipliers = []
        for index in range(1, grow_group.recipe.instance_count):
            glow_display = polar_population_instance(
                glow_node, glow_group, index, fixed_tick=3
            )
            grow_display = polar_population_instance(
                grow_node, grow_group, index, fixed_tick=3
            )
            sample = polar_population_glow_sample(
                grow_group,
                index=index,
                pose_word=grow_display.pose_word,
            )
            assert sample is not None
            multipliers.append(sample.display_scale_multiplier)
            self.assertEqual(glow_display.translation, grow_display.translation)
            for grown, base in zip(grow_display.scale, glow_display.scale):
                self.assertAlmostEqual(
                    grown,
                    base * sample.display_scale_multiplier,
                    places=5,
                )
        self.assertGreater(max(multipliers), 1.0)
        self.assertLessEqual(max(multipliers), 5.0)

        with self.assertRaisesRegex(ValueError, "requires glow_by_distance"):
            generator.build_project(128, grow_glowing_copies=True)

    def test_grow_lab_has_a_separate_one_click_launcher(self) -> None:
        launcher = (ROOT / "RUN_POLAR_GROW_LAB.cmd").read_text(encoding="utf-8")
        self.assertIn("build\\polar-grow-lab", launcher)
        self.assertIn("--glow-by-distance --grow-glowing-copies", launcher)
        self.assertIn("--validate-existing", launcher)
        self.assertIn('call "RUN_UGTS_STUDIO.cmd" "%UGTS_GROW_PROJECT%"', launcher)
        self.assertNotIn("UGTS_GLOW_PROJECT", launcher)

    def test_existing_grow_lab_validation_rejects_stale_glow_content(self) -> None:
        generator = _load_generator()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            grow_path = temp / "grow.json"
            glow_path = temp / "glow.json"
            generator.build_project(
                128,
                preset="burst",
                polar_mode="lut",
                glow_by_distance=True,
                grow_glowing_copies=True,
            ).write(grow_path)
            project, inspection = generator._validate_existing_grow_project(
                grow_path
            )
            self.assertEqual(project.id, "packed_polar_recipe_lab_3d")
            self.assertEqual(inspection["format_version"], 4)

            generator.build_project(
                128,
                preset="burst",
                glow_by_distance=True,
            ).write(glow_path)
            with self.assertRaisesRegex(ValueError, "KCPR v4 Grow"):
                generator._validate_existing_grow_project(glow_path)

            wrong_v4_path = temp / "wrong-v4-grow.json"
            generator.build_project(
                64,
                preset="ring",
                polar_mode="direct",
                bayer_mode="off",
                glow_by_distance=True,
                grow_glowing_copies=True,
            ).write(wrong_v4_path)
            with self.assertRaisesRegex(ValueError, "128 Burst/LUT/subtle"):
                generator._validate_existing_grow_project(wrong_v4_path)


if __name__ == "__main__":
    unittest.main()
