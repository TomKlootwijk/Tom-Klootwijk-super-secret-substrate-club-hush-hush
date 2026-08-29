from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parent.parent
ANDROID_MAIN = (
    ROOT
    / "src"
    / "ugts_kc3"
    / "android_template"
    / "project"
    / "app"
    / "src"
    / "main"
)
FRAGMENT_SHADER = ANDROID_MAIN / "assets" / "shaders" / "scene.frag"
VERTEX_SHADER = ANDROID_MAIN / "assets" / "shaders" / "scene.vert"
RENDERER_CPP = ANDROID_MAIN / "cpp" / "renderer_gles3.cpp"
RENDERER_HPP = ANDROID_MAIN / "cpp" / "renderer_gles3.hpp"


def _normalized(source: str) -> str:
    return " ".join(source.split())


def _glslang_validator() -> Path | None:
    found = shutil.which("glslangValidator")
    if found:
        return Path(found)
    candidates: list[Path] = []
    vulkan_sdk = os.environ.get("VULKAN_SDK")
    if vulkan_sdk:
        candidates.append(Path(vulkan_sdk) / "Bin" / "glslangValidator.exe")
    android_sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if android_sdk:
        candidates.append(
            Path(android_sdk) / "emulator" / "lib64" / "vulkan" / "glslangValidator.exe"
        )
    candidates.append(
        Path.home()
        / "AppData"
        / "Local"
        / "Android"
        / "Sdk"
        / "emulator"
        / "lib64"
        / "vulkan"
        / "glslangValidator.exe"
    )
    vulkan_root = Path(r"C:\VulkanSDK")
    if vulkan_root.is_dir():
        candidates.extend(sorted(vulkan_root.glob("*/Bin/glslangValidator.exe"), reverse=True))
    return next((candidate for candidate in candidates if candidate.is_file()), None)


class AndroidPbrLiteShaderTests(unittest.TestCase):
    def test_fragment_shader_uses_the_frozen_multiply_only_contract(self) -> None:
        shader = FRAGMENT_SHADER.read_text(encoding="utf-8")
        compact = _normalized(shader)
        for declaration in (
            "uniform float uMetallic;",
            "uniform float uRoughness;",
            "uniform vec3 uCameraPosition;",
        ):
            self.assertIn(declaration, shader)

        for formula in (
            "vec3 n = normalize(vWorldNormal);",
            "vec3 l = normalize(-uLightDirection);",
            "vec3 v = normalize(uCameraPosition - vWorldPosition);",
            "vec3 h = normalize(l + v);",
            "vec3 f0 = mix(vec3(0.04), uBaseColor.rgb, metallic);",
            "float fresnel2 = oneMinusNdotV * oneMinusNdotV;",
            "float fresnel4 = fresnel2 * fresnel2;",
            "float fresnel = fresnel4 * oneMinusNdotV;",
            "float ndoth4 = ndoth2 * ndoth2;",
            "float ndoth16 = ndoth8 * ndoth8;",
            "float lobe = mix(ndoth4, ndoth16, smooth2);",
            "float diffuse = (1.0 - metallic) * (uAmbient + uLightIntensity * ndotl * (0.65 + 0.35 * rough));",
            "float spec = uLightIntensity * ndotl * lobe * (0.25 + 1.75 * smoothness);",
            "vec3 specColor = f0 + (vec3(1.0) - f0) * fresnel;",
            "vec3 rim = fresnel4 * f0 * (0.03 + 0.07 * smoothness);",
            "lit += uEmissive * (1.0 + 0.25 * uPulse);",
        ):
            self.assertIn(formula, compact)

        self.assertNotIn("pow(", shader)
        self.assertNotIn("exp(", shader)
        self.assertNotIn("log(", shader)
        self.assertNotIn("acos(", shader)
        self.assertNotIn("GGX", shader.upper())
        self.assertNotIn("ACES", shader.upper())

    def test_renderer_uploads_camera_and_every_packed_material_field(self) -> None:
        header = RENDERER_HPP.read_text(encoding="utf-8")
        renderer = RENDERER_CPP.read_text(encoding="utf-8")
        for location in ("uMetallic_", "uRoughness_", "uCameraPosition_"):
            self.assertIn(location, header)
        for lookup in (
            'uMetallic_=glGetUniformLocation(program_,"uMetallic");',
            'uRoughness_=glGetUniformLocation(program_,"uRoughness");',
            'uCameraPosition_=glGetUniformLocation(program_,"uCameraPosition");',
            "glUniform3f(uCameraPosition_,eye.x,eye.y,eye.z);",
        ):
            self.assertIn(lookup, renderer)

        ordinary_start = renderer.index("for (const auto& node:nodes)")
        scatter_start = renderer.index("if (drawn<maxNodes && !scatterGroups_.empty())")
        ordinary = renderer[ordinary_start:scatter_start]
        scatter = renderer[scatter_start:]
        for draw_path in (ordinary, scatter):
            self.assertIn("glUniform1f(uMetallic_,material.metallic);", draw_path)
            self.assertIn("glUniform1f(uRoughness_,material.roughness);", draw_path)
            self.assertIn("glUniform3f(uEmissive_,material.emissive.x", draw_path)
        self.assertEqual(
            renderer.count("glUniform1f(uMetallic_,material.metallic);"),
            2,
        )
        self.assertEqual(
            renderer.count("glUniform1f(uRoughness_,material.roughness);"),
            2,
        )
        self.assertIn(
            "uMetallic_=uRoughness_=uEmissive_=uCameraPosition_=-1;",
            renderer,
        )

    def test_scene_program_links_when_glslang_is_installed(self) -> None:
        validator = _glslang_validator()
        if validator is None:
            self.skipTest("glslangValidator is not installed")
        compiled = subprocess.run(
            [str(validator), "-l", str(VERTEX_SHADER), str(FRAGMENT_SHADER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(
            compiled.returncode,
            0,
            compiled.stdout + compiled.stderr,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
