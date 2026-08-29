from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ugts_kc3.graphpack import (
    GraphPackError,
    NODE_DATA_OUTPUTS,
    NODE_INPUTS,
    NODE_OPCODES,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


def _attach_world(project: Mobile3DProject, graph: VisualGraph) -> None:
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.metadata["world_graphs"] = graph.id


class NearestTagGraphPackTests(unittest.TestCase):
    def test_opcode_22_is_append_only_and_keeps_all_linked_ports(self) -> None:
        self.assertEqual(NODE_OPCODES["value.seeded_number"], 21)
        self.assertEqual(NODE_OPCODES["query.nearest_tag"], 22)
        self.assertEqual(
            NODE_INPUTS["query.nearest_tag"],
            ("origin", "tag", "radius"),
        )
        self.assertEqual(
            NODE_DATA_OUTPUTS["query.nearest_tag"],
            ("found", "entity", "distance"),
        )

        graph = VisualGraph(
            "nearest_pack",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("origin", "value.constant", {"value": "player"}),
                GraphNode("tag", "value.constant", {"value": "goal"}),
                GraphNode("radius", "value.constant", {"value": 10.0}),
                GraphNode("nearest", "query.nearest_tag"),
                GraphNode("remember", "action.set_state", {"key": "found"}),
                GraphNode(
                    "place",
                    "action.set_component",
                    {
                        "entity": "goal",
                        "component": "transform",
                        "field": "translation.y",
                    },
                ),
                GraphNode("announce", "action.emit_event", {"kind": "nearest"}),
            ),
            (
                GraphLink("ready", "out", "remember", "in"),
                GraphLink("ready", "out", "place", "in"),
                GraphLink("ready", "out", "announce", "in"),
                GraphLink("origin", "value", "nearest", "origin"),
                GraphLink("tag", "value", "nearest", "tag"),
                GraphLink("radius", "value", "nearest", "radius"),
                GraphLink("nearest", "found", "remember", "value"),
                GraphLink("nearest", "distance", "place", "value"),
                GraphLink("nearest", "entity", "announce", "target"),
            ),
        )
        project = blank_mobile3d_project()
        _attach_world(project, graph)
        packed = compile_graph_pack_bytes(project)
        info = inspect_graph_pack(packed)
        self.assertEqual(info["node_count"], 8)
        self.assertEqual(info["input_count"], 16)
        self.assertEqual(info["state_keys"], ["found"])
        self.assertEqual(
            compile_graph_pack_bytes(Mobile3DProject.from_dict(project.to_dict())),
            packed,
        )

    def test_literal_origin_tag_and_radius_are_checked_before_export(self) -> None:
        cases = (
            (
                {"origin": "missing", "tag": "goal", "radius": 10},
                GraphPackError,
                "missing scene node",
            ),
            (
                {"origin": "player", "tag": "custom", "radius": 10},
                ValueError,
                "Tag must be player",
            ),
            (
                {"origin": "player", "tag": "goal", "radius": -1},
                ValueError,
                "Radius must be",
            ),
            (
                {"origin": "player", "tag": "goal", "radius": 1.0e30},
                ValueError,
                "Radius must be",
            ),
        )
        for properties, error_type, message in cases:
            with self.subTest(properties=properties):
                project = blank_mobile3d_project()
                graph = VisualGraph(
                    "invalid_nearest",
                    (GraphNode("nearest", "query.nearest_tag", properties),),
                )
                _attach_world(project, graph)
                with self.assertRaisesRegex(error_type, message):
                    compile_graph_pack_bytes(project)

    def test_null_origin_packs_for_entity_binding_but_world_binding_is_runtime_checked(self) -> None:
        graph = VisualGraph(
            "bound_nearest",
            (GraphNode("nearest", "query.nearest_tag"),),
        )
        project = blank_mobile3d_project()
        project.metadata["visual_graphs"] = [graph.to_dict()]
        player = next(node for node in project.nodes if node.id == "player")
        player.metadata["visual_graph"] = graph.id
        info = inspect_graph_pack(compile_graph_pack_bytes(project))
        self.assertEqual(info["bindings"][0]["scope"], "node")

        project.metadata["world_graphs"] = graph.id
        info = inspect_graph_pack(compile_graph_pack_bytes(project))
        self.assertEqual(info["world_binding_count"], 1)

    def test_invalid_linked_values_are_packed_for_runtime_validation(self) -> None:
        graph = VisualGraph(
            "dynamic_invalid",
            (
                GraphNode("bad_tag", "value.constant", {"value": "custom"}),
                GraphNode("bad_radius", "value.constant", {"value": -1.0}),
                GraphNode("nearest", "query.nearest_tag", {"origin": "player"}),
            ),
            (
                GraphLink("bad_tag", "value", "nearest", "tag"),
                GraphLink("bad_radius", "value", "nearest", "radius"),
            ),
        )
        project = blank_mobile3d_project()
        _attach_world(project, graph)
        self.assertEqual(inspect_graph_pack(compile_graph_pack_bytes(project))["node_count"], 3)


if __name__ == "__main__":
    unittest.main()
