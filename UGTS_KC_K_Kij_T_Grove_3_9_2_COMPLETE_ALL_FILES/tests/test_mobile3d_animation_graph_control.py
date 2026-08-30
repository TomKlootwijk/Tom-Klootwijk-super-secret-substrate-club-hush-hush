from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.animation3d import (  # noqa: E402
    TransformAnimation3D,
    TransformAnimationLibrary3D,
    TransformClip3D,
    TransformKey3D,
    metadata_with_transform_animation_library,
)
from ugts_kc3.mobile3d import InputFrame3D  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402


def _library() -> TransformAnimationLibrary3D:
    return TransformAnimationLibrary3D(
        (
            TransformClip3D(
                "idle",
                "Idle",
                TransformAnimation3D(
                    1.0,
                    (TransformKey3D(0.0),),
                    "loop",
                ),
            ),
            TransformClip3D(
                "jump",
                "Jump",
                TransformAnimation3D(
                    1.0,
                    (
                        TransformKey3D(0.0),
                        TransformKey3D(
                            1.0,
                            translation=(6.0, 0.0, 0.0),
                            easing="linear",
                        ),
                    ),
                ),
            ),
        ),
        autoplay=None,
    )


def _play_graph(clip: str = "jump") -> VisualGraph:
    return VisualGraph(
        "play_on_ready",
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "play",
                "action.play_animation",
                {"entity": None, "clip": clip, "restart": True},
            ),
        ),
        (GraphLink("ready", "out", "play", "in"),),
    )


def _animated_project(graph: VisualGraph):
    project = blank_mobile3d_project()
    floor = project.nodes[0]
    project.nodes = (
        replace(
            floor,
            metadata={
                **metadata_with_transform_animation_library(
                    floor.metadata,
                    _library(),
                ),
                "visual_graph": graph.id,
            },
        ),
        *project.nodes[1:],
    )
    project.metadata["visual_graphs"] = [graph.to_dict()]
    return project


class Mobile3DAnimationGraphControlTests(unittest.TestCase):
    def test_project_validation_and_ready_action_drive_real_ecs_component(self) -> None:
        project = _animated_project(_play_graph())
        report = project.validate()
        self.assertEqual(report.metrics["transform_animation_binding_count"], 1)
        self.assertEqual(report.metrics["transform_animation_clip_count"], 2)

        world = project.instantiate_world()
        component = world.require("floor", "transform_animation")
        self.assertEqual(component.active_clip, "jump")
        self.assertTrue(component.playing)
        self.assertEqual(component.elapsed, 0.0)
        self.assertEqual(world.require("floor").position, (0.0, 0.0, 0.0))

        for _ in range(60):
            world.step(InputFrame3D())
        self.assertAlmostEqual(component.elapsed, 0.5, places=12)
        self.assertAlmostEqual(world.require("floor").position[0], 3.0, places=5)

    def test_fixed_missing_clip_and_unanimated_target_fail_before_export(self) -> None:
        missing_clip = _animated_project(_play_graph("missing"))
        report = missing_clip.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        issue = next(
            item
            for item in report.issues
            if item.code == "transform_animation.graph_control"
        )
        self.assertIn("missing", issue.message)
        self.assertIn("do not have it", issue.message)

        graph = _play_graph()
        unanimated = blank_mobile3d_project()
        floor = unanimated.nodes[0]
        unanimated.nodes = (
            replace(floor, metadata={**floor.metadata, "visual_graph": graph.id}),
            *unanimated.nodes[1:],
        )
        unanimated.metadata["visual_graphs"] = [graph.to_dict()]
        report = unanimated.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        issue = next(
            item
            for item in report.issues
            if item.code == "transform_animation.graph_control"
        )
        self.assertIn("without an Animation", issue.message)

    def test_world_logic_requires_an_explicit_animation_target(self) -> None:
        project = blank_mobile3d_project()
        graph = _play_graph()
        project.metadata["visual_graphs"] = [graph.to_dict()]
        project.metadata["world_graphs"] = [graph.id]
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        issue = next(
            item
            for item in report.issues
            if item.code == "transform_animation.graph_control"
        )
        self.assertIn("World Logic", issue.message)
        self.assertIn("specific animated object", issue.message)


if __name__ == "__main__":
    unittest.main()
