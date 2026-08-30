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
    PackedKinematicComponent,
    PackedKinematicCodec,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import (
    MAX_POLAR_BURST_DURATION_TICKS,
    MAX_POLAR_BURST_INSTANCES_PER_RECIPE,
    MAX_POLAR_BURST_RECIPES,
    MAX_POLAR_BURST_TOTAL_INSTANCES,
    MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE,
    POLAR_POPULATION_OPERATORS,
    PolarPopulationError,
    PolarPopulationRecipe,
    collect_polar_population_project_spec,
    operator_mask_for_preset,
    polar_burst_phase,
    polar_burst_phase_pair,
    polar_population_instance,
    polar_population_operator_parameters,
    polar_population_preset,
)
from ugts_kc3.polar_population_pack import (
    POLAR_POPULATION_HEADER_BYTES,
    POLAR_POPULATION_OPERATOR_BYTES,
    POLAR_POPULATION_PACK_BURST_VERSION,
    POLAR_POPULATION_PACK_LEGACY_VERSION,
    POLAR_POPULATION_RECIPE_BYTES,
    PolarPopulationPackError,
    compile_polar_population_pack_bytes,
    inspect_polar_population_pack,
)
from ugts_kc3.templates3d import blank_mobile3d_project
from ugts_kc3.polarpack import quantized_profile_lut


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _add32(left: float, right: float) -> float:
    return _f32(_f32(left) + _f32(right))


def _sub32(left: float, right: float) -> float:
    return _f32(_f32(left) - _f32(right))


def _mul32(left: float, right: float) -> float:
    return _f32(_f32(left) * _f32(right))


def _div32(left: float, right: float) -> float:
    return _f32(_f32(left) / _f32(right))


