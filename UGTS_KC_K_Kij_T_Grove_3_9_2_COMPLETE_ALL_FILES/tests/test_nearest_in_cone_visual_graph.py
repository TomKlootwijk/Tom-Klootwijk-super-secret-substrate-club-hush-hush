from __future__ import annotations

import struct
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ugts_kc3.game import GameWorld, Transform2D  # noqa: E402
from ugts_kc3.mobile3d import (  # noqa: E402
    Collider3DRecord,
    EntityState3D,
    GameWorld3D,
)
from ugts_kc3.visual_graph import (  # noqa: E402
    BUILTIN_NODE_REGISTRY,
    GraphLink,
    GraphNode,
    GraphNodeExecutionError,
    GraphRuntime,
    GraphValidationError,
    VisualGraph,
)


def _bits(value: float) -> int:
    return struct.unpack("<I", struct.pack("<f", value))[0]


def _next_f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<I", _bits(value) + 1))[0]


def _query_graph(
    *,
    origin: str | None = None,
    tag: str = "goal",
    radius: float = 10.0,
    cone: object = (1.0, 0.0, 0.0, 0.8),
    extra_nodes: tuple[GraphNode, ...] = (),
    extra_links: tuple[GraphLink, ...] = (),
) -> VisualGraph:
    return VisualGraph(
        "nearest_in_cone",
        (
            GraphNode("ready", "event.ready"),
            *extra_nodes,
            GraphNode(
                "query",
                "query.nearest_in_cone",
                {"origin": origin, "tag": tag, "radius": radius, "cone": cone},
            ),
            GraphNode("announce", "action.emit_event", {"kind": "ahead"}),
        ),
        (
            GraphLink("ready", "out", "announce", "in"),
            GraphLink("query", "entity", "announce", "target"),
            *extra_links,
        ),
    )


def _query_outputs(result) -> dict[str, object]:
    item = next(trace for trace in result.trace if trace.node_id == "query")
    return dict(item.outputs)


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


