"""Verify the packed-polar real-ECS substrate example end to end."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any


EXAMPLE_DIR = Path(__file__).resolve().parent
ROOT = EXAMPLE_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from generate_variants import (  # noqa: E402
    DEFAULT_COUNT,
    DEFAULT_SEED,
    GRAPH_ID,
    PROFILE_ID,
    TIMER_SECONDS,
    WORKLOAD_COUNTS,
    build_project,
    reverse_graph,
)
from ugts_kc3.graphpack import (  # noqa: E402
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.mobile3d import (  # noqa: E402
    Mobile3DProject,
    visual_graphs_from_metadata,
)
from ugts_kc3.packed_kinematics import (  # noqa: E402
    POLAR_MOVEMENT_FIELDS,
    PolarMovementComponent3D,
)
from ugts_kc3.polarpack import (  # noqa: E402
    collect_polar_project_spec,
    compile_polar_pack_bytes,
    inspect_polar_pack,
)
from ugts_kc3.renderpack import (  # noqa: E402
    compile_render_substrate_pack_bytes,
    inspect_render_substrate_pack,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _movers(project: Mobile3DProject) -> tuple[Any, ...]:
    return tuple(
        node
        for node in project.nodes
        if "packed_kinematic" in node.metadata
    )


def _verify_authored_default() -> Mobile3DProject:
    project_path = EXAMPLE_DIR / "project.json"
    payload = json.loads(project_path.read_text("utf-8"))
    project = Mobile3DProject.from_dict(payload, validate=False)
    assert project.to_dict() == payload, "project.json is not canonical model output"
    generated = build_project()
    assert generated.to_dict() == payload, (
        "project.json drifted; refresh it with python generate_variants.py"
    )

    report = project.validate(raise_on_error=False)
    assert report.passed, report.to_dict()
    metrics = report.metrics
    assert metrics["packed_kinematic_profile_count"] == 1
    assert metrics["packed_kinematic_component_count"] == DEFAULT_COUNT
    assert metrics["visual_graph_count"] == 1
    assert metrics["visual_graph_binding_count"] == DEFAULT_COUNT
    assert metrics["dynamic_node_count"] == 0
    assert metrics["scatter_population_count"] == 0
    assert metrics["scatter_total_instance_count"] == 0
    assert metrics["scatter_generated_copy_count"] == 0

    movers = _movers(project)
    assert len(movers) == DEFAULT_COUNT
    assert all(not node.dynamic for node in movers)
    assert {node.mesh_id for node in movers} == {"orbit_shard"}
    assert {node.material_id for node in movers} == {"orbit_cyan"}
    assert all(node.metadata.get("visual_graph") == GRAPH_ID for node in movers)
    assert not any("scatter_population" in node.metadata for node in project.nodes)
    assert len({node.metadata["lab_ring"] for node in movers}) == 8

    profiles = project.metadata["packed_kinematic_profiles"]
    assert tuple(profiles) == (PROFILE_ID,)
    substrate = project.metadata["substrate_render"]
    assert substrate == {
        "polar_mode": "auto",
        "bayer_mode": "subtle",
        "levels": 64,
        "strength": 0.30,
        "seed": DEFAULT_SEED,
    }

    graphs = visual_graphs_from_metadata(project.metadata)
    assert len(graphs) == 1
    graph = graphs[0]
    graph.validate()
    assert graph.to_dict() == reverse_graph().to_dict()
    assert {node.type for node in graph.nodes} == {
        "event.timer",
        "value.polar_movement",
        "math.multiply",
        "action.set_polar_movement",
    }
    read_node = next(node for node in graph.nodes if node.id == "read_turn_speed")
    multiply = next(node for node in graph.nodes if node.id == "reverse_number")
    write_node = next(node for node in graph.nodes if node.id == "write_turn_speed")
    assert read_node.properties["entity"] is None
    assert "component" not in read_node.properties
    assert read_node.properties["field"] == "turns_per_second"
    assert multiply.properties["b"] == -1.0
    assert write_node.properties["entity"] is None
    assert "component" not in write_node.properties
    assert write_node.properties["field"] == "turns_per_second"
    return project


def _verify_variants() -> tuple[list[dict[str, Any]], dict[int, bytes]]:
    rows: list[dict[str, Any]] = []
    polar_packs: dict[int, bytes] = {}
    for count in WORKLOAD_COUNTS:
        project = build_project(count)
        repeat = build_project(count)
        assert project.content_hash() == repeat.content_hash()
        assert project.to_dict() == repeat.to_dict()

        validation = project.validate(raise_on_error=False)
        assert validation.passed, validation.to_dict()
        assert validation.metrics["packed_kinematic_profile_count"] == 1
        assert validation.metrics["packed_kinematic_component_count"] == count
        assert validation.metrics["visual_graph_count"] == 1
        assert validation.metrics["visual_graph_binding_count"] == count
        assert validation.metrics["scatter_population_count"] == 0

        spec = collect_polar_project_spec(project)
        assert len(spec.profiles) == 1
        assert spec.profiles[0].id == PROFILE_ID
        assert len(spec.components) == count

        polar_pack = compile_polar_pack_bytes(project)
        assert polar_pack == compile_polar_pack_bytes(project)
        assert polar_pack == compile_polar_pack_bytes(
            Mobile3DProject.from_dict(project.to_dict())
        )
        polar_info = inspect_polar_pack(polar_pack, node_count=len(project.nodes))
        assert polar_info["profile_count"] == 1
        assert polar_info["component_count"] == count
        polar_packs[count] = polar_pack

        graph_pack = compile_graph_pack_bytes(project)
        assert graph_pack == compile_graph_pack_bytes(repeat)
        graph_info = inspect_graph_pack(graph_pack)
        assert graph_info["graph_count"] == 1
        assert graph_info["binding_count"] == count
        assert graph_info["world_binding_count"] == 0
        assert graph_info["node_count"] == 4
        # Timer and Multiply contribute four additional inputs; the dedicated
        # Movement pair contributes six instead of the generic pair's eight.
        assert graph_info["input_count"] == 10
        assert b"polar_movement" not in graph_pack

        render_pack = compile_render_substrate_pack_bytes(project)
        assert render_pack == compile_render_substrate_pack_bytes(repeat)
        assert len(render_pack) == 32
        render_info = inspect_render_substrate_pack(render_pack)
        assert render_info["byte_length"] == 32
        assert render_info["polar_mode"] == "auto"
        assert render_info["bayer_mode"] == "subtle"

        rows.append(
            {
                "real_ecs_movers": count,
                "project_sha256": project.content_hash(),
                "kcpk_bytes": len(polar_pack),
                "kcpk_sha256": _sha256(polar_pack),
                "kcvg_bytes": len(graph_pack),
                "kcvg_sha256": _sha256(graph_pack),
                "graph_definitions": graph_info["graph_count"],
                "graph_bindings": graph_info["binding_count"],
                "render_pack_bytes": len(render_pack),
                "render_pack_sha256": _sha256(render_pack),
            }
        )

    for smaller, larger in zip(WORKLOAD_COUNTS, WORKLOAD_COUNTS[1:]):
        expected = (larger - smaller) * 24
        actual = len(polar_packs[larger]) - len(polar_packs[smaller])
        assert actual == expected, (
            f"KCPK {smaller}->{larger} grew {actual} bytes, expected {expected} "
            "(24 bytes per real packed component)"
        )
    return rows, polar_packs


def _verify_desktop_semantics(project: Mobile3DProject) -> dict[str, Any]:
    world = project.instantiate_world()
    semantic_query = world.query("polar_movement")
    typed_query = world.query(PolarMovementComponent3D)
    assert len(semantic_query) == DEFAULT_COUNT
    assert tuple(entity.id for entity in semantic_query) == tuple(
        entity.id for entity in typed_query
    )
    assert len(world.visual_graph_bindings) == DEFAULT_COUNT

    first_id = semantic_query[0].id
    first = world.require(first_id)
    before_position = tuple(first.position)
    before_y = first.position[1]
    before_speeds = {
        entity.id: world.require(entity.id, "polar_movement").turns_per_second
        for entity in semantic_query
    }
    before_view = world.require(first_id, "polar_movement")
    assert tuple(before_view.to_dict()) == POLAR_MOVEMENT_FIELDS

    timer_steps = round(TIMER_SECONDS / project.world.fixed_dt)
    assert math.isclose(
        timer_steps * project.world.fixed_dt,
        TIMER_SECONDS,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    )
    world.step(steps=timer_steps - 1)
    unchanged = world.require(first_id, "polar_movement").turns_per_second
    assert unchanged == before_speeds[first_id]
    world.step()

    for entity in semantic_query:
        after_speed = world.require(
            entity.id, "polar_movement"
        ).turns_per_second
        assert math.isclose(
            after_speed,
            -before_speeds[entity.id],
            rel_tol=0.0,
            abs_tol=2.0e-6,
        ), (entity.id, before_speeds[entity.id], after_speed)
    assert first.position[1] == before_y
    assert not all(
        math.isclose(left, right, rel_tol=0.0, abs_tol=1.0e-5)
        for left, right in zip(first.position, before_position)
    )
    return {
        "query_count": len(semantic_query),
        "typed_query_count": len(typed_query),
        "world_tick": world.tick,
        "timer_seconds": TIMER_SECONDS,
        "sample_speed_before": before_speeds[first_id],
        "sample_speed_after": world.require(
            first_id, "polar_movement"
        ).turns_per_second,
        "sample_y_preserved": first.position[1],
    }


def main() -> None:
    project = _verify_authored_default()
    variants, _ = _verify_variants()
    desktop = _verify_desktop_semantics(project)
    print(
        json.dumps(
            {
                "status": "PASS",
                "checked_project": str((EXAMPLE_DIR / "project.json").resolve()),
                "variants": variants,
                "desktop_semantic_runtime": desktop,
                "proven": (
                    "real static ECS composition, one shared profile/LUT, one shared "
                    "owner-relative graph definition, deterministic packs, and desktop semantics"
                ),
                "not_yet_proven": (
                    "GPU speed or phone performance; that requires an Android render-path "
                    "build and measurements on the connected device"
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
