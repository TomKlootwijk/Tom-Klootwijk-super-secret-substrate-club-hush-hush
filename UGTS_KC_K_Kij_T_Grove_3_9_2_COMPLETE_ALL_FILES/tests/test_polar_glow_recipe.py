# ruff: noqa: E402
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
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
    POLAR_GLOW_OPERATOR_MASK,
    POLAR_POPULATION_OPERATORS,
    POLAR_POPULATION_PRESETS,
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
)
from ugts_kc3.polar_population_pack import (
    POLAR_POPULATION_HEADER_BYTES,
    POLAR_POPULATION_OPERATOR_BYTES,
    POLAR_POPULATION_PACK_BURST_VERSION,
    POLAR_POPULATION_PACK_GLOW_VERSION,
    POLAR_POPULATION_PACK_LEGACY_VERSION,
    POLAR_POPULATION_RECIPE_BYTES,
    PolarPopulationPackError,
    compile_polar_population_pack_bytes,
    inspect_polar_population_pack,
)
from ugts_kc3.polarpack import quantized_profile_lut
from ugts_kc3.scatter import combine_seed, seed_unit_float
from ugts_kc3.templates3d import blank_mobile3d_project


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _project(
    *,
    preset: str = "ring",
    count: int | None = None,
    glow: dict[str, float] | None = None,
    core_radius: float = 0.01,
    rho_min: float = -4.0,
    validate: bool = True,
) -> Mobile3DProject:
    project = blank_mobile3d_project("Glow by Distance Fixture", "Test")
    project.world = replace(project.world, fixed_dt=1.0 / 32.0)
    profile = LogPolarProfile(
        r0=2.0,
        rho_min=rho_min,
        rho_max=4.0,
        core_radius=core_radius,
    )
    motion_range = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    component = codec.component(
        PolarPose(math.log(3.0 / profile.r0), math.radians(15.0), 321, 0.0),
        PolarMotion(0.15, math.tau * 0.1, 0.05, math.tau * -0.02),
        profile_id="display",
    )
    recipe = polar_population_preset(
        preset,
        instance_count=(32 if preset == "burst" else 64) if count is None else count,
        seed=23,
    ).to_dict()
    if glow is not None:
        recipe["glow_by_distance"] = glow
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
    if validate:
        project.validate()
    return project


def _group(project: Mobile3DProject):
    return collect_polar_population_project_spec(project).groups[0]


