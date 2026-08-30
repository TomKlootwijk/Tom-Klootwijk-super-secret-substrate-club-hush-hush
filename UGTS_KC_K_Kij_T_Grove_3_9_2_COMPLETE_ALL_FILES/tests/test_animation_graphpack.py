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
    TransformAnimationLibrary3D,
    TransformClip3D,
    default_transform_animation,
    metadata_with_transform_animation_library,
)
from ugts_kc3.graphpack import (  # noqa: E402
    GraphPackError,
    NODE_OPCODES,
    compile_graph_pack_bytes,
    inspect_graph_pack,
)
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402


def _project(graph: VisualGraph):
    project = blank_mobile3d_project()
    library = TransformAnimationLibrary3D(
        (TransformClip3D("jump", "Jump", default_transform_animation()),),
        autoplay=None,
    )
    floor = project.nodes[0]
    project.nodes = (
        replace(
            floor,
            metadata={
                **metadata_with_transform_animation_library(floor.metadata, library),
                "visual_graph": graph.id,
            },
        ),
        *project.nodes[1:],
    )
    project.metadata["visual_graphs"] = [graph.to_dict()]
    return project


class AnimationGraphPackTests(unittest.TestCase):
    def test_opcodes_are_append_only_and_ports_are_compact(self) -> None:
        self.assertEqual(NODE_OPCODES["event.message"], 25)
        self.assertEqual(NODE_OPCODES["action.play_animation"], 26)
        self.assertEqual(NODE_OPCODES["action.stop_animation"], 27)
        graph = VisualGraph(
            "animation_actions",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "play",
                    "action.play_animation",
                    {"entity": None, "clip": "jump", "restart": True},
                ),
                GraphNode(
                    "stop",
                    "action.stop_animation",
                    {"entity": None, "reset": False},
                ),
            ),
            (
                GraphLink("ready", "out", "play", "in"),
                GraphLink("play", "out", "stop", "in"),
            ),
        )
        packed = compile_graph_pack_bytes(_project(graph))
        self.assertEqual(compile_graph_pack_bytes(_project(graph)), packed)
        info = inspect_graph_pack(packed)
        self.assertEqual(info["node_count"], 3)
        self.assertEqual(info["input_count"], 5)
        self.assertEqual(info["flow_target_count"], 2)

    def test_connected_clip_compiles_but_literal_and_inspector_are_strict(self) -> None:
        dynamic = VisualGraph(
            "dynamic_animation",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "state",
                    "value.state",
                    {"key": "wanted_clip", "default": "jump"},
                ),
                GraphNode(
                    "play",
                    "action.play_animation",
                    {"entity": None, "restart": True},
                ),
            ),
            (
                GraphLink("ready", "out", "play", "in"),
                GraphLink("state", "value", "play", "clip"),
            ),
        )
        self.assertTrue(compile_graph_pack_bytes(_project(dynamic)))

        literal = VisualGraph(
            "literal_animation",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "play",
                    "action.play_animation",
                    {"entity": None, "clip": "jump", "restart": True},
                ),
            ),
            (GraphLink("ready", "out", "play", "in"),),
        )
        packed = compile_graph_pack_bytes(_project(literal))
        damaged = packed.replace(b"jump", b"Jump", 1)
        with self.assertRaisesRegex(GraphPackError, "portable animation clip"):
            inspect_graph_pack(damaged)


if __name__ == "__main__":
    unittest.main()
