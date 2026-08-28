"""KC Two Hands 3.0 reference vertical slice.

The demo compiles procedural geometry, builds a scene, applies a two-hand transform through the
authoritative event path, renders deterministic SVG previews, exports glTF/USDA, and writes a
replay/diagnostic record.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ugts_kc import gielis, gyroid_field
from ugts_kc3 import (
    Asset,
    BimanualAnchor,
    Camera,
    EventProposal,
    HandPose,
    KCRuntime,
    PBRMaterial,
    ReplayLog,
    RenderSettings,
    Scene,
    SceneNode,
    audit_scene,
    checkpoint_runtime,
    compute_bimanual_transform,
    compose_trs,
    marching_tetrahedra,
    mat4_identity,
    quat_from_axis_angle,
    render_scene_svg,
    runtime_report,
    tube_mesh,
    write_gltf,
    write_scene_json,
    write_usda,
)

OUT = ROOT / "examples" / "output"
OUT.mkdir(parents=True, exist_ok=True)


def build_scene():
    # Pattern-derived closed tube with a gentle height modulation.
    path = []
    samples = 48
    for i in range(samples + 1):
        t = 2.0 * math.pi * i / samples
        x, z = gielis(t, m=5, n1=0.7, n2=1.7, n3=1.7, a=1.0, b=1.0)
        path.append((1.05 * x, 0.22 * math.sin(3 * t), 1.05 * z))
    sculpture_mesh = tube_mesh(path, radius=0.085, sides=10, cap=False)

    # Small implicit gyroid panel demonstrates field -> render mesh compilation.
    field = lambda p: gyroid_field((p[0] * 2.1, p[1] * 2.1, p[2] * 2.1), threshold=0.25)
    field_mesh = marching_tetrahedra(field, (-0.75, -0.75, -0.75), (0.75, 0.75, 0.75), (9, 9, 9))

    scene = Scene()
    scene.add_asset(Asset("gielis_tube_asset", sculpture_mesh, "teal", "M199", metadata={"role": "interactive_sculpture"}))
    scene.add_asset(Asset("gyroid_asset", field_mesh, "gold", "M225", metadata={"role": "compiled_field"}))
    scene.add_node(SceneNode("world"))
    scene.add_node(SceneNode("sculpture", "gielis_tube_asset", "world", tags=frozenset({"interactive", "two_hand"})))
    scene.add_node(SceneNode("gyroid_panel", "gyroid_asset", "world", compose_trs((2.0, -0.1, 0.0), scale_value=0.8), tags=frozenset({"decorative"})))
    return scene


def main():
    materials = {
        "teal": PBRMaterial("teal", (0.12, 0.72, 0.78, 1.0), metallic=0.12, roughness=0.32),
        "gold": PBRMaterial("gold", (0.95, 0.62, 0.12, 0.86), metallic=0.42, roughness=0.28, alpha_mode="BLEND"),
    }
    initial_scene = build_scene()
    runtime = KCRuntime(initial_scene.clone())
    replay = ReplayLog(initial_scene)
    replay.add_checkpoint(checkpoint_runtime(runtime))

    camera = Camera(position=(5.2, 3.4, 6.2), target=(0.6, 0.2, 0.0))
    settings = RenderSettings(width=1100, height=720, show_node_labels=True)
    before = render_scene_svg(runtime.scene, OUT / "sandbox_before.svg", materials, camera, settings)

    left0 = HandPose("left", (-0.8, 0.0, 0.0), timestamp=0.0)
    right0 = HandPose("right", (0.8, 0.0, 0.0), timestamp=0.0)
    anchor = BimanualAnchor(left0, right0, runtime.scene.nodes["sculpture"].local_transform)
    left1 = HandPose("left", (-1.0, 0.65, 0.10), quat_from_axis_angle((1, 0, 0), -0.15), timestamp=1.0)
    right1 = HandPose("right", (1.65, 0.95, 0.35), quat_from_axis_angle((1, 0, 0), 0.55), timestamp=1.0)
    result = compute_bimanual_transform(anchor, left1, right1)

    committed = runtime.commit_proposals([
        EventProposal(
            proposal_id="hands-transform-0001",
            event_time=1.0,
            event_type="set_transform",
            entity_id="sculpture",
            payload={"transform": result.world_transform, "gesture": "bimanual_transform"},
            source="two_hands",
            priority=10,
            confidence=result.confidence,
            lineage_label="two_hands:transform:0001",
        )
    ])
    for event in committed:
        replay.append(event)

    after = render_scene_svg(runtime.scene, OUT / "sandbox_after.svg", materials, camera, settings)
    write_gltf(runtime.scene, OUT / "sandbox_scene.gltf", materials)
    write_usda(runtime.scene, OUT / "sandbox_scene.usda")
    write_scene_json(runtime.scene, OUT / "sandbox_scene.json")
    replay.write(OUT / "sandbox_replay.json")
    runtime_report(runtime).write(OUT / "sandbox_diagnostics.json")
    audit_scene(runtime.scene).write(OUT / "sandbox_scene_audit.json")

    summary = {
        "version": "3.0.0",
        "bimanual_result": {
            "status": result.status,
            "translation": result.translation,
            "scale": result.scale,
            "twist_radians": result.twist_radians,
            "confidence": result.confidence,
        },
        "event_count": len(runtime.events),
        "scene_hash": runtime.scene.content_hash(),
        "before_render": before.__dict__,
        "after_render": after.__dict__,
        "outputs": sorted(p.name for p in OUT.iterdir()),
    }
    (OUT / "sandbox_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
