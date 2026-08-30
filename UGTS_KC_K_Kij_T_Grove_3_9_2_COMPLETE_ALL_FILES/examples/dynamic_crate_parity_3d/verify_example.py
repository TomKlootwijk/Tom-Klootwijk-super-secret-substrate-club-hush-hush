"""Emit the deterministic Python golden for the generic dynamic-crate slice."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import sys
from typing import Any, Iterable


EXAMPLE_DIR = Path(__file__).resolve().parent
ROOT = EXAMPLE_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import (  # noqa: E402
    PACK_MAGIC,
    compile_scene_pack_bytes,
    inspect_scene_pack,
)
from ugts_kc3.graphpack import (  # noqa: E402
    GRAPH_PACK_MAGIC,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.mobile3d import (  # noqa: E402
    Mobile3DProject,
    visual_graphs_from_metadata,
)


CHECKPOINT_TICKS = (0, 1, 64, 128, 256, 512, 600)
STATE_GOLDEN_MAGIC = b"UGTS-DYNAMIC-CRATE-F32-1\0"
EXPECTED_PROJECT_CONTENT_SHA256 = (
    "20c137e6bec7ace4198270c5cfaacdc052b58739d0c7985573e13ad8dbb68d2d"
)
EXPECTED_SCENE_PACK = {
    "bytes": 1457,
    "sha256": "f64c03d171391d62e173cdf5641956b2d19fd54799976687f0ee6d933062bad4",
}
EXPECTED_GRAPH_PACK = {
    "bytes": 137,
    "sha256": "c2f40f242e08e13a345bbe94c82c0abc11eb1ca1ce93c5cfaab06646371d9e76",
}
EXPECTED_VELOCITY_BITS = ("0x3f800000", "0x00000000", "0x00000000")
EXPECTED_VELOCITY_SHA256 = (
    "480376c6bf738a0227f2bbf2b3506b7cde209152c0ba9a9077e5527169eb292e"
)
EXPECTED_CHECKPOINTS = {
    0: {
        "time_bits": "0x00000000",
        "position_bits": ("0xc1000000", "0x3f000000", "0x00000000"),
        "position_sha256": (
            "96cb5f4bde49d4e816fd4e5ba536965e6aa23b43f25a5cb3fc80ed09ff98a1b4"
        ),
        "state_sha256": (
            "001b2aeacbb2eabcbb256a9bd51843bdebc8e34e35537ec18da6e129059556a1"
        ),
    },
    1: {
        "time_bits": "0x3c800000",
        "position_bits": ("0xc0ff8000", "0x3f000000", "0x00000000"),
        "position_sha256": (
            "c01d002373acd323bd105e6f8f545e966c13ca1ea18646b69741b81a18d68e6e"
        ),
        "state_sha256": (
            "09d6744c9bf1d24f00a81fd883d7f6f3d0d60dcf4b92d9f3d27824a2cb4c70aa"
        ),
    },
    64: {
        "time_bits": "0x3f800000",
        "position_bits": ("0xc0e00000", "0x3f000000", "0x00000000"),
        "position_sha256": (
            "9f1159e8885f4558e60a6d1295344b88c5a867b97a9216536c30b5c0e6f9fc08"
        ),
        "state_sha256": (
            "a41fcea2f77169cb32d5d57da3d7a73af2dcc1c430c398453035d6f70da08484"
        ),
    },
    128: {
        "time_bits": "0x40000000",
        "position_bits": ("0xc0c00000", "0x3f000000", "0x00000000"),
        "position_sha256": (
            "652567e9266e16a00b84563b49c532f79b3c8f0e37ad1eade81e92d4e907e0b5"
        ),
        "state_sha256": (
            "536f50148ae4b26d50223a1a6ecf899036119a45fdccd883ffd90aa52b766563"
        ),
    },
    256: {
        "time_bits": "0x40800000",
        "position_bits": ("0xc0800000", "0x3f000000", "0x00000000"),
        "position_sha256": (
            "7cc264609364114ea5f18a3031d5001de25063a64004a5ce480c4e7bee8c0f43"
        ),
        "state_sha256": (
            "c4c6d2561f069a050470b964044183880c4563de994a64776211704e9166a0a9"
        ),
    },
    512: {
        "time_bits": "0x41000000",
        "position_bits": ("0x00000000", "0x3f000000", "0x00000000"),
        "position_sha256": (
            "3a890279e0acf00d624f87177a1a0e15281b483a0dd755417482c5a6957a84bb"
        ),
        "state_sha256": (
            "24d3fae001238b786fd2a233baeba2d7d4b06a7e948b916d94d01107b8776f34"
        ),
    },
    600: {
        "time_bits": "0x41160000",
        "position_bits": ("0x3fb00000", "0x3f000000", "0x00000000"),
        "position_sha256": (
            "c98f721d7e8562f115ba6059ddfd92b68d4a728e8a72f74d2c7b252598bdf8f6"
        ),
        "state_sha256": (
            "46dca53035cfb67afe92907c5d2113a74b9b382ddd4d38e983e0c46b47f949ba"
        ),
    },
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _f32_bytes(values: Iterable[float]) -> bytes:
    values = tuple(float(value) for value in values)
    return struct.pack(f"<{len(values)}f", *values)


def _f32_values(data: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{len(data) // 4}f", data)


def _f32_bits(data: bytes) -> tuple[str, ...]:
    return tuple(
        f"0x{struct.unpack_from('<I', data, offset)[0]:08x}"
        for offset in range(0, len(data), 4)
    )


def _state_golden_bytes(world: Any) -> bytes:
    crate = world.require("crate")
    return b"".join(
        (
            STATE_GOLDEN_MAGIC,
            struct.pack("<I", world.tick),
            _f32_bytes((world.time,)),
            _f32_bytes(crate.position),
            _f32_bytes(crate.velocity),
            struct.pack(
                "<4B",
                crate.alive,
                crate.active,
                crate.dynamic,
                crate.grounded,
            ),
            struct.pack(
                "<iiB",
                int(world.state["score"]),
                int(world.state["health"]),
                bool(world.state["finished"]),
            ),
        )
    )


def _checkpoint(world: Any) -> dict[str, Any]:
    crate = world.require("crate")
    position = _f32_bytes(crate.position)
    velocity = _f32_bytes(crate.velocity)
    time = _f32_bytes((world.time,))
    state = _state_golden_bytes(world)
    return {
        "tick": world.tick,
        "time_f32": _f32_values(time)[0],
        "time_bits": _f32_bits(time)[0],
        "position_f32": list(_f32_values(position)),
        "position_bits": list(_f32_bits(position)),
        "position_sha256": _sha256(position),
        "velocity_f32": list(_f32_values(velocity)),
        "velocity_bits": list(_f32_bits(velocity)),
        "velocity_sha256": _sha256(velocity),
        "state_bytes_hex": state.hex(),
        "state_sha256": _sha256(state),
    }


def _run_checkpoints(project: Mobile3DProject) -> list[dict[str, Any]]:
    world = project.instantiate_world()
    crate = world.require("crate")
    player = world.require("player")

    # Ready has already run. It must push the graph owner, never Player.
    assert crate.velocity == (1.0, 0.0, 0.0)
    assert player.velocity == (0.0, 0.0, 0.0)
    assert len(world.visual_graph_bindings) == 1

    checkpoints = []
    for tick in CHECKPOINT_TICKS:
        if world.tick < tick:
            world.step(steps=tick - world.tick)
        checkpoints.append(_checkpoint(world))

    assert world.tick == 600
    assert not world.events, "the isolated 600-tick integration must end before contact"
    assert world.require("floor").position == (0.0, -0.1, 0.0)
    assert world.require("wall").position == (6.0, 1.5, 0.0)
    assert player.position == (-6.0, 0.5, 4.0)
    return checkpoints


def _assert_checkpoint_golden(checkpoints: list[dict[str, Any]]) -> None:
    assert [item["tick"] for item in checkpoints] == list(CHECKPOINT_TICKS)
    for item in checkpoints:
        expected = EXPECTED_CHECKPOINTS[item["tick"]]
        assert item["time_bits"] == expected["time_bits"]
        assert tuple(item["position_bits"]) == expected["position_bits"]
        assert item["position_sha256"] == expected["position_sha256"]
        assert tuple(item["velocity_bits"]) == EXPECTED_VELOCITY_BITS
        assert item["velocity_sha256"] == EXPECTED_VELOCITY_SHA256
        assert item["state_sha256"] == expected["state_sha256"]


def main() -> None:
    project_path = EXAMPLE_DIR / "project.json"
    payload = json.loads(project_path.read_text("utf-8"))
    project = Mobile3DProject.from_dict(payload)
    assert project.to_dict() == payload
    report = project.validate()
    assert report.passed
    assert report.metrics["node_count"] == 4
    assert report.metrics["dynamic_node_count"] == 2
    assert report.metrics["visual_graph_count"] == 1
    assert report.metrics["visual_graph_binding_count"] == 1
    assert project.content_hash() == EXPECTED_PROJECT_CONTENT_SHA256

    nodes = {node.id: node for node in project.nodes}
    crate = nodes["crate"]
    player = nodes["player"]
    assert crate.dynamic and crate.tags == ()
    assert crate.mass == 1.5 and crate.velocity == (0.0, 0.0, 0.0)
    assert crate.metadata["visual_graph"] == "push_crate_once"
    assert player.dynamic and player.tags == ("player",)
    assert "visual_graph" not in player.metadata
    assert not nodes["floor"].dynamic and not nodes["wall"].dynamic

    graphs = visual_graphs_from_metadata(project.metadata)
    assert len(graphs) == 1
    graph = graphs[0]
    assert graph.id == "push_crate_once"
    assert {node.type for node in graph.nodes} == {
        "event.ready",
        "action.apply_force",
    }
    apply_force = next(node for node in graph.nodes if node.type == "action.apply_force")
    assert apply_force.properties["entity"] is None
    assert tuple(apply_force.properties["force"]) == (1.5, 0.0)
    bound_nodes = [
        node.id
        for node in project.nodes
        if node.metadata.get("visual_graph") == graph.id
    ]
    assert bound_nodes == ["crate"]

    scene_pack = compile_scene_pack_bytes(project)
    graph_pack = compile_graph_pack_bytes(project)
    assert compile_scene_pack_bytes(project) == scene_pack
    assert compile_graph_pack_bytes(project) == graph_pack
    assert scene_pack.startswith(PACK_MAGIC)
    assert graph_pack.startswith(GRAPH_PACK_MAGIC)
    assert len(scene_pack) == EXPECTED_SCENE_PACK["bytes"]
    assert _sha256(scene_pack) == EXPECTED_SCENE_PACK["sha256"]
    assert len(graph_pack) == EXPECTED_GRAPH_PACK["bytes"]
    assert _sha256(graph_pack) == EXPECTED_GRAPH_PACK["sha256"]

    scene_info = inspect_scene_pack(scene_pack)
    graph_info = inspect_graph_pack(graph_pack)
    assert scene_info["project_hash"] == EXPECTED_PROJECT_CONTENT_SHA256
    assert [node["id"] for node in scene_info["nodes"]] == [
        "floor",
        "wall",
        "player",
        "crate",
    ]
    packed_crate = scene_info["nodes"][3]
    assert packed_crate["dynamic"] and packed_crate["tag_mask"] == 0
    assert scene_info["nodes"][2]["tag_mask"] != 0
    assert graph_info["graphs"] == [
        {"id": "push_crate_once", "node_count": 2, "max_steps": 1024}
    ]
    assert graph_info["bindings"] == [
        {
            "graph": "push_crate_once",
            "scope": "node",
            "scene_node_index": 3,
        }
    ]
    assert graph_info["world_binding_count"] == 0

    checkpoints = _run_checkpoints(project)
    _assert_checkpoint_golden(checkpoints)
    assert _run_checkpoints(project) == checkpoints

    result = {
        "status": "python-golden-native-acceptance-is-a-separate-host-test",
        "authoring_evidence": {
            "crate_id": crate.id,
            "crate_dynamic": crate.dynamic,
            "crate_tags": list(crate.tags),
            "player_id": player.id,
            "player_is_graph_target": False,
            "graph_id": graph.id,
            "event": "event.ready",
            "action": "action.apply_force",
            "action_entity": None,
            "owner_binding": bound_nodes,
            "force_vec2": list(apply_force.properties["force"]),
            "crate_mass": crate.mass,
            "ready_velocity_f32": checkpoints[0]["velocity_f32"],
        },
        "simulation_contract": {
            "fixed_dt_f32": project.world.fixed_dt,
            "fixed_dt_bits": _f32_bits(_f32_bytes((project.world.fixed_dt,)))[0],
            "steps": 600,
            "state_magic_hex": STATE_GOLDEN_MAGIC.hex(),
            "state_layout": (
                "magic | u32 tick | f32 time | f32[3] position | "
                "f32[3] velocity | u8 alive,active,dynamic,grounded | "
                "i32 score,health | u8 finished; all little-endian"
            ),
            "checkpoints": checkpoints,
        },
        "packs": {
            "KC3D": {
                "magic_hex": PACK_MAGIC.hex(),
                "bytes": len(scene_pack),
                "sha256": _sha256(scene_pack),
                "format_version": scene_info["format_version"],
                "node_count": scene_info["node_count"],
                "crate_scene_node_index": 3,
                "crate_record": packed_crate,
            },
            "KCVG": {
                "magic_hex": GRAPH_PACK_MAGIC.hex(),
                "bytes": len(graph_pack),
                "sha256": _sha256(graph_pack),
                "format_version": graph_info["format_version"],
                "graph_count": graph_info["graph_count"],
                "node_count": graph_info["node_count"],
                "binding_count": graph_info["binding_count"],
                "bindings": graph_info["bindings"],
            },
        },
        "project_content_sha256": project.content_hash(),
        "validation_metrics": report.metrics,
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
