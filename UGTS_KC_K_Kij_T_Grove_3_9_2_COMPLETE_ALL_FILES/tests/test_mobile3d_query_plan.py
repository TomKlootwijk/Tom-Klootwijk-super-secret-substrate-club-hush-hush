from __future__ import annotations

from collections.abc import MutableMapping
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.mobile3d import (  # noqa: E402
    Collider3DRecord,
    EntityState3D,
    GameWorld3D,
)
from ugts_kc3.packed_kinematics import PackedKinematicComponent  # noqa: E402


def _entity(
    entity_id: str,
    *,
    tags: tuple[str, ...] = (),
    alive: bool = True,
    active: bool = True,
    extra_components: dict[str, object] | None = None,
) -> EntityState3D:
    return EntityState3D(
        entity_id,
        "mesh",
        "material",
        (0.0, 0.0, 0.0),
        (1.0, 0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        Collider3DRecord("none"),
        False,
        1.0,
        0.0,
        tags,
        alive=alive,
        active=active,
        extra_components=dict(extra_components or {}),
    )


class Mobile3DQueryPlanTests(unittest.TestCase):
    def test_extra_components_remain_a_live_dict_compatible_view(self) -> None:
        entity = _entity(
            "actor",
            extra_components={"first": {"value": 1}, "second": 2},
        )
        detached_dict = entity.extra_components
        detached_snapshot = entity.to_dict()
        world = GameWorld3D()
        world.spawn(entity)

        view = entity.extra_components
        self.assertIsInstance(view, MutableMapping)
        self.assertIsNot(view, detached_dict)
        self.assertEqual(entity.to_dict(), detached_snapshot)
        self.assertEqual(
            dict(view), {"first": {"value": 1}, "second": 2}
        )
        self.assertEqual(view.copy(), dict(view))
        self.assertEqual(copy.copy(view), dict(view))
        self.assertEqual(copy.deepcopy(entity).extra_components, dict(view))
        held_keys = view.keys()
        held_items = view.items()
        held_values = view.values()

        view["first"] = {"value": 3}
        self.assertEqual(world.require("actor", "first"), {"value": 3})
        self.assertEqual(view.setdefault("third", 3), 3)
        self.assertEqual(view.setdefault("third", 99), 3)
        view.update({"fourth": 4}, fifth=5)
        view |= {"sixth": 6}
        self.assertEqual(
            list(view), ["first", "second", "third", "fourth", "fifth", "sixth"]
        )
        self.assertEqual(list(held_keys), list(view))
        self.assertEqual(list(held_items), list(view.items()))
        self.assertEqual(list(held_values), list(view.values()))
        self.assertEqual(list(reversed(view)), list(reversed(list(view))))
        self.assertEqual(dict.copy(view), dict(view))
        self.assertEqual(
            json.dumps(view, sort_keys=True), json.dumps(dict(view), sort_keys=True)
        )
        self.assertEqual({"zero": 0} | view, {"zero": 0, **view.copy()})
        self.assertEqual(view | {"seventh": 7}, {**view.copy(), "seventh": 7})

        del view["second"]
        self.assertNotIn("second", view)
        self.assertEqual(view.pop("third"), 3)
        self.assertEqual(view.pop("missing", "fallback"), "fallback")
        self.assertEqual(view.popitem(), ("sixth", 6))
        self.assertEqual([item.id for item in world.query("fifth")], ["actor"])
        view.clear()
        self.assertEqual(dict(view), {})
        self.assertEqual(list(held_keys), [])
        self.assertEqual(list(held_items), [])
        self.assertEqual(list(held_values), [])
        self.assertEqual(world.query("fifth"), ())
        with self.assertRaisesRegex(KeyError, "popitem"):
            view.popitem()

    def test_plan_uses_smallest_live_sparse_candidate_and_dynamic_filters(self) -> None:
        rare_ids = {1, 2, 3, 4, 5}
        world = GameWorld3D()
        for index in reversed(range(100)):
            extras: dict[str, object] = {}
            if index < 80:
                extras["common"] = index
            if index in rare_ids:
                extras["rare"] = index
            tags = ("goal",) if index in {1, 2, 4, 5} else ()
            world.spawn(
                _entity(
                    f"n{index:03d}",
                    tags=tags,
                    active=index != 2,
                    alive=index != 4,
                    extra_components=extras,
                )
            )

        plan = world.compile_query("transform", "common", "rare", tags=("goal",))
        self.assertIs(
            plan,
            world.compile_query("transform", "common", "rare", tags=("goal",)),
        )
        self.assertIs(
            plan,
            world.compile_query("rare", "transform", "common", tags=("goal",)),
        )
        self.assertEqual(plan.diagnostics.candidate_component, "rare")
        self.assertEqual(plan.diagnostics.candidate_count, 5)
        self.assertEqual(plan.diagnostics.total_entity_count, 100)
        self.assertEqual([item.id for item in plan.execute()], ["n001", "n005"])

        inactive_plan = world.compile_query(
            "common", "rare", tags=("goal",), active_only=False
        )
        self.assertEqual(
            [item.id for item in inactive_plan.execute()],
            ["n001", "n002", "n005"],
        )

        world.require("n003").tags += ("goal",)
        world.require("n010").tags += ("goal",)
        world.add_component("n010", 10, "rare")
        self.assertEqual(plan.diagnostics.candidate_count, 6)
        self.assertEqual(
            [item.id for item in plan.execute()], ["n001", "n003", "n005", "n010"]
        )
        self.assertEqual(world.remove_component("n001", "rare"), 1)
        self.assertEqual(plan.diagnostics.candidate_count, 5)
        self.assertEqual(
            [item.id for item in world.query("transform", "common", "rare", tags=("goal",))],
            ["n003", "n005", "n010"],
        )

    def test_whole_extra_component_assignment_rebuilds_live_sparse_indexes(
        self,
    ) -> None:
        world = GameWorld3D()
        entity = _entity("actor", extra_components={"old": {"number": 1}})
        world.spawn(entity)
        old_plan = world.compile_query("old")
        new_plan = world.compile_query("new")
        held_view = entity.extra_components
        held_keys = held_view.keys()

        entity.extra_components = {"new": {"number": 2}}

        self.assertIs(entity.extra_components, held_view)
        self.assertEqual(list(held_keys), ["new"])
        self.assertIsNone(world.get("actor", "old"))
        self.assertEqual(world.get("actor", "new"), {"number": 2})
        self.assertEqual(old_plan.execute(), ())
        self.assertEqual([item.id for item in new_plan.execute()], ["actor"])
        self.assertEqual(
            world.snapshot()["entities"][0]["extra_components"],
            {"new": {"number": 2}},
        )

        expected = GameWorld3D()
        expected.spawn(
            _entity("actor", extra_components={"new": {"number": 2}})
        )
        self.assertEqual(world.snapshot(), expected.snapshot())
        self.assertEqual(world.state_hash(), expected.state_hash())

        before = world.snapshot()
        before_hash = world.state_hash()
        with self.assertRaises(TypeError):
            entity.extra_components = [(["unhashable"], 3)]  # type: ignore[assignment]
        self.assertEqual(world.snapshot(), before)
        self.assertEqual(world.state_hash(), before_hash)

    def test_builtins_and_virtual_polar_membership_keep_legacy_semantics(self) -> None:
        world = GameWorld3D()
        world.spawn(_entity("z_live"))
        world.spawn(_entity("a_inactive", active=False))
        world.spawn(_entity("m_dead", alive=False))

        builtins = world.compile_query("entity", "transform", "body", "render")
        self.assertEqual(builtins.diagnostics.candidate_component, "body")
        self.assertEqual(builtins.diagnostics.candidate_count, 3)
        self.assertEqual([item.id for item in builtins.execute()], ["z_live"])
        self.assertEqual(
            [
                item.id
                for item in world.query(
                    "entity", "transform", "body", "render", active_only=False
                )
            ],
            ["a_inactive", "z_live"],
        )

        packed = PackedKinematicComponent(0, 0, "profile")
        world.add_component("z_live", packed, "packed_kinematic")
        polar_plan = world.compile_query("polar_movement")
        self.assertEqual(
            polar_plan.diagnostics.candidate_component, "packed_kinematic"
        )
        self.assertEqual(polar_plan.diagnostics.candidate_count, 1)
        self.assertEqual([item.id for item in polar_plan.execute()], ["z_live"])
        self.assertEqual(
            [item.id for item in world.query("polar_movement", "packed_kinematic")],
            ["z_live"],
        )
        snapshot_components = next(
            item["extra_components"]
            for item in world.snapshot()["entities"]
            if item["id"] == "z_live"
        )
        self.assertIn("packed_kinematic", snapshot_components)
        self.assertNotIn("polar_movement", snapshot_components)

        self.assertIs(world.remove_component("z_live", "packed_kinematic"), packed)
        self.assertEqual(polar_plan.diagnostics.candidate_count, 0)
        self.assertEqual(polar_plan.execute(), ())

    def test_add_replace_remove_failures_are_atomic_and_hash_is_representation_free(
        self,
    ) -> None:
        class InvalidComponent:
            def validate(self) -> None:
                raise ValueError("invalid component")

        first = GameWorld3D()
        first.spawn(_entity("actor", extra_components={"value": {"number": 1}}))
        second = GameWorld3D()
        second.spawn(_entity("actor"))
        second.add_component("actor", {"number": 1}, "value")
        self.assertEqual(first.snapshot(), second.snapshot())
        self.assertEqual(first.state_hash(), second.state_hash())

        plan = first.compile_query("invalid")
        with self.assertRaisesRegex(ValueError, "invalid component"):
            first.add_component("actor", InvalidComponent(), "invalid")
        self.assertEqual(plan.diagnostics.candidate_count, 0)
        self.assertNotIn("invalid", first.require("actor").extra_components)

        original = first.require("actor", "value")
        with self.assertRaisesRegex(ValueError, "already has component"):
            first.add_component("actor", {"number": 2}, "value")
        self.assertIs(first.require("actor", "value"), original)
        with self.assertRaisesRegex(ValueError, "invalid component"):
            first.add_component(
                "actor", InvalidComponent(), "value", replace_existing=True
            )
        self.assertIs(first.require("actor", "value"), original)
        with self.assertRaises(KeyError):
            first.remove_component("actor", "missing")
        self.assertIs(first.require("actor", "value"), original)


if __name__ == "__main__":
    unittest.main()
