from __future__ import annotations

from dataclasses import replace
import copy
import math
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.animation3d import (  # noqa: E402
    ANIMATION_METADATA_KEY,
    TransformAnimation3D,
    TransformAnimationError,
    TransformKey3D,
    collect_transform_animation_spec,
    quantize_transform_animation,
    sample_transform_animation,
)
from ugts_kc3.mobile3d import InputFrame3D, Transform3DRecord  # noqa: E402
from ugts_kc3.math3d import quat_normalize  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402


def _clip(*, loop_mode: str = "once", easing: str = "smoothstep") -> TransformAnimation3D:
    return TransformAnimation3D(
        2.0,
        (
            TransformKey3D(0.0),
            TransformKey3D(
                2.0,
                (2.0, 4.0, -6.0),
                (math.sqrt(0.5), 0.0, math.sqrt(0.5), 0.0),
                (2.0, 0.5, 1.5),
                easing,
            ),
        ),
        loop_mode,
    )


def _animate_floor(project, animation: TransformAnimation3D | None = None):
    floor = project.nodes[0]
    animation = animation or _clip()
    project.nodes = (
        replace(
            floor,
            metadata={**floor.metadata, ANIMATION_METADATA_KEY: animation.to_dict()},
        ),
        *project.nodes[1:],
    )
    return project.nodes[0]


