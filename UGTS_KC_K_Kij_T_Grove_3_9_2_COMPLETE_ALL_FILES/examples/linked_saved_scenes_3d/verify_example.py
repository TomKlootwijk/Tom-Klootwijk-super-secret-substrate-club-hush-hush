"""Deterministic end-to-end verification for the linked Saved Scenes example."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any, Callable


EXAMPLE_DIR = Path(__file__).resolve().parent
ROOT = EXAMPLE_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import (  # noqa: E402
    PACK_MAGIC,
    compile_scene_pack_bytes,
    inspect_scene_pack,
    write_mobile3d_gltf,
)
from ugts_kc3.animation3d import (  # noqa: E402
    ANIMATION_METADATA_KEY,
    animation_clip_hash,
    transform_animation_library_from_metadata,
)
from ugts_kc3.animationpack import (  # noqa: E402
    ANIMATION_PACK_MAGIC,
    ANIMATION_PACK_VERSION,
    compile_animation_pack_bytes,
    inspect_animation_pack,
)
from ugts_kc3.graphpack import (  # noqa: E402
    GRAPH_PACK_MAGIC,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.mobile3d import (  # noqa: E402
    InputFrame3D,
    Mobile3DProject,
    visual_graphs_from_metadata,
)
from ugts_kc3.polarpack import (  # noqa: E402
    POLAR_PACK_MAGIC,
    compile_polar_pack_bytes,
    inspect_polar_pack,
)
from ugts_kc3.saved_scene import (  # noqa: E402
    SAVED_SCENE_INSTANCE_SCHEMA,
    SAVED_SCENE_INSTANCES_KEY,
    SAVED_SCENE_SCHEMA,
    SAVED_SCENES_KEY,
    materialize_saved_scenes,
    materialized_node_id,
    saved_scene_instances_from_metadata,
    saved_scene_owner_id,
    saved_scenes_from_metadata,
)
from ugts_kc3.scatterpack import (  # noqa: E402
    SCATTER_PACK_MAGIC,
    compile_scatter_pack_bytes,
    inspect_scatter_pack,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _compile_deterministically(
    project: Mobile3DProject,
    flat: Mobile3DProject,
    compiler: Callable[[Mobile3DProject], bytes],
    magic: bytes,
) -> bytes:
    first = compiler(project)
    assert first.startswith(magic)
    assert compiler(project) == first
    assert compiler(flat) == first
    return first


def _pack_result(data: bytes, inspection: dict[str, Any]) -> dict[str, Any]:
    return {
        "bytes": len(data),
        "sha256": _sha256(data),
        "format_version": inspection["format_version"],
    }


def main() -> None:
    project_path = EXAMPLE_DIR / "project.json"
    raw = project_path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    project = Mobile3DProject.from_dict(payload, validate=False)
    assert project.to_dict() == payload

    authoring_snapshot = copy.deepcopy(project.to_dict())
    authoring_hash = project.content_hash()
    validation = project.validate(raise_on_error=False)
    assert validation.passed, validation.to_dict()

    definitions = saved_scenes_from_metadata(project.metadata)
    instances = saved_scene_instances_from_metadata(project.metadata)
    assert len(definitions) == 1
    assert definitions[0].id == "glow_gate"
    assert definitions[0].schema == SAVED_SCENE_SCHEMA
    assert len(definitions[0].nodes) == 3
    assert tuple(instance.id for instance in instances) == (
        "gate_east",
        "gate_north",
        "gate_west",
    )
    assert all(instance.schema == SAVED_SCENE_INSTANCE_SCHEMA for instance in instances)

    raw_definition = payload["metadata"][SAVED_SCENES_KEY][0]
    raw_instances = payload["metadata"][SAVED_SCENE_INSTANCES_KEY]
    descriptor_fields = {"schema", "id", "scene_id", "transform"}
    assert len(raw_definition["nodes"]) == 3
    assert len(raw_definition["graphs"]) == 2
    assert all(set(item) == descriptor_fields for item in raw_instances)
    assert all("nodes" not in item and "graphs" not in item for item in raw_instances)

    definition = definitions[0]
    definition_graphs = {graph.id: graph for graph in definition.graphs}
    reveal_action = next(
        node
        for node in definition_graphs["reveal_lantern"].nodes
        if node.id == "show_lantern"
    )
    owner_action = next(
        node
        for node in definition_graphs["keep_bobbing"].nodes
        if node.id == "restart_bob"
    )
    assert reveal_action.properties["entity"] == "@node/lantern"
    assert owner_action.properties["entity"] is None
    assert definition.ordered_nodes()[0].node.transform.translation == (0.0, 0.0, 0.0)
    lantern_definition = next(item.node for item in definition.nodes if item.id == "lantern")
    library = transform_animation_library_from_metadata(lantern_definition.metadata)
    assert library is not None
    assert library.autoplay == "bob"
    assert tuple(clip.id for clip in library.clips) == ("bob",)
    assert len(library.clips[0].animation.keys) == 3

    flat = materialize_saved_scenes(project)
    second_flat = materialize_saved_scenes(project)
    assert project.to_dict() == authoring_snapshot
    assert project.content_hash() == authoring_hash
    assert flat.to_dict() == second_flat.to_dict()
    assert flat.to_dict() == materialize_saved_scenes(flat).to_dict()
    assert SAVED_SCENES_KEY not in flat.metadata
    assert SAVED_SCENE_INSTANCES_KEY not in flat.metadata

    authored_ids = tuple(node.id for node in project.nodes)
    flat_ids = tuple(node.id for node in flat.nodes)
    expected_generated_ids = tuple(
        materialized_node_id(instance.id, local_id, definition.root_id)
        for instance in instances
        for local_id in ("arch", "lantern", "sparkle")
    )
    assert authored_ids == ("floor", "player", "goal", "orbit_marker")
    assert flat_ids == (*authored_ids, *expected_generated_ids)
    assert len(flat_ids) == len(set(flat_ids)) == 13
    assert all(
        saved_scene_owner_id(node) == instance.id
        for instance in instances
        for node in flat.nodes
        if node.id in {
            materialized_node_id(instance.id, local_id, definition.root_id)
            for local_id in ("arch", "lantern", "sparkle")
        }
    )

    metrics = validation.metrics
    assert metrics["authored_node_count"] == 4
    assert metrics["materialized_node_count"] == 13
    assert metrics["saved_scene_definition_count"] == 1
    assert metrics["saved_scene_instance_count"] == 3
    assert metrics["visual_graph_count"] == 4
    assert metrics["visual_graph_binding_count"] == 6
    assert metrics["transform_animation_binding_count"] == 3
    assert metrics["scatter_population_count"] == 3
    assert metrics["packed_kinematic_component_count"] == 1
    stored_object_records = len(project.nodes) + len(definition.nodes)
    assert stored_object_records == 7 < len(flat.nodes)

    flat_nodes = {node.id: node for node in flat.nodes}
    flat_graphs = {
        graph.id: graph for graph in visual_graphs_from_metadata(flat.metadata)
    }
    shared_owner_graph = "saved_scene__glow_gate__keep_bobbing"
    assert shared_owner_graph in flat_graphs
    for instance in instances:
        root_graph_id = f"saved_scene__{instance.id}__reveal_lantern"
        root = flat_nodes[instance.id]
        lantern_id = f"{instance.id}__lantern"
        assert root.metadata["visual_graph"] == root_graph_id
        assert flat_nodes[lantern_id].metadata["visual_graph"] == shared_owner_graph
        action = next(
            node for node in flat_graphs[root_graph_id].nodes if node.id == "show_lantern"
        )
        assert action.properties["entity"] == lantern_id

    world = project.instantiate_world()
    assert set(world.entities) == set(flat_ids)
    north_lantern = world.require("gate_north__lantern")
    animation_component = world.require(
        "gate_north__lantern", ANIMATION_METADATA_KEY
    )
    start_position = tuple(north_lantern.position)
    assert animation_component.playing
    assert animation_component.active_clip == "bob"
    world.step(steps=60)
    mid_position = tuple(north_lantern.position)
    assert mid_position[1] > start_position[1] + 0.25
    world.step(InputFrame3D(move_z=-1.0), steps=400)
    assert world.state["finished"] is True

    kc3d = _compile_deterministically(
        project, flat, compile_scene_pack_bytes, PACK_MAGIC
    )
    kcvg = _compile_deterministically(
        project, flat, compile_graph_pack_bytes, GRAPH_PACK_MAGIC
    )
    kcan = _compile_deterministically(
        project, flat, compile_animation_pack_bytes, ANIMATION_PACK_MAGIC
    )
    kcsp = _compile_deterministically(
        project, flat, compile_scatter_pack_bytes, SCATTER_PACK_MAGIC
    )
    kcpk = _compile_deterministically(
        project, flat, compile_polar_pack_bytes, POLAR_PACK_MAGIC
    )

    node_indices = {node_id: index for index, node_id in enumerate(flat_ids)}
    scene_info = inspect_scene_pack(kc3d)
    graph_info = inspect_graph_pack(kcvg)
    animation_info = inspect_animation_pack(kcan, node_count=len(flat_ids))
    scatter_info = inspect_scatter_pack(kcsp, node_count=len(flat_ids))
    polar_info = inspect_polar_pack(kcpk, node_count=len(flat_ids))

    assert [node["id"] for node in scene_info["nodes"]] == list(flat_ids)
    assert scene_info["project_hash"] == flat.content_hash()
    assert graph_info["graph_count"] == 4
    assert graph_info["binding_count"] == 6
    assert graph_info["node_count"] == 8
    assert animation_info["format_version"] == ANIMATION_PACK_VERSION == 2
    assert animation_info["binding_count"] == 3
    assert animation_info["packed_key_count"] == 9
    assert {item["clip_hash"] for item in animation_info["bindings"]} == {
        animation_clip_hash("bob")
    }
    assert {item["node_index"] for item in animation_info["bindings"]} == {
        node_indices[f"{instance.id}__lantern"] for instance in instances
    }
    assert all(item["autoplay"] for item in animation_info["bindings"])
    assert scatter_info["group_count"] == 3
    assert scatter_info["total_instances"] == 12
    assert scatter_info["generated_copy_count"] == 9
    assert {item["prototype_node_index"] for item in scatter_info["groups"]} == {
        node_indices[f"{instance.id}__sparkle"] for instance in instances
    }
    assert polar_info["profile_count"] == 1
    assert polar_info["component_count"] == 1
    assert polar_info["components"][0]["node_index"] == node_indices["orbit_marker"]

    with tempfile.TemporaryDirectory() as temporary:
        output = Path(temporary)
        packed_path = project.write_packed(output / "linked_saved_scenes.kcec")
        packed_project = Mobile3DProject.load_packed(packed_path)
        assert tuple(node.id for node in packed_project.nodes) == flat_ids
        assert SAVED_SCENES_KEY not in packed_project.metadata
        assert SAVED_SCENE_INSTANCES_KEY not in packed_project.metadata

        gltf_path = output / "linked_saved_scenes.gltf"
        gltf = write_mobile3d_gltf(project, gltf_path)
        gltf_bytes = gltf_path.read_bytes()
        assert gltf["asset"]["version"] == "2.0"
        assert json.loads(gltf_bytes.decode("utf-8")) == gltf
        assert len(gltf["nodes"]) == 22
        gltf_names = {node["name"] for node in gltf["nodes"]}
        assert len(gltf_names) == len(gltf["nodes"])
        assert set(flat_ids).issubset(gltf_names)

    result = {
        "authoring": {
            "project_file_bytes": len(raw),
            "project_file_sha256": _sha256(raw),
            "project_content_sha256": authoring_hash,
            "ordinary_node_records": len(project.nodes),
            "saved_definition_node_records": len(definition.nodes),
            "compact_instance_descriptors": len(instances),
            "stored_object_records": stored_object_records,
        },
        "materialization": {
            "runtime_node_count": len(flat_ids),
            "runtime_content_sha256": flat.content_hash(),
            "unique_generated_ids": len(expected_generated_ids),
            "generated_ids": list(expected_generated_ids),
        },
        "runtime": {
            "completed_tick": world.tick,
            "goal_reached": world.state["finished"],
            "lantern_start": list(start_position),
            "lantern_mid_bob": list(mid_position),
            "state_sha256": world.state_hash(),
        },
        "packs": {
            "KC3D": {
                **_pack_result(kc3d, scene_info),
                "node_count": scene_info["node_count"],
            },
            "KCVG": {
                **_pack_result(kcvg, graph_info),
                "graph_count": graph_info["graph_count"],
                "binding_count": graph_info["binding_count"],
            },
            "KCAN": {
                **_pack_result(kcan, animation_info),
                "binding_count": animation_info["binding_count"],
                "key_count": animation_info["packed_key_count"],
            },
            "KCSP": {
                **_pack_result(kcsp, scatter_info),
                "group_count": scatter_info["group_count"],
                "generated_copy_count": scatter_info["generated_copy_count"],
            },
            "KCPK": {
                **_pack_result(kcpk, polar_info),
                "component_count": polar_info["component_count"],
            },
        },
        "gltf": {
            "bytes": len(gltf_bytes),
            "sha256": _sha256(gltf_bytes),
            "node_count": len(gltf["nodes"]),
        },
        "validation_metrics": metrics,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
