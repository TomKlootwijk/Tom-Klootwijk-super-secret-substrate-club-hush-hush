from __future__ import annotations

from dataclasses import replace
import math
import unittest

from ugts_kc3.animation3d import TransformAnimation3D, TransformKey3D
from ugts_kc3.hierarchy3d import (
    Hierarchy3DError,
    MAX_HIERARCHY_DEPTH_3D,
    TransformTRS3D,
    build_hierarchy3d,
    compose_world_trs_3d,
    hierarchy_issues3d,
    local_transform_for_parent_3d,
    local_trs_from_world_3d,
    remove_node3d_promote_children,
    reparent_node3d,
    world_trs_by_id,
)
from ugts_kc3.math3d import matrix_translation, quat_from_axis_angle
from ugts_kc3.mobile3d import (
    Collider3DRecord,
    Mobile3DProject,
    Node3DRecord,
    Transform3DRecord,
)
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph


def _node(
    node_id: str,
    parent_id: str | None = None,
    *,
    translation=(0.0, 0.0, 0.0),
    rotation=(1.0, 0.0, 0.0, 0.0),
    scale=(1.0, 1.0, 1.0),
    **changes,
) -> Node3DRecord:
    return Node3DRecord(
        node_id,
        "cube",
        "accent",
        Transform3DRecord(translation, rotation, scale),
        parent_id=parent_id,
        **changes,
    )


def _project(*nodes: Node3DRecord) -> Mobile3DProject:
    project = blank_mobile3d_project()
    project.nodes = tuple(nodes)
    return project


class HierarchyGraphTests(unittest.TestCase):
    def test_canonical_maps_depth_and_order(self):
        nodes = (
            _node("z_child", "root"),
            _node("other"),
            _node("root"),
            _node("a_child", "root"),
            _node("grandchild", "a_child"),
        )
        hierarchy = build_hierarchy3d(nodes)
        self.assertEqual(hierarchy.roots, ("other", "root"))
        self.assertEqual(hierarchy.children("root"), ("a_child", "z_child"))
        self.assertEqual(
            hierarchy.topological_order,
            ("other", "root", "a_child", "grandchild", "z_child"),
        )
        self.assertEqual(hierarchy.depth("grandchild"), 2)
        self.assertEqual(
            hierarchy.descendants("root"),
            ("a_child", "grandchild", "z_child"),
        )
        self.assertTrue(hierarchy.is_descendant("grandchild", "root"))
        self.assertFalse(hierarchy.is_descendant("root", "root"))

    def test_missing_parent_and_cycle_are_rejected(self):
        with self.assertRaises(Hierarchy3DError) as missing:
            build_hierarchy3d((_node("child", "missing"),))
        self.assertEqual(missing.exception.code, "parent_missing")

        with self.assertRaises(Hierarchy3DError) as cycle:
            build_hierarchy3d((_node("a", "b"), _node("b", "a")))
        self.assertEqual(cycle.exception.code, "cycle")

    def test_depth_eight_is_allowed_and_nine_is_rejected(self):
        allowed = tuple(
            _node(f"n{index}", None if index == 0 else f"n{index - 1}")
            for index in range(MAX_HIERARCHY_DEPTH_3D + 1)
        )
        self.assertEqual(
            build_hierarchy3d(allowed).depth(f"n{MAX_HIERARCHY_DEPTH_3D}"),
            MAX_HIERARCHY_DEPTH_3D,
        )
        rejected = allowed + (
            _node(
                f"n{MAX_HIERARCHY_DEPTH_3D + 1}",
                f"n{MAX_HIERARCHY_DEPTH_3D}",
            ),
        )
        self.assertIn("depth", {issue.code for issue in hierarchy_issues3d(rejected)})

    def test_first_slice_child_capabilities_are_bounded(self):
        root = _node("root")
        child = _node("child", "root")
        cases = {
            "child_dynamic": replace(child, dynamic=True),
            "child_collider": replace(
                child, collider=Collider3DRecord("sphere", radius=0.5)
            ),
            "child_tags": replace(child, tags=("decorative",)),
            "child_angular_velocity": replace(
                child, angular_velocity=(0.0, 1.0, 0.0)
            ),
            "child_visual_graph": replace(
                child, metadata={"visual_graph": "child_logic"}
            ),
            "child_packed_movement": replace(
                child, metadata={"packed_kinematic": {}}
            ),
            "child_population": replace(
                child, metadata={"scatter_population": {}}
            ),
            "child_transform_animation": replace(
                child, metadata={"transform_animation": {}}
            ),
        }
        for expected, candidate in cases.items():
            with self.subTest(expected=expected):
                codes = {issue.code for issue in hierarchy_issues3d((root, candidate))}
                self.assertIn(expected, codes)

    def test_every_parent_needs_uniform_positive_authored_scale(self):
        issues = hierarchy_issues3d(
            (_node("root", scale=(1.0, 2.0, 1.0)), _node("child", "root"))
        )
        self.assertIn("parent_scale", {issue.code for issue in issues})
        issues = hierarchy_issues3d(
            (_node("root", scale=(-1.0, -1.0, -1.0)), _node("child", "root"))
        )
        self.assertIn("parent_scale", {issue.code for issue in issues})