class NearestInConeVisualGraphTests(unittest.TestCase):
    def test_registry_contract_has_four_inputs_three_outputs_and_no_flow(self) -> None:
        definition = BUILTIN_NODE_REGISTRY.definition("query.nearest_in_cone")
        self.assertEqual(definition.label, "Find Object Ahead")
        self.assertEqual(definition.category, "Sensing")
        self.assertEqual(
            tuple(port.name for port in definition.inputs),
            ("origin", "tag", "radius", "cone"),
        )
        self.assertEqual(
            tuple(port.name for port in definition.outputs),
            ("found", "entity", "distance"),
        )
        self.assertEqual(definition.outputs[-1].data_type, "any")
        self.assertEqual(
            dict(definition.default_properties),
            {
                "origin": None,
                "tag": "goal",
                "radius": 10.0,
                "cone": (0.0, 0.0, -1.0, 0.7071067690849304),
            },
        )

    def test_bound_2d_query_is_inclusive_lexical_and_filters_candidates(self) -> None:
        world = GameWorld()
        world.spawn(
            "origin",
            tags=("goal",),
            components=(Transform2D((0.0, 0.0)),),
            emit_event=False,
        )
        # Reverse lexical authoring order is intentional. Both candidates are
        # exactly on the radius and cosine boundaries: distance 5, cosine 0.8.
        world.spawn(
            "zeta",
            tags=("goal",),
            components=(Transform2D((4.0, 3.0)),),
            emit_event=False,
        )
        world.spawn(
            "alpha",
            tags=("goal",),
            components=(Transform2D((4.0, -3.0)),),
            emit_event=False,
        )
        # A non-unit axis must be normalized. Without that normalization this
        # closer candidate's cosine 0.5 would incorrectly pass the 0.8 gate.
        world.spawn(
            "scaled_axis_trap",
            tags=("goal",),
            components=(Transform2D((0.5, 0.8660254)),),
            emit_event=False,
        )
        world.spawn(
            "behind",
            tags=("goal",),
            components=(Transform2D((-0.1, 0.0)),),
            emit_event=False,
        )
        inactive = world.spawn(
            "inactive",
            tags=("goal",),
            components=(Transform2D((1.0, 0.0)),),
            emit_event=False,
        )
        inactive.active = False
        dead = world.spawn(
            "dead",
            tags=("goal",),
            components=(Transform2D((1.5, 0.0)),),
            emit_event=False,
        )
        dead.alive = False
        world.spawn("missing_transform", tags=("goal",), emit_event=False)
        world.spawn(
            "wrong_tag",
            tags=("hazard",),
            components=(Transform2D((0.01, 0.0)),),
            emit_event=False,
        )

        result = GraphRuntime(
            _query_graph(radius=5.0, cone=(2.0, 0.0, 0.0, 0.8))
        ).ready(world, entity_id="origin")
        self.assertEqual(
            _query_outputs(result),
            {"found": True, "entity": "alpha", "distance": 5.0},
        )
        self.assertEqual(world.events[-1].target, "alpha")

        missing = GraphRuntime(
            _query_graph(tag="collectible", radius=5.0)
        ).ready(world, entity_id="origin")
        self.assertEqual(
            _query_outputs(missing),
            {"found": False, "entity": None, "distance": None},
        )
        self.assertIsNone(world.events[-1].target)

    def test_3d_source_aligned_f32_cosine_boundary_is_inclusive(self) -> None:
        # These binary32 values deliberately distinguish the frozen
        # normalize/divide/accumulate schedule from a squared-dot shortcut.
        axis = (
            0.5703175067901611,
            4.899357318878174,
            4.330081462860107,
        )
        position = (
            0.6566342711448669,
            -0.724554717540741,
            3.19600248336792,
        )
        boundary_cosine = 0.4861103892326355
        world = GameWorld3D()
        world.spawn(_entity3("origin", (0.0, 0.0, 0.0), ("player",)))
        world.spawn(_entity3("boundary", position, ("goal",)))

        included = GraphRuntime(
            _query_graph(
                origin="origin",
                radius=4.0,
                cone=(*axis, boundary_cosine),
            )
        ).ready(world)
        outputs = _query_outputs(included)
        self.assertEqual(outputs["entity"], "boundary")
        self.assertIs(outputs["found"], True)
        self.assertEqual(_bits(outputs["distance"]), 0x4055E74A)

        excluded = GraphRuntime(
            _query_graph(
                origin="origin",
                radius=4.0,
                cone=(*axis, _next_f32(boundary_cosine)),
            )
        ).ready(world)
        self.assertEqual(
            _query_outputs(excluded),
            {"found": False, "entity": None, "distance": None},
        )

    def test_epsilon_denominator_and_coincident_cosine_zero_are_exact(self) -> None:
        world = GameWorld()
        world.spawn(
            "origin",
            components=(Transform2D((0.0, 0.0)),),
            emit_event=False,
        )
        world.spawn(
            "tiny",
            tags=("collectible",),
            components=(Transform2D((5.0e-7, 0.0)),),
            emit_event=False,
        )
        world.spawn(
            "coincident",
            tags=("goal",),
            components=(Transform2D((0.0, 0.0)),),
            emit_event=False,
        )

        tiny = GraphRuntime(
            _query_graph(
                tag="collectible",
                radius=1.0e-6,
                cone=(1.0, 0.0, 0.0, 0.5),
            )
        ).ready(world, entity_id="origin")
        self.assertEqual(_query_outputs(tiny)["entity"], "tiny")
        self.assertEqual(_bits(_query_outputs(tiny)["distance"]), 0x350637BD)

        tiny_excluded = GraphRuntime(
            _query_graph(
                tag="collectible",
                radius=1.0e-6,
                cone=(1.0, 0.0, 0.0, _next_f32(0.5)),
            )
        ).ready(world, entity_id="origin")
        self.assertEqual(
            _query_outputs(tiny_excluded),
            {"found": False, "entity": None, "distance": None},
        )

        coincident = GraphRuntime(
            _query_graph(tag="goal", radius=0.0, cone=(1.0, 0.0, 0.0, 0.0))
        ).ready(world, entity_id="origin")
        self.assertEqual(
            _query_outputs(coincident),
            {"found": True, "entity": "coincident", "distance": 0.0},
        )
        coincident_excluded = GraphRuntime(
            _query_graph(tag="goal", radius=0.0, cone=(1.0, 0.0, 0.0, 1.0e-6))
        ).ready(world, entity_id="origin")
        self.assertEqual(
            _query_outputs(coincident_excluded),
            {"found": False, "entity": None, "distance": None},
        )

    def test_static_and_linked_invalid_cones_fail_at_the_right_boundary(self) -> None:
        for cone, message in (
            ((0.0, 0.0, 0.0, 0.0), "Facing direction must not be zero"),
            ((1.0, 0.0, 0.0, 1.0001), "minimum cosine from -1 to 1"),
            ((1.0, 0.0, 0.0, -1.0001), "minimum cosine from -1 to 1"),
            ((1.0e30, 0.0, 0.0, 0.5), "too large for deterministic device math"),
            ((1.0, 0.0, 0.0), "must be vector4"),
            ("ahead", "must be vector4"),
        ):
            with self.subTest(static=cone), self.assertRaisesRegex(
                GraphValidationError,
                message,
            ):
                VisualGraph(
                    "bad_static",
                    (GraphNode("query", "query.nearest_in_cone", {"cone": cone}),),
                ).validate()

        world = GameWorld()
        world.spawn(
            "origin",
            components=(Transform2D((0.0, 0.0)),),
            emit_event=False,
        )
        for cone, message in (
            ((0.0, 0.0, 0.0, 0.0), "Facing direction must not be zero"),
            ((1.0, 0.0, 0.0, 1.0001), "minimum cosine from -1 to 1"),
            ((1.0e30, 0.0, 0.0, 0.5), "too large for deterministic device math"),
            ("ahead", "expected vector4"),
        ):
            graph = _query_graph(
                origin="origin",
                extra_nodes=(GraphNode("bad", "value.constant", {"value": cone}),),
                extra_links=(GraphLink("bad", "value", "query", "cone"),),
            )
            graph.validate()
            with self.subTest(linked=cone), self.assertRaisesRegex(
                GraphNodeExecutionError,
                message,
            ):
                GraphRuntime(graph).ready(world)

        with self.assertRaisesRegex(GraphNodeExecutionError, "no entity was supplied"):
            GraphRuntime(_query_graph()).ready(world)


if __name__ == "__main__":
    unittest.main(verbosity=2)
