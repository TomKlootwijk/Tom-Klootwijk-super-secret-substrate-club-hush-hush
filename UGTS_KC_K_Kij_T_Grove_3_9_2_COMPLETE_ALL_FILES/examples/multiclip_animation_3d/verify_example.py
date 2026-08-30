"""Deterministic smoke check for the two-clips/Play/Stop example."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys


EXAMPLE_DIR = Path(__file__).resolve().parent
ROOT = EXAMPLE_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.animation3d import (  # noqa: E402
    ANIMATION_METADATA_KEY,
    animation_clip_hash,
    transform_animation_library_from_metadata,
)
from ugts_kc3.animationpack import (  # noqa: E402
    ANIMATION_PACK_VERSION,
    compile_animation_pack_bytes,
    inspect_animation_pack,
)
from ugts_kc3.graphpack import (  # noqa: E402
    NODE_OPCODES,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.mobile3d import Mobile3DProject, visual_graphs_from_metadata  # noqa: E402


def close_tuple(actual: tuple[float, ...], expected: tuple[float, ...]) -> bool:
    return all(
        math.isclose(left, right, rel_tol=0.0, abs_tol=1.0e-9)
        for left, right in zip(actual, expected)
    )


def main() -> None:
    project_path = EXAMPLE_DIR / "project.json"
    raw = project_path.read_bytes()

    # Mobile3DProject has from_dict/load rather than a separate from_json API.
    project = Mobile3DProject.from_dict(
        json.loads(raw.decode("utf-8")), validate=False
    )
    validation = project.validate(raise_on_error=False)
    assert validation.passed, validation.to_dict()

    cube_node = next(node for node in project.nodes if node.id == "motion_cube")
    assert cube_node.dynamic is False
    library = transform_animation_library_from_metadata(cube_node.metadata)
    assert library is not None
    assert tuple(clip.id for clip in library.clips) == ("sway", "hop")
    assert library.autoplay == "sway"
    assert library.clip("hop").id != library.autoplay

    graphs = visual_graphs_from_metadata(project.metadata)
    assert len(graphs) == 1
    graph = graphs[0]
    graph.validate()
    action_opcodes = {
        node.type: NODE_OPCODES[node.type]
        for node in graph.nodes
        if node.type in {"action.play_animation", "action.stop_animation"}
    }
    assert action_opcodes == {
        "action.play_animation": 26,
        "action.stop_animation": 27,
    }

    world = project.instantiate_world()
    cube = world.require("motion_cube")
    component = world.require("motion_cube", ANIMATION_METADATA_KEY)
    base = tuple(component.base_translation)
    assert base == (0.0, 1.0, 0.0)
    assert component.active_clip == "sway" and component.playing

    world.step(steps=59)
    assert component.active_clip == "sway"
    assert not close_tuple(tuple(cube.position), base)

    # The 60th 120 Hz step is exactly 0.5 seconds: Timer -> Stop -> Play hop.
    world.step()
    assert component.active_clip == "hop" and component.playing
    assert component.elapsed == 0.0
    assert close_tuple(tuple(cube.position), base)

    world.step(steps=30)
    assert component.active_clip == "hop" and component.playing
    assert math.isclose(component.elapsed, 0.25, rel_tol=0.0, abs_tol=1.0e-12)
    # KCAN uses a normalized uint16 key time, so authored 0.5 seconds lands a
    # few millionths later after its phone-format round trip.
    assert math.isclose(cube.position[1], 2.0, rel_tol=0.0, abs_tol=2.0e-5)

    world.step(steps=90)
    assert component.active_clip == "hop" and not component.playing
    assert math.isclose(component.elapsed, 1.0, rel_tol=0.0, abs_tol=1.0e-12)
    assert close_tuple(tuple(cube.position), base)

    kcan = compile_animation_pack_bytes(project)
    assert compile_animation_pack_bytes(project) == kcan
    kcan_info = inspect_animation_pack(kcan, node_count=len(project.nodes))
    assert kcan_info["format_version"] == ANIMATION_PACK_VERSION == 2
    assert kcan_info["binding_count"] == 2
    assert {item["clip_hash"] for item in kcan_info["bindings"]} == {
        animation_clip_hash("sway"),
        animation_clip_hash("hop"),
    }
    assert sum(item["autoplay"] for item in kcan_info["bindings"]) == 1

    kcvg = compile_graph_pack_bytes(project)
    assert compile_graph_pack_bytes(project) == kcvg
    kcvg_info = inspect_graph_pack(kcvg)
    assert kcvg_info["graph_count"] == 1
    assert kcvg_info["binding_count"] == 1
    assert kcvg_info["node_count"] == 3

    result = {
        "project_file_bytes": len(raw),
        "project_file_sha256": hashlib.sha256(raw).hexdigest(),
        "project_content_sha256": project.content_hash(),
        "validation_metrics": validation.metrics,
        "runtime": {
            "fixed_dt": project.world.fixed_dt,
            "timer_ring_tick": 60,
            "mid_hop_tick": 90,
            "completed_tick": world.tick,
            "final_active_clip": component.active_clip,
            "final_playing": component.playing,
            "final_position": list(cube.position),
            "state_sha256": world.state_hash(),
        },
        "kcan_v2": {
            "bytes": len(kcan),
            "sha256": hashlib.sha256(kcan).hexdigest(),
            "binding_count": kcan_info["binding_count"],
            "key_count": kcan_info["packed_key_count"],
            "clip_hashes": {
                "hop": f"0x{animation_clip_hash('hop'):016x}",
                "sway": f"0x{animation_clip_hash('sway'):016x}",
            },
        },
        "kcvg": {
            "bytes": len(kcvg),
            "sha256": hashlib.sha256(kcvg).hexdigest(),
            "graph_count": kcvg_info["graph_count"],
            "binding_count": kcvg_info["binding_count"],
            "opcodes": action_opcodes,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