class HierarchyMathTests(unittest.TestCase):
    def assertTupleAlmostEqual(self, first, second, places=7):
        self.assertEqual(len(first), len(second))
        for left, right in zip(first, second):
            self.assertAlmostEqual(left, right, places=places)

    def test_compose_and_inverse_roundtrip(self):
        parent = TransformTRS3D(
            (10.0, 2.0, -3.0),
            quat_from_axis_angle((0.0, 1.0, 0.0), math.pi / 2.0),
            (2.0, 2.0, 2.0),
        )
        local = TransformTRS3D(
            (1.0, 3.0, 0.0),
            quat_from_axis_angle((1.0, 0.0, 0.0), math.pi / 4.0),
            (0.5, 1.0, 1.5),
        )
        world = compose_world_trs_3d(parent, local)
        restored = local_trs_from_world_3d(parent, world)
        alias_restored = local_transform_for_parent_3d(world, parent)
        self.assertTupleAlmostEqual(restored.translation, local.translation)
        self.assertTupleAlmostEqual(restored.rotation, local.rotation)
        self.assertTupleAlmostEqual(restored.scale, local.scale)
        self.assertEqual(alias_restored, restored)

    def test_nonuniform_or_negative_parent_scale_is_never_approximated(self):
        local = TransformTRS3D()
        for unsafe in ((1.0, 2.0, 1.0), (-1.0, -1.0, -1.0)):
            with self.subTest(scale=unsafe):
                with self.assertRaisesRegex(ValueError, "uniform and positive"):
                    compose_world_trs_3d(TransformTRS3D(scale=unsafe), local)
                with self.assertRaisesRegex(ValueError, "uniform and positive"):
                    local_trs_from_world_3d(TransformTRS3D(scale=unsafe), local)

    def test_world_lookup_composes_multiple_levels(self):
        nodes = (
            _node("leaf", "middle", translation=(0.0, 0.0, 3.0)),
            _node("root", translation=(10.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0)),
            _node("middle", "root", translation=(1.0, 0.0, 0.0)),
        )
        worlds = world_trs_by_id(nodes)
        self.assertTupleAlmostEqual(worlds["middle"].translation, (12.0, 0.0, 0.0))
        self.assertTupleAlmostEqual(worlds["leaf"].translation, (12.0, 0.0, 6.0))


class HierarchyMutationTests(unittest.TestCase):
    def assertTrsAlmostEqual(self, first, second):
        for left, right in zip(first.translation, second.translation):
            self.assertAlmostEqual(left, right)
        for left, right in zip(first.rotation, second.rotation):
            self.assertAlmostEqual(left, right)
        for left, right in zip(first.scale, second.scale):
            self.assertAlmostEqual(left, right)

    def test_reparent_preserves_world_pose_and_rejects_cycles(self):
        nodes = (
            _node("a", translation=(10.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0)),
            _node("b", translation=(-4.0, 0.0, 0.0)),
            _node("child", "a", translation=(1.0, 2.0, 3.0)),
        )
        before = world_trs_by_id(nodes)["child"]
        changed = reparent_node3d(nodes, "child", "b")
        after = world_trs_by_id(changed)["child"]
        self.assertTrsAlmostEqual(before, after)
        self.assertEqual(next(node for node in changed if node.id == "child").parent_id, "b")

        chain = (_node("root"), _node("child", "root"), _node("leaf", "child"))
        with self.assertRaises(Hierarchy3DError):
            reparent_node3d(chain, "root", "leaf")

    def test_delete_promotes_direct_children_without_world_jump(self):
        nodes = (
            _node("root", translation=(5.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0)),
            _node("middle", "root", translation=(1.0, 0.0, 0.0)),
            _node("leaf", "middle", translation=(0.0, 3.0, 0.0)),
        )
        before = world_trs_by_id(nodes)["leaf"]
        changed = remove_node3d_promote_children(nodes, "middle")
        leaf = next(node for node in changed if node.id == "leaf")
        self.assertEqual(leaf.parent_id, "root")
        self.assertTrsAlmostEqual(before, world_trs_by_id(changed)["leaf"])

    def test_authorization_hook_blocks_cross_owner_reparent(self):
        nodes = (_node("root"), _node("child"))
        with self.assertRaises(PermissionError):
            reparent_node3d(
                nodes,
                "child",
                "root",
                allow=lambda node_id, parent_id: False,
            )


