import base64
from dataclasses import replace
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "src"))

from ugts_kc3 import *


def triangle_mesh():
    return Mesh(
        ((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
        ((0, 1, 2),),
        ((0.0, 0.0, 1.0),) * 3,
        ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
    )


def simple_scene():
    scene = Scene()
    scene.add_asset(Asset("tri", triangle_mesh(), material_id="mat", source_pattern_id="M210"))
    scene.add_node(SceneNode("root", asset_id="tri", tags=frozenset({"interactive"})))
    return scene


class Math3DTests(unittest.TestCase):
    def test_vector_cross(self):
        self.assertEqual(cross((1, 0, 0), (0, 1, 0)), (0, 0, 1))
        self.assertEqual(add((1, 2, 3), (3, 2, 1)), (4, 4, 4))

    def test_quaternion_two_vectors(self):
        q = quat_from_two_vectors((1, 0, 0), (0, 1, 0))
        v = quat_rotate(q, (1, 0, 0))
        self.assertAlmostEqual(v[0], 0.0, places=8)
        self.assertAlmostEqual(v[1], 1.0, places=8)

    def test_opposite_vector_rotation(self):
        q = quat_from_two_vectors((1, 0, 0), (-1, 0, 0))
        v = quat_rotate(q, (1, 0, 0))
        self.assertAlmostEqual(v[0], -1.0, places=8)

    def test_signed_twist(self):
        q = quat_from_axis_angle((0, 0, 1), 0.75)
        self.assertAlmostEqual(signed_twist_angle(q, (0, 0, 1)), 0.75, places=8)

    def test_compose_trs(self):
        m = compose_trs((1, 2, 3), quat_from_axis_angle((0, 0, 1), math.pi / 2), 2)
        p = transform_point(m, (1, 0, 0))
        self.assertAlmostEqual(p[0], 1.0, places=8)
        self.assertAlmostEqual(p[1], 4.0, places=8)
        self.assertAlmostEqual(p[2], 3.0, places=8)

    def test_rigid_inverse(self):
        m = compose_trs((1, 2, 3), quat_from_axis_angle((0, 1, 0), 0.5), 1.0)
        inv = rigid_inverse(m)
        p = transform_point(inv, transform_point(m, (0.2, -0.5, 1.1)))
        self.assertLess(distance(p, (0.2, -0.5, 1.1)), 1e-8)

    def test_quat_nlerp_endpoints(self):
        a = (1, 0, 0, 0)
        b = quat_from_axis_angle((0, 0, 1), 1.0)
        self.assertEqual(quat_nlerp(a, b, 0), a)
        self.assertTrue(all(abs(x-y) < 1e-9 for x, y in zip(quat_nlerp(a, b, 1), b)))

    def test_column_major_flatten(self):
        m = mat4_translation((1, 2, 3))
        flat = flatten_column_major(m)
        self.assertEqual(flat[12:15], [1, 2, 3])

    def test_finite_matrix(self):
        self.assertTrue(finite_matrix(mat4_identity()))
        bad = list(map(list, mat4_identity()))
        bad[0][0] = float("inf")
        self.assertFalse(finite_matrix(bad))


class GeometryCompilerTests(unittest.TestCase):
    def test_bezier_endpoints(self):
        p0, p1, p2, p3 = (0, 0, 0), (1, 2, 0), (2, 2, 0), (3, 0, 0)
        self.assertEqual(cubic_bezier_point(p0, p1, p2, p3, 0), p0)
        self.assertEqual(cubic_bezier_point(p0, p1, p2, p3, 1), p3)

    def test_adaptive_bezier(self):
        pts = adaptive_cubic_bezier((0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0), tolerance=0.01)
        self.assertGreater(len(pts), 4)
        self.assertEqual(pts[0], (0.0, 0.0, 0.0))
        self.assertEqual(pts[-1], (1.0, 0.0, 0.0))

    def test_resample_polyline(self):
        pts = resample_polyline([(0, 0, 0), (2, 0, 0)], 5)
        self.assertEqual(pts[2], (1.0, 0.0, 0.0))
        self.assertAlmostEqual(polyline_length(pts), 2.0)

    def test_parallel_frames(self):
        frames = parallel_transport_frames([(0, 0, 0), (1, 0, 0), (2, 0.2, 0.1)])
        self.assertEqual(len(frames), 3)
        for t, n, b in frames:
            self.assertAlmostEqual(dot(t, n), 0.0, places=8)
            self.assertAlmostEqual(dot(t, b), 0.0, places=8)

    def test_tube_counts(self):
        mesh = tube_mesh([(0, 0, 0), (0, 0, 1), (0.3, 0, 2)], 0.1, 8, cap=True)
        self.assertEqual(mesh.vertex_count, 26)
        self.assertEqual(mesh.triangle_count, 48)

    def test_stroke_mesh(self):
        mesh = stroke_polyline_2d([(0, 0), (1, 0), (1, 1)], width=0.1)
        self.assertEqual(mesh.vertex_count, 6)
        self.assertEqual(mesh.triangle_count, 4)

    def test_fill_rules(self):
        square = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
        self.assertTrue(point_in_polygon((0, 0), square, "even-odd"))
        self.assertTrue(point_in_polygon((0, 0), square, "nonzero"))
        self.assertFalse(point_in_polygon((2, 0), square, "even-odd"))

    def test_marching_sphere(self):
        field = lambda p: math.sqrt(sum(v*v for v in p)) - 0.7
        mesh = marching_tetrahedra(field, (-1, -1, -1), (1, 1, 1), (7, 7, 7))
        self.assertGreater(mesh.vertex_count, 50)
        self.assertGreater(mesh.triangle_count, 20)

    def test_marching_normals_finite(self):
        field = lambda p: p[0] * p[0] + p[1] * p[1] + p[2] * p[2] - 0.5
        mesh = marching_tetrahedra(field, (-1, -1, -1), (1, 1, 1), (6, 6, 6))
        self.assertTrue(all(abs(norm(n) - 1.0) < 1e-6 for n in mesh.normals))

    def test_transform_mesh(self):
        mesh = transform_mesh(triangle_mesh(), mat4_translation((2, 3, 4)))
        self.assertEqual(mesh.vertices[0], (2.0, 3.0, 4.0))

    def test_merge_meshes(self):
        merged = merge_meshes([triangle_mesh(), transform_mesh(triangle_mesh(), mat4_translation((2, 0, 0)))])
        self.assertEqual(merged.vertex_count, 6)
        self.assertEqual(merged.triangle_count, 2)

    def test_lod(self):
        tube = tube_mesh([(0, 0, 0), (0, 0, 1), (0, 0, 2)], 0.2, 12)
        lod = mesh_lod(tube, 0.25)
        self.assertLess(lod.triangle_count, tube.triangle_count)
        self.assertFalse(lod.metadata["topology_preserved"])

    def test_aabb_proxy(self):
        proxy = aabb_proxy(triangle_mesh())
        self.assertEqual(proxy.vertex_count, 8)
        self.assertEqual(proxy.triangle_count, 12)

    def test_screen_error(self):
        self.assertAlmostEqual(screen_space_error(0.01, 2.0, 1000), 5.0)

    def test_error_contract_validation(self):
        GeometryErrorContract(0.1, 0.1, 1.0, 5.0, True).validate()
        with self.assertRaises(ValueError):
            GeometryErrorContract(-1, 0, 0, 0).validate()


class SpatialTests(unittest.TestCase):
    def test_aabb_intersection(self):
        a = AABB((0, 0, 0), (1, 1, 1))
        b = AABB((0.5, 0.5, 0.5), (2, 2, 2))
        self.assertTrue(a.intersects(b))
        self.assertTrue(a.contains((0.2, 0.2, 0.2)))

    def test_aabb_union(self):
        a = AABB((0, 0, 0), (1, 1, 1)).union(AABB((-2, 0, 0), (0, 3, 1)))
        self.assertEqual(a.minimum, (-2, 0, 0))
        self.assertEqual(a.maximum, (1, 3, 1))

    def test_aabb_transform(self):
        box = AABB((0, 0, 0), (1, 1, 1)).transformed(mat4_translation((2, 3, 4)))
        self.assertEqual(box.minimum, (2.0, 3.0, 4.0))

    def test_ray_interval(self):
        box = AABB((0, 0, 0), (1, 1, 1))
        hit = box.ray_interval((-1, 0.5, 0.5), (1, 0, 0))
        self.assertEqual(hit, (1.0, 2.0))
        self.assertIsNone(box.ray_interval((-1, 2, 0), (1, 0, 0)))

    def test_bvh_queries(self):
        bvh = BVH([
            ("a", AABB((0, 0, 0), (1, 1, 1))),
            ("b", AABB((3, 0, 0), (4, 1, 1))),
            ("c", AABB((0, 3, 0), (1, 4, 1))),
        ], leaf_size=1)
        self.assertEqual(bvh.query_aabb(AABB((-1, -1, -1), (1.5, 1.5, 1.5))), ("a",))
        self.assertEqual(bvh.query_ray((-2, 0.5, 0.5), (1, 0, 0))[0][0], "a")

    def test_support_aware_query(self):
        bvh = BVH([("a", AABB((0, 0, 0), (1, 1, 1))), ("b", AABB((0, 0, 0), (1, 1, 1)))])
        result = bvh.support_aware_query(AABB((0, 0, 0), (1, 1, 1)), lambda item: item == "b")
        self.assertEqual(result, ("b",))

    def test_frustum_query(self):
        # Axis-aligned cube frustum -1..1.
        planes = [((1,0,0),1), ((-1,0,0),1), ((0,1,0),1), ((0,-1,0),1), ((0,0,1),1), ((0,0,-1),1)]
        bvh = BVH([("inside", AABB((-0.2,-0.2,-0.2),(0.2,0.2,0.2))), ("outside", AABB((3,3,3),(4,4,4)))])
        self.assertEqual(bvh.query_frustum(planes), ("inside",))

    def test_streaming_cells(self):
        cells = cells_for_aabb(AABB((0.1, 0.1, 0.1), (2.1, 0.9, 0.9)), 1.0)
        self.assertEqual(cells, ((0,0,0),(1,0,0),(2,0,0)))

    def test_interest_set(self):
        entries = [
            ("a", AABB((0,0,0),(1,1,1)), {"player"}),
            ("b", AABB((0,0,0),(1,1,1)), {"npc"}),
        ]
        self.assertEqual(interest_set(entries, (0,0,0), 2, {"player"}), ("a",))

    def test_cull_reason(self):
        planes = [((1,0,0),1), ((-1,0,0),1), ((0,1,0),1), ((0,-1,0),1), ((0,0,1),1), ((0,0,-1),1)]
        result = classify_culling("a", AABB((0,0,0),(0.5,0.5,0.5)), planes, True, False)
        self.assertEqual(result.reason, "incompatible")


class SceneTests(unittest.TestCase):
    def test_asset_hash_stable(self):
        a = Asset("a", triangle_mesh())
        self.assertEqual(a.content_hash(), a.content_hash())
        self.assertEqual(len(a.content_hash()), 64)

    def test_instances(self):
        scene = simple_scene()
        scene.add_node(SceneNode("copy", asset_id="tri", local_transform=mat4_translation((2,0,0))))
        self.assertEqual(scene.instances("tri"), ("copy", "root"))

    def test_parent_world_transform(self):
        scene = Scene()
        scene.add_asset(Asset("tri", triangle_mesh()))
        scene.add_node(SceneNode("parent", local_transform=mat4_translation((1,0,0))))
        scene.add_node(SceneNode("child", asset_id="tri", parent_id="parent", local_transform=mat4_translation((0,2,0))))
        self.assertEqual(matrix_translation(scene.world_transform("child")), (1.0,2.0,0.0))

    def test_cycle_rejected(self):
        scene = Scene()
        scene.add_node(SceneNode("a"))
        scene.add_node(SceneNode("b", parent_id="a"))
        with self.assertRaises(ValueError):
            scene.set_parent("a", "b")

    def test_layer_composition(self):
        scene = simple_scene()
        scene.add_layer(SceneLayer("hide", {"root": {"visible": False}}))
        self.assertFalse(scene.composed_node("root").visible)

    def test_serialization_roundtrip(self):
        scene = simple_scene()
        scene2 = Scene.from_dict(scene.to_dict())
        self.assertEqual(scene.content_hash(), scene2.content_hash())

    def test_scene_bounds(self):
        scene = simple_scene()
        box = scene.scene_bounds()
        self.assertEqual(box.minimum, (0.0,0.0,0.0))
        self.assertEqual(box.maximum, (1.0,1.0,0.0))

    def test_migration(self):
        scene = simple_scene()
        scene.migrate("3.0.1", "test migration")
        self.assertEqual(scene.metadata.schema_version, "3.0.1")
        self.assertEqual(scene.migration_history[-1]["from"], "3.0.0")

    def test_unknown_asset_rejected(self):
        with self.assertRaises(KeyError):
            Scene().add_node(SceneNode("x", asset_id="missing"))


class MaterialTests(unittest.TestCase):
    def test_material_validation(self):
        PBRMaterial("m").validate()
        with self.assertRaises(ValueError):
            PBRMaterial("m", metallic=2).validate()

    def test_srgb_roundtrip(self):
        c = (0.2, 0.5, 0.8)
        out = linear_to_srgb(srgb_to_linear(c))
        self.assertLess(max(abs(a-b) for a,b in zip(c,out)), 1e-8)

    def test_tone_map(self):
        self.assertLess(tone_map((10,10,10), "reinhard")[0], 1)
        self.assertTrue(all(0 <= x <= 1 for x in tone_map((10,2,0.2), "aces-fitted")))

    def test_preview_shade(self):
        c = shade_lambert(PBRMaterial("m", (1,0,0,1)), (0,0,1), (0,0,-1))
        self.assertGreater(c[0], c[1])

    def test_material_graph(self):
        graph = MaterialGraph()
        graph.add_node("p", "pattern", {"name": "phase"})
        graph.add_node("two", "constant", {"value": 2.0})
        graph.add_node("mul", "multiply", {"a": "$p", "b": "$two"})
        graph.set_output("mul")
        self.assertEqual(graph.evaluate({"phase": 0.25}), 0.5)

    def test_material_graph_cycle(self):
        graph = MaterialGraph()
        graph.add_node("a", "add", {"a": "$b", "b": 1})
        graph.add_node("b", "add", {"a": "$a", "b": 1})
        graph.set_output("a")
        with self.assertRaises(ValueError):
            graph.evaluate({})


class HandInteractionTests(unittest.TestCase):
    def test_pinch_hysteresis(self):
        detector = PinchDetector("left", 0.02, 0.04)
        p1 = emulate_hand_from_cursor("left", (0,0), True, 0)
        p2 = HandPose("left", (0,0,0), joints={"thumb_tip":(-0.015,0,0),"index_tip":(0.015,0,0)}, timestamp=1)
        p3 = emulate_hand_from_cursor("left", (0,0), False, 2)
        self.assertTrue(detector.update(p1).active)
        self.assertTrue(detector.update(p2).active)
        self.assertFalse(detector.update(p3).active)

    def test_pinch_tracking_reject(self):
        d = PinchDetector("right")
        pose = HandPose("right", (0,0,0), tracked=False)
        self.assertEqual(d.update(pose).reason, "tracking_unavailable")

    def test_bimanual_scale_translation(self):
        left0 = HandPose("left", (-1,0,0))
        right0 = HandPose("right", (1,0,0))
        anchor = BimanualAnchor(left0, right0, mat4_identity())
        result = compute_bimanual_transform(anchor, HandPose("left", (-1,1,0)), HandPose("right", (3,1,0)))
        self.assertAlmostEqual(result.scale, 2.0)
        self.assertEqual(result.translation, (1.0,1.0,0.0))
        self.assertEqual(result.status, "ok")

    def test_bimanual_rotation(self):
        anchor = BimanualAnchor(HandPose("left", (-1,0,0)), HandPose("right", (1,0,0)), mat4_identity())
        result = compute_bimanual_transform(anchor, HandPose("left", (0,-1,0)), HandPose("right", (0,1,0)))
        p = transform_point(result.world_transform, (1,0,0))
        self.assertAlmostEqual(p[0], 0.0, places=7)
        self.assertAlmostEqual(p[1], 1.0, places=7)

    def test_bimanual_tracking_reject(self):
        anchor = BimanualAnchor(HandPose("left", (-1,0,0)), HandPose("right", (1,0,0)), mat4_identity())
        result = compute_bimanual_transform(anchor, HandPose("left", (-1,0,0), tracked=False), HandPose("right", (1,0,0)))
        self.assertEqual(result.status, "tracking_rejected")

    def test_cooperative_handover(self):
        grab = CooperativeGrab("obj")
        self.assertEqual(grab.update(True, False, 0)[0].event_type, "grab_start")
        self.assertEqual(grab.update(True, True, 1)[0].event_type, "second_hand_join")
        event = grab.update(False, True, 2)[0]
        self.assertEqual(event.event_type, "handover")
        self.assertEqual(event.hands, ("right",))

    def test_desktop_emulation(self):
        pose = emulate_hand_from_cursor("right", (2,3), True)
        self.assertEqual(pose.source, "desktop_emulation")
        self.assertLess(pose.pinch_distance(), 0.02)


class RuntimeReplayExportTests(unittest.TestCase):
    def test_proposal_verification(self):
        p = EventProposal("p", 0, "custom", "x", {}, support_ok=False)
        self.assertEqual(p.verified()[1], "outside_support")

    def test_runtime_set_transform(self):
        runtime = KCRuntime(simple_scene())
        target = mat4_translation((2,0,0))
        event = runtime.commit_proposals([EventProposal("p", 0, "set_transform", "root", {"transform": target}, lineage_label="move")])[0]
        self.assertEqual(matrix_translation(runtime.scene.nodes["root"].local_transform), (2.0,0.0,0.0))
        self.assertEqual(event.lineage, ("move",))

    def test_conflict_resolution(self):
        runtime = KCRuntime(simple_scene())
        a = EventProposal("a", 0, "set_visibility", "root", {"visible": False, "field": "visible"}, priority=2)
        b = EventProposal("b", 0, "set_visibility", "root", {"visible": True, "field": "visible"}, priority=1)
        committed = runtime.commit_proposals([b,a])
        self.assertEqual(len(committed), 1)
        self.assertFalse(runtime.scene.nodes["root"].visible)
        self.assertEqual(runtime.metrics.conflicts, 1)

    def test_fixed_step_system(self):
        runtime = KCRuntime(simple_scene(), fixed_dt=0.5)
        def system(rt, t0, t1):
            if rt.tick == 1:
                return [EventProposal("hide", t1, "set_visibility", "root", {"visible": False})]
            return []
        runtime.add_system(system)
        runtime.step(2)
        self.assertEqual(runtime.tick, 2)
        self.assertFalse(runtime.scene.nodes["root"].visible)

    def test_snapshot_roundtrip(self):
        runtime = KCRuntime(simple_scene())
        runtime.commit_proposals([EventProposal("p", 0, "custom", "root", {"note":"x"})])
        clone = KCRuntime.from_snapshot(runtime.snapshot())
        self.assertEqual(runtime.state_hash(), clone.state_hash())

    def test_checkpoint(self):
        runtime = KCRuntime(simple_scene())
        cp = checkpoint_runtime(runtime)
        self.assertTrue(verify_checkpoint(cp))
        self.assertEqual(cp.sequence, 0)

    def test_replay_matches(self):
        initial = simple_scene()
        runtime = KCRuntime(initial.clone())
        runtime.commit_proposals([
            EventProposal("m1", 0, "set_transform", "root", {"transform": mat4_translation((1,0,0))}, lineage_label="m1"),
            EventProposal("m2", 0.1, "set_visibility", "root", {"visible": False}, lineage_label="m2"),
        ])
        replayed, divergence = replay_events(initial, runtime.events)
        self.assertIsNone(divergence)
        self.assertEqual(replayed.state_hash(), runtime.state_hash())

    def test_replay_detects_divergence(self):
        initial = simple_scene()
        runtime = KCRuntime(initial.clone())
        runtime.commit_proposals([EventProposal("m1", 0, "set_visibility", "root", {"visible": False})])
        bad = replace(runtime.events[0], post_state_hash="0"*64)
        _, divergence = replay_events(initial, [bad])
        self.assertIsNotNone(divergence)

    def test_replay_log(self):
        initial = simple_scene()
        runtime = KCRuntime(initial.clone())
        runtime.commit_proposals([EventProposal("m1", 0, "set_visibility", "root", {"visible": False})])
        log = ReplayLog(initial)
        log.append(runtime.events[0])
        rebuilt, divergence = log.reconstruct()
        self.assertIsNone(divergence)
        self.assertFalse(rebuilt.scene.nodes["root"].visible)

    def test_gltf_export(self):
        scene = simple_scene()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"scene.gltf"
            gltf = write_gltf(scene, path, {"mat": PBRMaterial("mat")})
            loaded = json.loads(path.read_text())
            self.assertEqual(loaded["asset"]["version"], "2.0")
            encoded = loaded["buffers"][0]["uri"].split(",",1)[1]
            self.assertEqual(len(base64.b64decode(encoded)), loaded["buffers"][0]["byteLength"])
            self.assertEqual(gltf["nodes"][0]["mesh"], 0)

    def test_usda_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"scene.usda"
            write_usda(simple_scene(), path)
            text = path.read_text()
            self.assertIn("#usda 1.0", text)
            self.assertIn('def Mesh "Geometry"', text)

    def test_svg_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"preview.svg"
            result = render_scene_svg(simple_scene(), path, {"mat": PBRMaterial("mat")})
            self.assertEqual(result.visible_nodes, 1)
            self.assertIn("<polygon", path.read_text())

    def test_scene_diagnostics(self):
        report = audit_scene(simple_scene())
        self.assertTrue(report.passed)
        self.assertEqual(report.metrics["asset_count"], 1)

    def test_runtime_diagnostics(self):
        runtime = KCRuntime(simple_scene())
        runtime.commit_proposals([EventProposal("p", 0, "custom", "root", {})])
        report = runtime_report(runtime)
        self.assertEqual(report.metrics["event_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
