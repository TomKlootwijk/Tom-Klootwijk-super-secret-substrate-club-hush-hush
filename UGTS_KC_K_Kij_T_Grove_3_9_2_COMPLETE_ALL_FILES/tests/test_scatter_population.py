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
from ugts_kc3.graphpack import compile_graph_pack_bytes
from ugts_kc3.mobile3d import Collider3DRecord, Transform3DRecord
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
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


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


def _f32_bits(value):
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _instance_bits(instance):
    return (
        instance.lineage,
        tuple(_f32_bits(value) for value in instance.translation),
        tuple(_f32_bits(value) for value in instance.rotation),
        tuple(_f32_bits(value) for value in instance.scale),
        _f32_bits(instance.yaw_radians),
    )


_MUTATING_GRAPH_PROPERTIES = {
    "action.set_component": {
        "entity": "floor",
        "component": "transform",
        "field": "translation.x",
        "value": 1.0,
    },
    "action.apply_force": {"entity": "floor", "force": [1.0, 0.0]},
    "action.set_active": {"entity": "floor", "active": False},
    "action.despawn": {"entity": "floor"},
}


def _mutation_graph(action_type, properties=None):
    return VisualGraph(
        f"unsafe_{action_type.rsplit('.', 1)[-1]}",
        (
            GraphNode("ready", "event.ready"),
            GraphNode("change_population", action_type, properties or {}),
        ),
        (GraphLink("ready", "out", "change_population", "in"),),
    )


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

    def test_python_transforms_match_native_binary32_golden_vectors(self):
        native_fixture = (
            (
                0xDF6E9843E9DA7E4F,
                (0xBFF5F0B4, 0xC0200000, 0x402D1DDC),
                (0x3D93123F, 0x00000000, 0x3F7F56CC, 0x00000000),
                (0x400D140D, 0x3F0D140D, 0x3FD39E14),
                0x400D98B9,
            ),
            (
                0x3C73BBA995B5F188,
                (0x4094CBE3, 0xC0200000, 0x40666EE9),
                (0xBD0795AB, 0x00000000, 0x3F7FDC16, 0x00000000),
                (0x3FDE103D, 0x3EDE103D, 0x3FA68C2E),
                0x401B08C4,
            ),
            (
                0xAD120CE70D177C14,
                (0x3FBF6884, 0xC0200000, 0x3F8CB570),
                (0xBF6B8A66, 0x00000000, 0x3EC890BB, 0x00000000),
                (0x400B29B6, 0x3F0B29B6, 0x3FD0BE91),
                0x40962B25,
            ),
        )
        project = blank_mobile3d_project()
        prototype = replace(
            project.nodes[0],
            id="oak",
            transform=Transform3DRecord(
                (1.25, -2.5, 3.75),
                (0.9238795, 0.0, 0.38268343, 0.0),
                (2.0, 0.5, 1.5),
            ),
        )
        project.nodes = (prototype,) + project.nodes[1:]
        _populate(project, count=4)
        group = collect_scatter_project_spec(project).groups[0]
        self.assertEqual(
            tuple(_instance_bits(item) for item in scatter_instances(prototype, group)),
            native_fixture,
        )

    def test_decimal_prototype_is_binary32_before_scatter_math_and_gltf(self):
        native_decimal_fixture = (
            (
                0xDF6E9843E9DA7E4F,
                (0xC04491F4, 0xBE4CCCCD, 0xBF3EBBC5),
                (0xBED0D460, 0x3F5105E6, 0x3ED1376C, 0x3A46178F),
                (0x3DE1B9AF, 0x3E61B9AF, 0x3EA94B43),
                0x400D98B9,
            ),
            (
                0x3C73BBA995B5F188,
                (0x405FFE2C, 0xBE4CCCCD, 0x3E1A21C4),
                (0xBEE59A7D, 0x3F4FE47C, 0x3EBA2E7C, 0xBDADB002),
                (0x3DB1A697, 0x3E31A697, 0x3E853CF2),
                0x401B08C4,
            ),
            (
                0xAD120CE70D177C14,
                (0x3EB0D543, 0xBE4CCCCD, 0xC0167215),
                (0xBF04D708, 0x3E88151B, 0xBE8198F5, 0xBF45A382),
                (0x3DDEA923, 0x3E5EA923, 0x3EA6FEDB),
                0x40962B25,
            ),
        )
        authored_transform = Transform3DRecord(
            (0.1, -0.2, 0.3),
            (0.1, 0.2, 0.3, 0.4),
            (0.1, 0.2, 0.3),
        )
        project = blank_mobile3d_project()
        prototype = replace(
            project.nodes[0], id="oak", transform=authored_transform
        )
        project.nodes = (prototype,) + project.nodes[1:]
        _populate(project, count=4)
        group = collect_scatter_project_spec(project).groups[0]
        instances = scatter_instances(prototype, group)
        self.assertEqual(tuple(_instance_bits(item) for item in instances), native_decimal_fixture)
        self.assertEqual(prototype.transform, authored_transform)

        with tempfile.TemporaryDirectory() as tmp:
            gltf = write_mobile3d_gltf(project, Path(tmp) / "decimal_population.gltf")
        gltf_nodes = {item["name"]: item for item in gltf["nodes"]}
        for instance, expected in zip(instances, native_decimal_fixture):
            node_id = f"oak__population_{instance.lineage:016x}"
            translation = tuple(gltf_nodes[node_id]["matrix"][12:15])
            self.assertEqual(tuple(_f32_bits(value) for value in translation), expected[1])

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

    def test_native_renderer_rolls_back_failed_initialization_and_transforms_normals(self):
        main = ROOT / "src/ugts_kc3/android_template/project/app/src/main"
        header = (main / "cpp/renderer_gles3.hpp").read_text("utf-8")
        renderer = (main / "cpp/renderer_gles3.cpp").read_text("utf-8")
        shader = (main / "assets/shaders/scene.vert").read_text("utf-8")

        self.assertIn("surface_!=EGL_NO_SURFACE &&", header)
        self.assertIn("context_!=EGL_NO_CONTEXT && program_!=0", header)
        initialize = renderer[
            renderer.index("bool RendererGles3::initialize("):
            renderer.index("\nvoid RendererGles3::destroyFramebuffer")
        ]
        after_egl_state_begins = initialize[initialize.index("display_=eglGetDisplay"):]
        self.assertNotIn("return false;", after_egl_state_begins)
        self.assertIn("if (!createProgram(assets)) return rollback();", initialize)
        self.assertIn("gpuRenderer_.clear();", renderer)
        self.assertIn("? mat4(aInstanceModel0", shader)
        self.assertIn(
            "mat3 normalMatrix = transpose(inverse(mat3(model)));",
            shader,
        )

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

    def test_world_and_other_owner_graphs_cannot_mutate_a_population_prototype(self):
        for action_type, properties in _MUTATING_GRAPH_PROPERTIES.items():
            for owner in ("world", "player"):
                with self.subTest(action=action_type, owner=owner):
                    project = blank_mobile3d_project()
                    _populate(project)
                    graph = _mutation_graph(action_type, properties)
                    project.metadata["visual_graphs"] = [graph.to_dict()]
                    if owner == "world":
                        project.metadata["world_graphs"] = graph.id
                    else:
                        project.nodes[1].metadata["visual_graph"] = graph.id
                    report = project.validate(raise_on_error=False)
                    matches = [
                        issue
                        for issue in report.issues
                        if issue.code == "scatter.graph_mutation"
                    ]
                    self.assertEqual(len(matches), 1, report.to_dict())
                    self.assertIn("Populate Area", matches[0].message)
                    self.assertIn("frozen", matches[0].message)
                    with self.assertRaisesRegex(ValueError, "frozen"):
                        compile_graph_pack_bytes(project)

    def test_linked_or_runtime_selected_population_mutation_is_rejected(self):
        project = blank_mobile3d_project()
        _populate(project)
        graph = _mutation_graph(
            "action.set_active", {"active": False}
        )
        graph = replace(
            graph,
            nodes=graph.nodes + (
                GraphNode("population", "value.constant", {"value": "floor"}),
            ),
            links=graph.links + (
                GraphLink("population", "value", "change_population", "entity"),
            ),
        )
        project.metadata["visual_graphs"] = [graph.to_dict()]
        project.metadata["world_graphs"] = graph.id
        report = project.validate(raise_on_error=False)
        self.assertTrue(
            any(issue.code == "scatter.graph_mutation" for issue in report.issues),
            report.to_dict(),
        )

        dynamic = blank_mobile3d_project()
        _populate(dynamic)
        graph = _mutation_graph("action.despawn")
        graph = replace(
            graph,
            nodes=graph.nodes + (
                GraphNode("chosen", "value.state", {"key": "chosen_object"}),
            ),
            links=graph.links + (
                GraphLink("chosen", "value", "change_population", "entity"),
            ),
        )
        dynamic.metadata["visual_graphs"] = [graph.to_dict()]
        dynamic.metadata["world_graphs"] = graph.id
        report = dynamic.validate(raise_on_error=False)
        match = next(
            issue for issue in report.issues if issue.code == "scatter.graph_mutation"
        )
        self.assertIn("chosen while the game runs", match.message)

    def test_population_allows_read_only_graphs_and_fixed_normal_targets(self):
        safe_world = VisualGraph(
            "inspect_population",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "read_height",
                    "value.component",
                    {
                        "entity": "floor",
                        "component": "transform",
                        "field": "translation.y",
                        "default": 0.0,
                    },
                ),
                GraphNode(
                    "remember",
                    "action.set_state",
                    {"key": "population_seen", "value": True},
                ),
            ),
            (GraphLink("ready", "out", "remember", "in"),),
        )
        project = blank_mobile3d_project()
        _populate(project)
        project.metadata["visual_graphs"] = [safe_world.to_dict()]
        project.metadata["world_graphs"] = safe_world.id
        report = project.validate(raise_on_error=False)
        self.assertTrue(report.passed, report.to_dict())
        self.assertTrue(compile_graph_pack_bytes(project))

        safe_mutation = _mutation_graph(
            "action.set_active", {"entity": "player", "active": True}
        )
        project.metadata["visual_graphs"] = [safe_mutation.to_dict()]
        project.metadata["world_graphs"] = safe_mutation.id
        report = project.validate(raise_on_error=False)
        self.assertTrue(report.passed, report.to_dict())
        self.assertTrue(compile_graph_pack_bytes(project))


if __name__ == "__main__":
    unittest.main()
