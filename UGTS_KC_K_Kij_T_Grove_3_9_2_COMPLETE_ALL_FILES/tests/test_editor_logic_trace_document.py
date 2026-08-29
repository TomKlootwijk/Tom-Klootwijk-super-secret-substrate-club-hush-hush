from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ugts_kc3.androidexport import compile_scene_pack_bytes
from ugts_kc3.editor.document import EditorDocument, LogicTraceSnapshot
from ugts_kc3.graphpack import compile_graph_pack_bytes
from ugts_kc3.polarpack import compile_polar_pack_bytes
from ugts_kc3.templates import first_steps_project
from ugts_kc3.templates3d import first_steps_mobile3d_project
from ugts_kc3.visual_graph import (
    GraphExecutionError,
    GraphLink,
    GraphNode,
    VisualGraph,
)


class EditorLogicTraceDocumentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    @staticmethod
    def _canonical(value: object) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")

    def test_mobile_dash_trace_survives_idle_frame_and_stop(self) -> None:
        document = EditorDocument()
        document.create(first_steps_mobile3d_project())
        document.set_dirty(False)
        changes: list[LogicTraceSnapshot | None] = []
        document.logicTraceChanged.connect(changes.append)

        document.begin_play()
        self.assertIsNone(document.logic_trace("dash_lesson", "player"))
        find_goal = document.logic_trace("find_goal_lesson", None)
        self.assertIsInstance(find_goal, LogicTraceSnapshot)
        assert find_goal is not None
        self.assertEqual(find_goal.trigger, "ready")
        self.assertEqual(
            tuple(entry.node_id for entry in find_goal.trace),
            ("when_game_starts", "find_goal", "remember_nearby_goal"),
        )
        self.assertIs(find_goal.trace[1].outputs["found"], True)
        self.assertEqual(find_goal.trace[1].outputs["entity"], "goal")
        find_goal_ahead = document.logic_trace("find_goal_ahead_lesson", None)
        self.assertIsInstance(find_goal_ahead, LogicTraceSnapshot)
        assert find_goal_ahead is not None
        self.assertEqual(find_goal_ahead.trigger, "ready")
        self.assertEqual(
            tuple(entry.node_id for entry in find_goal_ahead.trace),
            ("when_game_starts", "find_goal_ahead", "remember_goal_ahead"),
        )
        self.assertIs(find_goal_ahead.trace[1].outputs["found"], True)
        self.assertEqual(find_goal_ahead.trace[1].outputs["entity"], "goal")
        repeatable = document.logic_trace("repeatable_number_lesson", "floor")
        self.assertIsInstance(repeatable, LogicTraceSnapshot)
        assert repeatable is not None
        self.assertEqual(repeatable.trigger, "ready")
        self.assertEqual(
            tuple(entry.node_id for entry in repeatable.trace),
            ("when_game_starts", "pick_garden_number", "remember_garden_number"),
        )
        self.assertEqual(
            repeatable.trace[1].outputs["value"],
            -7.724208831787109,
        )
        document.step_play({"space"})

        snapshot = document.logic_trace("dash_lesson", "player")
        self.assertIsInstance(snapshot, LogicTraceSnapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.key, ("dash_lesson", "player"))
        self.assertEqual(snapshot.trigger, "tick")
        self.assertTrue(snapshot.completed)
        self.assertEqual(snapshot.steps, 7)
        self.assertEqual(
            tuple(entry.node_id for entry in snapshot.trace),
            (
                "when_dash",
                "grow_player",
                "current_score",
                "one",
                "add_one",
                "save_score",
                "send_dash_message",
            ),
        )
        self.assertIs(document.latest_logic_trace("dash_lesson"), snapshot)
        message = document.logic_trace("message_lesson", None)
        self.assertIsInstance(message, LogicTraceSnapshot)
        assert message is not None
        self.assertEqual(message.trigger, "message")
        self.assertEqual(
            tuple(entry.node_id for entry in message.trace),
            ("when_dash_message", "heard", "remember_message"),
        )
        self.assertEqual(message.trace[0].outputs["source"], "player")
        self.assertIsNone(message.trace[0].outputs["target"])
        self.assertEqual(
            document.logic_traces(),
            (repeatable, find_goal, find_goal_ahead, snapshot, message),
        )
        self.assertIs(changes[-1], message)
        with self.assertRaises(FrozenInstanceError):
            snapshot.trigger = "changed"  # type: ignore[misc]

        useful_change_count = len(changes)
        document.step_play(set())
        self.assertIs(document.logic_trace("dash_lesson", "player"), snapshot)
        self.assertEqual(len(changes), useful_change_count)

        document.stop_play()
        self.assertIs(document.logic_trace("dash_lesson", "player"), snapshot)
        document.begin_play()
        self.assertIsNone(document.logic_trace("dash_lesson", "player"))
        new_repeatable = document.logic_trace("repeatable_number_lesson", "floor")
        self.assertIsInstance(new_repeatable, LogicTraceSnapshot)
        self.assertIs(
            changes[-1],
            document.logic_trace("find_goal_ahead_lesson", None),
        )

    def test_trigger_trace_is_harvested_in_the_transition_frame(self) -> None:
        project = first_steps_mobile3d_project()
        nodes = []
        for node in project.nodes:
            if node.id != "goal":
                nodes.append(node)
                continue
            metadata = dict(node.metadata)
            metadata.pop("packed_kinematic", None)
            nodes.append(
                replace(
                    node,
                    transform=replace(node.transform, translation=(0.0, 0.55, 3.0)),
                    metadata=metadata,
                )
            )
        project.nodes = tuple(nodes)
        project.validate()

        document = EditorDocument()
        document.create(project)
        document.begin_play()
        _, events = document.step_play(set())

        self.assertIn("trigger_enter", tuple(event.kind for event in events))
        snapshot = document.logic_trace("goal_area_lesson", "goal")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.trigger, "trigger_enter")
        self.assertEqual(
            tuple(entry.node_id for entry in snapshot.trace),
            ("when_entered", "inside", "remember_inside"),
        )
        document.step_play(set())
        self.assertIs(document.logic_trace("goal_area_lesson", "goal"), snapshot)

    def test_timer_trace_appears_only_when_it_rings_and_resets_with_play(self) -> None:
        document = EditorDocument()
        document.create(first_steps_mobile3d_project())
        document.begin_play()

        for _ in range(119):
            document.step_play(set())
        self.assertIsNone(document.logic_trace("timer_lesson", None))

        state, _ = document.step_play(set())
        snapshot = document.logic_trace("timer_lesson", None)
        self.assertIsInstance(snapshot, LogicTraceSnapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.trigger, "tick")
        self.assertEqual(
            tuple(entry.node_id for entry in snapshot.trace),
            ("every_second", "remember_timer_rings"),
        )
        self.assertEqual(snapshot.trace[0].outputs["count"], 1.0)
        self.assertEqual(snapshot.trace[0].outputs["remaining"], 0.0)
        self.assertEqual(state["__world__"]["timer_rings"], 1.0)

        document.stop_play()
        document.begin_play()
        self.assertIsNone(document.logic_trace("timer_lesson", None))
        for _ in range(119):
            state, _ = document.step_play(set())
        self.assertIsNone(document.logic_trace("timer_lesson", None))
        self.assertEqual(state["__world__"]["timer_rings"], 0)

    def test_two_dimensional_preview_uses_the_same_trace_cache(self) -> None:
        document = EditorDocument()
        document.create(first_steps_project())
        document.begin_play()
        document.step_play({"space"})

        snapshot = document.logic_trace("dash_counter", "player")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.steps, 5)
        self.assertEqual(snapshot.trace[0].node_id, "when_dash")
        self.assertEqual(snapshot.trace[-1].node_id, "save_score")

    def test_ready_error_is_retained_when_world_creation_does_not_return(self) -> None:
        project = first_steps_mobile3d_project()
        broken = VisualGraph(
            "broken_ready",
            (
                GraphNode("begin", "event.ready"),
                GraphNode(
                    "break_here",
                    "action.set_component",
                    {
                        "entity": None,
                        "component": "transform",
                        "field": "_private",
                        "value": [1.0, 1.0, 1.0],
                    },
                ),
            ),
            (GraphLink("begin", "out", "break_here", "in"),),
        )
        project.metadata = {
            **project.metadata,
            "visual_graphs": [broken.to_dict()],
            "world_graphs": [],
        }
        project.nodes = tuple(
            replace(
                node,
                metadata={
                    key: value
                    for key, value in node.metadata.items()
                    if key not in {"visual_graph", "packed_kinematic"}
                }
                | ({"visual_graph": broken.id} if node.id == "player" else {}),
            )
            for node in project.nodes
        )
        project.validate()

        document = EditorDocument()
        document.create(project)
        with self.assertRaises(GraphExecutionError):
            document.begin_play()

        snapshot = document.logic_trace("broken_ready", "player")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual(snapshot.trigger, "ready")
        self.assertFalse(snapshot.completed)
        self.assertEqual(snapshot.trace[-1].node_id, "break_here")
        self.assertEqual(snapshot.trace[-1].status, "error")
        self.assertIn("private", snapshot.trace[-1].error or "")

    def test_step_error_is_captured_before_preview_propagates_it(self) -> None:
        project = first_steps_mobile3d_project()
        graphs = [VisualGraph.from_dict(value) for value in project.metadata["visual_graphs"]]
        dash = graphs[0]
        broken_dash = replace(
            dash,
            nodes=tuple(
                replace(
                    node,
                    properties={**node.properties, "field": "_private"},
                )
                if node.id == "grow_player"
                else node
                for node in dash.nodes
            ),
        )
        project.metadata = {
            **project.metadata,
            "visual_graphs": [broken_dash.to_dict(), *[graph.to_dict() for graph in graphs[1:]]],
        }
        project.validate()

        document = EditorDocument()
        document.create(project)
        document.begin_play()
        with self.assertRaises(GraphExecutionError):
            document.step_play({"space"})

        snapshot = document.logic_trace("dash_lesson", "player")
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertFalse(snapshot.completed)
        self.assertEqual(snapshot.trace[-1].node_id, "grow_player")
        self.assertEqual(snapshot.trace[-1].status, "error")
        document.stop_play()
        self.assertIs(document.logic_trace("dash_lesson", "player"), snapshot)

    def test_preview_traces_never_change_project_bytes_hash_or_dirty_state(self) -> None:
        project = first_steps_mobile3d_project()
        document = EditorDocument()
        document.create(project)
        document.set_dirty(False)
        before_document = self._canonical(document.serialize())
        before_hash = project.content_hash()
        before_scene = compile_scene_pack_bytes(project)
        before_graph = compile_graph_pack_bytes(project)
        before_polar = compile_polar_pack_bytes(project)

        document.begin_play()
        document.step_play({"space"})
        document.step_play(set())
        document.stop_play()

        self.assertFalse(document.is_dirty)
        self.assertEqual(self._canonical(document.serialize()), before_document)
        self.assertEqual(project.content_hash(), before_hash)
        self.assertEqual(compile_scene_pack_bytes(project), before_scene)
        self.assertEqual(compile_graph_pack_bytes(project), before_graph)
        self.assertEqual(compile_polar_pack_bytes(project), before_polar)
        self.assertNotIn("logic_trace", document.serialize())

        document.create(first_steps_mobile3d_project("Another Project"))
        self.assertEqual(document.logic_traces(), ())
        self.assertIsNone(document.latest_logic_trace())


if __name__ == "__main__":
    unittest.main()