class Mobile3DTransformAnimationTests(unittest.TestCase):
    def test_schema_roundtrip_quantization_and_shortest_rotation(self) -> None:
        source = _clip(loop_mode="pingpong")
        clone = TransformAnimation3D.from_dict(copy.deepcopy(source.to_dict()))
        self.assertEqual(clone, source)
        quantized = quantize_transform_animation(source)
        self.assertEqual(quantized.loop_mode, "pingpong")
        self.assertEqual(quantized.keys[0], TransformKey3D(0.0))
        midpoint = sample_transform_animation(quantized, 1.0)
        self.assertEqual(midpoint.translation, (1.0, 2.0, -3.0))
        self.assertTrue(all(math.isfinite(value) for value in midpoint.rotation))
        self.assertAlmostEqual(sum(value * value for value in midpoint.rotation), 1.0)

        equivalent = TransformAnimation3D(
            1.0,
            (TransformKey3D(0.0), TransformKey3D(1.0, rotation=(-1, 0, 0, 0))),
        )
        quantized_equivalent = quantize_transform_animation(equivalent)
        self.assertEqual(quantized_equivalent.keys[1].rotation, (1.0, -0.0, -0.0, -0.0))
        self.assertEqual(sample_transform_animation(quantized_equivalent, 0.5).rotation[0], 1.0)

        difficult = TransformAnimation3D(
            1.0,
            (
                TransformKey3D(0.0),
                TransformKey3D(
                    1.0,
                    rotation=(
                        -0.6017525172149985,
                        -0.06335381562929654,
                        0.008092805698616257,
                        -0.8704250769649022,
                    ),
                ),
            ),
        )
        difficult_key = quantize_transform_animation(difficult).keys[1]
        self.assertIsNotNone(difficult_key.packed_rotation)
        self.assertEqual(
            quat_normalize(difficult_key.packed_rotation), difficult_key.rotation
        )
        self.assertEqual(
            tuple(
                struct.unpack("<e", struct.pack("<e", value))[0]
                for value in difficult_key.packed_rotation
            ),
            difficult_key.packed_rotation,
        )

    def test_once_loop_pingpong_and_step_boundary(self) -> None:
        once = quantize_transform_animation(_clip(easing="step"))
        self.assertEqual(sample_transform_animation(once, 1.999).translation, (0.0, 0.0, 0.0))
        self.assertEqual(sample_transform_animation(once, 2.0).translation, (2.0, 4.0, -6.0))
        self.assertEqual(sample_transform_animation(once, 99.0).translation, (2.0, 4.0, -6.0))
        loop = quantize_transform_animation(_clip(loop_mode="loop", easing="linear"))
        self.assertEqual(sample_transform_animation(loop, 2.0).translation, (0.0, 0.0, 0.0))
        pingpong = quantize_transform_animation(_clip(loop_mode="pingpong", easing="linear"))
        self.assertEqual(sample_transform_animation(pingpong, 3.0).translation, (1.0, 2.0, -3.0))
        for invalid_time in (math.nan, math.inf, -math.inf):
            with self.subTest(invalid_time=invalid_time):
                with self.assertRaisesRegex(TransformAnimationError, "finite"):
                    sample_transform_animation(once, invalid_time)

    def test_validation_rejects_unreachable_keys_and_scale_overshoot(self) -> None:
        with self.assertRaisesRegex(TransformAnimationError, "later than"):
            TransformAnimation3D(
                1.0, (TransformKey3D(0.0), TransformKey3D(2.0))
            ).validate()
        with self.assertRaisesRegex(TransformAnimationError, "cross zero"):
            TransformAnimation3D(
                1.0,
                (
                    TransformKey3D(0.0),
                    TransformKey3D(1.0, scale=(0.001, 1.0, 1.0), easing="elastic_out"),
                ),
            ).validate()

    def test_project_metrics_and_relative_copy_runtime(self) -> None:
        project = blank_mobile3d_project()
        floor = _animate_floor(project, _clip(easing="linear"))
        copied = replace(
            floor,
            id="floor_copy",
            transform=Transform3DRecord((10.0, 0.0, 0.0)),
            metadata=copy.deepcopy(floor.metadata),
        )
        project.nodes = (*project.nodes, copied)
        report = project.validate()
        self.assertEqual(report.metrics["transform_animation_binding_count"], 2)
        self.assertEqual(report.metrics["transform_animation_key_count"], 4)
        spec = collect_transform_animation_spec(project)
        self.assertEqual([binding.node_id for binding in spec.bindings], ["floor", "floor_copy"])

        world = project.instantiate_world()
        for _ in range(120):
            world.step(InputFrame3D())
        first = world.require("floor")
        second = world.require("floor_copy")
        self.assertAlmostEqual(first.position[0], 1.0, places=12)
        self.assertAlmostEqual(second.position[0], 11.0, places=12)
        self.assertEqual(second.position[0] - first.position[0], 10.0)
        self.assertIn(ANIMATION_METADATA_KEY, world.snapshot()["entities"][0]["extra_components"])
        self.assertEqual(len(world.state_hash()), 64)

    def test_animation_ticks_before_logic_blocks(self) -> None:
        project = blank_mobile3d_project()
        floor = _animate_floor(project, _clip(easing="linear"))
        observe = VisualGraph(
            "observe_animation",
            (
                GraphNode("tick", "event.tick"),
                GraphNode(
                    "position",
                    "value.component",
                    {"component": "transform", "field": "position"},
                ),
                GraphNode("remember", "action.set_state", {"key": "animated_position"}),
            ),
            (
                GraphLink("tick", "out", "remember", "in"),
                GraphLink("position", "value", "remember", "value"),
            ),
        )
        project.metadata["visual_graphs"] = [observe.to_dict()]
        project.nodes = (
            replace(floor, metadata={**floor.metadata, "visual_graph": observe.id}),
            *project.nodes[1:],
        )
        world = project.instantiate_world()
        world.step(InputFrame3D())
        self.assertEqual(tuple(world.state["animated_position"]), world.require("floor").position)
        system_names = [entry.name for entry in world._systems["pre_physics"]]
        self.assertLess(
            system_names.index("transform_animation_3d"),
            next(index for index, name in enumerate(system_names) if name.startswith("visual_graph:")),
        )

    def test_conflicting_transform_authorities_are_rejected_centrally(self) -> None:
        cases = {
            "dynamic": (
                "static",
                lambda node: replace(node, dynamic=True),
            ),
            "Player": ("Player", lambda node: replace(node, tags=("player",))),
            "Movement Pattern": (
                "Movement Pattern",
                lambda node: replace(
                    node, metadata={**node.metadata, "packed_kinematic": {}}
                ),
            ),
            "Populate Area": (
                "Populate Area",
                lambda node: replace(
                    node,
                    metadata={
                        **node.metadata,
                        "scatter_population": {
                            "instance_count": 2,
                            "seed": 1,
                            "size": [1, 0, 1],
                            "scale_min": 1,
                            "scale_max": 1,
                        },
                    },
                ),
            ),
            "spin velocity": (
                "spin velocity",
                lambda node: replace(node, angular_velocity=(0, 1, 0)),
            ),
        }
        for label, (fragment, mutate) in cases.items():
            with self.subTest(label=label):
                project = blank_mobile3d_project()
                floor = _animate_floor(project)
                project.nodes = (mutate(floor), *project.nodes[1:])
                report = project.validate(raise_on_error=False)
                self.assertFalse(report.passed)
                issues = [
                    issue.message
                    for issue in report.issues
                    if issue.code == "transform_animation.invalid"
                ]
                self.assertTrue(issues)
                self.assertIn(fragment.casefold(), issues[0].casefold())


if __name__ == "__main__":
    unittest.main()
