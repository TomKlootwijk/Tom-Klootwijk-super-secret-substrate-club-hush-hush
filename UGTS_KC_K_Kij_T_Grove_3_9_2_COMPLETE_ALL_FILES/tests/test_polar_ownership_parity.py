# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.graphpack import compile_graph_pack_bytes
from ugts_kc3.mobile3d import TransformComponent3D
from ugts_kc3.packed_kinematics import (
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import (
    GraphLink,
    GraphNode,
    GraphNodeExecutionError,
    VisualGraph,
    attach_graph,
)


def _polar_project():
    project = blank_mobile3d_project("Polar Ownership", "Test")
    codec = PackedKinematicCodec()
    packed = codec.component(
        PolarPose(math.log(3.0), 0.25, 7, 0.5),
        PolarMotion(0.1, 0.2, 0.0, 0.0),
    )
    project.nodes = tuple(
        replace(
            node,
            angular_velocity=(0.0, 0.0, 0.0),
            metadata={**node.metadata, "packed_kinematic": packed.to_dict()},
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _graph(component: str, field: str, value, graph_id: str = "write_setting"):
    return VisualGraph(
        graph_id,
        (
            GraphNode("ready", "event.ready"),
            GraphNode(
                "write",
                "action.set_component",
                {"component": component, "field": field, "value": value},
            ),
        ),
        (GraphLink("ready", "out", "write", "in"),),
    )


def _bind(project, graph: VisualGraph):
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.nodes = tuple(
        replace(node, metadata={**node.metadata, "visual_graph": graph.id})
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    return project


class PolarOwnershipParityTests(unittest.TestCase):
    def test_player_and_binary32_nonzero_spin_are_rejected(self) -> None:
        player = _polar_project()
        player.nodes = tuple(
            replace(node, tags=(*node.tags, "player")) if node.id == "goal" else node
            for node in player.nodes
        )
        report = player.validate(raise_on_error=False)
        issue = next(
            item
            for item in report.issues
            if item.code == "packed_kinematic.player_conflict"
        )
        self.assertEqual(issue.path, "nodes[2].tags")
        self.assertIn("Player controller", issue.message)

        rounds_to_zero = _polar_project()
        rounds_to_zero.nodes = tuple(
            replace(node, angular_velocity=(1.0e-50, 0.0, 0.0))
            if node.id == "goal"
            else node
            for node in rounds_to_zero.nodes
        )
        zero_report = rounds_to_zero.validate(raise_on_error=False)
        self.assertFalse(
            any(
                issue.code == "packed_kinematic.angular_velocity_conflict"
                for issue in zero_report.issues
            )
        )

        nonzero = _polar_project()
        nonzero.nodes = tuple(
            replace(node, angular_velocity=(1.0e-30, 0.0, 0.0))
            if node.id == "goal"
            else node
            for node in nonzero.nodes
        )
        nonzero_report = nonzero.validate(raise_on_error=False)
        issue = next(
            item
            for item in nonzero_report.issues
            if item.code == "packed_kinematic.angular_velocity_conflict"
        )
        self.assertEqual(issue.path, "nodes[2].angular_velocity")
        self.assertIn("Facing", issue.message)

    def test_export_rejects_owned_named_and_numeric_field_aliases(self) -> None:
        conflicts = (
            ("transform", "", {"position": [1, 2, 3], "rotation": [1, 0, 0, 0], "scale": [1, 1, 1]}),
            ("transform", "position", [1, 2, 3]),
            ("transform", "position.x", 1.0),
            ("transform", "position.z", 1.0),
            ("transform", "position.0", 1.0),
            ("transform", "position.2", 1.0),
            ("transform", "translation.x", 1.0),
            ("transform", "translation.0", 1.0),
            ("transform", "rotation", [1, 0, 0, 0]),
            ("velocity", "", [1, 2, 3]),
            ("velocity", "x", 1.0),
            ("velocity", "z", 1.0),
            ("velocity", "0", 1.0),
            ("velocity", "2", 1.0),
            ("angular_velocity", "y", 1.0),
        )
        for index, (component, field, value) in enumerate(conflicts):
            with self.subTest(component=component, field=field):
                project = _bind(
                    _polar_project(),
                    _graph(component, field, value, f"conflict_{index}"),
                )
                report = project.validate(raise_on_error=False)
                issue = next(
                    item
                    for item in report.issues
                    if item.code == "packed_kinematic.graph_write_conflict"
                )
                self.assertIn("Movement Pattern owns X/Z", issue.message)
                with self.assertRaisesRegex(ValueError, "Movement Pattern owns X/Z"):
                    compile_graph_pack_bytes(project)

    def test_y_and_scale_writes_remain_valid_and_execute(self) -> None:
        safe = (
            ("transform", "position.y", 4.0),
            ("transform", "position.1", 4.0),
            ("transform", "translation.y", 4.0),
            ("transform", "translation.1", 4.0),
            ("transform", "scale", [1.25, 1.25, 1.25]),
            ("velocity", "y", 6.0),
            ("velocity", "1", 6.0),
        )
        for index, (component, field, value) in enumerate(safe):
            with self.subTest(component=component, field=field):
                project = _bind(
                    _polar_project(), _graph(component, field, value, f"safe_{index}")
                )
                report = project.validate(raise_on_error=False)
                self.assertFalse(
                    any(
                        issue.code == "packed_kinematic.graph_write_conflict"
                        for issue in report.issues
                    )
                )
                self.assertTrue(compile_graph_pack_bytes(project))

        world = _polar_project().instantiate_world()
        before_xz = (world.require("goal").position[0], world.require("goal").position[2])
        attach_graph(
            world,
            _graph("transform", "position.y", 4.5, "runtime_y"),
            entity_id="goal",
        )
        self.assertEqual(world.require("goal").position[1], 4.5)
        self.assertEqual(
            (world.require("goal").position[0], world.require("goal").position[2]),
            before_xz,
        )
        attach_graph(
            world,
            _graph("velocity", "1", 7.5, "runtime_velocity_y"),
            entity_id="goal",
        )
        self.assertEqual(world.require("goal").velocity[1], 7.5)

    def test_runtime_rejects_graph_and_direct_whole_component_bypasses(self) -> None:
        world = _polar_project().instantiate_world()
        before = world.require("goal").position
        with self.assertRaisesRegex(
            GraphNodeExecutionError, "Movement Pattern owns X/Z"
        ):
            attach_graph(
                world,
                _graph("transform", "position.0", 99.0, "runtime_conflict"),
                entity_id="goal",
            )
        self.assertEqual(world.require("goal").position, before)

        transform = world.require("goal", "transform")
        replacement = TransformComponent3D(
            (99.0, transform.position[1], 99.0),
            transform.rotation,
            transform.scale,
        )
        with self.assertRaisesRegex(ValueError, "Cannot change transform"):
            world.add_component(
                "goal", replacement, "transform", replace_existing=True
            )
        with self.assertRaisesRegex(ValueError, "Cannot change velocity"):
            world.add_component(
                "goal", (9.0, 1.0, 9.0), "velocity", replace_existing=True
            )


if __name__ == "__main__":
    unittest.main()