def _burst_project(
    *,
    count: int = 32,
    start_distance: float = 0.0,
    end_distance: float = 8.0,
    duration_seconds: float = 0.25,
    fixed_dt: float = 1.0 / 32.0,
    core_radius: float = 0.01,
    rho_min: float = -4.0,
    root_seed: int = 17,
    recipe_seed: int = 23,
    validate: bool = True,
) -> Mobile3DProject:
    project = blank_mobile3d_project("Radial Burst Fixture", "Test")
    project.world = replace(project.world, fixed_dt=fixed_dt)
    profile = LogPolarProfile(
        r0=2.0,
        rho_min=rho_min,
        rho_max=4.0,
        core_radius=core_radius,
    )
    motion_range = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    component = codec.component(
        PolarPose(
            math.log(3.0 / profile.r0),
            math.radians(15.0),
            321,
            math.radians(35.0),
        ),
        PolarMotion(0.15, math.tau * 0.1, 0.05, math.tau * -0.02),
        profile_id="display",
    )
    recipe = PolarPopulationRecipe.from_mapping(
        {
            "preset": "burst",
            "instance_count": count,
            "seed": recipe_seed,
            "start_distance": start_distance,
            "end_distance": end_distance,
            "duration_seconds": duration_seconds,
            "angle_step_turns": 0.125,
            "angle_jitter_turns": 0.0625,
            "height_arc": 1.5,
            "scale_min": 0.25,
            "scale_max": 0.75,
        }
    )
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
        "seed": root_seed,
    }
    project.nodes = tuple(
        replace(
            node,
            angular_velocity=(0.0, 0.0, 0.0),
            transform=Transform3DRecord(
                node.transform.translation[:1] + (1.25,) + node.transform.translation[2:],
                node.transform.rotation,
                (0.75, 1.25, 0.5),
            ),
            metadata={
                **node.metadata,
                "packed_kinematic": component.to_dict(),
                "polar_population": recipe.to_dict(),
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


class PolarBurstRecipeTests(unittest.TestCase):
    def test_machine_vectors_match_pack_and_random_access_materializer(self) -> None:
        fixture_root = ROOT / "tests" / "fixtures"
        fixture = json.loads(
            (fixture_root / "polar_burst_v2_vectors.json").read_text("utf-8")
        )
        self.assertEqual(fixture["format_version"], 2)
        self.assertEqual(fixture["operator_mask_hex"], "0x01e1")
        operators = {operator.code: operator for operator in POLAR_POPULATION_OPERATORS}
        for code_hex, slot, arity, meaning_hash in fixture["operator_records"]:
            operator = operators[int(code_hex, 16)]
            self.assertEqual((operator.slot, operator.arity), (slot, arity))
            self.assertEqual(f"{operator.meaning_hash:016x}", meaning_hash)
            self.assertEqual(operator.meaning, fixture["operator_meanings"][code_hex])
        fields = fixture["vector_fields"]
        for case in fixture["cases"]:
            with self.subTest(case=case["name"]):
                project = _burst_project(start_distance=case["start_distance"])
                group = _group(project)
                node = project.nodes[group.prototype_node_index]
                packed = compile_polar_population_pack_bytes(project)
                expected_hex = (fixture_root / case["pack_hex_file"]).read_text(
                    "ascii"
                ).strip()
                self.assertEqual(packed.hex(), expected_hex)
                self.assertEqual(hashlib.sha256(packed).hexdigest(), case["pack_sha256"])
                self.assertEqual(list(group.operator_parameters), case["operator_parameters_f32"])
                self.assertEqual(group.lineage_namespace.hex(), case["lineage_namespace_hex"])
                self.assertEqual(group.content_address.hex(), case["content_address_hex"])
                lut = quantized_profile_lut(group.profile)
                for row in case["vectors"]:
                    vector = dict(zip(fields, row))
                    instance = polar_population_instance(
                        node,
                        group,
                        vector["instance_index"],
                        fixed_tick=vector["fixed_tick_u64"],
                    )
                    self.assertEqual(instance.lineage, int(vector["lineage_u64_hex"], 16))
                    self.assertEqual(
                        instance.previous_pose_word,
                        int(vector["previous_local_pose_u64_hex"], 16),
                    )
                    self.assertEqual(
                        instance.pose_word,
                        int(vector["current_local_pose_u64_hex"], 16),
                    )
                    self.assertEqual(instance.cycle_tick, vector["cycle_tick"])
                    self.assertEqual(instance.duration_ticks, vector["duration_ticks"])
                    self.assertEqual(instance.age, vector["age_f32"])
                    self.assertEqual(instance.local_rho, vector["local_rho_f32"])
                    self.assertEqual(instance.envelope, vector["envelope_f32"])
                    self.assertEqual(instance.height_factor, vector["height_factor_f32"])
                    self.assertEqual(
                        instance.base_scale_scalar,
                        vector["base_scale_scalar_f32"],
                    )
                    local_state = group.profile.codec.cartesian_state(
                        PackedKinematicComponent(
                            instance.pose_word, 0, instance.profile_id
                        ),
                        lut,
                    )
                    self.assertEqual(
                        tuple(_f32(value) for value in local_state["position"]),
                        (
                            vector["local_position_x_lut_f32"],
                            vector["local_position_z_lut_f32"],
                        ),
                    )
                    self.assertEqual(
                        instance.translation,
                        tuple(
                            vector[f"final_translation_{axis}_f32"]
                            for axis in "xyz"
                        ),
                    )
                    self.assertEqual(
                        instance.rotation,
                        tuple(
                            vector[f"final_rotation_{axis}_f32"]
                            for axis in "wxyz"
                        ),
                    )
                    self.assertEqual(
                        instance.scale,
                        tuple(vector[f"final_scale_{axis}_f32"] for axis in "xyz"),
                    )

    def test_child_schema_is_discriminated_and_tightly_bounded(self) -> None:
        recipe = polar_population_preset("burst")
        self.assertEqual(recipe.instance_count, 32)
        self.assertEqual(
            set(recipe.to_dict()),
            {
                "preset",
                "instance_count",
                "seed",
                "start_distance",
                "end_distance",
                "duration_seconds",
                "angle_step_turns",
                "angle_jitter_turns",
                "height_arc",
                "scale_min",
                "scale_max",
            },
        )
        self.assertEqual(operator_mask_for_preset("burst"), 0x01E1)
        PolarPopulationRecipe.from_mapping(
            {"preset": "burst", "instance_count": MAX_POLAR_BURST_INSTANCES_PER_RECIPE}
        )
        polar_population_preset(
            "ring", instance_count=MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE
        )
        with self.assertRaisesRegex(PolarPopulationError, "unknown field"):
            PolarPopulationRecipe.from_mapping(
                {"preset": "burst", "radius_min": 1.0}
            )
        with self.assertRaisesRegex(PolarPopulationError, "between 2"):
            PolarPopulationRecipe.from_mapping(
                {
                    "preset": "burst",
                    "instance_count": MAX_POLAR_BURST_INSTANCES_PER_RECIPE + 1,
                }
            )

    def test_zero_and_explicit_clamped_core_compile_identically(self) -> None:
        clamped_zero = None
        for core_radius, expected_core_rho in (
            (1.0e-7, -4.0),
            (0.5, _f32(math.log(0.25))),
        ):
            with self.subTest(core_radius=core_radius):
                zero_project = _burst_project(
                    start_distance=0.0, core_radius=core_radius
                )
                zero = _group(zero_project)
                self.assertEqual(zero.operator_parameters[0], expected_core_rho)
                profile = zero.profile.codec.profile
                effective_core_distance = _f32(
                    _f32(profile.r0) * math.exp(zero.operator_parameters[0])
                )
                explicit_project = _burst_project(
                    start_distance=effective_core_distance,
                    core_radius=core_radius,
                )
                explicit = _group(explicit_project)
                self.assertEqual(explicit.operator_parameters, zero.operator_parameters)
                self.assertEqual(explicit.lineage_namespace, zero.lineage_namespace)
                self.assertEqual(explicit.content_address, zero.content_address)
                self.assertEqual(
                    compile_polar_population_pack_bytes(explicit_project),
                    compile_polar_population_pack_bytes(zero_project),
                )
                if core_radius == 1.0e-7:
                    clamped_zero = zero

        assert clamped_zero is not None
        positive = _group(_burst_project(start_distance=1.0, core_radius=1.0e-7))
        self.assertEqual(positive.operator_parameters[0], _f32(math.log(0.5)))
        self.assertNotEqual(positive.lineage_namespace, clamped_zero.lineage_namespace)
        with self.assertRaisesRegex(PolarPopulationError, "at least the Movement profile core"):
            _group(
                _burst_project(
                    start_distance=0.01,
                    core_radius=1.0e-7,
                    validate=False,
                )
            )
        with self.assertRaisesRegex(PolarPopulationError, "inside the Movement profile"):
            _group(_burst_project(end_distance=200.0, validate=False))

    def test_duration_uses_staged_binary32_half_up_and_exact_bounds(self) -> None:
        group = _group(_burst_project())
        half_up = PolarPopulationRecipe.from_mapping(
            {
                **group.recipe.to_dict(),
                "duration_seconds": 0.078125,
            }
        )
        parameters = polar_population_operator_parameters(
            half_up, profile=group.profile, fixed_dt=0.03125
        )
        self.assertEqual(parameters[2], 3.0)

        too_short = replace(half_up, duration_seconds=0.03125)
        with self.assertRaisesRegex(PolarPopulationError, "resolves to 1 fixed ticks"):
            polar_population_operator_parameters(
                too_short, profile=group.profile, fixed_dt=0.03125
            )
        too_long = replace(
            half_up,
            duration_seconds=_f32(0.03125 * (MAX_POLAR_BURST_DURATION_TICKS + 1)),
        )
        with self.assertRaisesRegex(PolarPopulationError, "resolves to 4097"):
            polar_population_operator_parameters(
                too_long, profile=group.profile, fixed_dt=0.03125
            )

    def test_tick_phase_previous_wrap_and_midpoint_preview_are_exact(self) -> None:
        project = _burst_project()
        group = _group(project)
        node = project.nodes[group.prototype_node_index]
        self.assertEqual(group.operator_parameters[2], 8.0)
        log_start, log_end = group.operator_parameters[:2]
        for tick in (0, 1, 4, 7, 8):
            with self.subTest(tick=tick):
                phase = polar_burst_phase(group, tick)
                cycle = tick % 8
                age = _div32(float(cycle), 7.0)
                expected_rho = _add32(
                    log_start, _mul32(_sub32(log_end, log_start), age)
                )
                expected_envelope = _mul32(
                    _mul32(4.0, age), _sub32(1.0, age)
                )
                self.assertEqual(phase.age, age)
                self.assertEqual(phase.rho, expected_rho)
                self.assertEqual(phase.envelope, expected_envelope)
                instance = polar_population_instance(
                    node, group, 1, fixed_tick=tick
                )
                self.assertEqual((instance.pose_word >> 12) & 0x3FFF, cycle)
                self.assertEqual(instance.cycle_tick, cycle)
                self.assertEqual(instance.fixed_tick, tick)
                self.assertEqual(instance.envelope, expected_envelope)
                self.assertTrue(instance.local_pose)
                self.assertEqual(instance.motion_word, 0)

        at_zero = polar_population_instance(node, group, 1, fixed_tick=0)
        at_one = polar_population_instance(node, group, 1, fixed_tick=1)
        at_wrap = polar_population_instance(node, group, 1, fixed_tick=8)
        self.assertEqual(at_zero.previous_pose_word, at_zero.pose_word)
        self.assertEqual(at_one.previous_pose_word, at_zero.pose_word)
        self.assertEqual(at_wrap.previous_pose_word, at_wrap.pose_word)
        previous, current = polar_burst_phase_pair(group, 8)
        self.assertIs(previous, current)
        maximum_tick = (1 << 64) - 1
        self.assertEqual(
            polar_burst_phase(group, maximum_tick).cycle_tick,
            maximum_tick % 8,
        )
        with self.assertRaisesRegex(PolarPopulationError, "Fixed tick"):
            polar_burst_phase(group, maximum_tick + 1)
        with self.assertRaisesRegex(PolarPopulationError, "whole number"):
            polar_burst_phase(group, True)
        midpoint = polar_population_instance(node, group, 1)
        self.assertEqual(midpoint.fixed_tick, 4)
        self.assertEqual(
            midpoint.pose_word,
            polar_population_instance(node, group, 1, fixed_tick=4).pose_word,
        )
        self.assertEqual(at_zero.scale, (0.0, 0.0, 0.0))
        at_end = polar_population_instance(node, group, 1, fixed_tick=7)
        self.assertEqual(at_end.scale, (0.0, 0.0, 0.0))
        self.assertEqual(at_end.translation[1], 1.25)

    def test_count_growth_preserves_random_access_lineage_and_tick_values(self) -> None:
        projects = [_burst_project(count=count) for count in (32, 128, 512)]
        groups = [_group(project) for project in projects]
        self.assertEqual(len({group.lineage_namespace for group in groups}), 1)
        self.assertEqual(len({group.content_address for group in groups}), 3)
        for index in (1, 31):
            values = []
            for project, group in zip(projects, groups):
                node = project.nodes[group.prototype_node_index]
                instance = polar_population_instance(
                    node, group, index, fixed_tick=4
                )
                values.append(
                    (
                        instance.lineage,
                        instance.previous_pose_word,
                        instance.pose_word,
                        instance.translation,
                        instance.rotation,
                        instance.scale,
                    )
                )
            self.assertEqual(values[0], values[1])
            self.assertEqual(values[0], values[2])

    def test_burst_project_recipe_and_total_limits_do_not_loosen_legacy(self) -> None:
        def repeated(count: int, instance_count: int) -> Mobile3DProject:
            project = _burst_project(count=instance_count)
            source = project.nodes[_group(project).prototype_node_index]
            copies = tuple(
                replace(source, id=f"burst_{index}")
                for index in range(1, count)
            )
            project.nodes = (*project.nodes, *copies)
            return project

        allowed = repeated(MAX_POLAR_BURST_RECIPES, 2)
        self.assertEqual(
            len(collect_polar_population_project_spec(allowed).groups),
            MAX_POLAR_BURST_RECIPES,
        )
        with self.assertRaisesRegex(PolarPopulationError, "at most 16"):
            collect_polar_population_project_spec(
                repeated(MAX_POLAR_BURST_RECIPES + 1, 2)
            )
        with self.assertRaisesRegex(PolarPopulationError, "project limit is 2048"):
            collect_polar_population_project_spec(repeated(5, 512))
        self.assertEqual(MAX_POLAR_BURST_TOTAL_INSTANCES, 2048)
        self.assertEqual(MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE, 4096)

    def test_v2_pack_is_minimal_and_v1_legacy_bytes_are_unchanged(self) -> None:
        burst_project = _burst_project()
        packed = compile_polar_population_pack_bytes(burst_project)
        info = inspect_polar_population_pack(packed)
        self.assertEqual(info["format_version"], POLAR_POPULATION_PACK_BURST_VERSION)
        self.assertEqual(info["native_consumer"], "android-kcpr392-v2")
        self.assertEqual(len(packed), 240)
        self.assertEqual(
            len(packed),
            POLAR_POPULATION_HEADER_BYTES
            + 5 * POLAR_POPULATION_OPERATOR_BYTES
            + POLAR_POPULATION_RECIPE_BYTES,
        )
        self.assertEqual(info["recipes"][0]["preset"], "burst")
        self.assertEqual(info["recipes"][0]["operator_mask"], 0x01E1)
        self.assertEqual(
            [operator["code"] for operator in info["operators"]],
            [0x0001, 0x0012, 0x0021, 0x0031, 0x0040],
        )
        expected_hashes = {
            0x0001: "8bf057fe8b6a4c18",
            0x0012: "8bfd166d5fdd0cbe",
            0x0021: "5cbb2ec2262e07e0",
            0x0031: "013b483f9ae2d7cc",
            0x0040: "276bd26b782ef226",
        }
        self.assertEqual(
            {operator["code"]: operator["meaning_hash"] for operator in info["operators"]},
            expected_hashes,
        )
        self.assertEqual(packed[-12:], bytes(12))

        legacy_project = _burst_project()
        goal = legacy_project.nodes[_group(legacy_project).prototype_node_index]
        legacy_recipe = polar_population_preset(
            "ring", instance_count=64, seed=23
        ).to_dict()
        legacy_project.nodes = tuple(
            replace(
                node,
                metadata={**node.metadata, "polar_population": legacy_recipe},
            )
            if node.id == goal.id
            else node
            for node in legacy_project.nodes
        )
        legacy = compile_polar_population_pack_bytes(legacy_project)
        legacy_info = inspect_polar_population_pack(legacy)
        self.assertEqual(
            legacy_info["format_version"], POLAR_POPULATION_PACK_LEGACY_VERSION
        )
        self.assertEqual(
            hashlib.sha256(legacy).hexdigest(),
            "8daaffb0130932b23520d6b8749e46a0fa875cafab2db20f0426c221170ece26",
        )

        forged_v2_legacy = bytearray(legacy)
        forged_v2_legacy[12:16] = struct.pack("<I", 2)
        with self.assertRaisesRegex(PolarPopulationPackError, "requires a Radial Burst"):
            inspect_polar_population_pack(forged_v2_legacy)
        forged_v1_burst = bytearray(packed)
        forged_v1_burst[12:16] = struct.pack("<I", 1)
        with self.assertRaisesRegex(PolarPopulationPackError, "unknown polar population operator"):
            inspect_polar_population_pack(forged_v1_burst)

    def test_mixed_legacy_and_burst_pack_is_canonical_v2(self) -> None:
        project = _burst_project()
        burst_group = _group(project)
        floor = next(node for node in project.nodes if node.id == "floor")
        legacy_floor = replace(
            floor,
            dynamic=False,
            angular_velocity=(0.0, 0.0, 0.0),
            metadata={
                **floor.metadata,
                "packed_kinematic": burst_group.component.to_dict(),
                "polar_population": polar_population_preset(
                    "ring", instance_count=2, seed=99
                ).to_dict(),
            },
        )
        project.nodes = tuple(
            legacy_floor if node.id == floor.id else node for node in project.nodes
        )
        packed = compile_polar_population_pack_bytes(project)
        info = inspect_polar_population_pack(packed)
        self.assertEqual(info["format_version"], 2)
        self.assertEqual(info["recipe_count"], 2)
        self.assertEqual(
            [recipe["preset"] for recipe in info["recipes"]],
            ["ring", "burst"],
        )
        self.assertEqual(
            [operator["code"] for operator in info["operators"]],
            [0x0001, 0x0010, 0x0012, 0x0020, 0x0021, 0x0030, 0x0031, 0x0040],
        )
        all_codes = {operator.code for operator in POLAR_POPULATION_OPERATORS}
        self.assertNotIn(0x0011, {operator["code"] for operator in info["operators"]})
        self.assertIn(0x0011, all_codes)

    def test_generated_values_remain_display_data_not_ecs_identities(self) -> None:
        project = _burst_project(count=512)
        group = _group(project)
        world = project.instantiate_world()
        node = project.nodes[group.prototype_node_index]
        sample = polar_population_instance(node, group, 511, fixed_tick=4)
        self.assertEqual(len(world.entities), len(project.nodes))
        self.assertNotIn(sample.display_id, world.entities)


if __name__ == "__main__":
    unittest.main()
