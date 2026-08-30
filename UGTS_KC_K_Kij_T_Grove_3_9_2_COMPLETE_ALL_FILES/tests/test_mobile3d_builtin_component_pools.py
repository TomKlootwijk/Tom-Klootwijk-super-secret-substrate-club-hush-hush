from __future__ import annotations

import copy
from dataclasses import asdict, fields, replace
from pathlib import Path
import pickle
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.mobile3d import (  # noqa: E402
    BodyComponent3D,
    Collider3DRecord,
    ColliderComponent3D,
    EntityState3D,
    GameWorld3D,
    RenderComponent3D,
    TransformComponent3D,
)
from ugts_kc3.packed_kinematics import PackedKinematicComponent  # noqa: E402


def _entity(
    entity_id: str = "actor",
    *,
    extra_components: dict[str, object] | None = None,
) -> EntityState3D:
    return EntityState3D(
        entity_id,
        "mesh",
        "material",
        (1.0, 2.0, 3.0),
        (1.0, 0.0, 0.0, 0.0),
        (1.0, 1.5, 2.0),
        (4.0, 5.0, 6.0),
        (0.0, 0.5, 0.0),
        Collider3DRecord("sphere", radius=0.75),
        True,
        2.0,
        0.25,
        ("goal",),
        metadata={"nested": {"value": 7}},
        extra_components=dict(extra_components or {}),
    )


