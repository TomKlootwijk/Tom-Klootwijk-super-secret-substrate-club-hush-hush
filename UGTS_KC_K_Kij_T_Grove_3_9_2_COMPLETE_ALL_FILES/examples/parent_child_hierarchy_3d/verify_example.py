"""Verify the bounded retained-transform hierarchy example end to end."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
from typing import Any, Iterable


EXAMPLE_DIR = Path(__file__).resolve().parent
ROOT = EXAMPLE_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import (  # noqa: E402
    compile_scene_pack_bytes,
    inspect_scene_pack,
    write_mobile3d_gltf,
)
from ugts_kc3.hierarchy3d import (  # noqa: E402
    TransformTRS3D,
    build_hierarchy3d,
    compose_world_trs_3d,
    world_trs_by_id,
)
from ugts_kc3.hierarchypack import (  # noqa: E402
    HIERARCHY_PACK_MAGIC,
    compile_hierarchy_pack_bytes,
    inspect_hierarchy_pack,
)
from ugts_kc3.mobile3d import Mobile3DProject  # noqa: E402


EXPECTED_PROJECT_SHA256 = (
    "201ac0c62fd761fa65c2f72abd7aeb9f5b7ef806210679812ef882cf1768d8a4"
)
EXPECTED_SCENE_PACK_SHA256 = (
    "d61049e17f196df928d1e5a8387e22c7df63e33932c756dd6629fd4d28a86bb9"
)
EXPECTED_HIERARCHY_PACK_SHA256 = (
    "2439348374214aabee889c5d5be1998755c6958037d95cfd0f59e2df97c8f23f"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _near(actual: Iterable[float], expected: Iterable[float], tolerance: float = 1e-9) -> None:
    actual_values = tuple(float(value) for value in actual)
    expected_values = tuple(float(value) for value in expected)
    assert len(actual_values) == len(expected_values)
    assert all(
        math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)
        for left, right in zip(actual_values, expected_values)
    ), (actual_values, expected_values)


def _runtime_trs(world: Any, node_id: str) -> TransformTRS3D:
    entity = world.require(node_id)
    return TransformTRS3D(entity.position, entity.rotation, entity.scale)


def _assert_runtime_links(project: Mobile3DProject, world: Any) -> None:
    by_id = {node.id: node for node in project.nodes}
    root = _runtime_trs(world, "carrier")
    arm = compose_world_trs_3d(root, by_id["arm"].transform)
    mast = compose_world_trs_3d(root, by_id["mast"].transform)
    beacon = compose_world_trs_3d(mast, by_id["beacon"].transform)
    for node_id, expected in (("arm", arm), ("mast", mast), ("beacon", beacon)):
        actual = _runtime_trs(world, node_id)
        _near(actual.translation, expected.translation)
        _near(actual.rotation, expected.rotation)
        _near(actual.scale, expected.scale)


def main() -> None:
    project_path = EXAMPLE_DIR / "project.json"
    payload = json.loads(project_path.read_text("utf-8"))
    project = Mobile3DProject.from_dict(payload)
    assert project.to_dict() == payload
    report = project.validate()
    assert report.passed

    hierarchy = build_hierarchy3d(project.nodes)
    assert hierarchy.parent("carrier") is None
    assert hierarchy.children("carrier") == ("arm", "mast")
    assert hierarchy.parent("beacon") == "mast"
    assert hierarchy.depth("beacon") == 2
    assert hierarchy.descendants("carrier") == ("arm", "mast", "beacon")

    authored_world = world_trs_by_id(project.nodes, hierarchy)
    _near(authored_world["carrier"].translation, (-4.0, 1.0, 0.0))
    _near(authored_world["arm"].translation, (-1.0, 1.75, 0.0))
    _near(authored_world["mast"].translation, (-4.0, 2.875, 0.0))
    _near(authored_world["beacon"].translation, (-3.25, 3.625, 0.0))

    retained = project.to_scene()
    assert retained.children("carrier") == ("arm", "mast")
    assert retained.children("mast") == ("beacon",)
    beacon_world_matrix = retained.world_transform("beacon")
    _near(
        (beacon_world_matrix[0][3], beacon_world_matrix[1][3], beacon_world_matrix[2][3]),
        authored_world["beacon"].translation,
    )

    scene_pack = compile_scene_pack_bytes(project)
    scene_info = inspect_scene_pack(scene_pack)
    assert [node["id"] for node in scene_info["nodes"]] == [
        "floor",
        "carrier",
        "arm",
        "mast",
        "beacon",
    ]

    hierarchy_pack = compile_hierarchy_pack_bytes(project)
    assert hierarchy_pack.startswith(HIERARCHY_PACK_MAGIC)
    assert len(hierarchy_pack) == 48
    hierarchy_info = inspect_hierarchy_pack(
        hierarchy_pack, node_count=len(project.nodes)
    )
    assert hierarchy_info["links"] == [
        {"child_index": 2, "parent_index": 1, "depth": 1},
        {"child_index": 3, "parent_index": 1, "depth": 1},
        {"child_index": 4, "parent_index": 3, "depth": 2},
    ]
    assert hierarchy_info["topological_child_indices"] == [2, 3, 4]

    with tempfile.TemporaryDirectory() as temporary:
        gltf_path = Path(temporary) / "hierarchy.gltf"
        write_mobile3d_gltf(project, gltf_path)
        gltf = json.loads(gltf_path.read_text("utf-8"))
        node_index = {node["name"]: index for index, node in enumerate(gltf["nodes"])}
        assert gltf["nodes"][node_index["carrier"]]["children"] == [
            node_index["arm"],
            node_index["mast"],
        ]
        assert gltf["nodes"][node_index["mast"]]["children"] == [
            node_index["beacon"]
        ]

    world = project.instantiate_world()
    assert world.transform_hierarchy_system is not None
    _assert_runtime_links(project, world)
    initial_positions = {
        node_id: tuple(world.require(node_id).position)
        for node_id in ("carrier", "arm", "mast", "beacon")
    }
    world.step(steps=64)
    _assert_runtime_links(project, world)
    _near(world.require("carrier").position, (-3.5, 1.0, 0.0))
    _near(world.require("arm").position, (-3.5, 1.75, -3.0), 2e-8)
    _near(world.require("mast").position, (-3.5, 2.875, 0.0), 2e-8)
    _near(world.require("beacon").position, (-3.5, 3.625, -0.75), 2e-8)
    assert tuple(world.require("arm").position) != initial_positions["arm"]
    assert tuple(world.require("beacon").position) != initial_positions["beacon"]

    repeated = project.instantiate_world()
    repeated.step(steps=64)
    assert repeated.state_hash() == world.state_hash()
    assert compile_scene_pack_bytes(project) == scene_pack
    assert compile_hierarchy_pack_bytes(project) == hierarchy_pack

    hashes = {
        "project": project.content_hash(),
        "KC3D": _sha256(scene_pack),
        "KCHI": _sha256(hierarchy_pack),
    }
    assert hashes == {
        "project": EXPECTED_PROJECT_SHA256,
        "KC3D": EXPECTED_SCENE_PACK_SHA256,
        "KCHI": EXPECTED_HIERARCHY_PACK_SHA256,
    }

    print(
        json.dumps(
            {
                "status": "source-level-desktop-and-native-pack-verified",
                "hierarchy": {
                    "roots": list(hierarchy.roots),
                    "topological_order": list(hierarchy.topological_order),
                    "link_count": hierarchy_info["link_count"],
                    "max_depth": hierarchy_info["max_depth"],
                    "links": hierarchy_info["links"],
                },
                "tick_64_world_positions": {
                    node_id: list(world.require(node_id).position)
                    for node_id in ("carrier", "arm", "mast", "beacon")
                },
                "packs": {
                    "KC3D": {"bytes": len(scene_pack), "sha256": hashes["KC3D"]},
                    "KCHI": {
                        "bytes": len(hierarchy_pack),
                        "sha256": hashes["KCHI"],
                    },
                },
                "project_content_sha256": hashes["project"],
                "deterministic_state_sha256": world.state_hash(),
                "evidence_boundary": (
                    "No physical phone install, launch, frame timing, or Mali capture is claimed."
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
