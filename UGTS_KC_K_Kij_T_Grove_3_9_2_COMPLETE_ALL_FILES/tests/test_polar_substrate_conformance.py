from __future__ import annotations

from dataclasses import replace
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
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.conformance import (  # noqa: E402
    POLAR_SUBSTRATE_VECTOR_PATH,
    load_polar_substrate_conformance,
)
from ugts_kc3.packed_kinematics import (  # noqa: E402
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PackedKinematicComponent,
    PolarLookupTable,
    PolarPose,
)
from ugts_kc3.polarpack import compile_polar_pack_bytes  # noqa: E402
from ugts_kc3.templates3d import blank_mobile3d_project  # noqa: E402


HOST_TESTS = ROOT / "native" / "host_tests"
SHADER = (
    ROOT
    / "src"
    / "ugts_kc3"
    / "android_template"
    / "project"
    / "app"
    / "src"
    / "main"
    / "assets"
    / "shaders"
    / "polar_scene.vert"
)


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _codec_and_lut():
    artifact = load_polar_substrate_conformance()
    profile = LogPolarProfile(
        artifact.number("r0"),
        artifact.number("rho_min"),
        artifact.number("rho_max"),
        artifact.number("core_radius"),
    )
    motion = MotionRange(
        artifact.number("rho_velocity_limit"),
        artifact.number("theta_velocity_limit"),
        artifact.number("rho_acceleration_limit"),
        artifact.number("theta_acceleration_limit"),
    )
    codec = PackedKinematicCodec(profile, motion)
    lut = PolarLookupTable.from_bytes(
        PolarLookupTable.generate(
            profile, artifact.integer("lut_resolution")
        ).to_bytes()
    )
    return artifact, codec, lut


def _project_from_vectors():
    artifact, codec, _lut = _codec_and_lut()
    project = blank_mobile3d_project("Polar Conformance", "UGTS")
    profile_id = "conformance"
    project.metadata["packed_kinematic_profiles"] = {
        profile_id: {
            "profile": codec.profile.to_dict(),
            "motion_range": codec.motion_range.to_dict(),
            "lut_resolution": artifact.integer("lut_resolution"),
        }
    }
    node_base = artifact.integer("native_node_base")
    prototype = project.nodes[node_base]
    vector_nodes = []
    for index, vector in enumerate(artifact.vectors):
        packed = PackedKinematicComponent(
            vector.pose_word, vector.motion_word, profile_id
        )
        vector_nodes.append(
            replace(
                prototype,
                id=prototype.id if index == 0 else f"polar_vector_{vector.name}",
                tags=prototype.tags if index == 0 else (),
                angular_velocity=(0.0, 0.0, 0.0),
                metadata={
                    **prototype.metadata,
                    "packed_kinematic": packed.to_dict(),
                },
            )
        )
    project.nodes = project.nodes[:node_base] + tuple(vector_nodes)
    project.validate()
    return artifact, project


