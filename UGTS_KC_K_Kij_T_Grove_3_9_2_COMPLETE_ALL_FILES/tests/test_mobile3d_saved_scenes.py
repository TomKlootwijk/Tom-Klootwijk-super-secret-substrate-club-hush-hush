from __future__ import annotations

from dataclasses import replace
import copy
import json
import math

import pytest

from ugts_kc3.androidexport import compile_scene_pack_bytes, inspect_scene_pack
from ugts_kc3.graphpack import compile_graph_pack_bytes, inspect_graph_pack
from ugts_kc3.math3d import quat_from_axis_angle, quat_rotate
from ugts_kc3.mobile3d import Transform3DRecord, visual_graphs_from_metadata
from ugts_kc3.saved_scene import (
    SAVED_SCENE_INSTANCES_KEY,
    SAVED_SCENES_KEY,
    SavedScene3D,
    SavedSceneError,
    SavedSceneNode3D,
    bake_saved_scene_instance,
    instantiate_saved_scene,
    make_saved_scene,
    materialize_saved_scenes,
    metadata_with_saved_scene_instances,
    metadata_with_saved_scenes,
    saved_scene_instances_from_metadata,
    saved_scene_owner_id,
    saved_scenes_from_metadata,
)
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


def _source_pair(*, graph: bool = False):
    project = blank_mobile3d_project()
    root_metadata = {"description": "A linked root"}
    child_metadata = {"description": "A linked child"}
    logic = None
    if graph:
        logic = VisualGraph(
            "open_child",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "show", "action.set_active", {"entity": "lamp", "active": True}
                ),
            ),
            (GraphLink("ready", "out", "show", "in"),),
        )
        root_metadata["visual_graph"] = logic.id
    root = replace(
        project.nodes[0],
        id="base",
        transform=Transform3DRecord((2.0, 0.0, 3.0)),
        metadata=root_metadata,
    )
    child = replace(
        project.nodes[2],
        id="lamp",
        tags=(),
        angular_velocity=(0.0, 0.0, 0.0),
        transform=Transform3DRecord((4.0, 1.0, 3.0)),
        metadata=child_metadata,
    )
    return project, root, child, logic


def _linked_project(*, graphs: bool = False, two_instances: bool = True):
    project, root, child, logic = _source_pair(graph=graphs)
    definition = make_saved_scene(
        "lamp_pair",
        "Lamp Pair",
        (root, child),
        "base",
        () if logic is None else (logic,),
    )
    instances = [
        instantiate_saved_scene(
            definition,
            "pair_a",
            Transform3DRecord((10.0, 0.0, 0.0)),
        )
    ]
    if two_instances:
        instances.append(
            instantiate_saved_scene(
                definition,
                "pair_b",
                Transform3DRecord((-5.0, 0.0, 7.0)),
            )
        )
    project.metadata = metadata_with_saved_scenes(project.metadata, (definition,))
    project.metadata = metadata_with_saved_scene_instances(
        project.metadata, reversed(instances)
    )
    return project, definition, tuple(instances)


def test_compact_roundtrip_stores_definition_once_and_instances_only_hold_transforms():
    project, definition, instances = _linked_project()
    payload = json.loads(json.dumps(project.to_dict()))
    clone = type(project).from_dict(payload)

    assert saved_scenes_from_metadata(clone.metadata) == (definition,)
    assert saved_scene_instances_from_metadata(clone.metadata) == instances
    raw_definition = clone.metadata[SAVED_SCENES_KEY][0]
    assert len(raw_definition["nodes"]) == 2
    assert all("nodes" not in item for item in clone.metadata[SAVED_SCENE_INSTANCES_KEY])
    assert [item["id"] for item in clone.metadata[SAVED_SCENE_INSTANCES_KEY]] == [
        "pair_a",
        "pair_b",
    ]


def test_world_capture_and_instance_transform_compose_deterministically():
    project, definition, _ = _linked_project(two_instances=False)
    root, child = definition.ordered_nodes()
    assert root.node.transform.translation == (0.0, 0.0, 0.0)
    assert child.node.transform.translation == (2.0, 1.0, 0.0)

    turn = quat_from_axis_angle((0.0, 1.0, 0.0), math.pi / 2.0)
    instance = instantiate_saved_scene(
        definition,
        "turned_pair",
        Transform3DRecord((3.0, 2.0, 1.0), turn, (2.0, 2.0, 2.0)),
    )
    project.metadata = metadata_with_saved_scene_instances(project.metadata, (instance,))
    flat = materialize_saved_scenes(project)
    generated = flat.nodes[-2:]
    assert [node.id for node in generated] == ["turned_pair", "turned_pair__lamp"]
    expected_offset = quat_rotate(turn, (4.0, 2.0, 0.0))
    assert generated[1].transform.translation == pytest.approx(
        tuple((3.0, 2.0, 1.0)[axis] + expected_offset[axis] for axis in range(3))
    )
    assert saved_scene_owner_id(generated[1]) == "turned_pair"


