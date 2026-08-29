import json
import struct
import unittest

from ugts_kc3.game import Body2D, GameWorld, Health2D, Transform2D
from ugts_kc3.game_input import InputFrame
from ugts_kc3.scatter import REPEATABLE_NUMBER_NAMESPACE, repeatable_number
from ugts_kc3.visual_graph import (
    BUILTIN_NODE_REGISTRY,
    GraphLink,
    GraphNode,
    GraphNodeExecutionError,
    GraphRuntime,
    GraphStepLimitError,
    GraphValidationError,
    VisualGraph,
    attach_graph,
)


def link(source_node, source_port, target_node, target_port):
    return GraphLink(source_node, source_port, target_node, target_port)


class VisualGraphRecordTests(unittest.TestCase):
    def test_roundtrip_is_immutable_and_canonical(self):
        source_properties = {"value": {"items": [1, 2, 3]}}
        graph = VisualGraph(
            "roundtrip",
            (
                GraphNode("ready", "event.ready", position=(12, 24)),
                GraphNode("constant", "value.constant", source_properties, (30, 24)),
                GraphNode("set", "action.set_state", {"key": "items"}, (48, 24)),
            ),
            (
                link("ready", "out", "set", "in"),
                link("constant", "value", "set", "value"),
            ),
            {"editor": {"zoom": 1.25}},
        )
        source_properties["value"]["items"].append(99)
        constant = next(node for node in graph.nodes if node.id == "constant")
        self.assertEqual(constant.properties["value"]["items"], (1, 2, 3))
        with self.assertRaises(TypeError):
            constant.properties["value"] = 4

        encoded = graph.canonical_bytes()
        self.assertNotIn(b"\n", encoded)
        self.assertEqual(VisualGraph.from_json(encoded), graph)
        self.assertEqual(json.loads(encoded), graph.to_dict())
        self.assertEqual(len(graph.content_hash()), 64)
        self.assertEqual(VisualGraph.from_dict(graph.to_dict()).content_hash(), graph.content_hash())

    def test_registry_has_friendly_metadata_and_requested_nodes(self):
        expected = {
            "event.ready", "event.tick", "event.input_pressed", "flow.branch",
            "value.constant", "value.state", "value.component", "math.add",
            "math.subtract", "math.multiply", "math.divide", "compare",
            "action.set_state", "action.set_component", "action.emit_event",
            "action.apply_force", "action.set_active", "action.despawn",
        }
        self.assertTrue(expected.issubset(BUILTIN_NODE_REGISTRY.types))
        for definition in BUILTIN_NODE_REGISTRY:
            self.assertTrue(definition.label)
            self.assertTrue(definition.category)
            self.assertTrue(definition.description)
            self.assertIsNotNone(definition.default_properties)

    def test_validation_reports_port_problem_in_plain_language(self):
        graph = VisualGraph(
            "invalid",
            (GraphNode("ready", "event.ready"), GraphNode("set", "action.set_state")),
            (link("ready", "missing", "set", "value"),),
        )
        with self.assertRaises(GraphValidationError) as caught:
            graph.validate()
        message = str(caught.exception)
        self.assertIn("no output port named 'missing'", message)
        self.assertIn("Node 'ready'", message)

    def test_data_cycle_is_rejected_but_flow_cycle_reaches_guard(self):
        data_cycle = VisualGraph(
            "data-cycle",
            (GraphNode("a", "math.add"), GraphNode("b", "math.add")),
            (
                link("a", "result", "b", "a"),
                link("b", "result", "a", "a"),
            ),
        )
        with self.assertRaises(GraphValidationError) as caught:
            data_cycle.validate()
        self.assertIn("Data links form a cycle", str(caught.exception))

        flow_cycle = VisualGraph(
            "flow-cycle",
            (GraphNode("ready", "event.ready"), GraphNode("branch", "flow.branch")),
            (
                link("ready", "out", "branch", "in"),
                link("branch", "true", "branch", "in"),
            ),
        )
        runtime = GraphRuntime(flow_cycle, max_steps=5)
        with self.assertRaises(GraphStepLimitError) as limit:
            runtime.ready(GameWorld())
        self.assertEqual(limit.exception.limit, 5)
        self.assertEqual(len(limit.exception.trace), 5)
        self.assertFalse(runtime.last_result.completed)


