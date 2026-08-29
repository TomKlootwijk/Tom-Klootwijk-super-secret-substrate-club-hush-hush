from __future__ import annotations

from pathlib import Path
import struct
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ugts_kc3.game import GameWorld  # noqa: E402
from ugts_kc3.visual_graph import (  # noqa: E402
    BUILTIN_NODE_REGISTRY,
    GraphLink,
    GraphNode,
    GraphNodeExecutionError,
    GraphRuntime,
    GraphValidationError,
    VisualGraph,
    attach_graph,
)


def _timer_graph(*, seconds: float = 1.0, repeat: bool = True) -> VisualGraph:
    return VisualGraph(
        "timer",
        (
            GraphNode(
                "timer",
                "event.timer",
                {"seconds": seconds, "repeat": repeat},
            ),
            GraphNode("remember", "action.set_state", {"key": "rings"}),
        ),
        (
            GraphLink("timer", "out", "remember", "in"),
            GraphLink("timer", "count", "remember", "value"),
        ),
    )


def _timer_outputs(result) -> dict[str, object]:
    return dict(next(item for item in result.trace if item.node_id == "timer").outputs)


class TimerVisualGraphTests(unittest.TestCase):
    def test_registry_has_child_facing_literal_timer_contract(self) -> None:
        definition = BUILTIN_NODE_REGISTRY.definition("event.timer")
        self.assertEqual(definition.label, "When Timer Rings")
        self.assertEqual(definition.category, "Events")
        self.assertEqual(
            tuple(port.name for port in definition.inputs),
            ("seconds", "repeat"),
        )
        self.assertEqual(
            tuple(port.name for port in definition.outputs),
            ("out", "count", "remaining", "entity"),
        )
        self.assertEqual(dict(definition.default_properties), {"seconds": 1.0, "repeat": True})

    def test_repeat_rings_at_exact_60_and_120_active_steps(self) -> None:
        world = GameWorld(fixed_dt=1.0 / 60.0)
        binding = attach_graph(world, _timer_graph())

        world.step(steps=59)
        before = _timer_outputs(binding.last_result)
        self.assertEqual(before["count"], 0.0)
        self.assertEqual(
            struct.unpack("<I", struct.pack("<f", before["remaining"]))[0],
            0x3C888889,
        )
        self.assertNotIn("rings", world.state)

        world.step()
        self.assertEqual(world.state["rings"], 1.0)
        self.assertEqual(
            _timer_outputs(binding.last_result),
            {"count": 1.0, "remaining": 0.0, "entity": None},
        )
        world.step(steps=60)
        self.assertEqual(world.state["rings"], 2.0)
        self.assertEqual(_timer_outputs(binding.last_result)["count"], 2.0)

    def test_120_hz_one_shot_rings_once_and_stays_finished(self) -> None:
        world = GameWorld(fixed_dt=1.0 / 120.0)
        runtime = GraphRuntime(_timer_graph(repeat=False))
        runtime.ready(world)
        for _ in range(120):
            result = runtime.tick(world)
        self.assertEqual(result.trace[0].flow_outputs, ("out",))
        self.assertEqual(world.state["rings"], 1.0)

        result = runtime.tick(world)
        timer = next(item for item in result.trace if item.node_id == "timer")
        self.assertEqual(timer.flow_outputs, ())
        self.assertEqual(
            dict(timer.outputs),
            {"count": 1.0, "remaining": 0.0, "entity": None},
        )

    def test_entity_inactivity_pauses_and_ready_resets_binding_counter(self) -> None:
        world = GameWorld(fixed_dt=1.0 / 60.0)
        owner = world.spawn("owner", emit_event=False)
        binding = attach_graph(world, _timer_graph(), entity_id=owner.id)

        world.step(steps=30)
        owner.active = False
        world.step(steps=90)
        self.assertEqual(binding.active_step, 30)
        self.assertNotIn("rings", world.state)
        owner.active = True
        world.step(steps=30)
        self.assertEqual(world.state["rings"], 1.0)

        binding.run_ready()
        self.assertEqual(binding.active_step, 0)
        world.state.pop("rings")
        world.step(steps=59)
        self.assertNotIn("rings", world.state)
        world.step()
        self.assertEqual(world.state["rings"], 1.0)

    def test_invalid_literals_links_and_zero_dt_fail_clearly(self) -> None:
        for seconds in (0.0, -1.0, 86400.1, 1.0e40):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(
                GraphValidationError,
                "Seconds must be a finite positive number up to 86400",
            ):
                _timer_graph(seconds=seconds).validate()

        linked = VisualGraph(
            "linked_timer",
            (
                GraphNode("value", "value.constant", {"value": 1.0}),
                GraphNode("timer", "event.timer"),
            ),
            (GraphLink("value", "value", "timer", "seconds"),),
        )
        with self.assertRaisesRegex(GraphValidationError, "set on the block"):
            linked.validate()

        runtime = GraphRuntime(_timer_graph())
        runtime.ready(GameWorld())
        with self.assertRaisesRegex(
            GraphNodeExecutionError,
            "needs a positive fixed-step duration",
        ):
            runtime.tick(GameWorld(), dt=0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
