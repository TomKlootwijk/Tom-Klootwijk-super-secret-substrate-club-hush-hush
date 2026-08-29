from dataclasses import replace
import math
from pathlib import Path
import tempfile
import unittest

from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    PackedKinematicCodec,
    PolarLookupTable,
    PolarMotion,
    PolarPose,
    canonical_document_bytes,
    pack_ecs_document,
    unpack_ecs_document,
)
from ugts_kc3.game import GameWorld
from ugts_kc3.mobile3d import Mobile3DProject
from ugts_kc3.project import GameProject
from ugts_kc3.templates import first_steps_project
from ugts_kc3.templates3d import blank_mobile3d_project


class PackedKinematicsTests(unittest.TestCase):
    def test_pose_and_motion_fit_two_words_and_roundtrip(self):
        codec = PackedKinematicCodec(LogPolarProfile(rho_min=-8, rho_max=8))
        pose = PolarPose(math.log(5.0), 1.25, 12345, -0.75)
        motion = PolarMotion(0.5, -1.25, 2.0, -3.0)
        component = codec.component(pose, motion)
        self.assertLess(component.pose_word, 1 << 64)
        self.assertLess(component.motion_word, 1 << 64)
        restored_pose = codec.unpack_pose(component.pose_word)
        restored_motion = codec.unpack_motion(component.motion_word)
        self.assertAlmostEqual(restored_pose.rho, pose.rho, places=4)
        self.assertAlmostEqual(restored_pose.theta, pose.theta, places=4)
        self.assertEqual(restored_pose.tick, pose.tick)
        self.assertAlmostEqual(restored_motion.theta_velocity, motion.theta_velocity, places=3)

    def test_lut_is_small_and_accurate_enough_for_preview(self):
        profile = LogPolarProfile(rho_min=-4, rho_max=4)
        lut = PolarLookupTable.generate(profile, 256)
        binary = lut.to_bytes()
        self.assertLess(len(binary), 1700)
        restored = PolarLookupTable.from_bytes(binary)
        sine, cosine = restored.sin_cos(1.234)
        self.assertAlmostEqual(sine, math.sin(1.234), places=3)
        self.assertAlmostEqual(cosine, math.cos(1.234), places=3)
        self.assertAlmostEqual(restored.radius(0.7), math.exp(0.7), delta=0.002)

    def test_default_lut_scales_radii_that_exceed_binary16(self):
        lut = PolarLookupTable.generate(resolution=256)
        binary = lut.to_bytes()
        self.assertTrue(binary.startswith(b"UGLUT2"))
        self.assertLess(len(binary), 1700)
        restored = PolarLookupTable.from_bytes(binary)
        self.assertAlmostEqual(
            restored.radius(restored.profile.rho_max),
            math.exp(restored.profile.rho_max),
            delta=math.exp(restored.profile.rho_max) * 0.001,
        )

    def test_polar_kinematic_calculus_matches_reference_formula(self):
        codec = PackedKinematicCodec(LogPolarProfile(rho_min=-4, rho_max=4))
        component = codec.component(
            PolarPose(math.log(2), 0.0),
            PolarMotion(rho_velocity=0.5, theta_velocity=1.0),
        )
        state = codec.cartesian_state(component)
        x, y = state["position"]
        vx, vy = state["velocity"]
        self.assertAlmostEqual(x, 2.0, places=3)
        self.assertAlmostEqual(y, 0.0, places=3)
        self.assertAlmostEqual(vx, 1.0, places=3)
        self.assertAlmostEqual(vy, 2.0, places=3)

    def test_ecs_archive_is_canonical_small_and_checksummed(self):
        document = {
            "entities": [
                {"id": f"flower-{index}", "components": {"transform": [index, 0]}}
                for index in range(200)
            ],
            "graphs": {"move": {"nodes": ["ready", "move"]}},
        }
        raw = canonical_document_bytes(document)
        packed = pack_ecs_document(document)
        self.assertLess(len(packed), len(raw) // 4)
        self.assertEqual(unpack_ecs_document(packed), document)
        damaged = bytearray(packed)
        damaged[-1] ^= 0xFF
        with self.assertRaises(ValueError):
            unpack_ecs_document(bytes(damaged))

    def test_component_roundtrips_through_the_existing_ecs_snapshot(self):
        codec = PackedKinematicCodec()
        packed = codec.component(PolarPose(0.25, 0.75, 42), PolarMotion(1, 2, 3, 4))
        world = GameWorld()
        world.spawn("orbiting-star", components={"packed_kinematic": packed})
        restored = GameWorld.from_snapshot(world.snapshot())
        component = restored.require("orbiting-star", "packed_kinematic")
        self.assertEqual(component.pose_word, packed.pose_word)
        self.assertEqual(component.motion_word, packed.motion_word)

    def test_packed_component_composes_with_transform_system(self):
        from ugts_kc3.game import Transform2D
        from ugts_kc3.packed_kinematics import attach_packed_kinematics

        codec = PackedKinematicCodec(LogPolarProfile(rho_min=-4, rho_max=4))
        packed = codec.component(PolarPose(math.log(2), 0), PolarMotion(0, 1))
        world = GameWorld(fixed_dt=0.1)
        world.spawn("orbit", components={"transform": Transform2D(), "packed_kinematic": packed})
        self.assertTrue(attach_packed_kinematics(world, codec))
        world.step()
        transform = world.require("orbit", "transform")
        self.assertAlmostEqual(math.hypot(*transform.position), 2.0, places=3)
        self.assertGreater(transform.position[1], 0.0)

    def test_projects_offer_direct_packed_roundtrips(self):
        project_2d = first_steps_project()
        project_3d = blank_mobile3d_project()
        with tempfile.TemporaryDirectory() as temp_dir:
            packed_2d = project_2d.write_packed(Path(temp_dir) / "first_steps.ugecs")
            packed_3d = project_3d.write_packed(Path(temp_dir) / "blank_3d.ugecs")
            self.assertEqual(GameProject.load_packed(packed_2d).content_hash(), project_2d.content_hash())
            self.assertEqual(Mobile3DProject.load_packed(packed_3d).content_hash(), project_3d.content_hash())

    def test_profile_ids_select_the_matching_codec_in_a_project(self):
        profile = LogPolarProfile(rho_min=-4, rho_max=4)
        codec = PackedKinematicCodec(profile)
        component = codec.component(
            PolarPose(2.0, 0.0), PolarMotion(), profile_id="small"
        )
        project = first_steps_project()
        scene = project.scenes[project.start_scene]
        target = next(entity for entity in scene.entities if "collectible" in entity.tags)
        project.scenes[scene.id] = replace(
            scene,
            entities=tuple(
                replace(
                    entity,
                    components={
                        **entity.components,
                        "packed_kinematic": component.to_dict(),
                    },
                )
                if entity.id == target.id
                else entity
                for entity in scene.entities
            ),
        )
        project.build["packed_kinematic_profiles"] = {
            "small": {"profile": profile.to_dict()}
        }
        self.assertTrue(project.validate(raise_on_error=False).passed)
        world = project.instantiate_world()
        world.step()
        transform = world.require(target.id, "transform")
        self.assertAlmostEqual(math.hypot(*transform.position), math.exp(2.0), delta=0.002)

        project.build["packed_kinematic_profiles"] = {}
        report = project.validate(raise_on_error=False)
        self.assertFalse(report.passed)
        self.assertTrue(
            any(issue.code == "packed_kinematic.profile_unknown" for issue in report.issues)
        )


if __name__ == "__main__":
    unittest.main()
