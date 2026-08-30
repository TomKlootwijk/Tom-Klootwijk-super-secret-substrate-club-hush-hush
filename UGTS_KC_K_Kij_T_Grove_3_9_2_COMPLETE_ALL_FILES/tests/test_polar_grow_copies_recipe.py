# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
import hashlib
import math
from pathlib import Path
import struct
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.mobile3d import Mobile3DProject, Transform3DRecord
from ugts_kc3.packed_kinematics import (
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import (
    POLAR_GROW_COPIES_OPERATOR_MASK,
    POLAR_POPULATION_OPERATORS,
    POLAR_POPULATION_V4_OPERATOR_CODES,
    PolarGlowByDistance,
    PolarPopulationError,
    PolarPopulationRecipe,
    collect_polar_population_project_spec,
    polar_glow_by_distance_sample,
    polar_glow_phase12,
    polar_population_glow_sample,
    polar_population_instance,
    polar_population_lineage,
    polar_population_preset,
    polar_recipe_record_addresses,
)
from ugts_kc3.polar_population_pack import (
    POLAR_POPULATION_HEADER_BYTES,
    POLAR_POPULATION_OPERATOR_BYTES,
    POLAR_POPULATION_PACK_GLOW_VERSION,
    POLAR_POPULATION_PACK_VERSION,
    POLAR_POPULATION_RECIPE_BYTES,
    PolarPopulationPackError,
    compile_polar_population_pack_bytes,
    inspect_polar_population_pack,
)
from ugts_kc3.polarpack import quantized_profile_lut
from ugts_kc3.templates3d import blank_mobile3d_project


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _project(
    *,
    grow_copies: bool = False,
    glow: bool = True,
    count: int | None = None,
    preset: str = "ring",
) -> Mobile3DProject:
    project = blank_mobile3d_project("Grow Glowing Copies Fixture", "Test")
    project.world = replace(project.world, fixed_dt=1.0 / 32.0)
    profile = LogPolarProfile(2.0, -4.0, 4.0, 0.01)
    motion_range = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    component = codec.component(
        PolarPose(math.log(3.0 / profile.r0), math.radians(15.0), 321, 0.0),
        PolarMotion(0.15, math.tau * 0.1, 0.05, math.tau * -0.02),
        profile_id="display",
    )
    resolved_count = (32 if preset == "burst" else 64) if count is None else count
    recipe = polar_population_preset(
        preset, instance_count=resolved_count, seed=23
    ).to_dict()
    if glow:
        recipe["glow_by_distance"] = {
            "start_distance": 0.0,
            "end_distance": 4.0,
            "strength": 1.5,
            **({"grow_copies": True} if grow_copies else {}),
        }
    project.metadata["packed_kinematic_profiles"] = {
        "display": {
            "profile": profile.to_dict(),
            "motion_range": motion_range.to_dict(),
            "lut_resolution": 64,
        }
    }
    project.metadata["substrate_render"] = {
        "polar_mode": "lut",
        "bayer_mode": "subtle",
        "seed": 17,
    }
    project.nodes = tuple(
        replace(
            node,
            angular_velocity=(0.0, 0.0, 0.0),
            transform=Transform3DRecord(
                (node.transform.translation[0], 1.25, node.transform.translation[2]),
                node.transform.rotation,
                (0.75, 1.25, 0.5),
            ),
            metadata={
                **node.metadata,
                "packed_kinematic": component.to_dict(),
                "polar_population": recipe,
            },
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _group(project: Mobile3DProject):
    return collect_polar_population_project_spec(project).groups[-1]


class PolarGrowCopiesRecipeTests(unittest.TestCase):
    def test_nested_schema_operator_and_shared_field_sample_are_exact(self) -> None:
        legacy = PolarGlowByDistance(0.0, 4.0, 2.5)
        self.assertEqual(
            legacy.to_dict(),
            {"start_distance": 0.0, "end_distance": 4.0, "strength": 2.5},
        )
        enabled = PolarGlowByDistance.from_mapping(
            {**legacy.to_dict(), "grow_copies": True}
        )
        self.assertTrue(enabled.grow_copies)
        self.assertEqual(enabled.to_dict()["grow_copies"], True)
        disabled = PolarGlowByDistance.from_mapping(
            {**legacy.to_dict(), "grow_copies": False}
        )
        self.assertNotIn("grow_copies", disabled.to_dict())
        for invalid in (None, 0, 1, "true"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(PolarPopulationError, "true or false"):
                    PolarGlowByDistance.from_mapping(
                        {**legacy.to_dict(), "grow_copies": invalid}
                    )

        recipe = PolarPopulationRecipe.from_mapping(
            {
                **polar_population_preset("ring").to_dict(),
                "glow_by_distance": enabled.to_dict(),
            }
        )
        self.assertEqual(recipe.operator_mask, 0x1E3B)
        self.assertEqual(POLAR_GROW_COPIES_OPERATOR_MASK, 0x1000)
        operator = next(
            item for item in POLAR_POPULATION_OPERATORS if item.code == 0x0053
        )
        self.assertEqual(
            (operator.slot, operator.arity, operator.name),
            (12, 2, "polar_display_scale_from_glow"),
        )
        self.assertEqual(operator.meaning_hash, 0x1D558C07B7A6796B)
        self.assertEqual(
            POLAR_POPULATION_V4_OPERATOR_CODES,
            frozenset(operator.code for operator in POLAR_POPULATION_OPERATORS[:13]),
        )
        self.assertEqual(max(POLAR_POPULATION_V4_OPERATOR_CODES), 0x0053)

        group = _group(_project(grow_copies=True))
        lineage = polar_population_lineage(group, 1)
        phase12 = polar_glow_phase12(lineage)
        theta_code = (-(phase12 << 6)) & ((1 << 18) - 1)
        lut = quantized_profile_lut(group.profile)
        unchanged = polar_glow_by_distance_sample(
            (0.0, 1.0, 2.5),
            lineage=lineage,
            rho=0.0,
            theta_code=theta_code,
            lut=lut,
        )
        grown = polar_glow_by_distance_sample(
            (0.0, 1.0, 2.5),
            lineage=lineage,
            rho=0.0,
            theta_code=theta_code,
            lut=lut,
            grow_copies=True,
        )
        maximum = polar_glow_by_distance_sample(
            (0.0, 1.0, 4.0),
            lineage=lineage,
            rho=0.0,
            theta_code=theta_code,
            lut=lut,
            grow_copies=True,
        )
        self.assertEqual(unchanged.display_scale_multiplier, 1.0)
        self.assertEqual(grown.glow, 2.5)
        self.assertEqual(grown.display_scale_multiplier, 3.5)
        self.assertEqual(maximum.display_scale_multiplier, 5.0)
        with self.assertRaisesRegex(PolarPopulationError, "true or false"):
            polar_glow_by_distance_sample(
                (0.0, 1.0, 1.0),
                lineage=lineage,
                rho=0.0,
                theta_code=theta_code,
                lut=lut,
                grow_copies=1,  # type: ignore[arg-type]
            )

    def test_generated_copy_compounds_once_without_changing_spatial_lineage(self) -> None:
        glow_project = _project()
        grow_project = _project(grow_copies=True)
        glow_group = _group(glow_project)
        grow_group = _group(grow_project)
        glow_node = glow_project.nodes[glow_group.prototype_node_index]
        grow_node = grow_project.nodes[grow_group.prototype_node_index]
        glow_instance = polar_population_instance(glow_node, glow_group, 1)
        grow_instance = polar_population_instance(grow_node, grow_group, 1)
        sample = polar_population_glow_sample(
            grow_group,
            index=1,
            pose_word=grow_instance.pose_word,
        )
        assert sample is not None
        self.assertEqual(grow_instance.glow_sample, sample)
        expected_scale = tuple(
            _f32(value * sample.display_scale_multiplier)
            for value in glow_instance.scale
        )
        self.assertEqual(grow_instance.scale, expected_scale)
        self.assertEqual(
            (grow_instance.lineage, grow_instance.pose_word, grow_instance.translation),
            (glow_instance.lineage, glow_instance.pose_word, glow_instance.translation),
        )
        self.assertEqual(grow_node.transform.scale, (0.75, 1.25, 0.5))
        self.assertEqual(grow_group.lineage_namespace, glow_group.lineage_namespace)
        self.assertNotEqual(grow_group.content_address, glow_group.content_address)

        prefixes = [_group(_project(grow_copies=True, count=count)) for count in (64, 256)]
        self.assertEqual(prefixes[0].lineage_namespace, prefixes[1].lineage_namespace)
        self.assertNotEqual(prefixes[0].content_address, prefixes[1].content_address)

    def test_burst_uses_packed_local_rho_and_multiplies_after_legacy_scale(self) -> None:
        glow_project = _project(preset="burst")
        grow_project = _project(preset="burst", grow_copies=True)
        glow_group = _group(glow_project)
        grow_group = _group(grow_project)
        glow_node = glow_project.nodes[glow_group.prototype_node_index]
        grow_node = grow_project.nodes[grow_group.prototype_node_index]
        glow_instance = polar_population_instance(
            glow_node, glow_group, 1, fixed_tick=4
        )
        grow_instance = polar_population_instance(
            grow_node, grow_group, 1, fixed_tick=4
        )
        sample = polar_population_glow_sample(
            grow_group,
            index=1,
            pose_word=grow_instance.pose_word,
        )
        assert sample is not None
        packed_pose = grow_group.profile.codec.unpack_pose(grow_instance.pose_word)
        theta_code = (grow_instance.pose_word >> 26) & ((1 << 18) - 1)
        direct = polar_glow_by_distance_sample(
            grow_group.glow_parameters,
            lineage=grow_instance.lineage,
            rho=packed_pose.rho,
            theta_code=theta_code,
            lut=quantized_profile_lut(grow_group.profile),
            grow_copies=True,
        )
        self.assertEqual(sample, direct)
        self.assertIsNotNone(grow_instance.local_rho)
        # The pre-v4 Burst schedule is retained exactly: base*envelope first,
        # authored scale second.  V4 compounds the shared field only afterward.
        display_scalar = _f32(
            grow_instance.base_scale_scalar * grow_instance.envelope
        )
        expected_legacy = tuple(
            _f32(authored * display_scalar)
            for authored in grow_node.transform.scale
        )
        expected_grown = tuple(
            _f32(value * sample.display_scale_multiplier)
            for value in expected_legacy
        )
        self.assertEqual(glow_instance.scale, expected_legacy)
        self.assertEqual(grow_instance.scale, expected_grown)
        self.assertEqual(
            (
                grow_instance.pose_word,
                grow_instance.local_rho,
                grow_instance.envelope,
                grow_instance.base_scale_scalar,
            ),
            (
                glow_instance.pose_word,
                glow_instance.local_rho,
                glow_instance.envelope,
                glow_instance.base_scale_scalar,
            ),
        )

    def test_v4_pack_is_fixed_width_and_v3_bytes_stay_exact(self) -> None:
        v3_project = _project()
        v4_project = _project(grow_copies=True)
        v3 = compile_polar_population_pack_bytes(v3_project)
        v4 = compile_polar_population_pack_bytes(v4_project)
        v3_info = inspect_polar_population_pack(v3)
        v4_info = inspect_polar_population_pack(v4)
        self.assertEqual(v3_info["format_version"], POLAR_POPULATION_PACK_GLOW_VERSION)
        self.assertEqual(v4_info["format_version"], POLAR_POPULATION_PACK_VERSION)
        self.assertEqual((POLAR_POPULATION_PACK_GLOW_VERSION, POLAR_POPULATION_PACK_VERSION), (3, 4))
        self.assertEqual(len(v4), 304)
        self.assertEqual(
            len(v4),
            POLAR_POPULATION_HEADER_BYTES
            + 9 * POLAR_POPULATION_OPERATOR_BYTES
            + POLAR_POPULATION_RECIPE_BYTES,
        )
        self.assertEqual(v4[-12:], v3[-12:])
        self.assertEqual(v4_info["recipes"][0]["operator_mask"], 0x1E3B)
        self.assertEqual(v4_info["recipes"][0]["glow_by_distance"]["grow_copies"], True)
        self.assertEqual(v4_info["operators"][-1]["code"], 0x0053)
        self.assertEqual(v4_info["operators"][-1]["meaning_hash"], "1d558c07b7a6796b")
        self.assertEqual(
            v4_info["recipes"][0]["lineage_namespace"],
            "3fc9fbaefa749152412a5f52f4608c3f",
        )
        self.assertEqual(
            v4_info["recipes"][0]["content_address"],
            "a5be3ded374f694f696c16aa61ee6588",
        )
        self.assertEqual(
            hashlib.sha256(v4).hexdigest(),
            "486ef3c3fb6bb596c228861f54abac173b9f3247d26cb268fde8597e963f508f",
        )

    def test_mixed_v4_and_malformed_masks_versions_and_meanings_fail_closed(self) -> None:
        project = _project(grow_copies=True)
        group = _group(project)
        floor = next(node for node in project.nodes if node.id == "floor")
        project.nodes = tuple(
            replace(
                node,
                dynamic=False,
                angular_velocity=(0.0, 0.0, 0.0),
                metadata={
                    **node.metadata,
                    "packed_kinematic": group.component.to_dict(),
                    "polar_population": polar_population_preset(
                        "ring", instance_count=2, seed=99
                    ).to_dict(),
                },
            )
            if node.id == floor.id
            else node
            for node in project.nodes
        )
        mixed = compile_polar_population_pack_bytes(project)
        mixed_info = inspect_polar_population_pack(mixed)
        self.assertEqual(mixed_info["format_version"], 4)
        self.assertEqual(
            [
                bool(recipe["glow_by_distance"] and recipe["glow_by_distance"].get("grow_copies"))
                for recipe in mixed_info["recipes"]
            ],
            [False, True],
        )

        packed = compile_polar_population_pack_bytes(_project(grow_copies=True))
        info = inspect_polar_population_pack(packed)
        recipe_offset = (
            POLAR_POPULATION_HEADER_BYTES
            + info["operator_count"] * POLAR_POPULATION_OPERATOR_BYTES
        )
        without_grow_mask = bytearray(packed)
        mask = struct.unpack_from("<H", without_grow_mask, recipe_offset + 6)[0]
        struct.pack_into(
            "<H",
            without_grow_mask,
            recipe_offset + 6,
            mask & ~POLAR_GROW_COPIES_OPERATOR_MASK,
        )
        with self.assertRaisesRegex(PolarPopulationPackError, "content address mismatch"):
            inspect_polar_population_pack(without_grow_mask)

        missing_glow = bytearray(packed)
        missing_glow[-12:] = bytes(12)
        with self.assertRaisesRegex(PolarPopulationPackError, "requires Glow"):
            inspect_polar_population_pack(missing_glow)

        downgraded = bytearray(packed)
        downgraded[12:16] = struct.pack("<I", POLAR_POPULATION_PACK_GLOW_VERSION)
        with self.assertRaisesRegex(PolarPopulationPackError, "unknown polar population operator 0x0053"):
            inspect_polar_population_pack(downgraded)

        forged_v4 = bytearray(compile_polar_population_pack_bytes(_project()))
        forged_v4[12:16] = struct.pack("<I", POLAR_POPULATION_PACK_VERSION)
        with self.assertRaisesRegex(PolarPopulationPackError, "version 4 requires"):
            inspect_polar_population_pack(forged_v4)

        changed_meaning = bytearray(packed)
        last_operator_hash = (
            POLAR_POPULATION_HEADER_BYTES
            + (info["operator_count"] - 1) * POLAR_POPULATION_OPERATOR_BYTES
            + 8
        )
        changed_meaning[last_operator_hash] ^= 0x01
        with self.assertRaisesRegex(PolarPopulationPackError, "meaning mismatch"):
            inspect_polar_population_pack(changed_meaning)

        with self.assertRaisesRegex(PolarPopulationError, "requires Glow"):
            polar_recipe_record_addresses(
                preset="ring",
                instance_count=2,
                recipe_seed=1,
                operator_parameters=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0),
                profile_address=bytes(16),
                prototype_address=bytes(16),
                grow_copies=True,
            )


if __name__ == "__main__":
    unittest.main()
