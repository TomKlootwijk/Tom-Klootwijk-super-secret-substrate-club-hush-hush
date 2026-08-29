from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import build_android_project
from ugts_kc3.graphpack import (
    GRAPH_PACK_ASSET,
    GRAPH_PACK_MAGIC,
    GraphPackError,
    compile_graph_pack_bytes,
    inspect_graph_pack,
    write_graph_pack,
)
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


def _player(project):
    return next(node for node in project.nodes if node.id == "player")


def _attach(project, graph: VisualGraph) -> None:
    project.metadata["visual_graphs"] = [graph.to_dict()]
    _player(project).metadata["visual_graph"] = graph.id


class GraphPackTests(unittest.TestCase):
    def test_graph_free_project_has_no_asset(self):
        project = blank_mobile3d_project()
        self.assertEqual(compile_graph_pack_bytes(project), b"")
        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNone(built.graph_pack)
            self.assertFalse((built.output_dir / "app/src/main/assets" / GRAPH_PACK_ASSET).exists())
            report = json.loads(built.build_report.read_text("utf-8"))
            self.assertIsNone(report["visual_graph_runtime"])

    def test_deterministic_roundtrip_and_mapping_form(self):
        graph = VisualGraph(
            "start",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("set", "action.set_state", {"key": "started", "value": True}),
            ),
            (GraphLink("ready", "out", "set", "in"),),
        )
        project = blank_mobile3d_project()
        _attach(project, graph)
        packed = compile_graph_pack_bytes(project)
        self.assertEqual(packed[:8], GRAPH_PACK_MAGIC)
        clone = Mobile3DProject.from_dict(project.to_dict())
        self.assertEqual(compile_graph_pack_bytes(clone), packed)
        clone.metadata["visual_graphs"] = {graph.id: graph.to_dict()}
        self.assertEqual(compile_graph_pack_bytes(clone), packed)
        info = inspect_graph_pack(packed)
        self.assertEqual(info["graph_count"], 1)
        self.assertEqual(info["binding_count"], 1)
        self.assertEqual(info["state_keys"], ["started"])
        self.assertLess(info["byte_length"], 256)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / GRAPH_PACK_ASSET
            self.assertEqual(write_graph_pack(project, output), output)
            self.assertEqual(output.read_bytes(), packed)
            self.assertEqual(inspect_graph_pack(output), info)

    def test_all_mobile_opcodes_compile(self):
        nodes = (
            GraphNode("ready", "event.ready"),
            GraphNode("tick", "event.tick"),
            GraphNode("pressed", "event.input_pressed", {"action": "jump"}),
            GraphNode("branch", "flow.branch", {"condition": True}),
            GraphNode("constant", "value.constant", {"value": [1, 2, 3]}),
            GraphNode("state", "value.state", {"key": "score", "default": 0}),
            GraphNode("component", "value.component", {"component": "transform", "field": "translation"}),
            GraphNode("add", "math.add"),
            GraphNode("subtract", "math.subtract"),
            GraphNode("multiply", "math.multiply"),
            GraphNode("divide", "math.divide"),
            GraphNode("compare", "compare"),
            GraphNode("set_state", "action.set_state", {"key": "score", "value": 1}),
            GraphNode("set_component", "action.set_component", {"component": "transform", "field": "translation", "value": [0, 1, 0]}),
            GraphNode("emit", "action.emit_event", {"kind": "hello", "payload": {}}),
            GraphNode("active", "action.set_active"),
            GraphNode("despawn", "action.despawn"),
        )
        project = blank_mobile3d_project()
        _attach(project, VisualGraph("portable", nodes))
        info = inspect_graph_pack(compile_graph_pack_bytes(project))
        self.assertEqual(info["node_count"], 17)
        self.assertEqual(info["state_keys"], ["score"])

    def test_many_nodes_remain_small(self):
        actions = tuple(
            GraphNode(f"set_{index:03}", "action.set_state", {"key": "counter", "value": index})
            for index in range(200)
        )
        links = tuple(GraphLink("tick", "out", node.id, "in") for node in actions)
        graph = VisualGraph("compact", (GraphNode("tick", "event.tick"),) + actions, links)
        project = blank_mobile3d_project()
        _attach(project, graph)
        packed = compile_graph_pack_bytes(project)
        self.assertLess(len(packed), 7000)
        self.assertEqual(inspect_graph_pack(packed)["node_count"], 201)

    def test_android_project_adds_graph_only_when_present(self):
        graph = VisualGraph("ready", (GraphNode("ready", "event.ready"),))
        project = blank_mobile3d_project()
        _attach(project, graph)
        with tempfile.TemporaryDirectory() as tmp:
            built = build_android_project(project, Path(tmp) / "android")
            self.assertIsNotNone(built.graph_pack)
            assert built.graph_pack is not None
            self.assertEqual(built.graph_pack.name, GRAPH_PACK_ASSET)
            self.assertTrue(built.graph_pack.exists())
            report = json.loads(built.build_report.read_text("utf-8"))
            self.assertEqual(report["visual_graph_runtime"]["graph_count"], 1)

    def test_rejects_2d_force_node(self):
        graph = VisualGraph("bad", (GraphNode("force", "action.apply_force"),))
        project = blank_mobile3d_project()
        _attach(project, graph)
        with self.assertRaisesRegex(GraphPackError, "action.apply_force"):
            compile_graph_pack_bytes(project)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "existing"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("untouched", encoding="utf-8")
            with self.assertRaisesRegex(GraphPackError, "action.apply_force"):
                build_android_project(project, output, clean=True)
            self.assertEqual(marker.read_text("utf-8"), "untouched")

        project = blank_mobile3d_project()
        _attach(
            project,
            VisualGraph(
                "input",
                (GraphNode("pressed", "event.input_pressed", {"action": "custom_unmapped_action"}),),
            ),
        )
        with self.assertRaisesRegex(GraphPackError, "not available in the Android template"):
            compile_graph_pack_bytes(project)

    def test_rejects_nonempty_event_payload_and_event_object_link(self):
        project = blank_mobile3d_project()
        _attach(project, VisualGraph("payload", (GraphNode("emit", "action.emit_event", {"payload": {"points": 1}}),)))
        with self.assertRaisesRegex(GraphPackError, "empty payload"):
            compile_graph_pack_bytes(project)

        emit = GraphNode("emit", "action.emit_event")
        state = GraphNode("state", "action.set_state", {"key": "last"})
        graph = VisualGraph("event_value", (emit, state), (GraphLink("emit", "event", "state", "value"),))
        project = blank_mobile3d_project()
        _attach(project, graph)
        with self.assertRaisesRegex(GraphPackError, "cannot be consumed"):
            compile_graph_pack_bytes(project)

    def test_rejects_unknown_component_and_missing_binding(self):
        graph = VisualGraph(
            "component",
            (GraphNode("set", "action.set_component", {"component": "body", "field": "velocity", "value": [0, 0, 0]}),),
        )
        project = blank_mobile3d_project()
        _attach(project, graph)
        with self.assertRaisesRegex(GraphPackError, "NodeData supports"):
            compile_graph_pack_bytes(project)

        project = blank_mobile3d_project()
        _player(project).metadata["visual_graph"] = "missing"
        with self.assertRaisesRegex(ValueError, "missing"):
            compile_graph_pack_bytes(project)

        project = blank_mobile3d_project()
        project.metadata["visual_graphs"] = [VisualGraph("world", (GraphNode("tick", "event.tick"),)).to_dict()]
        project.metadata["world_graphs"] = "world"
        with self.assertRaisesRegex(GraphPackError, "world_graphs"):
            compile_graph_pack_bytes(project)

    def test_inspector_rejects_damage(self):
        project = blank_mobile3d_project()
        _attach(project, VisualGraph("ready", (GraphNode("ready", "event.ready"),)))
        packed = compile_graph_pack_bytes(project)
        with self.assertRaises(GraphPackError):
            inspect_graph_pack(packed[:-1])
        with self.assertRaisesRegex(GraphPackError, "trailing"):
            inspect_graph_pack(packed + b"x")


if __name__ == "__main__":
    unittest.main(verbosity=2)
