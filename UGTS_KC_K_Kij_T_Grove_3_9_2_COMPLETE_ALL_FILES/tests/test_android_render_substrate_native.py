from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
HOST_TESTS = ROOT / "native" / "host_tests"
ANDROID_MAIN = (
    ROOT / "src" / "ugts_kc3" / "android_template" / "project" / "app" / "src" / "main"
)
CPP = ANDROID_MAIN / "cpp"
SHADERS = ANDROID_MAIN / "assets" / "shaders"


def _compact(source: str) -> str:
    return "".join(source.split())


def _host_cpp_toolchain_available() -> bool:
    if os.name != "nt":
        return any(shutil.which(name) for name in ("c++", "g++", "clang++"))
    if shutil.which("cl") or shutil.which("clang++") or shutil.which("g++"):
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
        text=True, capture_output=True, check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _glslang_validator() -> Path | None:
    found = shutil.which("glslangValidator")
    if found:
        return Path(found)
    candidates: list[Path] = []
    android_sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if android_sdk:
        candidates.append(
            Path(android_sdk) / "emulator" / "lib64" / "vulkan" / "glslangValidator.exe"
        )
    candidates.append(
        Path.home() / "AppData" / "Local" / "Android" / "Sdk" / "emulator"
        / "lib64" / "vulkan" / "glslangValidator.exe"
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


class AndroidRenderSubstrateNativeTests(unittest.TestCase):
    def test_bayer_is_canonical_static_and_last(self) -> None:
        shader = (SHADERS / "grove_post.frag").read_text("utf-8")
        matrix = re.search(r"const int Bayer8\[64\]=int\[64\]\((.*?)\);", shader, re.S)
        self.assertIsNotNone(matrix)
        values = [int(value) for value in re.findall(r"\d+", matrix.group(1))]
        self.assertEqual(
            values,
            [
                0, 48, 12, 60, 3, 51, 15, 63,
                32, 16, 44, 28, 35, 19, 47, 31,
                8, 56, 4, 52, 11, 59, 7, 55,
                40, 24, 36, 20, 43, 27, 39, 23,
                2, 50, 14, 62, 1, 49, 13, 61,
                34, 18, 46, 30, 33, 17, 45, 29,
                10, 58, 6, 54, 9, 57, 5, 53,
                42, 26, 38, 22, 41, 25, 37, 21,
            ],
        )
        self.assertEqual(sorted(values), list(range(64)))
        self.assertEqual(shader.count("const int Bayer8[64]"), 1)
        compact = _compact(shader)
        off_branch = "if(uBayerMode==0){fragColor=vec4(c,1.0);return;}"
        off = compact.index(off_branch)
        physical = compact.index("intyTop=(uOutputHeight-1-int(gl_FragCoord.y))&7;")
        final_effect = compact.index("c*=1.0+uJuicePulse*0.035;")
        self.assertLess(final_effect, off)
        self.assertLess(off, physical)
        self.assertNotIn("clamp", compact[final_effect:off + len(off_branch)])
        self.assertIn("vec3src=clamp(c,0.0,1.0);", compact)
        self.assertIn("floatt=(bayer+0.5)/64.0-0.5;", compact)
        self.assertIn(
            "vec3q=floor(src*levelSpan+0.5+t)/levelSpan;", compact
        )
        self.assertIn("c=mix(src,q,uBayerStrength);fragColor=vec4(c,1.0);", compact)
        self.assertIn("ivec2physical=ivec2(int(gl_FragCoord.x)&7,yTop);", compact)
        self.assertIn("uniformintuOutputHeight;", compact)
        self.assertNotIn("uTime", compact[physical:])
        # gl_FragCoord is bottom-origin. The shader's phase conversion must
        # make the canonical matrix top-origin for both portrait and landscape.
        for output_height in (2712, 1220):
            for top_row in range(16):
                bottom_origin_y = output_height - 1 - top_row
                y_top = (output_height - 1 - bottom_origin_y) & 7
                self.assertEqual(y_top, top_row & 7)

    def test_polar_shader_decodes_packed_pose_and_has_separate_variants(self) -> None:
        shader = (SHADERS / "polar_scene.vert").read_text("utf-8")
        compact = _compact(shader)
        for decode in (
            "rho=words.y>>12u;",
            "theta=(words.x>>26u)|((words.y&0x0fffu)<<6u);",
            "heading=words.x&0x0fffu;",
            "delta-=floor(delta/codeCount+0.5)*codeCount;",
        ):
            self.assertIn(decode, compact)
        self.assertIn("#ifdef POLAR_LUT", shader)
        self.assertIn("uniform sampler2D uPolarLut;", shader)
        self.assertIn("texelFetch(uPolarLut,ivec2(directionLow+1,0),0)", compact)
        self.assertIn("exp(uPolarProfile.z+clamp(rho", compact)
        self.assertNotIn("uPolarProfile.z*exp", compact)

        renderer = (CPP / "renderer_gles3.cpp").read_text("utf-8")
        header = (CPP / "renderer_gles3.hpp").read_text("utf-8")
        self.assertIn('polarLutSource.insert(versionEnd+1u,"#define POLAR_LUT 1\\n")', renderer)
        self.assertIn("polarDirectProgram_", header)
        self.assertIn("polarLutProgram_", header)
        self.assertIn("static_assert(offsetof(PolarInstance,glowPhase12)==32u);", header)
        self.assertIn("PolarInstanceStrideBytes=36u;", header)
        self.assertIn(
            "static_assert(sizeof(PolarInstance)==PolarInstanceStrideBytes);", header
        )
        self.assertIn("glVertexAttribIPointer(2,4,GL_UNSIGNED_INT", renderer)
        self.assertIn("GL_DYNAMIC_DRAW", renderer)
        self.assertIn("glDrawElementsInstanced", renderer)
        self.assertIn("GL_RGBA16F", renderer)
        self.assertIn("GL_RGBA,GL_HALF_FLOAT,texels.data()", _compact(renderer))
        self.assertIn("direction=vec2(cos(theta),sin(theta));", compact)
        self.assertIn("texels[index*4u]=source.cosineHalf[index];", renderer)
        self.assertIn("texels[index*4u+1u]=source.sineHalf[index];", renderer)
        self.assertIn("texels[index*4u+2u]=source.normalizedRadiusHalf[index];", renderer)
        self.assertIn("texels[count*4u]=source.cosineHalf.front();", renderer)
        self.assertIn("texels[count*4u+1u]=source.sineHalf.front();", renderer)
        self.assertIn("texels[count*4u+2u]=source.normalizedRadiusHalf.back();", renderer)
        self.assertNotIn("texels[index*4u]=source.sineHalf[index];", renderer)

        polar_header = (CPP / "polar_kinematics.hpp").read_text("utf-8")
        polar_source = (CPP / "polar_kinematics.cpp").read_text("utf-8")
        for lane in ("sineHalf", "cosineHalf", "normalizedRadiusHalf"):
            self.assertIn(lane, polar_header)
        self.assertIn("profile.radiusScale=static_cast<float>(radiusScale);", polar_source)

    def test_renderer_wires_authority_limits_fallbacks_and_final_pass(self) -> None:
        renderer = (CPP / "renderer_gles3.cpp").read_text("utf-8")
        engine = (CPP / "engine.cpp").read_text("utf-8")
        polar = (CPP / "polar_kinematics.cpp").read_text("utf-8")
        hierarchy = (CPP / "transform_hierarchy.hpp").read_text("utf-8")

        self.assertIn("component.previousPose=component.pose;", polar)
        self.assertIn("KCPK packed polar cannot bind the Player controller node", polar)
        self.assertIn("part==\"0\"||part==\"2\"", _compact(polar))
        self.assertIn("field==\"0\"||field==\"2\"", _compact(polar))
        self.assertIn("profile.normalizedRadii[index]*profile.radiusScale", _compact(polar))
        self.assertIn("snapPreviousToCurrent", engine)
        self.assertIn("accumulator_/scene_.fixedDt", engine)
        self.assertIn("transformHierarchy.isLinked(component.sceneNode)", renderer)
        self.assertIn("GL_MAX_VERTEX_ATTRIBS", renderer)
        self.assertIn("GL_MAX_VERTEX_TEXTURE_IMAGE_UNITS", renderer)
        self.assertIn("no_vertex_texture_units", renderer)
        self.assertIn("hierarchy_linked", renderer)
        self.assertIn("bool isLinked(std::uint32_t sceneNode) const", hierarchy)
        self.assertIn("gpuPolarNodeMask_[nodeIndex]", renderer)
        self.assertIn("gpuPolarNodeQueued_[nodeIndex]=1u", renderer)
        self.assertEqual(renderer.count("gpuPolarNodeQueued_[nodeIndex]=1u"), 1)
        for field in (
            "polar_requested=%s", "polar_effective=%s", "gpu_instances=%u",
            "gpu_profiles=%u", "gpu_batches=%u", "cpu_fallbacks=%u", "reason=%s",
            "bayer=%s",
        ):
            self.assertIn(field, renderer)
        self.assertIn("animation_fallbacks=%u", renderer)
        self.assertIn("render shaders scene=linked polar_direct=linked", renderer)
        self.assertIn("animation_owned", renderer)
        self.assertIn("transformAnimations.owns(component.sceneNode)", renderer)
        self.assertIn("transformHierarchy.isLinked(component.sceneNode)", renderer)
        self.assertIn("transformHierarchy_.isChild(component.sceneNode)", engine)
        self.assertIn("cannot bind a transform hierarchy child", engine)
        self.assertIn("cannot also own a transform animation controller", engine)
        self.assertIn("composePackedOwnership();", engine)
        self.assertGreaterEqual(engine.count("composePackedOwnership();"), 4)
        compact = _compact(renderer)
        self.assertIn(
            "constboolfinalPass=postProcessing||substrate_.bayerEnabled();",
            compact,
        )
        self.assertIn("postProcessing?juice.saturation:1.0f", compact)
        self.assertIn("postProcessing?juice.contrast:1.0f", compact)
        self.assertIn("glUniform1i(pOutputHeight_,height_);", compact)

    def test_polar_material_bands_reuses_the_packed_chart_on_every_draw_path(self) -> None:
        vertex = (SHADERS / "polar_scene.vert").read_text("utf-8")
        fragment = (SHADERS / "scene.frag").read_text("utf-8")
        renderer = (CPP / "renderer_gles3.cpp").read_text("utf-8")
        header = (CPP / "renderer_gles3.hpp").read_text("utf-8")
        ordinary_vertex = (SHADERS / "scene.vert").read_text("utf-8")
        compact_vertex = _compact(vertex)
        compact_fragment = _compact(fragment)
        compact_renderer = _compact(renderer)

        self.assertIn("PolarMaterialValidFlag=0x40000000u", _compact(header))
        self.assertIn("PolarGeneratedCopyFlag=0x80000000u", _compact(header))
        self.assertIn("PolarInstanceStrideBytes=36u", _compact(header))
        self.assertIn("aGlowPhase12&0x0fffu", compact_vertex)
        self.assertIn("aGlowPhase12&PolarMaterialValidFlag", compact_vertex)
        self.assertIn(
            "vec4(normalizedLogRadius,direction,materialPhase)", compact_vertex
        )
        self.assertEqual(vertex.count("vec4 sampleValue=lutSample(rho,theta);"), 1)
        self.assertIn("uniform vec4 uPolarMaterialCoord;", ordinary_vertex)
        self.assertIn("vPolarMaterial = uPolarMaterialCoord;", ordinary_vertex)

        self.assertIn(
            "floatcoordinate=float(uPolarMaterialBands)*"
            "clamp(vPolarMaterial.x,0.0,1.0)+vPolarMaterial.w+"
            "0.25*(1.0+vPolarMaterial.y);",
            compact_fragment,
        )
        self.assertIn("floatband=1.0-abs(2.0*wave-1.0);", compact_fragment)
        material_base = compact_fragment.index("vec3materialBase=uBaseColor.rgb;")
        pbr = compact_fragment.index("vec3f0=mix(vec3(0.04),materialBase,metallic);")
        glow = compact_fragment.index("lit+=materialBase*vPolarGlow;")
        self.assertLess(material_base, pbr)
        self.assertLess(pbr, glow)

        self.assertIn("PolarMaterialValidFlag|", renderer)
        self.assertIn("cpuMaterialCoordinate", renderer)
        self.assertIn("copy.materialCoordinate", renderer)
        self.assertIn(
            "glUniform4f(uPolarMaterialCoord_,0.0f,0.0f,0.0f,-1.0f);",
            renderer,
        )
        self.assertIn(
            "uniforms.polarMaterialStrength,substrate_.polarMaterialStrength",
            compact_renderer,
        )
        for field in (
            "polar_material=%s",
            "material_bands=%u",
            "material_strength=%.3f",
        ):
            self.assertEqual(renderer.count(field), 2)

    def test_gpu_timer_is_nonblocking_disjoint_checked_and_truthfully_logged(self) -> None:
        header = (CPP / "gpu_timer_query.hpp").read_text("utf-8")
        source = (CPP / "gpu_timer_query.cpp").read_text("utf-8")
        renderer = (CPP / "renderer_gles3.cpp").read_text("utf-8")
        compact = _compact(renderer)
        cmake = (CPP / "CMakeLists.txt").read_text("utf-8")
        self.assertIn("gpu_timer_query.cpp", cmake)
        self.assertIn("QueryCount=4u", _compact(header))
        self.assertIn("GL_QUERY_COUNTER_BITS_EXT", source)
        self.assertIn("counterBits<30", _compact(source))
        self.assertIn("GL_QUERY_RESULT_AVAILABLE_EXT", source)
        self.assertIn("GL_GPU_DISJOINT_EXT", source)
        self.assertNotIn("glFinish", source)
        self.assertNotIn("glClientWaitSync", source)
        self.assertIn("gpuTimer_.beginFrame();", renderer)
        self.assertIn("gpuTimer_.endFrame();", renderer)
        self.assertGreaterEqual(renderer.count("gpuTimer_.abandon();"), 2)
        self.assertIn("nonblocking=true", renderer)
        self.assertIn("reason=runtime_error", renderer)
        self.assertIn("group.staging.reserve(instanceCapacity);", compact)
        self.assertIn("possibleGeneratedInstances,maximumVisibleCapacity", compact)
        self.assertIn("glBufferData(GL_ARRAY_BUFFER,group.capacityBytes,nullptr,GL_DYNAMIC_DRAW);", compact)
        self.assertIn("glBufferSubData(GL_ARRAY_BUFFER,0,", compact)
        self.assertNotIn("std::vector<PolarInstance>instances;", compact)
        self.assertIn("reason=instance_upload_failed", renderer)
        self.assertIn("gpuPolarNodeMask_[components[componentIndex].sceneNode]=0u", compact)
        self.assertGreaterEqual(compact.count("if(effectivePolarMode_==PolarRenderMode::Cpu)releaseGpuPolar();"), 2)
        all_sources = "\n".join(
            path.read_text("utf-8") for path in (*CPP.glob("*.cpp"), *SHADERS.glob("*"))
        )
        self.assertNotIn("RGB565", all_sources.upper())

    @unittest.skipUnless(shutil.which("cmake"), "CMake is required for the KCRP host test")
    def test_strict_kcrp_parser_executes_in_host_cpp(self) -> None:
        if not _host_cpp_toolchain_available():
            self.skipTest("No host C++20 compiler is installed")
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary) / "build"
            configured = subprocess.run(
                ["cmake", "-S", str(HOST_TESTS), "-B", str(build)],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(configured.returncode, 0, configured.stdout + configured.stderr)
            compiled = subprocess.run(
                [
                    "cmake", "--build", str(build), "--config", "Release",
                    "--target", "render_substrate_tests",
                ],
                cwd=ROOT, text=True, capture_output=True, check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            candidates = tuple(build.rglob("render_substrate_tests.exe")) or tuple(
                path for path in build.rglob("render_substrate_tests") if path.is_file()
            )
            self.assertTrue(candidates, "CMake did not produce render_substrate_tests")
            executed = subprocess.run(
                [str(candidates[0])], cwd=ROOT, text=True, capture_output=True, check=False
            )
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("PASS strict optional KCRP render substrate", executed.stdout)

    def test_polar_variants_and_bayer_program_link_when_glslang_is_installed(self) -> None:
        validator = _glslang_validator()
        if validator is None:
            self.skipTest("glslangValidator is not installed")
        programs = (
            ([], SHADERS / "polar_scene.vert", SHADERS / "scene.frag"),
            (["-DPOLAR_LUT=1"], SHADERS / "polar_scene.vert", SHADERS / "scene.frag"),
            ([], SHADERS / "grove_post.vert", SHADERS / "grove_post.frag"),
        )
        for definitions, vertex, fragment in programs:
            with self.subTest(vertex=vertex.name, definitions=definitions):
                compiled = subprocess.run(
                    [str(validator), *definitions, "-l", str(vertex), str(fragment)],
                    cwd=ROOT, text=True, capture_output=True, check=False,
                )
                self.assertEqual(
                    compiled.returncode, 0, compiled.stdout + compiled.stderr
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
