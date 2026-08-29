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
}


def _project_with(graph: VisualGraph):
    project = blank_mobile3d_project()
    project.metadata["visual_graphs"] = [graph.to_dict()]
    project.metadata["world_graphs"] = graph.id
    return project


class TimerGraphPackTests(unittest.TestCase):
    def test_opcode_23_is_append_only_with_two_literals_and_three_outputs(self) -> None:
        self.assertEqual(
            {name: NODE_OPCODES[name] for name in OLD_OPCODES},
            OLD_OPCODES,
        )
        self.assertEqual(NODE_OPCODES["event.timer"], 23)
        self.assertEqual(NODE_INPUTS["event.timer"], ("seconds", "repeat"))
        self.assertEqual(
            NODE_DATA_OUTPUTS["event.timer"],
            ("count", "remaining", "entity"),
        )
        self.assertEqual(NODE_FLOW_OUTPUTS["event.timer"], ("out",))

    def test_timer_pack_is_compact_canonical_and_inspectable(self) -> None:
        graph = VisualGraph(
            "timer",
            (GraphNode("timer", "event.timer", {"seconds": 0.5, "repeat": False}),),
        )
        project = _project_with(graph)
        packed = compile_graph_pack_bytes(project)
        self.assertLess(len(packed), 160)
        self.assertEqual(compile_graph_pack_bytes(_project_with(graph)), packed)
        info = inspect_graph_pack(packed)
        self.assertEqual(info["node_count"], 1)
        self.assertEqual(info["input_count"], 2)
        self.assertEqual(info["flow_target_count"], 0)
        self.assertEqual(info["world_binding_count"], 1)

    def test_linked_or_invalid_timer_settings_are_rejected_before_export(self) -> None:
        linked = VisualGraph(
            "linked",
            (
                GraphNode("value", "value.constant", {"value": 1.0}),
                GraphNode("timer", "event.timer"),
            ),
            (GraphLink("value", "value", "timer", "seconds"),),
        )
        with self.assertRaisesRegex(ValueError, "set on the block"):
            compile_graph_pack_bytes(_project_with(linked))

        for properties, message in (
            ({"seconds": 0.0}, "finite positive number"),
            ({"seconds": 86400.1}, "finite positive number"),
            ({"repeat": 1}, "must be boolean"),
        ):
            graph = VisualGraph(
                "invalid",
                (GraphNode("timer", "event.timer", properties),),
            )
            with self.subTest(properties=properties), self.assertRaisesRegex(
                ValueError,
                message,
            ):
                compile_graph_pack_bytes(_project_with(graph))


if __name__ == "__main__":
    unittest.main(verbosity=2)
