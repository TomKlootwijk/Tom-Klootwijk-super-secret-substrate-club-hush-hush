from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import build_android_project, write_mobile3d_gltf
from ugts_kc3.mobile3d import Collider3DRecord
from ugts_kc3.scatter import (
    SCATTER_METADATA_KEY,
    ScatterError,
    collect_scatter_project_spec,
    combine_seed,
    hash64,
    scatter_instances,
    seed_unit_float,
    splitmix64,
    stable_id,
)
from ugts_kc3.scatterpack import (
    SCATTER_PACK_ASSET,
    SCATTER_PACK_MAGIC,
    ScatterPackError,
    compile_scatter_pack_bytes,
    inspect_scatter_pack,
)
from ugts_kc3.templates3d import blank_mobile3d_project, first_steps_mobile3d_project


def _populate(project, *, count=8, seed=7):
    project.nodes[0].metadata[SCATTER_METADATA_KEY] = {
        "instance_count": count,
        "seed": seed,
        "size": [8.0, 0.0, 6.0],
        "scale_min": 0.8,
        "scale_max": 1.2,
        "random_yaw": True,
    }
    return project.nodes[0]


class ScatterPopulationTests(unittest.TestCase):
    def test_ugts41_seed_golden_vectors(self):
        self.assertEqual(splitmix64(0), 0xE220A8397B1DCDAF)
        self.assertEqual(hash64("oak"), 0x7E447CF1466E5484)
        self.assertEqual(combine_seed(7, 3), 0xAEB185ABD810BEDF)
        self.assertEqual(
            stable_id(7, hash64("tree"), 1), 0x8139DC489E25520A
        )
        self.assertEqual(seed_unit_float(0), 0.8833107948303223)

    def test_same_recipe_is_deterministic_and_count_preserves_prefix(self):
        project = blank_mobile3d_project()
        prototype = _populate(project, count=12)
        group = collect_scatter_project_spec(project).groups[0]
        first = scatter_instances(prototype, group)
        again = scatter_instances(prototype, group)
        self.assertEqual(first, again)
        for instance in first:
            for value in (*instance.translation, *instance.scale, instance.yaw_radians):
                self.assertEqual(value, struct.unpack("<f", struct.pack("<f", value))[0])

        prototype.metadata[SCATTER_METADATA_KEY]["instance_count"] = 32
        larger_group = collect_scatter_project_spec(project).groups[0]
        larger = scatter_instances(prototype, larger_group)
        self.assertEqual(first, larger[: len(first)])

    def test_project_keeps_one_recipe_but_scene_and_gltf_bake_instances(self):
        project = blank_mobile3d_project()
        _populate(project, count=9)
        report = project.validate()
        self.assertEqual(report.metrics["node_count"], 3)
        self.assertEqual(report.metrics["scatter_population_count"], 1)
        self.assertEqual(report.metrics["scatter_total_instance_count"], 9)
        self.assertEqual(report.metrics["scatter_generated_copy_count"], 8)
        authoring = project.to_dict()
        self.assertEqual(len(authoring["nodes"]), 3)
        self.assertEqual(
            authoring["nodes"][0]["metadata"][SCATTER_METADATA_KEY]["instance_count"], 9
        )
        scene = project.to_scene()
        self.assertEqual(len(scene.nodes), 11)
        generated = [
            node for node in scene.nodes.values()
            if node.metadata.get("population_prototype") == "floor"
        ]
        self.assertEqual(len(generated), 8)
        self.assertTrue(all(node.metadata["render_only"] for node in generated))

        with tempfile.TemporaryDirectory() as tmp:
            result = write_mobile3d_gltf(project, Path(tmp) / "population.gltf")
            self.assertEqual(len(result["nodes"]), 11)
            self.assertEqual(len(result["meshes"]), 3)

    def test_first_steps_crystal_garden_is_visible_but_not_gameplay_ecs(self):
        project = first_steps_mobile3d_project()
        report = project.validate()
        self.assertEqual(report.metrics["scatter_population_count"], 1)
        self.assertEqual(report.metrics["scatter_total_instance_count"], 18)
        world = project.instantiate_world()
        self.assertEqual(len(world.entities), len(project.nodes))
        self.assertIn("crystal_garden", world.entities)
        self.assertEqual(len(compile_scatter_pack_bytes(project)), 60)

    def test_pack_is_optional_fixed_size_and_strictly_inspected(self):
        project = blank_mobile3d_project()
        self.assertEqual(compile_scatter_pack_bytes(project), b"")
        prototype = _populate(project, count=2)
        small = compile_scatter_pack_bytes(project)
        self.assertEqual(small[:8], SCATTER_PACK_MAGIC)
        self.assertEqual(len(small), 60)
        prototype.metadata[SCATTER_METADATA_KEY]["instance_count"] = 256
        large = compile_scatter_pack_bytes(project)
        self.assertEqual(len(large), 60)
        info = inspect_scatter_pack(large, node_count=len(project.nodes))
        self.assertEqual(info["group_count"], 1)
        self.assertEqual(info["total_instances"], 256)
        self.assertEqual(info["generated_copy_count"], 255)

        with self.assertRaisesRegex(ScatterPackError, "trailing bytes"):
            inspect_scatter_pack(large + b"x", node_count=len(project.nodes))
        corrupt = bytearray(large)
        struct.pack_into("<I", corrupt, 24, len(project.nodes))
        with self.assertRaisesRegex(ScatterPackError, "prototype node"):
            inspect_scatter_pack(bytes(corrupt), node_count=len(project.nodes))

    def test_android_source_contains_only_the_sparse_population_asset(self):
        project = blank_mobile3d_project()
        _populate(project, count=64)
        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNotNone(built.scatter_pack)
            assert built.scatter_pack is not None
            self.assertEqual(built.scatter_pack.name, SCATTER_PACK_ASSET)
            self.assertEqual(built.scatter_pack.stat().st_size, 60)
            inspection = json.loads(built.build_report.read_text("utf-8"))
            self.assertEqual(inspection["population_runtime"]["total_instances"], 64)
            scene_info = json.loads(
                (built.output_dir / "scene-pack-inspection.json").read_text("utf-8")
            )
            self.assertEqual(scene_info["node_count"], 3)

    def test_native_template_loads_sparse_recipe_and_draws_instanced_prefix(self):
        cpp = ROOT / "src/ugts_kc3/android_template/project/app/src/main/cpp"
        engine = (cpp / "engine.cpp").read_text("utf-8")
        renderer = (cpp / "renderer_gles3.cpp").read_text("utf-8")
        shader = (
            ROOT
            / "src/ugts_kc3/android_template/project/app/src/main/assets/shaders/scene.vert"
        ).read_text("utf-8")
        self.assertIn('readAsset("scatter_populations.kcsp")', engine)
        self.assertLess(
            engine.index('readAsset("packed_kinematics.kcpk")'),
            engine.index('readAsset("scatter_populations.kcsp")'),
        )
        self.assertLess(
            engine.index('readAsset("scatter_populations.kcsp")'),
            engine.index('readAsset("visual_graphs.kcvg")'),
        )
        self.assertIn("glDrawElementsInstanced", renderer)
        self.assertIn("remaining=maxNodes-drawn", renderer)
        self.assertIn("glVertexAttribDivisor(location,1)", renderer)
        self.assertIn("layout(location = 5) in vec4 aInstanceModel3", shader)
        self.assertIn("uniform bool uInstanced", shader)

    def test_unsafe_gameplay_or_transform_authority_is_rejected(self):
        cases = []
        dynamic = blank_mobile3d_project()
        _populate(dynamic)
        dynamic.nodes = (replace(dynamic.nodes[0], dynamic=True),) + dynamic.nodes[1:]
        cases.append((dynamic, "static"))

        collider = blank_mobile3d_project()
        _populate(collider)
        collider.nodes = (
            replace(collider.nodes[0], collider=Collider3DRecord("sphere", 1.0)),
        ) + collider.nodes[1:]
        cases.append((collider, "collider"))

        gameplay = blank_mobile3d_project()
        _populate(gameplay)
        gameplay.nodes = (replace(gameplay.nodes[0], tags=("goal",)),) + gameplay.nodes[1:]
        cases.append((gameplay, "gameplay tag"))

        graph = blank_mobile3d_project()
        _populate(graph)
        graph.nodes[0].metadata["visual_graph"] = "some_graph"
        cases.append((graph, "Logic Blocks"))

        movement = blank_mobile3d_project()
        _populate(movement)
        movement.nodes[0].metadata["packed_kinematic"] = {"pose": "0", "motion": "0"}
        cases.append((movement, "Movement Pattern"))

        for project, message in cases:
            with self.subTest(message=message):
                report = project.validate(raise_on_error=False)
                self.assertFalse(report.passed)
                self.assertTrue(any(issue.code == "scatter.invalid" for issue in report.issues))
                with self.assertRaisesRegex(ScatterError, message):
                    collect_scatter_project_spec(project)


if __name__ == "__main__":
    unittest.main()