class PolarGlowRecipeTests(unittest.TestCase):
    def test_nested_schema_is_strict_binary32_and_available_to_every_preset(self) -> None:
        authored = {
            "start_distance": -0.0,
            "end_distance": 4.00000001,
            "strength": 1.50000001,
        }
        for preset in POLAR_POPULATION_PRESETS:
            with self.subTest(preset=preset):
                recipe = PolarPopulationRecipe.from_mapping(
                    {
                        **polar_population_preset(preset).to_dict(),
                        "glow_by_distance": authored,
                    }
                )
                self.assertIsInstance(recipe.glow_by_distance, PolarGlowByDistance)
                assert recipe.glow_by_distance is not None
                self.assertEqual(
                    set(recipe.to_dict()["glow_by_distance"]),
                    {"start_distance", "end_distance", "strength"},
                )
                self.assertEqual(
                    struct.pack("<f", recipe.glow_by_distance.start_distance),
                    struct.pack("<f", 0.0),
                )
                self.assertEqual(recipe.operator_mask & POLAR_GLOW_OPERATOR_MASK, 0x0E00)
                packed_info = inspect_polar_population_pack(
                    compile_polar_population_pack_bytes(
                        _project(
                            preset=preset,
                            glow={
                                "start_distance": 0.0,
                                "end_distance": 4.0,
                                "strength": 1.0,
                            },
                        )
                    )
                )
                self.assertEqual(packed_info["format_version"], 3)
                self.assertIsNotNone(
                    packed_info["recipes"][0]["glow_by_distance"]
                )

        for invalid, message in (
            (None, "must be an object"),
            ({"start_distance": 0.0, "end_distance": 4.0}, "missing field"),
            (
                {
                    "start_distance": 0.0,
                    "end_distance": 4.0,
                    "strength": 1.0,
                    "enabled": True,
                },
                "unknown field",
            ),
            (
                {"start_distance": -1.0, "end_distance": 4.0, "strength": 1.0},
                "zero or greater",
            ),
            (
                {"start_distance": 1.0, "end_distance": 1.0, "strength": 1.0},
                "greater than",
            ),
            (
                {"start_distance": 0.0, "end_distance": 4.0, "strength": 4.01},
                "between 0 and 4",
            ),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(PolarPopulationError, message):
                    PolarPopulationRecipe.from_mapping(
                        {"preset": "ring", "glow_by_distance": invalid}
                    )

    def test_zero_and_explicit_clamped_core_compile_to_one_address(self) -> None:
        effective_core = _f32(2.0 * math.exp(-4.0))
        zero_project = _project(
            glow={"start_distance": 0.0, "end_distance": 4.0, "strength": 1.5}
        )
        explicit_project = _project(
            glow={
                "start_distance": effective_core,
                "end_distance": 4.0,
                "strength": 1.5,
            }
        )
        no_glow_project = _project()
        zero = _group(zero_project)
        explicit = _group(explicit_project)
        no_glow = _group(no_glow_project)
        self.assertEqual(zero.glow_parameters, explicit.glow_parameters)
        self.assertEqual(zero.lineage_namespace, explicit.lineage_namespace)
        self.assertEqual(zero.content_address, explicit.content_address)
        self.assertEqual(zero.lineage_namespace, no_glow.lineage_namespace)
        self.assertNotEqual(zero.content_address, no_glow.content_address)

        maximum = _f32(2.0 * math.exp(4.0))
        accepted = _group(
            _project(
                glow={
                    "start_distance": 1.0,
                    "end_distance": maximum,
                    "strength": 4.0,
                }
            )
        )
        self.assertIsNotNone(accepted.glow_parameters)
        with self.assertRaisesRegex(PolarPopulationError, "profile maximum"):
            _group(
                _project(
                    glow={
                        "start_distance": 1.0,
                        "end_distance": _f32(maximum * 1.01),
                        "strength": 1.0,
                    },
                    validate=False,
                )
            )

    def test_phase_and_uglut2_reference_are_random_access_and_exactly_bounded(self) -> None:
        project = _project(
            glow={"start_distance": 0.0, "end_distance": 4.0, "strength": 2.5}
        )
        group = _group(project)
        lineage = polar_population_lineage(group, 1)
        expected_phase = int(
            math.floor(_f32(seed_unit_float(combine_seed(lineage, 5)) * 4096.0))
        ) & 0xFFF
        self.assertEqual(polar_glow_phase12(lineage), expected_phase)
        theta_code = (-(expected_phase << 6)) & ((1 << 18) - 1)
        lut = quantized_profile_lut(group.profile)
        centered = polar_glow_by_distance_sample(
            (0.0, 1.0, 2.5),
            lineage=lineage,
            rho=0.0,
            theta_code=theta_code,
            lut=lut,
        )
        self.assertEqual(centered.shifted_theta_code, 0)
        self.assertEqual(centered.pulse, 1.0)
        self.assertEqual(centered.direction, 1.0)
        self.assertEqual(centered.glow, 2.5)
        edge = polar_glow_by_distance_sample(
            (0.0, 1.0, 4.0),
            lineage=lineage,
            rho=1.0,
            theta_code=theta_code,
            lut=lut,
        )
        self.assertEqual(edge.pulse, 0.0)
        self.assertEqual(edge.glow, 0.0)

        node = project.nodes[group.prototype_node_index]
        instance = polar_population_instance(node, group, 1)
        wrapped = polar_population_glow_sample(
            group,
            index=instance.index,
            pose_word=instance.pose_word,
            lut=lut,
        )
        self.assertIsNotNone(wrapped)
        self.assertEqual(wrapped.phase12, expected_phase)
        self.assertNotEqual(
            polar_population_lineage(group, 0),
            polar_population_lineage(group, 1),
        )
        self.assertIsNone(
            polar_population_glow_sample(
                _group(_project()),
                index=0,
                pose_word=group.component.pose_word,
            )
        )

    def test_v3_pack_uses_only_the_reserved_tail_and_new_operator_records(self) -> None:
        project = _project(
            glow={"start_distance": 0.0, "end_distance": 4.0, "strength": 1.5}
        )
        group = _group(project)
        packed = compile_polar_population_pack_bytes(project)
        inspection = inspect_polar_population_pack(packed)
        fixture_root = ROOT / "tests" / "fixtures"
        manifest = json.loads(
            (fixture_root / "polar_glow_v3_vectors.json").read_text("utf-8")
        )
        expected_pack = bytes.fromhex(
            (fixture_root / manifest["kcpr_fixture"]).read_text("ascii")
        )
        self.assertEqual(packed, expected_pack)
        self.assertEqual(hashlib.sha256(packed).hexdigest(), manifest["kcpr_sha256"])
        self.assertEqual(inspection["format_version"], POLAR_POPULATION_PACK_GLOW_VERSION)
        self.assertEqual(POLAR_POPULATION_PACK_GLOW_VERSION, 3)
        self.assertEqual(len(packed), 288)
        self.assertEqual(
            len(packed),
            POLAR_POPULATION_HEADER_BYTES
            + 8 * POLAR_POPULATION_OPERATOR_BYTES
            + POLAR_POPULATION_RECIPE_BYTES,
        )
        self.assertEqual(
            [operator["code"] for operator in inspection["operators"][-3:]],
            [0x0050, 0x0051, 0x0052],
        )
        self.assertEqual(
            [operator["meaning_hash"] for operator in inspection["operators"][-3:]],
            ["564ed3e6ad87ef6a", "1d7fceba2fb0deb3", "f3fde5381d6703a6"],
        )
        self.assertEqual(inspection["recipes"][0]["operator_mask"], 0x0E3B)
        self.assertEqual(
            packed[-12:],
            struct.pack("<3f", *group.glow_parameters),
        )
        self.assertEqual(
            inspection["recipes"][0]["glow_by_distance"],
            dict(
                zip(
                    ("center_rho", "inv_half_width", "strength"),
                    group.glow_parameters,
                )
            ),
        )
        self.assertEqual(
            [(operator.code, operator.slot, operator.arity) for operator in POLAR_POPULATION_OPERATORS[-4:-1]],
            [(0x0050, 9, 3), (0x0051, 10, 2), (0x0052, 11, 3)],
        )

        vector_bytes = bytes.fromhex(
            (fixture_root / manifest["kpgv_fixture"]).read_text("ascii")
        )
        self.assertEqual(
            hashlib.sha256(vector_bytes).hexdigest(), manifest["kpgv_sha256"]
        )
        header = struct.Struct("<8sII16s16s3f")
        record = struct.Struct("<IIQII4f")
        (
            magic,
            vector_version,
            vector_count,
            namespace,
            content,
            center,
            inverse,
            strength,
        ) = header.unpack_from(vector_bytes)
        self.assertEqual((magic, vector_version), (b"KPGV392\0", 1))
        self.assertEqual((namespace, content), (group.lineage_namespace, group.content_address))
        self.assertEqual((center, inverse, strength), group.glow_parameters)
        self.assertEqual(len(vector_bytes), header.size + vector_count * record.size)
        lut = quantized_profile_lut(group.profile)
        for vector_index in range(vector_count):
            values = record.unpack_from(vector_bytes, header.size + vector_index * record.size)
            (
                instance_index,
                theta_code,
                lineage,
                phase12,
                shifted_theta_code,
                rho,
                pulse,
                direction,
                glow,
            ) = values
            with self.subTest(vector=vector_index):
                self.assertEqual(lineage, polar_population_lineage(group, instance_index))
                sample = polar_glow_by_distance_sample(
                    group.glow_parameters,
                    lineage=lineage,
                    rho=rho,
                    theta_code=theta_code,
                    lut=lut,
                )
                self.assertEqual(
                    (sample.phase12, sample.shifted_theta_code),
                    (phase12, shifted_theta_code),
                )
                self.assertEqual(
                    struct.pack("<3f", sample.pulse, sample.direction, sample.glow),
                    struct.pack("<3f", pulse, direction, glow),
                )

    def test_mixed_v3_and_corrupt_tails_are_strict(self) -> None:
        project = _project(
            glow={"start_distance": 0.0, "end_distance": 4.0, "strength": 1.0}
        )
        glow_group = _group(project)
        floor = next(node for node in project.nodes if node.id == "floor")
        project.nodes = tuple(
            replace(
                node,
                dynamic=False,
                angular_velocity=(0.0, 0.0, 0.0),
                metadata={
                    **node.metadata,
                    "packed_kinematic": glow_group.component.to_dict(),
                    "polar_population": polar_population_preset(
                        "burst", instance_count=2, seed=99
                    ).to_dict(),
                },
            )
            if node.id == floor.id
            else node
            for node in project.nodes
        )
        packed = compile_polar_population_pack_bytes(project)
        inspection = inspect_polar_population_pack(packed)
        self.assertEqual(inspection["format_version"], 3)
        self.assertEqual(inspection["recipe_count"], 2)
        self.assertEqual(
            [recipe["glow_by_distance"] is not None for recipe in inspection["recipes"]],
            [False, True],
        )

        single = compile_polar_population_pack_bytes(
            _project(
                glow={
                    "start_distance": 0.0,
                    "end_distance": 4.0,
                    "strength": 1.0,
                }
            )
        )
        single_info = inspect_polar_population_pack(single)
        recipe_offset = (
            POLAR_POPULATION_HEADER_BYTES
            + single_info["operator_count"] * POLAR_POPULATION_OPERATOR_BYTES
        )
        tail_offset = recipe_offset + POLAR_POPULATION_RECIPE_BYTES - 12
        invalid_width = bytearray(single)
        invalid_width[tail_offset:] = struct.pack("<3f", 0.0, 0.0, 1.0)
        with self.assertRaisesRegex(PolarPopulationPackError, "inverse half width"):
            inspect_polar_population_pack(invalid_width)
        negative_zero = bytearray(single)
        center, inverse, _strength = struct.unpack("<3f", single[-12:])
        negative_zero[tail_offset:] = struct.pack("<3f", center, inverse, -0.0)
        with self.assertRaisesRegex(PolarPopulationPackError, "not canonical"):
            inspect_polar_population_pack(negative_zero)
        changed_strength = bytearray(single)
        changed_strength[tail_offset:] = struct.pack(
            "<3f", center, inverse, 0.5
        )
        with self.assertRaisesRegex(PolarPopulationPackError, "content address mismatch"):
            inspect_polar_population_pack(changed_strength)

        legacy = bytearray(compile_polar_population_pack_bytes(_project()))
        self.assertEqual(
            inspect_polar_population_pack(legacy)["format_version"],
            POLAR_POPULATION_PACK_LEGACY_VERSION,
        )
        forged_v1_tail = bytearray(legacy)
        forged_v1_tail[-12:] = struct.pack("<3f", center, inverse, 1.0)
        with self.assertRaisesRegex(PolarPopulationPackError, "reserved bytes"):
            inspect_polar_population_pack(forged_v1_tail)
        legacy[12:16] = struct.pack("<I", POLAR_POPULATION_PACK_GLOW_VERSION)
        with self.assertRaisesRegex(PolarPopulationPackError, "version 3 requires"):
            inspect_polar_population_pack(legacy)

        burst = compile_polar_population_pack_bytes(_project(preset="burst"))
        self.assertEqual(
            inspect_polar_population_pack(burst)["format_version"],
            POLAR_POPULATION_PACK_BURST_VERSION,
        )
        self.assertEqual(burst[-12:], bytes(12))
        forged_v2_tail = bytearray(burst)
        forged_v2_tail[-12:] = struct.pack("<3f", center, inverse, 1.0)
        with self.assertRaisesRegex(PolarPopulationPackError, "reserved bytes"):
            inspect_polar_population_pack(forged_v2_tail)


if __name__ == "__main__":
    unittest.main()