def _host_cpp_toolchain_available() -> bool:
    if os.name != "nt":
        return any(shutil.which(name) for name in ("c++", "g++", "clang++"))
    if any(shutil.which(name) for name in ("cl", "clang++", "g++")):
        return True
    vswhere = (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Microsoft Visual Studio"
        / "Installer"
        / "vswhere.exe"
    )
    if not vswhere.exists():
        return False
    result = subprocess.run(
        [
            str(vswhere),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


class PolarSubstrateConformanceTests(unittest.TestCase):
    def assert_binary32_pair(
        self, actual: tuple[float, float], expected: tuple[float, float]
    ) -> None:
        self.assertEqual(tuple(_f32(value) for value in actual), expected)

    def test_shared_vectors_drive_desktop_direct_lut_and_derivatives(self) -> None:
        artifact, codec, lut = _codec_and_lut()
        self.assertEqual(
            {vector.name for vector in artifact.vectors},
            {
                "core_sentinel",
                "radius_min_clamp",
                "radius_mid_heading",
                "radius_max_clamp",
                "lut_interpolation",
                "seam_wrap_derivative",
                "derivative_mixed",
            },
        )
        self.assertEqual(
            artifact.metadata["evidence"],
            "shader_source_formula_only_no_gpu_execution",
        )
        position_errors: list[float] = []
        velocity_errors: list[float] = []
        acceleration_errors: list[float] = []
        heading_errors: list[float] = []
        dt = artifact.number("fixed_dt")
        for vector in artifact.vectors:
            with self.subTest(case=vector.name):
                component = PackedKinematicComponent(
                    vector.pose_word, vector.motion_word, "conformance"
                )
                pose = codec.unpack_pose(component.pose_word)
                motion = codec.unpack_motion(component.motion_word)
                self.assertEqual(codec.pack_pose(pose), vector.pose_word)
                self.assertEqual(codec.pack_motion(motion), vector.motion_word)

                rho, theta, core = codec.profile.encode_cartesian(
                    vector.input_x, vector.input_z
                )
                self.assertEqual(core, vector.core)
                reconstructed = codec.pack_pose(
                    PolarPose(rho, theta, pose.tick, pose.heading)
                )
                self.assertEqual(reconstructed, vector.pose_word)

                direct = codec.cartesian_state(component)
                quantized_lut = codec.cartesian_state(component, lut)
                self.assert_binary32_pair(
                    direct["position"], vector.direct_position
                )
                self.assert_binary32_pair(
                    quantized_lut["position"], vector.lut_position
                )
                self.assert_binary32_pair(
                    direct["velocity"], vector.direct_velocity
                )
                self.assert_binary32_pair(
                    quantized_lut["velocity"], vector.lut_velocity
                )
                self.assert_binary32_pair(
                    direct["acceleration"], vector.direct_acceleration
                )
                self.assert_binary32_pair(
                    quantized_lut["acceleration"], vector.lut_acceleration
                )
                self.assert_binary32_pair(
                    (math.cos(pose.heading * 0.5), math.sin(pose.heading * 0.5)),
                    vector.heading_quaternion_wy,
                )
                self.assert_binary32_pair(
                    (math.cos(pose.heading), math.sin(pose.heading)),
                    vector.direct_heading_direction,
                )
                heading_sine, heading_cosine = lut.sin_cos(pose.heading)
                self.assert_binary32_pair(
                    (heading_cosine, heading_sine),
                    vector.lut_heading_direction,
                )

                advanced = codec.advance(component, dt)
                self.assertEqual(advanced.pose_word, vector.next_pose_word)
                self.assertEqual(advanced.motion_word, vector.next_motion_word)

                position_errors.append(
                    math.dist(direct["position"], quantized_lut["position"])
                )
                velocity_errors.append(
                    math.dist(direct["velocity"], quantized_lut["velocity"])
                )
                acceleration_errors.append(
                    math.dist(
                        direct["acceleration"], quantized_lut["acceleration"]
                    )
                )
                heading_errors.append(
                    math.dist(
                        vector.direct_heading_direction,
                        vector.lut_heading_direction,
                    )
                )

        self.assertGreater(max(position_errors), 0.0)
        self.assertLessEqual(
            max(position_errors),
            artifact.number("maximum_direct_lut_position_error"),
        )
        self.assertLessEqual(
            max(velocity_errors),
            artifact.number("maximum_direct_lut_velocity_error"),
        )
        self.assertLessEqual(
            max(acceleration_errors),
            artifact.number("maximum_direct_lut_acceleration_error"),
        )
        self.assertLessEqual(
            max(heading_errors),
            artifact.number("maximum_direct_lut_heading_error"),
        )
        seam = next(
            vector
            for vector in artifact.vectors
            if vector.name == "seam_wrap_derivative"
        )
        self.assertEqual((seam.pose_word >> 26) & 0x3FFFF, 0x3FFFF)
        self.assertLess((seam.next_pose_word >> 26) & 0x3FFFF, 1024)
        self.assertEqual(seam.pose_word & 0xFFF, 0xFFF)
        self.assertLess(seam.next_pose_word & 0xFFF, 32)

    def test_shader_source_matches_artifact_formulas_without_gpu_claim(self) -> None:
        artifact = load_polar_substrate_conformance()
        shader = "".join(SHADER.read_text("utf-8").split())
        for name, snippet in artifact.shader_snippets.items():
            with self.subTest(formula=name):
                self.assertIn("".join(snippet.split()), shader)
        heading_start = shader.index("vec3scaledPosition=")
        heading_end = shader.index("vec3rotatedPosition=", heading_start)
        heading = shader[heading_start:heading_end]
        self.assertIn("#ifdefPOLAR_LUT", heading)
        self.assertIn("vec2headingDirection=lutDirection(heading);", heading)
        self.assertIn("#else", heading)
        self.assertIn("floatheadingCosine=cos(heading);", heading)
        self.assertEqual(shader.count("lutDirection("), 4)
        self.assertIn("lutDirection(materialAngle).x", shader)

    @unittest.skipUnless(shutil.which("cmake"), "CMake is required")
    def test_same_artifact_executes_in_native_host_runtime(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        artifact, project = _project_from_vectors()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            polar_pack = root / "packed_kinematics.kcpk"
            polar_pack.write_bytes(compile_polar_pack_bytes(project))
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
                    "cmake",
                    "--build",
                    str(build),
                    "--config",
                    "Release",
                    "--target",
                    "polar_substrate_conformance_tests",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                compiled.returncode, 0, compiled.stdout + compiled.stderr
            )
            candidates = tuple(
                build.rglob("polar_substrate_conformance_tests.exe")
            ) or tuple(
                path
                for path in build.rglob("polar_substrate_conformance_tests")
                if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce conformance host test")
            executed = subprocess.run(
                [
                    str(candidates[0]),
                    str(POLAR_SUBSTRATE_VECTOR_PATH),
                    str(polar_pack),
                    str(SHADER),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                executed.returncode, 0, executed.stdout + executed.stderr
            )
            self.assertIn(
                f"PASS polar substrate conformance vectors={len(artifact.vectors)} "
                "source_formula_only=true",
                executed.stdout,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
