from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ugts_kc3.graphpack import (  # noqa: E402
    GRAPH_MAX_EVENTS,
    GRAPH_MAX_STEPS,
    GRAPH_MAX_TOTAL_STEPS,
    GraphPackError,
    NODE_DATA_OUTPUTS,
    NODE_FLOW_OUTPUTS,
    NODE_INPUTS,
    NODE_OPCODES,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402
from ugts_kc3.visual_graph import (  # noqa: E402
    GraphLink,
    GraphNode,
    VisualGraph,
)


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
    "query.nearest_in_cone": 24,
}


def _project_with(graph: VisualGraph):
    project = blank_mobile3d_project()
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.metadata["world_graphs"] = graph.id
    return project


class MessageGraphPackTests(unittest.TestCase):
    def test_opcode_25_is_append_only_and_uses_compact_ports(self) -> None:
        self.assertEqual(
            {name: NODE_OPCODES[name] for name in OLD_OPCODES},
            OLD_OPCODES,
        )
        self.assertEqual(NODE_OPCODES["event.message"], 25)
        self.assertEqual(NODE_INPUTS["event.message"], ("message",))
        self.assertEqual(
            NODE_DATA_OUTPUTS["event.message"],
            ("source", "target", "entity"),
        )
        self.assertEqual(NODE_FLOW_OUTPUTS["event.message"], ("out",))
        self.assertEqual(GRAPH_MAX_STEPS, 1024)
        self.assertEqual(GRAPH_MAX_EVENTS, 64)
        self.assertEqual(GRAPH_MAX_TOTAL_STEPS, 16384)

    def test_message_pack_is_canonical_compact_and_inspectable(self) -> None:
        graph = VisualGraph(
            "message",
            (
                GraphNode(
                    "heard",
                    "event.message",
                    {"message": "level.2-ready"},
                ),
                GraphNode(
                    "remember_source",
                    "action.set_state",
                    {"key": "source"},
                ),
                GraphNode(
                    "remember_target",
                    "action.set_state",
                    {"key": "target"},
                ),
                GraphNode(
                    "remember_entity",
                    "action.set_state",
                    {"key": "entity"},
                ),
            ),
            (
                GraphLink("heard", "out", "remember_source", "in"),
                GraphLink("heard", "source", "remember_source", "value"),
                GraphLink("heard", "out", "remember_target", "in"),
                GraphLink("heard", "target", "remember_target", "value"),
                GraphLink("heard", "out", "remember_entity", "in"),
                GraphLink("heard", "entity", "remember_entity", "value"),
            ),
        )
        project = _project_with(graph)
        packed = compile_graph_pack_bytes(project)
        self.assertEqual(compile_graph_pack_bytes(_project_with(graph)), packed)
        self.assertLess(len(packed), 320)
        info = inspect_graph_pack(packed)
        self.assertEqual(info["node_count"], 4)
        self.assertEqual(info["input_count"], 7)
        self.assertEqual(info["flow_target_count"], 3)
        self.assertEqual(info["world_binding_count"], 1)
        self.assertEqual(info["state_keys"], ["entity", "source", "target"])

    def test_linked_or_invalid_saved_messages_are_rejected(self) -> None:
        linked = VisualGraph(
            "linked",
            (
                GraphNode("value", "value.constant", {"value": "hello"}),
                GraphNode("heard", "event.message"),
            ),
            (GraphLink("value", "value", "heard", "message"),),
        )
        with self.assertRaisesRegex(ValueError, "saved on the block"):
            compile_graph_pack_bytes(_project_with(linked))

        for message in ("", "Upper", "2start", "has space", "z" * 65):
            graph = VisualGraph(
                "invalid",
                (GraphNode("heard", "event.message", {"message": message}),),
            )
            with self.subTest(message=message), self.assertRaisesRegex(
                ValueError,
                "lowercase letter",
            ):
                compile_graph_pack_bytes(_project_with(graph))

        dynamic_sender = VisualGraph(
            "dynamic_sender",
            (
                GraphNode("kind", "value.constant", {"value": "Dynamic Kind"}),
                GraphNode("send", "action.emit_event", {"payload": {}}),
            ),
            (GraphLink("kind", "value", "send", "kind"),),
        )
        self.assertEqual(
            inspect_graph_pack(
                compile_graph_pack_bytes(_project_with(dynamic_sender))
            )["node_count"],
            2,
        )

    def test_inspector_rejects_nonportable_message_literal(self) -> None:
        graph = VisualGraph(
            "message",
            (
                GraphNode(
                    "heard",
                    "event.message",
                    {"message": "graph_event"},
                ),
            ),
        )
        packed = compile_graph_pack_bytes(_project_with(graph))
        damaged = packed.replace(b"graph_event", b"Graph_event", 1)
        self.assertNotEqual(damaged, packed)
        with self.assertRaisesRegex(GraphPackError, "portable message name"):
            inspect_graph_pack(damaged)


if __name__ == "__main__":
    unittest.main(verbosity=2)
