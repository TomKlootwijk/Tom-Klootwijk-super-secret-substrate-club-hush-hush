from __future__ import annotations

import struct
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ugts_kc3.game import GameWorld, Transform2D
from ugts_kc3.mobile3d import (
    Collider3DRecord,
    EntityState3D,
    GameWorld3D,
)
from ugts_kc3.visual_graph import (
    BUILTIN_NODE_REGISTRY,
    GraphLink,
    GraphNode,
    GraphNodeExecutionError,
    GraphRuntime,
    GraphValidationError,
    PORTABLE_QUERY_TAGS,
    VisualGraph,
)


def _query_graph(
    *,
    origin: str | None = None,
    tag: str = "goal",
    radius: float = 10.0,
    extra_nodes: tuple[GraphNode, ...] = (),
    extra_links: tuple[GraphLink, ...] = (),
) -> VisualGraph:
    return VisualGraph(
        "nearest",
        (
            GraphNode("ready", "event.ready"),
            *extra_nodes,
            GraphNode(
                "nearest",
                "query.nearest_tag",
                {"origin": origin, "tag": tag, "radius": radius},
            ),
            GraphNode("announce", "action.emit_event", {"kind": "nearest"}),
        ),
        (
            GraphLink("ready", "out", "announce", "in"),
            GraphLink("nearest", "entity", "announce", "target"),
            *extra_links,
        ),
    )


def _query_outputs(result) -> dict[str, object]:
    trace = next(item for item in result.trace if item.node_id == "nearest")
    return dict(trace.outputs)


def _entity3(
    entity_id: str,
    position: tuple[float, float, float],
    tags: tuple[str, ...] = (),
    *,
    active: bool = True,
    alive: bool = True,
) -> EntityState3D:
    return EntityState3D(
        entity_id,
        "mesh",
        "material",
        position,
        (1.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        Collider3DRecord("none"),
        False,
        1.0,
        0.0,
        tags,
        active=active,
        alive=alive,
    )


class NearestTagVisualGraphTests(unittest.TestCase):
    def test_registry_contract_is_portable_and_nullable(self) -> None:
        self.assertEqual(
            PORTABLE_QUERY_TAGS,
            ("player", "collectible", "goal", "decorative", "hazard"),
        )
        definition = BUILTIN_NODE_REGISTRY.definition("query.nearest_tag")
        self.assertEqual(definition.category, "Sensing")
        self.assertEqual(
            tuple(port.name for port in definition.inputs),
            ("origin", "tag", "radius"),
        )
        self.assertEqual(
            tuple(port.name for port in definition.outputs),
            ("found", "entity", "distance"),
        )
        self.assertEqual(definition.outputs[-1].data_type, "any")

    def test_bound_2d_query_is_inclusive_and_skips_self_inactive_and_missing_transform(self) -> None:
        world = GameWorld()
        world.spawn(
            "origin",
            tags=("goal",),
            components=(Transform2D((0.0, 0.0)),),
            emit_event=False,
        )
        world.spawn(
            "boundary",
            tags=("goal",),
            components=(Transform2D((4.2, 0.0)),),
            emit_event=False,
        )
        inactive = world.spawn(
            "closer",
            tags=("goal",),
            components=(Transform2D((0.1, 0.0)),),
            emit_event=False,
        )
        inactive.active = False
        world.spawn("missing_transform", tags=("goal",), emit_event=False)

        result = GraphRuntime(_query_graph(radius=4.2)).ready(
            world,
            entity_id="origin",
        )
        self.assertEqual(
            _query_outputs(result),
            {"found": True, "entity": "boundary", "distance": 4.199999809265137},
        )
        self.assertEqual(world.events[-1].target, "boundary")

    def test_explicit_3d_origin_uses_f32_distance_and_lexical_tie(self) -> None:
        world = GameWorld3D()
        world.spawn(_entity3("origin", (0.0, 0.0, 0.0), ("player", "goal")))
        # Authored in reverse lexical order; equal f32 squared distances must
        # still select alpha.
        world.spawn(_entity3("zeta", (1.1, 2.2, 3.3), ("goal",)))
        world.spawn(_entity3("alpha", (-1.1, -2.2, -3.3), ("goal",)))
        world.spawn(_entity3("dead_closer", (0.1, 0.0, 0.0), ("goal",), alive=False))
        world.spawn(_entity3("inactive_closer", (0.2, 0.0, 0.0), ("goal",), active=False))

        outputs = _query_outputs(
            GraphRuntime(_query_graph(origin="origin")).ready(world)
        )
        self.assertEqual(outputs["entity"], "alpha")
        self.assertIs(outputs["found"], True)
        self.assertEqual(
            struct.unpack("<I", struct.pack("<f", outputs["distance"]))[0],
            0x4083B4D2,
        )

    def test_no_match_returns_three_exact_nullable_outputs(self) -> None:
        world = GameWorld()
        world.spawn(
            "origin",
            components=(Transform2D((0.0, 0.0)),),
            emit_event=False,
        )
        result = GraphRuntime(_query_graph(tag="hazard", radius=1.0)).ready(
            world,
            entity_id="origin",
        )
        self.assertEqual(
            _query_outputs(result),
            {"found": False, "entity": None, "distance": None},
        )
        self.assertIsNone(world.events[-1].target)

    def test_invalid_static_and_linked_inputs_fail_at_the_right_boundary(self) -> None:
        for properties, message in (
            ({"tag": "custom"}, "Tag must be player"),
            ({"radius": -1.0}, "Radius must be a finite non-negative"),
            ({"radius": 1.0e30}, "Radius must be a finite non-negative"),
        ):
            with self.subTest(properties=properties), self.assertRaisesRegex(
                GraphValidationError,
                message,
            ):
                VisualGraph(
                    "bad-static",
                    (GraphNode("nearest", "query.nearest_tag", properties),),
                ).validate()

        world = GameWorld()
        world.spawn(
            "origin",
            components=(Transform2D((0.0, 0.0)),),
            emit_event=False,
        )
        bad_tag = _query_graph(
            extra_nodes=(GraphNode("bad", "value.constant", {"value": "custom"}),),
            extra_links=(GraphLink("bad", "value", "nearest", "tag"),),
        )
        with self.assertRaisesRegex(GraphNodeExecutionError, "tag must be player"):
            GraphRuntime(bad_tag).ready(world, entity_id="origin")

        bad_radius = _query_graph(
            extra_nodes=(GraphNode("bad", "value.constant", {"value": -1.0}),),
            extra_links=(GraphLink("bad", "value", "nearest", "radius"),),
        )
        with self.assertRaisesRegex(GraphNodeExecutionError, "radius must be non-negative"):
            GraphRuntime(bad_radius).ready(world, entity_id="origin")

    def test_world_query_requires_an_explicit_origin(self) -> None:
        world = GameWorld()
        world.spawn(
            "origin",
            components=(Transform2D((0.0, 0.0)),),
            emit_event=False,
        )
        with self.assertRaisesRegex(GraphNodeExecutionError, "no entity was supplied"):
            GraphRuntime(_query_graph()).ready(world)


if __name__ == "__main__":
    unittest.main()
