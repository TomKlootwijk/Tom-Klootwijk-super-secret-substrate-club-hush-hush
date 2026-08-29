from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ugts_kc3.game import GameWorld  # noqa: E402
from ugts_kc3.visual_graph import (  # noqa: E402
    BUILTIN_NODE_REGISTRY,
    GRAPH_MESSAGE_MAX_EVENTS,
    GRAPH_MESSAGE_MAX_STEPS,
    GraphEventLimitError,
    GraphLink,
    GraphNode,
    GraphRuntime,
    GraphTotalStepLimitError,
    GraphValidationError,
    VisualGraph,
    attach_graph,
    run_ready_batch,
)


def _link(
    source: str,
    source_port: str,
    target: str,
    target_port: str,
) -> GraphLink:
    return GraphLink(source, source_port, target, target_port)


def _listener(graph_id: str, message: str, marker: str) -> VisualGraph:
    return VisualGraph(
        graph_id,
        (
            GraphNode("heard", "event.message", {"message": message}),
            GraphNode("mark", "action.emit_event", {"kind": marker}),
        ),
        (_link("heard", "out", "mark", "in"),),
    )


class MessageVisualGraphTests(unittest.TestCase):
    def test_registry_ports_and_saved_message_validation(self) -> None:
        definition = BUILTIN_NODE_REGISTRY.definition("event.message")
        self.assertEqual(
            tuple(port.name for port in definition.ports),
            ("message", "out", "source", "target", "entity"),
        )
        self.assertEqual(definition.default_properties["message"], "graph_event")
        self.assertEqual(definition.event, "message")

        for message in ("a", "level.2-ready_now", "z" * 64):
            with self.subTest(message=message):
                VisualGraph(
                    "valid",
                    (GraphNode("heard", "event.message", {"message": message}),),
                ).validate()

        for message in ("", "2start", "Upper", "has space", "z" * 65):
            graph = VisualGraph(
                "invalid",
                (GraphNode("heard", "event.message", {"message": message}),),
            )
            with self.subTest(message=message), self.assertRaises(
                GraphValidationError
            ) as caught:
                graph.validate()
            self.assertIn("message_name", {issue.code for issue in caught.exception.issues})

        linked = VisualGraph(
            "linked",
            (
                GraphNode("saved", "value.constant", {"value": "hello"}),
                GraphNode("heard", "event.message"),
            ),
            (_link("saved", "value", "heard", "message"),),
        )
        with self.assertRaises(GraphValidationError) as caught:
            linked.validate()
        self.assertIn(
            "message_literal_only",
            {issue.code for issue in caught.exception.issues},
        )

        exact = GraphRuntime(
            VisualGraph(
                "exact",
                (GraphNode("heard", "event.message", {"message": "hello"}),),
            )
        )
        mismatch = exact.event(
            "message",
            GameWorld(),
            payload={"message": "hello.extra"},
        )
        self.assertEqual(mismatch.steps, 0)
        self.assertEqual(mismatch.trace, ())

    def test_ready_batch_registers_every_binding_and_routes_canonically(self) -> None:
        world = GameWorld()
        world.spawn("first", emit_event=False)
        world.spawn("second", emit_event=False)

        first = VisualGraph(
            "a_first",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "ready_state",
                    "action.set_state",
                    {"key": "first_ready", "value": True},
                ),
                GraphNode("heard", "event.message", {"message": "begin"}),
                GraphNode("second_ready", "value.state", {"key": "second_ready", "default": False}),
                GraphNode("saw_ready", "action.set_state", {"key": "saw_second_ready"}),
                GraphNode("source", "action.set_state", {"key": "heard_source"}),
                GraphNode("target", "action.set_state", {"key": "heard_target"}),
                GraphNode("entity", "action.set_state", {"key": "heard_entity"}),
                GraphNode("marker", "action.emit_event", {"kind": "first_heard"}),
            ),
            (
                _link("ready", "out", "ready_state", "in"),
                _link("heard", "out", "saw_ready", "in"),
                _link("second_ready", "value", "saw_ready", "value"),
                _link("heard", "out", "source", "in"),
                _link("heard", "source", "source", "value"),
                _link("heard", "out", "target", "in"),
                _link("heard", "target", "target", "value"),
                _link("heard", "out", "entity", "in"),
                _link("heard", "entity", "entity", "value"),
                _link("heard", "out", "marker", "in"),
            ),
        )
        second = VisualGraph(
            "z_second",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "ready_state",
                    "action.set_state",
                    {"key": "second_ready", "value": True},
                ),
                GraphNode("heard", "event.message", {"message": "begin"}),
                GraphNode("marker", "action.emit_event", {"kind": "second_heard"}),
            ),
            (
                _link("ready", "out", "ready_state", "in"),
                _link("heard", "out", "marker", "in"),
            ),
        )
        world_graph = VisualGraph(
            "world_sender",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("send", "action.emit_event", {"kind": "begin"}),
                GraphNode("heard", "event.message", {"message": "begin"}),
                GraphNode("marker", "action.emit_event", {"kind": "world_heard"}),
            ),
            (
                _link("ready", "out", "send", "in"),
                _link("heard", "out", "marker", "in"),
            ),
        )

        sender_binding = attach_graph(world, world_graph, run_ready=False)
        second_binding = attach_graph(
            world,
            second,
            entity_id="second",
            run_ready=False,
        )
        first_binding = attach_graph(
            world,
            first,
            entity_id="first",
            run_ready=False,
        )
        run_ready_batch((sender_binding, second_binding, first_binding))

        self.assertTrue(world.state["first_ready"])
        self.assertTrue(world.state["second_ready"])
        self.assertTrue(world.state["saw_second_ready"])
        self.assertIsNone(world.state["heard_source"])
        self.assertIsNone(world.state["heard_target"])
        self.assertEqual(world.state["heard_entity"], "first")
        self.assertEqual(
            [event.kind for event in world.events[:4]],
            ["begin", "first_heard", "second_heard", "world_heard"],
        )

    def test_target_reaches_world_and_target_owner_only(self) -> None:
        world = GameWorld()
        world.spawn("first", emit_event=False)
        world.spawn("second", emit_event=False)
        sender = VisualGraph(
            "sender",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "send",
                    "action.emit_event",
                    {"kind": "poke", "target": "first"},
                ),
            ),
            (_link("ready", "out", "send", "in"),),
        )
        bindings = (
            attach_graph(world, sender, run_ready=False),
            attach_graph(
                world,
                _listener("world_listener", "poke", "world_poke"),
                run_ready=False,
            ),
            attach_graph(
                world,
                _listener("first_listener", "poke", "first_poke"),
                entity_id="first",
                run_ready=False,
            ),
            attach_graph(
                world,
                _listener("second_listener", "poke", "second_poke"),
                entity_id="second",
                run_ready=False,
            ),
        )
        run_ready_batch(bindings)
        kinds = [event.kind for event in world.events]
        self.assertIn("first_poke", kinds)
        self.assertIn("world_poke", kinds)
        self.assertNotIn("second_poke", kinds)

        broadcast = VisualGraph(
            "broadcast",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("send", "action.emit_event", {"kind": "poke"}),
            ),
            (_link("ready", "out", "send", "in"),),
        )
        world.entities["second"].active = False
        start = len(world.events)
        run_ready_batch((attach_graph(world, broadcast, run_ready=False),))
        broadcast_kinds = [event.kind for event in world.events[start:]]
        self.assertIn("first_poke", broadcast_kinds)
        self.assertIn("world_poke", broadcast_kinds)
        self.assertNotIn("second_poke", broadcast_kinds)

    def test_nested_sends_are_fifo_breadth_first_and_exact(self) -> None:
        world = GameWorld()
        world.spawn("owner", emit_event=False)
        nested_sender = _listener("a_nested_sender", "start", "nested")
        first_wave = _listener("b_first_wave", "start", "b_done")
        second_wave = _listener("c_second_wave", "nested", "c_done")
        seed = VisualGraph(
            "seed",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("send", "action.emit_event", {"kind": "start"}),
            ),
            (_link("ready", "out", "send", "in"),),
        )
        bindings = tuple(
            attach_graph(
                world,
                graph,
                entity_id="owner",
                run_ready=False,
            )
            for graph in (second_wave, first_wave, nested_sender)
        ) + (attach_graph(world, seed, run_ready=False),)
        run_ready_batch(bindings)
        self.assertEqual(
            [event.kind for event in world.events[:4]],
            ["start", "nested", "b_done", "c_done"],
        )

    def test_legacy_eager_ready_defers_message_delivery_to_outer_tick(self) -> None:
        world = GameWorld()
        listener = VisualGraph(
            "listener",
            (
                GraphNode("heard", "event.message", {"message": "hello"}),
                GraphNode(
                    "remember",
                    "action.set_state",
                    {"key": "heard", "value": True},
                ),
            ),
            (_link("heard", "out", "remember", "in"),),
        )
        sender = VisualGraph(
            "sender",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("send", "action.emit_event", {"kind": "hello"}),
            ),
            (_link("ready", "out", "send", "in"),),
        )
        attach_graph(world, sender)
        # This listener registers after the sender's eager Ready already queued
        # the message.  Delivery still waits for the one world-level late drain.
        attach_graph(world, listener)
        self.assertNotIn("heard", world.state)
        world.step()
        self.assertTrue(world.state["heard"])

    def test_tick_messages_run_after_every_graph_tick_root(self) -> None:
        world = GameWorld()
        sender = VisualGraph(
            "a_sender",
            (
                GraphNode("tick", "event.tick"),
                GraphNode("send", "action.emit_event", {"kind": "after_tick"}),
            ),
            (_link("tick", "out", "send", "in"),),
        )
        later_tick = VisualGraph(
            "b_later_tick",
            (
                GraphNode("tick", "event.tick"),
                GraphNode(
                    "done",
                    "action.set_state",
                    {"key": "later_tick_done", "value": True},
                ),
            ),
            (_link("tick", "out", "done", "in"),),
        )
        listener = VisualGraph(
            "c_listener",
            (
                GraphNode(
                    "heard",
                    "event.message",
                    {"message": "after_tick"},
                ),
                GraphNode(
                    "done",
                    "value.state",
                    {"key": "later_tick_done", "default": False},
                ),
                GraphNode(
                    "remember",
                    "action.set_state",
                    {"key": "message_saw_later_tick"},
                ),
            ),
            (
                _link("heard", "out", "remember", "in"),
                _link("done", "value", "remember", "value"),
            ),
        )
        bindings = tuple(
            attach_graph(world, graph, run_ready=False)
            for graph in (sender, later_tick, listener)
        )
        self.assertEqual(
            sum(
                entry.name == "visual_graph:message_drain"
                for entry in world._systems["late"]
            ),
            1,
        )
        run_ready_batch(bindings)
        world.step()
        self.assertTrue(world.state["later_tick_done"])
        self.assertTrue(world.state["message_saw_later_tick"])

    def test_message_cascades_have_explicit_event_and_total_step_limits(self) -> None:
        loop = VisualGraph(
            "loop",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("heard", "event.message", {"message": "loop"}),
                GraphNode("send", "action.emit_event", {"kind": "loop"}),
            ),
            (
                _link("ready", "out", "send", "in"),
                _link("heard", "out", "send", "in"),
            ),
        )
        world = GameWorld()
        binding = attach_graph(world, loop, run_ready=False)
        with self.assertRaises(GraphEventLimitError) as caught:
            run_ready_batch((binding,))
        self.assertEqual(caught.exception.code, "EventLimit")
        self.assertEqual(caught.exception.limit, GRAPH_MESSAGE_MAX_EVENTS)

        many_world = GameWorld()
        emitter = attach_graph(many_world, loop, run_ready=False)
        listener_runtime = GraphRuntime(
            VisualGraph(
                "listener",
                (GraphNode("heard", "event.message", {"message": "loop"}),),
            )
        )
        listeners = tuple(
            attach_graph(
                many_world,
                listener_runtime,
                name=f"listener:{index}",
                run_ready=False,
            )
            for index in range(256)
        )
        with self.assertRaises(GraphTotalStepLimitError) as caught:
            run_ready_batch((emitter, *listeners))
        self.assertEqual(caught.exception.code, "TotalStepLimit")
        self.assertEqual(caught.exception.limit, GRAPH_MESSAGE_MAX_STEPS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
