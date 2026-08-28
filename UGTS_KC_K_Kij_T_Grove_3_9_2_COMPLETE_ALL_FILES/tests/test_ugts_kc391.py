from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import (
    PACK_MAGIC,
    build_android_project,
    compile_scene_pack_bytes,
    inspect_scene_pack,
    write_mobile3d_gltf,
)
from ugts_kc3.mobile3d import (
    AdaptiveQualityController3D,
    AndroidTargetProfile,
    Collider3DRecord,
    DeviceCapabilities3D,
    EntityState3D,
    GameWorld3D,
    InputFrame3D,
    Material3DRecord,
    Mobile3DProject,
    Node3DRecord,
    QualityTier3D,
    Transform3DRecord,
    World3DSettings,
    cube_mesh3d,
    plane_mesh3d,
    pyramid_mesh3d,
    select_device_profile,
    uv_sphere_mesh3d,
)
from ugts_kc3.templates3d import (
    blank_mobile3d_project,
    signature_android_targets,
    signature_quality_tiers,
    tom_signature_arena_project,
)
from ugts_kc3.version import __version__, __edition__


class Version391Tests(unittest.TestCase):
    def test_version(self):
        self.assertEqual(__version__, "3.9.1")
        self.assertIn("Tom Klootwijk Signature", __edition__)

    def test_root_imports(self):
        import ugts_kc3
        self.assertTrue(hasattr(ugts_kc3, "Mobile3DProject"))
        self.assertTrue(hasattr(ugts_kc3, "build_android_project"))

    def test_info_cli(self):
        env = dict(os.environ, PYTHONPATH=str(SRC))
        result = subprocess.run(
            [sys.executable, "-m", "ugts_kc3", "info"],
            cwd=ROOT, env=env, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("UGTS-KC 3.9.1", result.stdout)
        self.assertIn("4D: design-contract TODO only", result.stdout)


class Primitive391Tests(unittest.TestCase):
    def test_cube(self):
        mesh = cube_mesh3d(size=2)
        mesh.validate()
        self.assertEqual(len(mesh.vertices), 24)
        self.assertEqual(len(mesh.triangles), 12)

    def test_plane(self):
        mesh = plane_mesh3d(width=4, depth=6)
        self.assertEqual(mesh.vertices[0], (-2.0, 0, -3.0))
        self.assertEqual(len(mesh.triangles), 2)

    def test_pyramid(self):
        mesh = pyramid_mesh3d()
        mesh.validate()
        self.assertEqual(len(mesh.triangles), 6)

    def test_sphere(self):
        mesh = uv_sphere_mesh3d(segments=12, rings=8)
        mesh.validate()
        self.assertGreater(len(mesh.vertices), 100)
        self.assertGreater(len(mesh.triangles), 100)

    def test_bad_primitives(self):
        with self.assertRaises(ValueError):
            cube_mesh3d(size=0)
        with self.assertRaises(ValueError):
            uv_sphere_mesh3d(segments=2)


class Project391Tests(unittest.TestCase):
    def test_signature_metrics(self):
        report = tom_signature_arena_project().validate()
        self.assertEqual(report.metrics["node_count"], 66)
        self.assertEqual(report.metrics["mesh_count"], 4)
        self.assertEqual(report.metrics["target_profile_count"], 4)

    def test_blank_project(self):
        self.assertTrue(blank_mobile3d_project().validate().passed)

    def test_roundtrip(self):
        project = tom_signature_arena_project()
        clone = Mobile3DProject.from_dict(project.to_dict())
        self.assertEqual(clone.content_hash(), project.content_hash())

    def test_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = tom_signature_arena_project()
            path = project.write(Path(tmp) / "project.json")
            self.assertEqual(Mobile3DProject.load(path).content_hash(), project.content_hash())

    def test_hash_stable(self):
        self.assertEqual(
            tom_signature_arena_project().content_hash(),
            tom_signature_arena_project().content_hash(),
        )

    def test_unknown_mesh(self):
        project = blank_mobile3d_project()
        project.nodes = project.nodes + (
            Node3DRecord("bad", "missing", "accent"),
        )
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertTrue(any(issue.code == "mesh.unknown" for issue in report.issues))

    def test_unknown_material(self):
        project = blank_mobile3d_project()
        project.nodes = project.nodes + (
            Node3DRecord("bad", "cube", "missing"),
        )
        report = project.validate(raise_on_error=False)
        self.assertTrue(any(issue.code == "material.unknown" for issue in report.issues))

    def test_duplicate_node(self):
        project = blank_mobile3d_project()
        project.nodes = project.nodes + (project.nodes[0],)
        report = project.validate(raise_on_error=False)
        self.assertTrue(any(issue.code == "node.duplicate" for issue in report.issues))

    def test_bad_start_quality(self):
        project = blank_mobile3d_project()
        project.start_quality = "missing"
        report = project.validate(raise_on_error=False)
        self.assertTrue(any(issue.code == "quality.start" for issue in report.issues))

    def test_scene_preserves_material_variants(self):
        project = tom_signature_arena_project()
        scene = project.to_scene()
        cube_assets = [asset for asset in scene.assets.values() if asset.metadata.get("source_mesh_id") == "cube"]
        self.assertGreaterEqual(len(cube_assets), 4)

    def test_schema_file(self):
        schema = json.loads((ROOT / "spec/mobile_3d_project_schema_3_9_1.json").read_text())
        self.assertEqual(schema["properties"]["schema"]["const"], "ugts-kc-mobile-3d-project-3.9.1")


class World391Tests(unittest.TestCase):
    def test_player_movement(self):
        world = blank_mobile3d_project().instantiate_world()
        start = world.require("player").position
        world.step(InputFrame3D(move_z=-1), steps=60)
        self.assertLess(world.require("player").position[2], start[2])

    def test_floor_contact(self):
        world = blank_mobile3d_project().instantiate_world()
        player = world.require("player")
        player.position = (0, 4, 0)
        player.velocity = (0, -10, 0)
        world.step(steps=240)
        self.assertGreaterEqual(player.position[1], world.settings.floor_y + player.collider.vertical_extent(player.scale))

    def test_jump(self):
        world = blank_mobile3d_project().instantiate_world()
        player = world.require("player")
        player.position = (
            player.position[0],
            world.settings.floor_y + player.collider.vertical_extent(player.scale),
            player.position[2],
        )
        player.velocity = (0, 0, 0)
        player.grounded = True
        world.step(InputFrame3D(jump=True))
        self.assertGreater(player.velocity[1], 0)
        self.assertTrue(any(event.kind == "jump" for event in world.events))

    def test_bounds(self):
        world = blank_mobile3d_project().instantiate_world()
        player = world.require("player")
        player.position = (100, 1, 100)
        world.step()
        self.assertLessEqual(player.position[0], world.settings.bounds_max[0])
        self.assertLessEqual(player.position[2], world.settings.bounds_max[2])

    def test_dynamic_pair_collision(self):
        world = GameWorld3D(World3DSettings(gravity=(0, 0, 0)))
        collider = Collider3DRecord("sphere", 1)
        a = EntityState3D("a","sphere","a",(0,1,0),(1,0,0,0),(1,1,1),(1,0,0),(0,0,0),collider,True,1,0.5,())
        b = EntityState3D("b","sphere","b",(1.5,1,0),(1,0,0,0),(1,1,1),(-1,0,0),(0,0,0),collider,True,1,0.5,())
        world.spawn(a); world.spawn(b)
        events = world.step()
        self.assertTrue(any(event.kind == "collision" for event in events))
        self.assertLess(a.velocity[0], 1)

    def test_collectible(self):
        world = blank_mobile3d_project().instantiate_world()
        player = world.require("player")
        collectible = EntityState3D(
            "c","sphere","accent",player.position,(1,0,0,0),(1,1,1),(0,0,0),(0,0,0),
            Collider3DRecord("sphere",0.5, sensor=True),False,1,0,("collectible",)
        )
        world.spawn(collectible)
        world.step()
        self.assertEqual(world.state["score"], 1)
        self.assertFalse(collectible.alive)

    def test_goal(self):
        world = blank_mobile3d_project().instantiate_world()
        player = world.require("player")
        goal = world.require("goal")
        goal.translation = getattr(goal, "translation", None) if False else goal.position
        player.position = goal.position
        world.step()
        self.assertTrue(world.state["finished"])

    def test_hazard(self):
        world = blank_mobile3d_project().instantiate_world()
        player = world.require("player")
        hazard = EntityState3D(
            "h","sphere","accent",player.position,(1,0,0,0),(1,1,1),(0,0,0),(0,0,0),
            Collider3DRecord("sphere",0.5, sensor=True),False,1,0,("hazard",)
        )
        world.spawn(hazard)
        world.step()
        self.assertEqual(world.state["health"], 2)

    def test_deterministic_hash(self):
        a = blank_mobile3d_project().instantiate_world()
        b = blank_mobile3d_project().instantiate_world()
        a.step(InputFrame3D(move_x=0.5), steps=120)
        b.step(InputFrame3D(move_x=0.5), steps=120)
        self.assertEqual(a.state_hash(), b.state_hash())

    def test_save(self):
        world = blank_mobile3d_project().instantiate_world()
        with tempfile.TemporaryDirectory() as tmp:
            path = world.save(Path(tmp) / "snapshot.json")
            data = json.loads(path.read_text())
            self.assertEqual(data["schema"], "ugts-kc-game-world-3d-snapshot-3.9.1")


class Device391Tests(unittest.TestCase):
    def test_poco_auto(self):
        selected = select_device_profile(
            DeviceCapabilities3D(
                model="POCO X7 Pro", manufacturer="POCO", gpu_renderer="Mali-G720 MC7",
                ram_mb=12288, cpu_cores=8, gles_major=3, gles_minor=2,
                display_refresh_hz=120,
            ),
            signature_android_targets(), signature_quality_tiers(),
        )
        self.assertEqual(selected.profile_id, "poco_x7_pro_12gb")
        self.assertEqual(selected.target_fps, 120)

    def test_explicit_profile(self):
        selected = select_device_profile(
            DeviceCapabilities3D(display_refresh_hz=60),
            signature_android_targets(), signature_quality_tiers(), "android_compat",
        )
        self.assertEqual(selected.profile_id, "android_compat")

    def test_bad_explicit_profile(self):
        with self.assertRaises(KeyError):
            select_device_profile(
                DeviceCapabilities3D(),
                signature_android_targets(), signature_quality_tiers(), "missing",
            )

    def test_quality_downgrade(self):
        controller = AdaptiveQualityController3D(tuple(q.id for q in signature_quality_tiers()))
        for _ in range(4):
            controller.update(30, 120, 4, 0.5)
        self.assertNotEqual(controller.current, "signature_ultra")

    def test_quality_recovery(self):
        controller = AdaptiveQualityController3D(tuple(q.id for q in signature_quality_tiers()), current_index=1)
        for _ in range(17):
            controller.update(120, 120, 0, 0.5)
        self.assertEqual(controller.current, "signature_ultra")


class Pack391Tests(unittest.TestCase):
    def setUp(self):
        self.project = tom_signature_arena_project()
        self.data = compile_scene_pack_bytes(self.project)

    def test_magic_and_counts(self):
        self.assertEqual(self.data[:8], PACK_MAGIC)
        info = inspect_scene_pack(self.data)
        self.assertEqual(info["node_count"], 66)
        self.assertEqual(info["project_hash"], self.project.content_hash())

    def test_hash(self):
        info = inspect_scene_pack(self.data)
        self.assertEqual(info["sha256"], hashlib.sha256(self.data).hexdigest())

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            inspect_scene_pack(b"badmagic" + self.data[8:])

    def test_truncated(self):
        with self.assertRaises(ValueError):
            inspect_scene_pack(self.data[:-4])

    def test_trailing(self):
        with self.assertRaises(ValueError):
            inspect_scene_pack(self.data + b"x")

    def test_target_records(self):
        info = inspect_scene_pack(self.data)
        ids = {item["id"] for item in info["targets"]}
        self.assertIn("poco_x7_pro_12gb", ids)
        self.assertIn("android_compat", ids)


class AndroidExport391Tests(unittest.TestCase):
    def test_build_android_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_android_project(tom_signature_arena_project(), Path(tmp) / "android")
            self.assertTrue((result.output_dir / "app/src/main/cpp/main.cpp").exists())
            self.assertTrue(result.scene_pack.exists())
            self.assertIn("Tom Klootwijk Signature Arena 3D", (result.output_dir / "app/src/main/res/values/strings.xml").read_text())

    def test_poco_profile_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_android_project(
                tom_signature_arena_project(), Path(tmp) / "android",
                profile_hint="poco_x7_pro_12gb",
            )
            gradle = (result.output_dir / "app/build.gradle").read_text()
            self.assertIn("poco_x7_pro_12gb", gradle)
            self.assertNotIn("__PROFILE_HINT__", gradle)

    def test_build_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = build_android_project(tom_signature_arena_project(), Path(tmp) / "android")
            report = json.loads(result.build_report.read_text())
            self.assertEqual(report["schema"], "ugts-kc-android-source-build-3.9.1")
            self.assertEqual(report["target_sdk"], 36)
            self.assertGreater(len(report["files"]), 20)

    def test_gltf_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scene.gltf"
            write_mobile3d_gltf(tom_signature_arena_project(), path)
            data = json.loads(path.read_text())
            self.assertEqual(data["asset"]["version"], "2.0")
            self.assertGreater(len(data["nodes"]), 60)

    def test_cli_validate_and_pack(self):
        env = dict(os.environ, PYTHONPATH=str(SRC))
        with tempfile.TemporaryDirectory() as tmp:
            project = tom_signature_arena_project().write(Path(tmp) / "project.json")
            valid = subprocess.run(
                [sys.executable, "-m", "ugts_kc3", "validate-3d", str(project)],
                cwd=ROOT, env=env, text=True, capture_output=True,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)
            pack = Path(tmp) / "scene.kc3d"
            built = subprocess.run(
                [sys.executable, "-m", "ugts_kc3", "pack-3d", str(project), str(pack)],
                cwd=ROOT, env=env, text=True, capture_output=True,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            self.assertTrue(pack.exists())

    def test_checked_in_android_source(self):
        base = ROOT / "android/UGTSKC391Signature"
        self.assertTrue((base / "app/src/main/cpp/renderer_gles3.cpp").exists())
        self.assertTrue((base / "app/src/main/assets/signature_scene.kc3d").exists())
        self.assertIn("compileSdk 36", (base / "app/build.gradle").read_text())


class CatalogAndBoundary391Tests(unittest.TestCase):
    def test_catalog_continuity(self):
        data = json.loads((ROOT / "spec/engineering_catalog_M198_M449.json").read_text())
        ids = [int(item["id"][1:]) for item in data["mechanisms"]]
        self.assertEqual(ids, list(range(198, 450)))
        self.assertEqual(data["extended_total"], 449)

    def test_release_catalog(self):
        data = json.loads((ROOT / "spec/kc391_mechanisms_M390_M449.json").read_text())
        self.assertEqual(len(data["mechanisms"]), 60)
        self.assertEqual(data["mechanisms"][0]["id"], "M390")
        self.assertEqual(data["mechanisms"][-1]["id"], "M449")

    def test_four_d_boundary(self):
        text = (ROOT / "docs/FOUR_D_ROADMAP.md").read_text()
        self.assertIn("TODO", text)
        self.assertIn("M450 is not", text)
        self.assertIn("allocated by this release", text)

    def test_no_apk_claim(self):
        text = (ROOT / "docs/BUILD_STATUS_3_9_1.md").read_text()
        self.assertIn("Android Gradle/NDK compilation into an APK/AAB", text)

    def test_source_basis(self):
        data = json.loads((ROOT / "spec/source_basis_3_9_1.json").read_text())
        self.assertEqual(data["device_target_basis"]["primary"], "POCO X7 Pro 12 GB")


if __name__ == "__main__":
    unittest.main(verbosity=2)