class MobileProjectHierarchyTests(unittest.TestCase):
    def assertTupleAlmostEqual(self, first, second, places=7):
        self.assertEqual(len(first), len(second))
        for left, right in zip(first, second):
            self.assertAlmostEqual(left, right, places=places)

    def test_parentless_record_dictionary_and_project_hash_stay_compatible(self):
        project = blank_mobile3d_project()
        original_hash = project.content_hash()
        self.assertTrue(all("parent_id" not in node.to_dict() for node in project.nodes))
        rebuilt = Mobile3DProject.from_dict(project.to_dict())
        self.assertEqual(rebuilt.content_hash(), original_hash)
        self.assertTrue(all(node.parent_id is None for node in rebuilt.nodes))

    def test_project_json_roundtrip_reads_parent_id(self):
        project = _project(_node("root"), _node("child", "root"))
        data = project.to_dict()
        self.assertEqual(data["nodes"][1]["parent_id"], "root")
        rebuilt = Mobile3DProject.from_dict(data)
        self.assertEqual(rebuilt.nodes[1].parent_id, "root")

    def test_project_validation_reports_precise_hierarchy_path(self):
        project = _project(_node("child", "missing"))
        report = project.validate(raise_on_error=False)
        issue = next(issue for issue in report.issues if issue.code == "hierarchy.parent_missing")
        self.assertEqual(issue.path, "nodes[0].parent_id")
        with self.assertRaises(ValueError):
            project.validate()

    def test_parent_animation_must_keep_scale_uniform_positive(self):
        unsafe = TransformAnimation3D(
            1.0,
            (
                TransformKey3D(0.0),
                TransformKey3D(1.0, scale=(2.0, 1.0, 1.0)),
            ),
        )
        root = _node("root", metadata={"transform_animation": unsafe.to_dict()})
        project = _project(root, _node("child", "root"))
        report = project.validate(raise_on_error=False)
        self.assertIn(
            "hierarchy.parent_animation_scale",
            {issue.code for issue in report.issues},
        )

        safe = TransformAnimation3D(
            1.0,
            (
                TransformKey3D(0.0),
                TransformKey3D(1.0, scale=(2.0, 2.0, 2.0)),
            ),
        )
        safe_project = _project(
            _node("root", metadata={"transform_animation": safe.to_dict()}),
            _node("child", "root"),
        )
        self.assertTrue(safe_project.validate(raise_on_error=False).passed)

    def test_parent_graph_scale_write_must_prove_uniform_positive_result(self):
        def bound_project(graph):
            project = _project(
                replace(_node("root"), metadata={"visual_graph": graph.id}),
                _node("child", "root"),
            )
            project.metadata = {"visual_graphs": [graph.to_dict()]}
            return project

        def project_with_scale(value):
            graph = VisualGraph(
                "resize_parent",
                (
                    GraphNode("ready", "event.ready"),
                    GraphNode(
                        "resize",
                        "action.set_component",
                        {
                            "component": "transform",
                            "field": "scale",
                            "value": value,
                        },
                    ),
                ),
                (GraphLink("ready", "out", "resize", "in"),),
            )
            return bound_project(graph)

        unsafe = project_with_scale([1.0, 2.0, 1.0])
        report = unsafe.validate(raise_on_error=False)
        self.assertIn(
            "hierarchy.parent_graph_scale", {issue.code for issue in report.issues}
        )
        issue = next(
            issue
            for issue in report.issues
            if issue.code == "hierarchy.parent_graph_scale"
        )
        self.assertEqual(
            issue.path, "metadata.visual_graphs.resize_parent.nodes.resize"
        )
        with self.assertRaisesRegex(ValueError, "parent_graph_scale"):
            unsafe.instantiate_world()

        per_axis = bound_project(
            VisualGraph(
                "resize_one_axis",
                (
                    GraphNode("ready", "event.ready"),
                    GraphNode(
                        "resize",
                        "action.set_component",
                        {
                            "component": "transform",
                            "field": "scale.x",
                            "value": 2.0,
                        },
                    ),
                ),
                (GraphLink("ready", "out", "resize", "in"),),
            )
        )
        self.assertIn(
            "hierarchy.parent_graph_scale",
            {issue.code for issue in per_axis.validate(raise_on_error=False).issues},
        )

        whole_transform = bound_project(
            VisualGraph(
                "replace_transform",
                (
                    GraphNode("ready", "event.ready"),
                    GraphNode(
                        "replace",
                        "action.set_component",
                        {
                            "component": "transform",
                            "field": "",
                            "value": {"scale": [1.0, 2.0, 1.0]},
                        },
                    ),
                ),
                (GraphLink("ready", "out", "replace", "in"),),
            )
        )
        self.assertIn(
            "hierarchy.parent_graph_scale",
            {
                issue.code
                for issue in whole_transform.validate(raise_on_error=False).issues
            },
        )

        dynamic = bound_project(
            VisualGraph(
                "resize_from_state",
                (
                    GraphNode("ready", "event.ready"),
                    GraphNode(
                        "saved_scale",
                        "value.state",
                        {"key": "parent_scale", "default": [1.0, 1.0, 1.0]},
                    ),
                    GraphNode(
                        "resize",
                        "action.set_component",
                        {"component": "transform", "field": "scale"},
                    ),
                ),
                (
                    GraphLink("ready", "out", "resize", "in"),
                    GraphLink("saved_scale", "value", "resize", "value"),
                ),
            )
        )
        self.assertIn(
            "hierarchy.parent_graph_scale",
            {issue.code for issue in dynamic.validate(raise_on_error=False).issues},
        )

        safe = project_with_scale([2.0, 2.0, 2.0])
        self.assertTrue(safe.validate(raise_on_error=False).passed)
        world = safe.instantiate_world()
        self.assertEqual(world.require("root").scale, (2.0, 2.0, 2.0))
        self.assertEqual(world.require("child").scale, (2.0, 2.0, 2.0))

    def test_to_scene_retains_parent_local_transform_and_world_pose(self):
        root = _node("root", translation=(10.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0))
        child = _node("child", "root", translation=(1.0, 2.0, 3.0))
        scene = _project(child, root).to_scene()
        self.assertEqual(scene.nodes["child"].parent_id, "root")
        self.assertTupleAlmostEqual(
            matrix_translation(scene.nodes["child"].local_transform),
            child.transform.translation,
        )
        self.assertTupleAlmostEqual(
            matrix_translation(scene.world_transform("child")),
            (12.0, 4.0, 6.0),
        )

    def test_runtime_captures_local_pose_and_recomposes_after_late_writers(self):
        root = _node("root", translation=(1.0, 0.0, 0.0), scale=(2.0, 2.0, 2.0))
        child = _node("child", "root", translation=(1.0, 0.0, 0.0))
        world = _project(child, root).instantiate_world()
        self.assertIsNotNone(world.transform_hierarchy_system)
        self.assertIn(
            "transform_hierarchy_3d",
            {entry.name for entry in world._systems["late"]},
        )
        self.assertTupleAlmostEqual(world.require("child").position, (3.0, 0.0, 0.0))

        def last_writer(target_world, dt, frame):
            del dt, frame
            target_world.require("root").position = (10.0, 0.0, 0.0)
            # Child-local writes are not retained in this bounded slice.
            target_world.require("child").position = (999.0, 999.0, 999.0)

        world.add_system(
            last_writer,
            phase="late",
            priority=3_000_000_000,
            name="last_writer",
        )
        world.step()
        self.assertTupleAlmostEqual(world.require("child").position, (12.0, 0.0, 0.0))

    def test_runtime_rejects_a_graph_or_system_making_parent_scale_unsafe(self):
        world = _project(_node("root"), _node("child", "root")).instantiate_world()

        def unsafe_writer(target_world, dt, frame):
            del dt, frame
            target_world.require("root").scale = (1.0, 2.0, 1.0)

        world.add_system(
            unsafe_writer,
            phase="late",
            priority=3_000_000_000,
            name="unsafe_writer",
        )
        with self.assertRaisesRegex(ValueError, "uniform and positive"):
            world.step()

    def test_parentless_runtime_does_not_install_a_hierarchy_system(self):
        world = blank_mobile3d_project().instantiate_world()
        self.assertIsNone(world.transform_hierarchy_system)
        self.assertNotIn(
            "transform_hierarchy_3d",
            {entry.name for entry in world._systems["late"]},
        )


if __name__ == "__main__":
    unittest.main()
