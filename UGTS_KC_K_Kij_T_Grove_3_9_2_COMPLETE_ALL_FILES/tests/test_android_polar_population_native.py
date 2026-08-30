from __future__ import annotations

from dataclasses import replace
import importlib.util
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
HOST_TESTS = ROOT / "native" / "host_tests"
GENERATOR = (
    ROOT / "examples" / "packed_polar_gpu_lab_3d" / "generate_recipe_variants.py"
)
CPP = SRC / "ugts_kc3" / "android_template" / "project" / "app" / "src" / "main" / "cpp"
SHADER = (
    SRC / "ugts_kc3" / "android_template" / "project" / "app" / "src" / "main"
    / "assets" / "shaders" / "polar_scene.vert"
)
GLOW_KCPR_FIXTURE = ROOT / "tests" / "fixtures" / "polar_glow_ring_v3.kcpr.hex"
GLOW_VECTOR_FIXTURE = ROOT / "tests" / "fixtures" / "polar_glow_ring_v3.kpgv.hex"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.androidexport import compile_scene_pack_bytes  # noqa: E402
from ugts_kc3.mobile3d import Transform3DRecord  # noqa: E402
from ugts_kc3.packed_kinematics import (  # noqa: E402
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PackedKinematicComponent,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polar_population import (  # noqa: E402
    PolarPopulationRecipe,
    collect_polar_population_project_spec,
    polar_population_instance,
    polar_population_preset,
)
from ugts_kc3.polar_population_pack import (  # noqa: E402
    compile_polar_population_pack_bytes,
)
from ugts_kc3.polarpack import (  # noqa: E402
    compile_polar_pack_bytes,
    quantized_profile_lut,
)
from ugts_kc3.renderpack import compile_render_substrate_pack_bytes  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402


def _generator_module():
    spec = importlib.util.spec_from_file_location("_ugts_native_recipe_lab", GENERATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load packed-polar recipe lab generator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _host_cpp_toolchain_available() -> bool:
    if os.name != "nt":
        return any(shutil.which(name) for name in ("c++", "g++", "clang++"))
    if any(shutil.which(name) for name in ("cl", "clang++", "g++")):
        return True
    vswhere = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
    )
    if not vswhere.exists():
        return False
    result = subprocess.run(
        [
            str(vswhere), "-latest", "-products", "*", "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property", "installationPath",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _maximal_project():
    generator = _generator_module()
    project = generator.build_project(
        1024,
        preset="ring",
        polar_mode="direct",
        bayer_mode="off",
        seed=17,
        recipe_seed=23,
    )
    prototype = next(node for node in project.nodes if node.id == "orbit_mover_0000")
    environment = tuple(
        node for node in project.nodes
        if node.metadata.get("role") == "nonpolar_environment"
    )
    prototypes = []
    for index in range(4):
        metadata = {
            key: value
            for key, value in prototype.metadata.items()
            if key not in {"visual_graph", "polar_population"}
        }
        metadata["polar_population"] = polar_population_preset(
            "ring", instance_count=4096, seed=23 + index
        ).to_dict()
        prototypes.append(
            replace(
                prototype,
                id=f"orbit_recipe_prototype_{index}",
                metadata=metadata,
            )
        )
    project = replace(
        project,
        nodes=environment + tuple(prototypes),
        quality_tiers=tuple(
            replace(quality, max_visible_nodes=64)
            for quality in project.quality_tiers
        ),
    )
    project.validate()
    return project


def _burst_project(*, start_distance: float = 0.0):
    """Controlled single-recipe fixture shared with polar_burst_v2_vectors."""

    project = blank_mobile3d_project("Radial Burst Fixture", "Test")
    project.world = replace(project.world, fixed_dt=1.0 / 32.0)
    profile = LogPolarProfile(
        r0=2.0,
        rho_min=-4.0,
        rho_max=4.0,
        core_radius=0.01,
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
            "instance_count": 32,
            "seed": 23,
            "start_distance": start_distance,
            "end_distance": 8.0,
            "duration_seconds": 0.25,
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
                "polar_population": recipe.to_dict(),
            },
        )
        if node.id == "goal"
        else node
        for node in project.nodes
    )
    project.validate()
    return project


def _glow_project():
    """Controlled single-recipe fixture shared with polar_glow_v3_vectors."""

    project = blank_mobile3d_project("Glow by Distance Fixture", "Test")
    project.world = replace(project.world, fixed_dt=1.0 / 32.0)
    profile = LogPolarProfile(
        r0=2.0,
        rho_min=-4.0,
        rho_max=4.0,
        core_radius=0.01,
    )
    motion_range = MotionRange(2.0, 8.0, 4.0, 16.0)
    codec = PackedKinematicCodec(profile, motion_range)
    component = codec.component(
        PolarPose(math.log(3.0 / profile.r0), math.radians(15.0), 321, 0.0),
        PolarMotion(0.15, math.tau * 0.1, 0.05, math.tau * -0.02),
        profile_id="display",
    )
    recipe = polar_population_preset(
        "ring", instance_count=64, seed=23
    ).to_dict()
    recipe["glow_by_distance"] = {
        "start_distance": 0.0,
        "end_distance": 4.0,
        "strength": 1.5,
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


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", float(value)))[0]


def _expected_vectors(project) -> bytes:
    spec = collect_polar_population_project_spec(project)
    self_dt = _f32(project.world.fixed_dt)
    selected = list(range(60))
    base = 0
    for group in spec.groups:
        selected.append(base + group.recipe.instance_count - 2)
        base += group.recipe.instance_count - 1
    if len(selected) != 64 or len(set(selected)) != 64:
        raise AssertionError("native conformance selection must contain 64 distinct copies")

    lookup = []
    start = 0
    for recipe_index, group in enumerate(spec.groups):
        count = group.recipe.instance_count - 1
        lookup.append((start, start + count, recipe_index, group))
        start += count

    output = bytearray(
        struct.pack(
            "<8sIfIIIQI",
            b"KPXV392\0",
            1,
            self_dt,
            len(spec.groups),
            spec.generated_copies,
            spec.total_instances,
            spec.root_seed,
            len(selected),
        )
    )
    for generated_index in selected:
        for first, end, recipe_index, group in lookup:
            if first <= generated_index < end:
                instance_index = generated_index - first + 1
                break
        else:  # pragma: no cover - selection is constructed from these spans
            raise AssertionError("selected generated index is outside every recipe")
        node = project.nodes[group.prototype_node_index]
        previous = polar_population_instance(node, group, instance_index)
        advanced = group.profile.codec.advance(group.component, self_dt)
        current = polar_population_instance(
            node, group, instance_index, component=advanced
        )
        values = (
            *current.translation,
            *current.rotation,
            *current.scale,
            *current.velocity,
        )
        output.extend(
            struct.pack(
                "<IIIIHHQQQQ13f",
                generated_index,
                recipe_index,
                group.prototype_node_index,
                instance_index,
                0,
                0,
                current.lineage,
                previous.pose_word,
                current.pose_word,
                current.motion_word,
                *values,
            )
        )
    return bytes(output)


def _burst_expected_vectors(project) -> bytes:
    """Emit KPBV392 v1: exact fixed-tick local and Cartesian endpoints."""

    spec = collect_polar_population_project_spec(project)
    if len(spec.groups) != 1 or spec.groups[0].recipe.preset != "burst":
        raise AssertionError("Burst native fixture must contain one Burst recipe")
    group = spec.groups[0]
    node = project.nodes[group.prototype_node_index]
    lut = quantized_profile_lut(group.profile)
    ticks = (0, 1, 4, 7, 8)
    output = bytearray(struct.pack("<8sII", b"KPBV392\0", 1, len(ticks)))
    for fixed_tick in ticks:
        instance = polar_population_instance(
            node, group, 1, fixed_tick=fixed_tick
        )
        if instance.previous_pose_word is None:
            raise AssertionError("Burst vector is missing its previous local pose")
        if instance.duration_ticks is None or instance.local_rho is None:
            raise AssertionError("Burst vector is missing its fixed-tick phase")
        local_state = group.profile.codec.cartesian_state(
            PackedKinematicComponent(
                instance.pose_word, 0, instance.profile_id
            ),
            lut,
        )
        values = (
            instance.age,
            instance.local_rho,
            instance.envelope,
            instance.height_factor,
            instance.base_scale_scalar,
            *(_f32(value) for value in local_state["position"]),
            *instance.translation,
            *instance.rotation,
            *instance.scale,
        )
        output.extend(
            struct.pack(
                "<QIIQQQII17f",
                fixed_tick,
                0,
                1,
                instance.lineage,
                instance.previous_pose_word,
                instance.pose_word,
                instance.cycle_tick,
                instance.duration_ticks,
                *values,
            )
        )
    return bytes(output)


class AndroidPolarPopulationNativeTests(unittest.TestCase):
    def test_native_wiring_is_visibility_bounded_and_uses_shared_batches(self) -> None:
        engine = (CPP / "engine.cpp").read_text("utf-8")
        renderer = (CPP / "renderer_gles3.cpp").read_text("utf-8")
        header = (CPP / "polar_populations.hpp").read_text("utf-8")
        cmake = (CPP / "CMakeLists.txt").read_text("utf-8")
        shader = SHADER.read_text("utf-8")
        self.assertIn('readAsset("polar_populations.kcpr")', engine)
        self.assertIn("renderSubstrate_.seed", engine)
        self.assertIn("polar_populations.cpp", cmake)
        self.assertIn("Generated members", header)
        self.assertIn("polarPopulations.materialize(", renderer)
        self.assertIn("drawn<maxNodes", renderer)
        self.assertIn("visiblePopulationCopies", renderer)
        self.assertIn("group.populationRecipeIndices", renderer)
        self.assertIn("gpuPolarRecipeGroup_", renderer)
        self.assertNotIn("populationCopyIndices", renderer)
        self.assertNotIn("gpuPolarCopyGroup_", renderer)
        self.assertNotIn("struct Generated", header)
        self.assertNotIn("std::vector<Generated>", header)
        self.assertIn("generated_total=%u generated_visible=%u", renderer)
        self.assertGreater(
            renderer.index('KC_LOGI("polar population generated_total=%u'),
            renderer.index("glBufferSubData(GL_ARRAY_BUFFER,0,"),
        )
        self.assertIn("polarPopulations.composeCartesian(", renderer)
        self.assertIn("visibleGeneratedCpu+=visibleFallbacks;", renderer)
        self.assertNotIn("polarPopulations.update(", engine)
        self.assertIn("profile.logR0", renderer)
        self.assertIn("radius=exp(uPolarProfile.z+clamp(rho", shader)
        self.assertNotIn("uPolarProfile.z*exp", shader)

    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for native KCPR test")
    def test_exact_python_vectors_execute_in_bounded_host_cpp(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        project = _maximal_project()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = {
                "scene": root / "signature_scene.kc3d",
                "polar": root / "packed_kinematics.kcpk",
                "population": root / "polar_populations.kcpr",
                "substrate": root / "render_substrate.kcrp",
                "expected": root / "expected.kpxv",
            }
            paths["scene"].write_bytes(compile_scene_pack_bytes(project))
            paths["polar"].write_bytes(compile_polar_pack_bytes(project))
            paths["population"].write_bytes(
                compile_polar_population_pack_bytes(project)
            )
            paths["substrate"].write_bytes(
                compile_render_substrate_pack_bytes(project)
            )
            paths["expected"].write_bytes(_expected_vectors(project))
            burst_path_sets = []
            for name, start_distance in (("core", 0.0), ("positive", 1.0)):
                burst_project = _burst_project(start_distance=start_distance)
                burst_paths = {
                    "scene": root / f"{name}_signature_scene.kc3d",
                    "polar": root / f"{name}_packed_kinematics.kcpk",
                    "population": root / f"{name}_polar_populations.kcpr",
                    "substrate": root / f"{name}_render_substrate.kcrp",
                    "expected": root / f"{name}_expected.kpbv",
                }
                burst_paths["scene"].write_bytes(
                    compile_scene_pack_bytes(burst_project)
                )
                burst_paths["polar"].write_bytes(
                    compile_polar_pack_bytes(burst_project)
                )
                burst_paths["population"].write_bytes(
                    compile_polar_population_pack_bytes(burst_project)
                )
                burst_paths["substrate"].write_bytes(
                    compile_render_substrate_pack_bytes(burst_project)
                )
                burst_paths["expected"].write_bytes(
                    _burst_expected_vectors(burst_project)
                )
                burst_path_sets.append((name, burst_paths))
            glow_project = _glow_project()
            glow_paths = {
                "scene": root / "glow_signature_scene.kc3d",
                "polar": root / "glow_packed_kinematics.kcpk",
                "population": root / "glow_polar_populations.kcpr",
                "substrate": root / "glow_render_substrate.kcrp",
                "expected": root / "glow_expected.kpgv",
            }
            glow_paths["scene"].write_bytes(compile_scene_pack_bytes(glow_project))
            glow_paths["polar"].write_bytes(compile_polar_pack_bytes(glow_project))
            glow_pack = compile_polar_population_pack_bytes(glow_project)
            frozen_glow_pack = bytes.fromhex(
                GLOW_KCPR_FIXTURE.read_text("ascii")
            )
            self.assertEqual(glow_pack, frozen_glow_pack)
            glow_paths["population"].write_bytes(glow_pack)
            glow_paths["substrate"].write_bytes(
                compile_render_substrate_pack_bytes(glow_project)
            )
            glow_paths["expected"].write_bytes(
                bytes.fromhex(GLOW_VECTOR_FIXTURE.read_text("ascii"))
            )
            build = root / "build"
            configured = subprocess.run(
                ["cmake", "-S", str(HOST_TESTS), "-B", str(build)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                configured.returncode, 0, configured.stdout + configured.stderr
            )
            compiled = subprocess.run(
                [
                    "cmake", "--build", str(build), "--config", "Release",
                    "--target", "polar_population_tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            candidates = tuple(build.rglob("polar_population_tests.exe")) or tuple(
                path for path in build.rglob("polar_population_tests") if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce polar_population_tests")
            executed = subprocess.run(
                [str(candidates[0]), *(str(path) for path in paths.values())],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn(
                "PASS native KCPR392 polar populations generated=16380 tested=64",
                executed.stdout,
            )
            for name, burst_paths in burst_path_sets:
                with self.subTest(burst=name):
                    burst_executed = subprocess.run(
                        [
                            str(candidates[0]),
                            *(str(path) for path in burst_paths.values()),
                        ],
                        cwd=ROOT,
                        text=True,
                        capture_output=True,
                        check=False,
                    )
                    self.assertEqual(
                        burst_executed.returncode,
                        0,
                        burst_executed.stdout + burst_executed.stderr,
                    )
                    self.assertIn(
                        "PASS native KCPR392 Burst vectors=5 generated=31",
                        burst_executed.stdout,
                    )
            glow_executed = subprocess.run(
                [
                    str(candidates[0]),
                    *(str(path) for path in glow_paths.values()),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                glow_executed.returncode,
                0,
                glow_executed.stdout + glow_executed.stderr,
            )
            self.assertIn(
                "PASS native KCPR392 Glow vectors=6 generated=63",
                glow_executed.stdout,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