def test_saved_scene_parent_edges_do_not_leak_into_nested_runtime_records():
    project, root, child, _ = _source_pair()
    child = replace(child, parent_id=root.id)
    definition = make_saved_scene(
        "attached_pair", "Attached Pair", (root, child), root.id
    )
    saved_child = next(item for item in definition.nodes if item.id == child.id)

    assert saved_child.parent_id == root.id
    assert saved_child.node.parent_id is None
    assert "parent_id" not in saved_child.to_dict()["node"]

    instance = instantiate_saved_scene(definition, "linked_pair")
    project.metadata = metadata_with_saved_scenes(project.metadata, (definition,))
    project.metadata = metadata_with_saved_scene_instances(
        project.metadata, (instance,)
    )
    flat = materialize_saved_scenes(project)
    generated = flat.nodes[-2:]
    assert [node.id for node in generated] == ["linked_pair", "linked_pair__lamp"]
    assert all(node.parent_id is None for node in generated)
    assert flat.validate(raise_on_error=False).passed


def test_materialization_is_pure_idempotent_and_canonical():
    project, _, _ = _linked_project()
    authored = copy.deepcopy(project.to_dict())
    flat = materialize_saved_scenes(project)
    again = materialize_saved_scenes(flat)

    assert project.to_dict() == authored
    assert flat.to_dict() == again.to_dict()
    assert SAVED_SCENES_KEY not in flat.metadata
    assert SAVED_SCENE_INSTANCES_KEY not in flat.metadata
    assert [node.id for node in flat.nodes[-4:]] == [
        "pair_a",
        "pair_a__lamp",
        "pair_b",
        "pair_b__lamp",
    ]


def test_project_validation_and_scene_pack_use_the_same_flat_node_order():
    project, _, _ = _linked_project()
    report = project.validate(raise_on_error=False)
    flat = materialize_saved_scenes(project)
    scene_info = inspect_scene_pack(compile_scene_pack_bytes(project))

    assert report.passed, report.to_dict()
    assert report.metrics["authored_node_count"] == len(project.nodes)
    assert report.metrics["materialized_node_count"] == len(flat.nodes)
    assert scene_info["node_count"] == len(flat.nodes)
    assert compile_scene_pack_bytes(project) == compile_scene_pack_bytes(flat)


def test_internal_logic_reference_is_cloned_and_remapped_per_instance():
    project, _, _ = _linked_project(graphs=True)
    flat = materialize_saved_scenes(project)
    generated = flat.nodes[-4:]
    graph_ids = [node.metadata.get("visual_graph") for node in generated[::2]]
    assert len(set(graph_ids)) == 2
    graphs = {graph.id: graph for graph in visual_graphs_from_metadata(flat.metadata)}
    for instance_id, graph_id in zip(("pair_a", "pair_b"), graph_ids):
        action = next(node for node in graphs[graph_id].nodes if node.id == "show")
        assert action.properties["entity"] == f"{instance_id}__lamp"

    graph_info = inspect_graph_pack(compile_graph_pack_bytes(project))
    assert graph_info["binding_count"] == 2
    assert {
        binding["scene_node_index"] for binding in graph_info["bindings"]
    } == {len(project.nodes), len(project.nodes) + 2}


def test_external_logic_reference_is_rejected_during_capture():
    project, root, child, _ = _source_pair()
    graph = VisualGraph(
        "bad_reference",
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "hide", "action.set_active", {"entity": "player", "active": False}
            ),
        ),
        (GraphLink("ready", "out", "hide", "in"),),
    )
    root = replace(root, metadata={"visual_graph": graph.id})
    with pytest.raises(SavedSceneError, match="outside the selected objects"):
        make_saved_scene("bad_pair", "Bad Pair", (root, child), "base", (graph,))


def test_unused_definition_adds_zero_runtime_bytes():
    project, root, child, _ = _source_pair()
    before = compile_scene_pack_bytes(project)
    definition = make_saved_scene("unused_pair", "Unused Pair", (root, child), "base")
    project.metadata = metadata_with_saved_scenes(project.metadata, (definition,))

    assert compile_scene_pack_bytes(project) == before
    assert inspect_scene_pack(before)["node_count"] == len(project.nodes)


def test_bake_unlinks_one_instance_and_keeps_the_other_linked():
    project, _, _ = _linked_project()
    baked = bake_saved_scene_instance(project, "pair_a")
    remaining = saved_scene_instances_from_metadata(baked.metadata)

    assert [instance.id for instance in remaining] == ["pair_b"]
    assert [node.id for node in baked.nodes[-2:]] == ["pair_a", "pair_a__lamp"]
    assert all(saved_scene_owner_id(node) is None for node in baked.nodes[-2:])
    assert SAVED_SCENES_KEY in baked.metadata
    flat = materialize_saved_scenes(baked)
    assert [node.id for node in flat.nodes[-4:]] == [
        "pair_a",
        "pair_a__lamp",
        "pair_b",
        "pair_b__lamp",
    ]


