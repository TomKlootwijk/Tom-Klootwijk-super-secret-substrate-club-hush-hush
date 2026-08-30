from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import (  # noqa: E402
    build_android_project,
    compile_scene_pack_bytes,
    inspect_scene_pack,
    write_mobile3d_gltf,
)
from ugts_kc3.animation3d import (  # noqa: E402
    default_transform_animation_library,
    metadata_with_transform_animation_library,
)
from ugts_kc3.animationpack import (  # noqa: E402
    compile_animation_pack_bytes,
    inspect_animation_pack,
)
from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack  # noqa: E402
from ugts_kc3.mobile3d import Mobile3DProject, visual_graphs_from_metadata  # noqa: E402
from ugts_kc3.polarpack import compile_polar_pack_bytes, inspect_polar_pack  # noqa: E402
from ugts_kc3.saved_scene import (  # noqa: E402
    SAVED_SCENE_INSTANCES_KEY,
    SAVED_SCENES_KEY,
    instantiate_saved_scene,
    make_saved_scene,
    materialize_saved_scenes,
    metadata_with_saved_scene_instances,
    metadata_with_saved_scenes,
)
from ugts_kc3.scatterpack import (  # noqa: E402
    compile_scatter_pack_bytes,
    inspect_scatter_pack,
)
from ugts_kc3.templates3d import first_steps_mobile3d_project  # noqa: E402


def _linked_project() -> Mobile3DProject:
    project = first_steps_mobile3d_project()
    nodes = {node.id: node for node in project.nodes}
    graphs = {graph.id: graph for graph in visual_graphs_from_metadata(project.metadata)}

    # The authored goal keeps its packed world-centred movement.  Its Saved
    # Scene copy is a leaf animation instead, which exercises a distinct KCAN
    # index without weakening the Saved Scene restriction on movement patterns.
    goal_metadata = dict(nodes["goal"].metadata)
    goal_metadata.pop("packed_kinematic", None)
    goal_metadata = metadata_with_transform_animation_library(
        goal_metadata,
        default_transform_animation_library(),
    )
    saved_goal = replace(
        nodes["goal"],
        metadata=goal_metadata,
        angular_velocity=(0.0, 0.0, 0.0),
    )
    definition = make_saved_scene(
        "test_cluster",
        "Test Cluster",
        (nodes["floor"], saved_goal, nodes["crystal_garden"]),
        root_id="floor",
        graphs=(
            graphs["repeatable_number_lesson"],
            graphs["goal_area_lesson"],
        ),
    )
    instance = instantiate_saved_scene(
        definition,
        "cluster_one",
        {"translation": [9.0, 1.0, -2.0]},
    )
    project.metadata = metadata_with_saved_scenes(project.metadata, (definition,))
    project.metadata = metadata_with_saved_scene_instances(
        project.metadata,
        (instance,),
    )
    return project