class Mobile3DBuiltinComponentPoolTests(unittest.TestCase):
    def test_spawn_transfers_builtins_to_one_world_authority(self) -> None:
        entity = _entity(extra_components={"custom": {"number": 3}})
        before = entity.to_dict()
        detached_collider = entity.collider

        world = GameWorld3D()
        world.spawn(entity)

        self.assertEqual(entity.to_dict(), before)
        self.assertEqual(world.snapshot()["entities"], [before])
        self.assertIs(world._collider_components["actor"], detached_collider)
        self.assertEqual(
            world._transform_components["actor"].position, tuple(before["position"])
        )
        self.assertEqual(
            world._body_components["actor"].velocity, tuple(before["velocity"])
        )
        self.assertEqual(world._render_components["actor"].mesh_id, before["mesh_id"])
        for name in (
            "mesh_id",
            "material_id",
            "position",
            "rotation",
            "scale",
            "velocity",
            "angular_velocity",
            "collider",
            "dynamic",
            "mass",
            "restitution",
        ):
            with self.subTest(mirrored_field=name):
                self.assertNotIn(name, entity.__dict__)

        entity.position = (8.0, 9.0, 10.0)
        entity.velocity = (1.0, 2.0, 3.0)
        entity.collider = Collider3DRecord("box", half_extents=(1.0, 2.0, 3.0))
        entity.material_id = "changed"
        self.assertEqual(
            world._transform_components["actor"].position, (8.0, 9.0, 10.0)
        )
        self.assertEqual(world._body_components["actor"].velocity, (1.0, 2.0, 3.0))
        self.assertEqual(world._collider_components["actor"].shape, "box")
        self.assertEqual(world._render_components["actor"].material_id, "changed")

        world._transform_components["actor"].scale = (3.0, 3.0, 3.0)
        world._body_components["actor"].mass = 4.0
        world._render_components["actor"].mesh_id = "other_mesh"
        self.assertEqual(entity.scale, (3.0, 3.0, 3.0))
        self.assertEqual(entity.mass, 4.0)
        self.assertEqual(entity.mesh_id, "other_mesh")

    def test_component_replacement_updates_the_pool_and_compatibility_view(self) -> None:
        world = GameWorld3D()
        entity = _entity()
        world.spawn(entity)

        transform = TransformComponent3D(
            (9.0, 8.0, 7.0),
            (1.0, 0.0, 0.0, 0.0),
            (2.0, 2.0, 2.0),
        )
        body = BodyComponent3D(
            (3.0, 2.0, 1.0),
            (0.0, 1.0, 0.0),
            False,
            5.0,
            0.5,
        )
        render = RenderComponent3D("replacement_mesh", "replacement_material")
        world.add_component("actor", transform, "transform", replace_existing=True)
        world.add_component("actor", body, "body", replace_existing=True)
        world.add_component(
            "actor",
            ColliderComponent3D("sphere", radius=2.5),
            "collider",
            replace_existing=True,
        )
        world.add_component("actor", render, "render", replace_existing=True)

        self.assertIs(world._transform_components["actor"], transform)
        self.assertIs(world._body_components["actor"], body)
        self.assertIs(world._render_components["actor"], render)
        self.assertEqual(entity.position, transform.position)
        self.assertEqual(entity.velocity, body.velocity)
        self.assertEqual(entity.collider.radius, 2.5)
        self.assertEqual(entity.mesh_id, "replacement_mesh")
        self.assertIs(world.get("actor", "transform").position, transform.position)

        body_plan = world.compile_query("body", "velocity", "angular_velocity")
        self.assertEqual(body_plan.diagnostics.candidate_component, "body")
        self.assertEqual(body_plan.diagnostics.candidate_count, 1)
        self.assertEqual(body_plan.execute(), (entity,))

        for name in ("transform", "body", "velocity", "angular_velocity", "collider", "render"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "cannot be removed"):
                    world.remove_component("actor", name)
        self.assertEqual(body_plan.execute(), (entity,))

    def test_copy_of_spawned_entity_is_detached_and_representation_free(self) -> None:
        world = GameWorld3D()
        entity = _entity(extra_components={"custom": {"numbers": [1, 2]}})
        world.spawn(entity)

        shallow = copy.copy(entity)
        self.assertEqual(shallow, entity)
        self.assertNotIn("_component_owner", shallow.__dict__)
        self.assertNotIn("_component_pool_id", shallow.__dict__)
        shallow.position = (10.0, 20.0, 30.0)
        self.assertEqual(entity.position, (1.0, 2.0, 3.0))
        shallow_world = GameWorld3D()
        shallow_world.spawn(shallow)
        self.assertEqual(
            shallow_world.require("actor").position, (10.0, 20.0, 30.0)
        )
        shallow.extra_components["custom"] = {"numbers": [9]}
        self.assertEqual(entity.extra_components["custom"], {"numbers": [1, 2]})

        clone = copy.deepcopy(entity)
        self.assertEqual(clone, entity)
        self.assertNotIn("_component_owner", clone.__dict__)
        self.assertNotIn("_component_pool_id", clone.__dict__)
        self.assertIn("position", clone.__dict__)
        self.assertIn("velocity", clone.__dict__)
        self.assertIn("collider", clone.__dict__)
        self.assertIn("mesh_id", clone.__dict__)
        self.assertIsInstance(clone.extra_components, dict)

        clone.position = (100.0, 200.0, 300.0)
        clone.extra_components["custom"]["numbers"].append(3)
        clone.metadata["nested"]["value"] = 99
        self.assertEqual(entity.position, (1.0, 2.0, 3.0))
        self.assertEqual(entity.extra_components["custom"], {"numbers": [1, 2]})
        self.assertEqual(entity.metadata, {"nested": {"value": 7}})

        second = GameWorld3D()
        second.spawn(clone)
        self.assertEqual(second.require("actor").position, (100.0, 200.0, 300.0))
        third = GameWorld3D()
        with self.assertRaisesRegex(ValueError, "already belongs"):
            third.spawn(entity)

    def test_public_dataclass_shape_asdict_and_replace_remain_compatible(self) -> None:
        entity = _entity(
            extra_components={
                "optional_collider": ColliderComponent3D(
                    "sphere", radius=1.25, sensor=True
                )
            }
        )
        expected_fields = (
            "id",
            "mesh_id",
            "material_id",
            "position",
            "rotation",
            "scale",
            "velocity",
            "angular_velocity",
            "collider",
            "dynamic",
            "mass",
            "restitution",
            "tags",
            "grounded",
            "alive",
            "active",
            "metadata",
            "extra_components",
        )
        detached_values = asdict(entity)
        detached_repr = repr(entity)
        self.assertEqual(
            detached_values["extra_components"]["optional_collider"],
            {
                "shape": "sphere",
                "radius": 1.25,
                "half_extents": (0.5, 0.5, 0.5),
                "sensor": True,
            },
        )
        self.assertEqual(tuple(item.name for item in fields(entity)), expected_fields)

        world = GameWorld3D()
        world.spawn(entity)

        attached_values = asdict(entity)
        self.assertIs(type(attached_values["extra_components"]), dict)
        self.assertEqual(attached_values, detached_values)
        self.assertEqual(repr(entity), detached_repr)
        replacement = replace(entity, position=(10.0, 20.0, 30.0))
        self.assertNotIn("_component_owner", replacement.__dict__)
        self.assertEqual(replacement.position, (10.0, 20.0, 30.0))
        self.assertEqual(entity.position, (1.0, 2.0, 3.0))
        self.assertEqual(replacement.mesh_id, entity.mesh_id)
        replacement_world = GameWorld3D()
        replacement_world.spawn(replacement)
        replacement.extra_components["added"] = 1
        self.assertNotIn("added", entity.extra_components)

    def test_deepcopy_world_relinks_entity_views_to_independent_copied_pools(
        self,
    ) -> None:
        world = GameWorld3D()
        world.spawn(
            _entity(
                extra_components={
                    "custom": {"numbers": [1, 2]},
                    "packed_kinematic": PackedKinematicComponent(1, 2, "profile"),
                }
            )
        )
        source_plan = world.compile_query("transform", "custom")
        source_snapshot = world.snapshot()
        source_hash = world.state_hash()

        cloned = copy.deepcopy(world)
        cloned_entity = cloned.require("actor")
        cloned_plan = cloned.compile_query("transform", "custom")

        self.assertIsNot(cloned, world)
        self.assertEqual(cloned.snapshot(), source_snapshot)
        self.assertEqual(cloned.state_hash(), source_hash)
        self.assertIs(cloned_entity.__dict__["_component_owner"], cloned)
        self.assertIs(cloned_plan._world, cloned)
        self.assertIsNot(cloned_plan, source_plan)
        self.assertIsNot(
            cloned._transform_components["actor"],
            world._transform_components["actor"],
        )
        self.assertIsNot(
            cloned._body_components["actor"], world._body_components["actor"]
        )

        cloned_entity.position = (9.0, 8.0, 7.0)
        cloned_entity.mass = 8.0
        cloned_entity.extra_components["custom"]["numbers"].append(3)
        self.assertEqual(cloned._transform_components["actor"].position, (9.0, 8.0, 7.0))
        self.assertEqual(cloned._body_components["actor"].mass, 8.0)
        self.assertEqual(world.require("actor").position, (1.0, 2.0, 3.0))
        self.assertEqual(world.require("actor").mass, 2.0)
        self.assertEqual(
            world.require("actor").extra_components["custom"], {"numbers": [1, 2]}
        )
        self.assertEqual([item.id for item in cloned_plan.execute()], ["actor"])

    def test_pickle_spawned_entity_is_standalone_with_packed_motion(self) -> None:
        packed = PackedKinematicComponent(0x1234, 0x5678, "profile")
        world = GameWorld3D()
        entity = _entity(extra_components={"packed_kinematic": packed})
        world.spawn(entity)
        before = entity.to_dict()

        restored_components = pickle.loads(pickle.dumps(entity.extra_components))
        payload = pickle.dumps(entity)
        restored = pickle.loads(payload)

        self.assertIs(type(restored_components), dict)
        self.assertEqual(restored_components, {"packed_kinematic": packed})
        self.assertNotIn(b"GameWorld3D", payload)
        self.assertEqual(restored.to_dict(), before)
        self.assertNotIn("_component_owner", restored.__dict__)
        self.assertNotIn("_component_pool_id", restored.__dict__)
        self.assertIsInstance(restored.extra_components, dict)
        self.assertEqual(restored.extra_components["packed_kinematic"], packed)
        restored.position = (5.0, 6.0, 7.0)
        self.assertEqual(entity.position, (1.0, 2.0, 3.0))
        second = GameWorld3D()
        second.spawn(restored)
        self.assertEqual(second.require("actor").position, (5.0, 6.0, 7.0))

    def test_pickle_world_relinks_entities_and_sparse_views(self) -> None:
        world = GameWorld3D()
        world.spawn(_entity(extra_components={"custom": {"numbers": [1, 2]}}))
        source_plan = world.compile_query("transform", "custom")

        restored = pickle.loads(pickle.dumps(world))
        restored_entity = restored.require("actor")
        restored_plan = restored.compile_query("transform", "custom")

        self.assertEqual(restored.snapshot(), world.snapshot())
        self.assertIs(restored_entity.__dict__["_component_owner"], restored)
        self.assertIs(restored_plan._world, restored)
        self.assertIsNot(restored_plan, source_plan)
        restored_entity.position = (7.0, 8.0, 9.0)
        restored_entity.extra_components["custom"]["numbers"].append(3)
        self.assertEqual(restored._transform_components["actor"].position, (7.0, 8.0, 9.0))
        self.assertEqual(world.require("actor").position, (1.0, 2.0, 3.0))
        self.assertEqual(
            world.require("actor").extra_components["custom"], {"numbers": [1, 2]}
        )

    def test_spawn_failure_restores_detached_entity_and_all_pools(self) -> None:
        entity = _entity(extra_components={"first": 1, "second": 2})
        before = entity.to_dict()
        original_extra_components = entity.extra_components
        world = GameWorld3D()
        original_set = world._set_sparse_component

        def fail_on_second(entity_id: str, name: str, component: object) -> None:
            if name == "second":
                raise RuntimeError("injected sparse failure")
            original_set(entity_id, name, component)

        world._set_sparse_component = fail_on_second  # type: ignore[method-assign]
        with self.assertRaisesRegex(RuntimeError, "injected sparse failure"):
            world.spawn(entity)

        self.assertEqual(entity.to_dict(), before)
        self.assertIs(entity.extra_components, original_extra_components)
        self.assertNotIn("_component_owner", entity.__dict__)
        self.assertNotIn("_component_pool_id", entity.__dict__)
        self.assertIn("position", entity.__dict__)
        self.assertIn("velocity", entity.__dict__)
        self.assertIn("collider", entity.__dict__)
        self.assertIn("mesh_id", entity.__dict__)
        self.assertNotIn("actor", world.entities)
        self.assertEqual(world._ordered_entity_ids, [])
        self.assertEqual(world._transform_components, {})
        self.assertEqual(world._body_components, {})
        self.assertEqual(world._collider_components, {})
        self.assertEqual(world._render_components, {})
        self.assertEqual(world._sparse_components, {})
        self.assertEqual(world._sparse_component_order, {})


if __name__ == "__main__":
    unittest.main()