def test_missing_parent_cycles_collisions_and_reserved_ids_fail_clearly():
    project, root, child, _ = _source_pair()
    with pytest.raises(SavedSceneError, match="double underscore"):
        make_saved_scene("bad__scene", "Bad", (root, child), "base")

    local_root = SavedSceneNode3D("base", "lamp", replace(root, id="base"))
    local_child = SavedSceneNode3D("lamp", "base", replace(child, id="lamp"))
    cyclic = SavedScene3D("cycle", "Cycle", "base", (local_root, local_child))
    with pytest.raises(SavedSceneError, match="exactly one root|parent cycle"):
        cyclic.validate(project.meshes, project.materials)

    linked, _, _ = _linked_project(two_instances=False)
    linked.nodes = (*linked.nodes, replace(linked.nodes[0], id="pair_a"))
    with pytest.raises(SavedSceneError, match="duplicate object id"):
        materialize_saved_scenes(linked)


def test_runtime_transform_authority_on_a_parent_is_rejected():
    project, root, child, _ = _source_pair()
    dynamic_root = replace(root, dynamic=True)
    with pytest.raises(SavedSceneError, match="Dynamic physics"):
        make_saved_scene(
            "dynamic_group", "Dynamic Group", (dynamic_root, child), "base"
        )


def test_nonuniform_instance_scale_before_rotated_child_is_rejected_as_shear():
    project, definition, _ = _linked_project(two_instances=False)
    child = next(item for item in definition.nodes if item.id == "lamp")
    rotated_child = replace(
        child,
        node=replace(
            child.node,
            transform=replace(
                child.node.transform,
                rotation=quat_from_axis_angle((0.0, 1.0, 0.0), math.pi / 4.0),
            ),
        ),
    )
    definition = replace(
        definition,
        nodes=tuple(
            rotated_child if item.id == "lamp" else item
            for item in definition.nodes
        ),
    )
    project.metadata = metadata_with_saved_scenes(project.metadata, (definition,))
    project.metadata = metadata_with_saved_scene_instances(
        project.metadata,
        (
            instantiate_saved_scene(
                definition,
                "stretched",
                Transform3DRecord(scale=(2.0, 1.0, 1.0)),
            ),
        ),
    )
    with pytest.raises(SavedSceneError, match="cannot represent shear"):
        materialize_saved_scenes(project)


def test_parent_transform_writing_logic_is_rejected():
    _, root, child, _ = _source_pair()
    graph = VisualGraph(
        "move_parent",
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "move",
                "action.set_component",
                {
                    "entity": None,
                    "component": "transform",
                    "field": "translation.x",
                    "value": 2.0,
                },
            ),
        ),
        (GraphLink("ready", "out", "move", "in"),),
    )
    root = replace(root, metadata={"visual_graph": graph.id})
    with pytest.raises(SavedSceneError, match="Logic Blocks move it"):
        make_saved_scene("moving_parent", "Moving Parent", (root, child), "base", (graph,))


def test_raw_local_graph_reference_is_remapped_and_external_is_rejected():
    project, definition, _ = _linked_project(graphs=True, two_instances=False)
    graph = definition.graphs[0]
    raw = graph.to_dict()
    action = next(node for node in raw["nodes"] if node["id"] == "show")
    action["properties"]["entity"] = "lamp"
    local_graph = VisualGraph.from_dict(raw)
    local_definition = replace(definition, graphs=(local_graph,))
    project.metadata = metadata_with_saved_scenes(project.metadata, (local_definition,))
    flat = materialize_saved_scenes(project)
    cloned = next(
        graph
        for graph in visual_graphs_from_metadata(flat.metadata)
        if graph.id.startswith("saved_scene__")
    )
    cloned_action = next(node for node in cloned.nodes if node.id == "show")
    assert cloned_action.properties["entity"] == "pair_a__lamp"

    action["properties"]["entity"] = "outside"
    external = replace(
        definition, graphs=(VisualGraph.from_dict(raw),)
    )
    with pytest.raises(SavedSceneError, match="outside this Saved Scene"):
        external.validate(project.meshes, project.materials)


def test_definition_snapshots_do_not_alias_source_or_serialized_metadata():
    _, root, child, _ = _source_pair()
    root.metadata["nested"] = {"value": 1}
    definition = make_saved_scene("detached", "Detached", (root, child), "base")
    metadata = metadata_with_saved_scenes({}, (definition,))
    root.metadata["nested"]["value"] = 99
    metadata[SAVED_SCENES_KEY][0]["nodes"][0]["node"]["metadata"]["nested"][
        "value"
    ] = 7

    assert definition.nodes[0].node.metadata["nested"]["value"] == 1


def test_instance_parser_rejects_hidden_nested_payloads():
    with pytest.raises(SavedSceneError, match="unsupported fields"):
        saved_scene_instances_from_metadata(
            {
                SAVED_SCENE_INSTANCES_KEY: [
                    {
                        "id": "sneaky",
                        "scene_id": "lamp_pair",
                        "nodes": [{"id": "hidden"}],
                    }
                ]
            }
        )
