from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.visual_graph import (  # noqa: E402
    BUILTIN_NODE_REGISTRY,
    GraphExecutionError,
    GraphLink,
    GraphNode,
    GraphRuntime,
    VisualGraph,
)


class _AnimationComponent:
    def __init__(self) -> None:
        self.base_translation = (1.0, 2.0, 3.0)
        self.base_rotation = (1.0, 0.0, 0.0, 0.0)
        self.base_scale = (2.0, 2.0, 2.0)
        self.active_clip: str | None = "idle"
        self.play_calls: list[tuple[str, bool]] = []
        self.stop_calls: list[bool] = []
        self.reset_calls = 0

    def play(self, clip: str, restart: bool = True) -> None:
        self.play_calls.append((clip, restart))
        self.active_clip = clip

    def stop(self, reset: bool = True) -> None:
        self.stop_calls.append(reset)
        if reset:
            self.active_clip = None

    def reset_pose(self, entity: object) -> None:
        self.reset_calls += 1
        entity.position = self.base_translation
        entity.rotation = self.base_rotation
        entity.scale = self.base_scale


class _World:
    def __init__(self, *, animated: bool = True) -> None:
        component = _AnimationComponent() if animated else None
        extras = {} if component is None else {"transform_animation": component}
        self.entities = {
            "actor": SimpleNamespace(
                active=True,
                alive=True,
                position=(9.0, 9.0, 9.0),
                rotation=(0.0, 1.0, 0.0, 0.0),
                scale=(9.0, 9.0, 9.0),
                extra_components=extras,
            )
        }
        self.state: dict[str, object] = {}

    def require(self, entity_id: str, component: str | None = None) -> object:
        entity = self.entities[entity_id]
        if component is None:
            return entity
        if component not in entity.extra_components:
            raise KeyError(f"entity {entity_id} lacks component {component}")
        return entity.extra_components[component]


def _action_graph(type_id: str, properties: dict[str, object]) -> VisualGraph:
    return VisualGraph(
        type_id,
        (
            GraphNode("ready", "event.ready"),
            GraphNode("action", type_id, properties=properties),
        ),
        (GraphLink("ready", "out", "action", "in"),),
    )


class AnimationVisualGraphTests(unittest.TestCase):
    def test_registry_and_literal_validation(self) -> None:
        play = BUILTIN_NODE_REGISTRY.definition("action.play_animation")
        stop = BUILTIN_NODE_REGISTRY.definition("action.stop_animation")
        self.assertEqual(play.label, "Play Animation")
        self.assertEqual(play.default_properties["clip"], "main")
        self.assertEqual(stop.label, "Stop Animation")
        with self.assertRaisesRegex(ValueError, "Play Animation Clip"):
            _action_graph(
                "action.play_animation",
                {"entity": None, "clip": "Bad Clip", "restart": True},
            ).validate()

    def test_play_and_stop_use_the_bound_animation_component(self) -> None:
        world = _World()
        play = _action_graph(
            "action.play_animation",
            {"entity": None, "clip": "jump", "restart": True},
        )
        GraphRuntime(play).ready(world, entity_id="actor")
        component = world.require("actor", "transform_animation")
        self.assertEqual(component.play_calls, [("jump", True)])
        self.assertEqual(world.entities["actor"].position, component.base_translation)

        world.entities["actor"].position = (8.0, 8.0, 8.0)
        stop = _action_graph(
            "action.stop_animation",
            {"entity": None, "reset": True},
        )
        GraphRuntime(stop).ready(world, entity_id="actor")
        self.assertEqual(component.stop_calls, [True])
        self.assertEqual(component.reset_calls, 1)
        self.assertEqual(world.entities["actor"].position, component.base_translation)

    def test_connected_clip_is_runtime_checked_and_missing_component_is_clear(self) -> None:
        connected = VisualGraph(
            "connected",
            (
                GraphNode("ready", "event.ready"),
                GraphNode("clip", "value.constant", {"value": "Bad Clip"}),
                GraphNode(
                    "play",
                    "action.play_animation",
                    {"entity": None, "restart": False},
                ),
            ),
            (
                GraphLink("ready", "out", "play", "in"),
                GraphLink("clip", "value", "play", "clip"),
            ),
        )
        connected.validate()
        with self.assertRaisesRegex(GraphExecutionError, "Play Animation Clip"):
            GraphRuntime(connected).ready(_World(), entity_id="actor")

        play = _action_graph(
            "action.play_animation",
            {"entity": None, "clip": "jump", "restart": True},
        )
        with self.assertRaisesRegex(GraphExecutionError, "has no transform animation"):
            GraphRuntime(play).ready(_World(animated=False), entity_id="actor")


if __name__ == "__main__":
    unittest.main()
