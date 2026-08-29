from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ugts_kc3.graphpack import (  # noqa: E402
    NODE_DATA_OUTPUTS,
    NODE_FLOW_OUTPUTS,
    NODE_INPUTS,
    NODE_OPCODES,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.mobile3d import Mobile3DProject  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402


OLD_OPCODES = {
    "event.ready": 1,
    "event.tick": 2,
    "event.input_pressed": 3,
    "flow.branch": 4,
    "value.constant": 5,
    "value.state": 6,
    "value.component": 7,
    "math.add": 8,
    "math.subtract": 9,
    "math.multiply": 10,
    "math.divide": 11,
    "compare": 12,
    "action.set_state": 13,
    "action.set_component": 14,
    "action.emit_event": 15,
    "action.set_active": 16,
    "action.despawn": 17,
    "action.apply_force": 18,
    "event.trigger_enter": 19,
    "event.trigger_exit": 20,
    "value.seeded_number": 21,
    "query.nearest_tag": 22,
    "event.timer": 23,
}


def _attach_world(project: Mobile3DProject, graph: VisualGraph) -> None:
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.metadata["world_graphs"] = graph.id


def _project_with(graph: VisualGraph) -> Mobile3DProject:
    project = blank_mobile3d_project()
    _attach_world(project, graph)
    return project


class NearestInConeGraphPackTests(unittest.TestCase):
    def test_opcode_24_is_append_only_with_four_inputs_and_three_outputs(self) -> None:
        self.assertEqual(
            {name: NODE_OPCODES[name] for name in OLD_OPCODES},
            OLD_OPCODES,
        )
        self.assertEqual(NODE_OPCODES["query.nearest_in_cone"], 24)
        self.assertEqual(
            NODE_INPUTS["query.nearest_in_cone"],
            ("origin", "tag", "radius", "cone"),
        )
        self.assertEqual(
            NODE_DATA_OUTPUTS["query.nearest_in_cone"],
            ("found", "entity", "distance"),
        )
        self.assertEqual(NODE_FLOW_OUTPUTS["query.nearest_in_cone"], ())
        self.assertLessEqual(len(NODE_INPUTS["query.nearest_in_cone"]), 4)
        self.assertEqual(len(NODE_DATA_OUTPUTS["query.nearest_in_cone"]), 3)

    def test_all_ports_pack_canonically_and_inspection_accepts_opcode_24(self) -> None:
        graph = VisualGraph(
            "cone_pack",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("origin", "value.constant", {"value": "player"}),
                GraphNode("tag", "value.constant", {"value": "goal"}),
                GraphNode("radius", "value.constant", {"value": 10.0}),
                GraphNode(
                    "cone",
                    "value.constant",
                    {"value": (2.0, 0.0, 0.0, 0.8)},
                ),
                GraphNode("query", "query.nearest_in_cone"),
                GraphNode("remember_found", "action.set_state", {"key": "found"}),
                GraphNode("remember_entity", "action.set_state", {"key": "entity"}),
                GraphNode("remember_distance", "action.set_state", {"key": "distance"}),
            ),
            (
                GraphLink("ready", "out", "remember_found", "in"),
                GraphLink("ready", "out", "remember_entity", "in"),
                GraphLink("ready", "out", "remember_distance", "in"),
                GraphLink("origin", "value", "query", "origin"),
                GraphLink("tag", "value", "query", "tag"),
                GraphLink("radius", "value", "query", "radius"),
                GraphLink("cone", "value", "query", "cone"),
                GraphLink("query", "found", "remember_found", "value"),
                GraphLink("query", "entity", "remember_entity", "value"),
                GraphLink("query", "distance", "remember_distance", "value"),
            ),
        )
        project = _project_with(graph)
        packed = compile_graph_pack_bytes(project)
        self.assertEqual(
            compile_graph_pack_bytes(Mobile3DProject.from_dict(project.to_dict())),
            packed,
        )
        info = inspect_graph_pack(packed)
        self.assertEqual(info["node_count"], 9)
        self.assertEqual(info["input_count"], 14)
        self.assertEqual(info["flow_target_count"], 3)
        self.assertEqual(info["world_binding_count"], 1)
        self.assertEqual(info["state_keys"], ["distance", "entity", "found"])

    def test_invalid_literal_cones_are_rejected_before_export(self) -> None:
        for cone, message in (
            ((0.0, 0.0, 0.0, 0.0), "Facing direction must not be zero"),
            ((1.0, 0.0, 0.0, 1.0001), "minimum cosine from -1 to 1"),
            ((1.0, 0.0, 0.0, -1.0001), "minimum cosine from -1 to 1"),
            ((1.0e30, 0.0, 0.0, 0.5), "too large for deterministic"),
            ((1.0, 0.0, 0.0), "must be vector4"),
            ("ahead", "must be vector4"),
        ):
            graph = VisualGraph(
                "bad_literal",
                (
                    GraphNode(
                        "query",
                        "query.nearest_in_cone",
                        {
                            "origin": "player",
                            "tag": "goal",
                            "radius": 10.0,
                            "cone": cone,
                        },
                    ),
                ),
            )
            with self.subTest(cone=cone), self.assertRaisesRegex(ValueError, message):
                compile_graph_pack_bytes(_project_with(graph))

    def test_linked_invalid_cones_remain_packed_for_runtime_validation(self) -> None:
        for cone in (
            (0.0, 0.0, 0.0, 0.0),
            (1.0, 0.0, 0.0, 1.0001),
            (1.0e30, 0.0, 0.0, 0.5),
            "ahead",
        ):
            graph = VisualGraph(
                "dynamic_invalid",
                (
                    GraphNode("bad", "value.constant", {"value": cone}),
                    GraphNode(
                        "query",
                        "query.nearest_in_cone",
                        {"origin": "player", "tag": "goal", "radius": 10.0},
                    ),
                ),
                (GraphLink("bad", "value", "query", "cone"),),
            )
            packed = compile_graph_pack_bytes(_project_with(graph))
            with self.subTest(cone=cone):
                info = inspect_graph_pack(packed)
                self.assertEqual(info["node_count"], 2)
                self.assertEqual(info["input_count"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