class VisualGraphExecutionTests(unittest.TestCase):
    def test_repeatable_random_number_has_binary32_golden_and_linked_inputs(self):
        self.assertEqual(REPEATABLE_NUMBER_NAMESPACE, 0x7F1400ACD2EBB3AE)
        direct = repeatable_number(392.000001, 7, -10.0, 10.0)
        self.assertEqual(struct.unpack("<I", struct.pack("<f", direct))[0], 0xC0F72CB8)

        graph = VisualGraph(
            "repeatable",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("world", "value.constant", {"value": 392.000001}),
                GraphNode("pick", "value.constant", {"value": 7}),
                GraphNode("low", "value.constant", {"value": -10.0}),
                GraphNode("high", "value.constant", {"value": 10.0}),
                GraphNode("number", "value.seeded_number"),
                GraphNode("remember", "action.set_state", {"key": "draw"}),
            ),
            (
                link("ready", "out", "remember", "in"),
                link("world", "value", "number", "world_number"),
                link("pick", "value", "number", "pick_number"),
                link("low", "value", "number", "smallest"),
                link("high", "value", "number", "largest"),
                link("number", "value", "remember", "value"),
            ),
        )
        restored = VisualGraph.from_json(graph.canonical_bytes())
        world = GameWorld()
        result = GraphRuntime(restored).ready(world)
        self.assertEqual(
            struct.unpack("<I", struct.pack("<f", world.state["draw"]))[0],
            0xC0F72CB8,
        )
        number_trace = next(item for item in result.trace if item.node_id == "number")
        self.assertEqual(dict(number_trace.inputs), {
            "world_number": 392.000001,
            "pick_number": 7,
            "smallest": -10.0,
            "largest": 10.0,
        })

    def test_repeatable_random_number_errors_explain_the_bad_setting(self):
        static_near_integer = VisualGraph(
            "near-integer",
            (
                GraphNode(
                    "number",
                    "value.seeded_number",
                    {"world_number": 392.000001, "pick_number": 7},
                ),
            ),
        )
        static_near_integer.validate()
        with self.assertRaisesRegex(
            GraphValidationError,
            "World number must be a whole number from 0 to 65535",
        ):
            VisualGraph(
                "fractional-static",
                (
                    GraphNode(
                        "number",
                        "value.seeded_number",
                        {"world_number": 392.1},
                    ),
                ),
            ).validate()
        for bad_world in (-1, 392.1, 65536, True):
            with self.subTest(world_number=bad_world), self.assertRaisesRegex(
                ValueError, "World number must be a whole number from 0 to 65535"
            ):
                repeatable_number(bad_world, 0, 0.0, 1.0)
        with self.assertRaises(GraphValidationError) as caught:
            VisualGraph(
                "bad-range",
                (GraphNode("number", "value.seeded_number", {"smallest": 2, "largest": 1}),),
            ).validate()
        self.assertIn("Smallest must not be bigger than Largest", str(caught.exception))

        graph = VisualGraph(
            "bad-linked-pick",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("bad", "value.constant", {"value": 392.1}),
                GraphNode("number", "value.seeded_number"),
                GraphNode("remember", "action.set_state", {"key": "draw"}),
            ),
            (
                link("ready", "out", "remember", "in"),
                link("bad", "value", "number", "pick_number"),
                link("number", "value", "remember", "value"),
            ),
        )
        with self.assertRaises(GraphNodeExecutionError) as dynamic:
            GraphRuntime(graph).ready(GameWorld())
        self.assertIn("Pick number must be a whole number from 0 to 65535", str(dynamic.exception))

    def test_ready_math_compare_branch_and_state_execution(self):
        graph = VisualGraph(
            "score-on-ready",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("two", "value.constant", {"value": 2}),
                GraphNode("three", "value.constant", {"value": 3}),
                GraphNode("sum", "math.add"),
                GraphNode("five", "value.constant", {"value": 5}),
                GraphNode("equals", "compare", {"operator": "equal"}),
                GraphNode("branch", "flow.branch"),
                GraphNode("success", "action.set_state", {"key": "answer"}),
                GraphNode("failure", "action.set_state", {"key": "answer", "value": -1}),
            ),
            (
                link("ready", "out", "branch", "in"),
                link("two", "value", "sum", "a"),
                link("three", "value", "sum", "b"),
                link("sum", "result", "equals", "a"),
                link("five", "value", "equals", "b"),
                link("equals", "result", "branch", "condition"),
                link("branch", "true", "success", "in"),
                link("branch", "false", "failure", "in"),
                link("sum", "result", "success", "value"),
            ),
        )
        world = GameWorld()
        result = GraphRuntime(graph).ready(world)
        self.assertEqual(world.state["answer"], 5)
        self.assertTrue(result.completed)
        self.assertEqual(result.steps, len(result.trace))
        self.assertEqual(result.trace[-1].node_id, "success")
        self.assertEqual(result.to_dict()["trace"][-1]["inputs"]["value"], 5)

    def test_tick_reads_fresh_state_each_flow_activation(self):
        graph = VisualGraph(
            "increment",
            (
                GraphNode("tick", "event.tick"),
                GraphNode("current", "value.state", {"key": "count", "default": 0}),
                GraphNode("one", "value.constant", {"value": 1}),
                GraphNode("add", "math.add"),
                GraphNode("store", "action.set_state", {"key": "count"}),
            ),
            (
                link("tick", "out", "store", "in"),
                link("current", "value", "add", "a"),
                link("one", "value", "add", "b"),
                link("add", "result", "store", "value"),
            ),
        )
        world = GameWorld()
        runtime = GraphRuntime(graph)
        runtime.tick(world)
        runtime.tick(world)
        self.assertEqual(world.state["count"], 2)

    def test_input_pressed_only_fires_on_edge(self):
        graph = VisualGraph(
            "input",
            (
                GraphNode("pressed", "event.input_pressed", {"action": "jump"}),
                GraphNode("mark", "action.set_state", {"key": "jumped", "value": True}),
            ),
            (link("pressed", "out", "mark", "in"),),
        )
        world = GameWorld()
        runtime = GraphRuntime(graph)
        held = InputFrame({"jump": 1}, {"jump": 1}, {"jump": 0.5})
        result = runtime.tick(world, input_frame=held)
        self.assertNotIn("jumped", world.state)
        self.assertEqual(tuple(item.node_id for item in result.trace), ("pressed",))
        edge = InputFrame({"jump": 1}, {"jump": 0}, {"jump": 0.5})
        runtime.tick(world, input_frame=edge)
        self.assertTrue(world.state["jumped"])

    def test_component_force_active_event_and_despawn_actions(self):
        world = GameWorld()
        world.spawn("actor", components=(Transform2D(), Body2D(gravity_scale=0), Health2D(5, 5)), emit_event=False)
        graph = VisualGraph(
            "actions",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("health", "action.set_component", {"component": "health", "field": "current", "value": 3}),
                GraphNode("force", "action.apply_force", {"force": [4, -2]}),
                GraphNode("inactive", "action.set_active", {"active": False}),
                GraphNode("emit", "action.emit_event", {"kind": "configured", "payload": {"ok": True}}),
            ),
            (
                link("ready", "out", "health", "in"),
                link("health", "out", "force", "in"),
                link("force", "out", "inactive", "in"),
                link("inactive", "out", "emit", "in"),
            ),
        )
        GraphRuntime(graph).ready(world, entity_id="actor")
        self.assertEqual(world.require("actor", Health2D).current, 3)
        self.assertEqual(world.require("actor", Body2D).force, (4.0, -2.0))
        self.assertFalse(world.entities["actor"].active)
        self.assertEqual(world.events[-1].kind, "configured")
        self.assertEqual(world.events[-1].payload, {"ok": True})

        despawn = VisualGraph(
            "despawn",
            (GraphNode("ready", "event.ready"), GraphNode("remove", "action.despawn")),
            (link("ready", "out", "remove", "in"),),
        )
        GraphRuntime(despawn).ready(world, entity_id="actor")
        self.assertNotIn("actor", world.entities)

    def test_component_value_and_divide_error_include_node(self):
        world = GameWorld()
        world.spawn("actor", components=(Health2D(4, 5),), emit_event=False)
        graph = VisualGraph(
            "component-read",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("health", "value.component", {"component": "health", "field": "current"}),
                GraphNode("zero", "value.constant", {"value": 0}),
                GraphNode("divide", "math.divide"),
                GraphNode("set", "action.set_state", {"key": "bad"}),
            ),
            (
                link("ready", "out", "set", "in"),
                link("health", "value", "divide", "a"),
                link("zero", "value", "divide", "b"),
                link("divide", "result", "set", "value"),
            ),
        )
        with self.assertRaises(GraphNodeExecutionError) as caught:
            GraphRuntime(graph).ready(world, entity_id="actor")
        self.assertEqual(caught.exception.node_id, "divide")
        self.assertIn("divide by zero", str(caught.exception))
        self.assertEqual(caught.exception.trace[-1].status, "error")

    def test_whole_typed_component_replacement_is_normalized(self):
        world = GameWorld()
        world.spawn("actor", components=(Transform2D(), Body2D(gravity_scale=0)), emit_event=False)
        graph = VisualGraph(
            "replace-body",
            (
                GraphNode("ready", "event.ready"),
                GraphNode(
                    "replace",
                    "action.set_component",
                    {
                        "component": "body",
                        "field": "",
                        "value": {"body_type": "dynamic", "mass": 2, "gravity_scale": 0},
                    },
                ),
            ),
            (link("ready", "out", "replace", "in"),),
        )
        GraphRuntime(graph).ready(world, entity_id="actor")
        body = world.require("actor", Body2D)
        self.assertIsInstance(body, Body2D)
        self.assertEqual(body.mass, 2)
        world.step()

    def test_attach_runs_ready_and_fixed_tick(self):
        graph = VisualGraph(
            "bound",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("mark", "action.set_state", {"key": "ready", "value": True}),
                GraphNode("tick", "event.tick"),
                GraphNode("dt", "action.set_state", {"key": "dt"}),
            ),
            (
                link("ready", "out", "mark", "in"),
                link("tick", "out", "dt", "in"),
                link("tick", "dt", "dt", "value"),
            ),
        )
        world = GameWorld(fixed_dt=0.125)
        binding = attach_graph(world, graph)
        self.assertTrue(world.state["ready"])
        world.step()
        self.assertEqual(world.state["dt"], 0.125)
        self.assertIsNotNone(binding.ready_result)
        self.assertIsNotNone(binding.last_result)


if __name__ == "__main__":
    unittest.main()