class SavedSceneRuntimeIntegrationTests(unittest.TestCase):
    def test_runtime_and_compact_indices_share_one_materialized_order(self) -> None:
        project = _linked_project()
        authored_ids = tuple(node.id for node in project.nodes)
        authored_hash = project.content_hash()
        flat = materialize_saved_scenes(project)
        flat_ids = tuple(node.id for node in flat.nodes)
        node_indices = {node_id: index for index, node_id in enumerate(flat_ids)}

        self.assertEqual(tuple(node.id for node in project.nodes), authored_ids)
        self.assertEqual(project.content_hash(), authored_hash)
        self.assertEqual(
            flat_ids[-3:],
            ("cluster_one", "cluster_one__crystal_garden", "cluster_one__goal"),
        )
        self.assertNotIn(SAVED_SCENES_KEY, flat.metadata)
        self.assertNotIn(SAVED_SCENE_INSTANCES_KEY, flat.metadata)

        validation = project.validate(raise_on_error=False)
        self.assertTrue(validation.passed, validation.issues)
        self.assertEqual(validation.metrics["authored_node_count"], len(authored_ids))
        self.assertEqual(validation.metrics["materialized_node_count"], len(flat_ids))
        self.assertEqual(validation.metrics["saved_scene_definition_count"], 1)
        self.assertEqual(validation.metrics["saved_scene_instance_count"], 1)

        scene = inspect_scene_pack(compile_scene_pack_bytes(project))
        self.assertEqual([node["id"] for node in scene["nodes"]], list(flat_ids))
        self.assertEqual(scene["project_hash"], flat.content_hash())

        graph = inspect_graph_pack(compile_graph_pack_bytes(project))
        self.assertTrue(
            all(
                binding["scene_node_index"] is None
                or binding["scene_node_index"] < len(flat_ids)
                for binding in graph["bindings"]
            )
        )
        linked_graph_indices = {
            binding["scene_node_index"]
            for binding in graph["bindings"]
            if str(binding["graph"]).startswith("saved_scene__")
        }
        self.assertEqual(
            linked_graph_indices,
            {node_indices["cluster_one"], node_indices["cluster_one__goal"]},
        )

        polar = inspect_polar_pack(
            compile_polar_pack_bytes(project), node_count=len(flat_ids)
        )
        self.assertEqual(
            [component["node_index"] for component in polar["components"]],
            [node_indices["goal"]],
        )
        scatter = inspect_scatter_pack(
            compile_scatter_pack_bytes(project), node_count=len(flat_ids)
        )
        self.assertEqual(
            [group["prototype_node_index"] for group in scatter["groups"]],
            [
                node_indices["crystal_garden"],
                node_indices["cluster_one__crystal_garden"],
            ],
        )
        animation = inspect_animation_pack(
            compile_animation_pack_bytes(project), node_count=len(flat_ids)
        )
        self.assertEqual(
            [binding["node_index"] for binding in animation["bindings"]],
            [node_indices["cluster_one__goal"]],
        )

        world = project.instantiate_world()
        self.assertEqual(set(world.entities), set(flat_ids))
        retained = project.to_scene()
        self.assertTrue(set(flat_ids).issubset(retained.nodes))

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packed = project.write_packed(root / "linked.kcec")
            loaded = Mobile3DProject.load_packed(packed)
            self.assertEqual(tuple(node.id for node in loaded.nodes), flat_ids)
            self.assertNotIn(SAVED_SCENES_KEY, loaded.metadata)
            gltf = write_mobile3d_gltf(project, root / "linked.gltf")
            self.assertEqual(
                len(gltf["nodes"]),
                validation.metrics["materialized_node_count"]
                + validation.metrics["scatter_generated_copy_count"],
            )

    def test_android_materializes_once_before_every_asset(self) -> None:
        project = _linked_project()
        flat = materialize_saved_scenes(project)
        with tempfile.TemporaryDirectory() as temporary, patch(
            "ugts_kc3.saved_scene.materialize_saved_scenes",
            wraps=materialize_saved_scenes,
        ) as materialize:
            built = build_android_project(project, Path(temporary) / "android")

            self.assertEqual(materialize.call_count, 1)
            self.assertEqual(built.project_hash, flat.content_hash())
            scene = inspect_scene_pack(built.scene_pack)
            self.assertEqual(scene["node_count"], len(flat.nodes))
            self.assertEqual(scene["project_hash"], flat.content_hash())
            self.assertIsNotNone(built.graph_pack)
            self.assertIsNotNone(built.polar_pack)
            self.assertIsNotNone(built.scatter_pack)
            self.assertIsNotNone(built.animation_pack)

            authoring = json.loads(built.project_file.read_text("utf-8"))
            self.assertIn(SAVED_SCENES_KEY, authoring["metadata"])
            self.assertIn(SAVED_SCENE_INSTANCES_KEY, authoring["metadata"])
            report = json.loads(built.build_report.read_text("utf-8"))
            self.assertEqual(report["project_hash"], flat.content_hash())
            self.assertEqual(report["authoring_project_hash"], project.content_hash())


if __name__ == "__main__":
    unittest.main()
