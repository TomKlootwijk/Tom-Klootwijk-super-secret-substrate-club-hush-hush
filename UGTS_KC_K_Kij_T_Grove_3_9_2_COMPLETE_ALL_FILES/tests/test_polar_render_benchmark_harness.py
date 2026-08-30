from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.benchmark_polar_render_poco import (  # noqa: E402
    BURST_WORKLOAD_COUNTS,
    GLOW_WORKLOAD_COUNTS,
    GROW_WORKLOAD_COUNTS,
    RECIPE_LAB_GENERATOR,
    BenchmarkCase,
    artifact_record,
    benchmark_cases,
    build_project_for_case,
    case_name,
    comparison_summary,
    load_lab_builder,
    validate_runtime_proof,
    validate_timings,
)
import validation.benchmark_polar_render_poco as benchmark_harness  # noqa: E402
from ugts_kc3.polar_population_pack import (  # noqa: E402
    compile_polar_population_pack_bytes,
    inspect_polar_population_pack,
)


class _FakeProject:
    def write(self, path: str | Path) -> None:
        Path(path).write_text('{"fake": true}\n', encoding="utf-8")


def _fake_build_functions(
    case: BenchmarkCase, captured: dict[str, Path]
) -> tuple[object, object]:
    base_application_id = "org.ugts.games.shortbuild"
    application_id = f"{base_application_id}.pocox7pro"

    def fake_export(
        project: object,
        output_dir: str | Path,
        *,
        profile_hint: str,
        clean: bool,
        include_authoring_assets: bool,
    ) -> SimpleNamespace:
        del project, clean, include_authoring_assets
        output = Path(output_dir)
        captured["android_dir"] = output
        assets = output / "app" / "src" / "main" / "assets"
        assets.mkdir(parents=True)
        project_file = output / "project.json"
        project_file.write_text('{"exported": true}\n', encoding="utf-8")
        polar_pack = assets / "packed_kinematics.kcpk"
        polar_pack.write_bytes(b"KCPK")
        substrate_pack = assets / "render_substrate.kcrp"
        substrate_pack.write_bytes(b"KCRP")
        report = output / "build-report.json"
        report.write_text(
            json.dumps(
                {
                    "application_id": base_application_id,
                    "packed_kinematic_runtime": {
                        "profile_count": 1,
                        "component_count": case.count,
                    },
                    "polar_population_recipe_asset": None,
                    "render_substrate_runtime": {
                        "polar_mode": case.polar_mode,
                        "bayer_mode": case.bayer_mode,
                        "levels": case.expected_levels,
                        "strength": case.expected_strength,
                    },
                }
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(
            project_file=project_file,
            polar_pack=polar_pack,
            render_substrate_pack=substrate_pack,
            polar_population_pack=None,
            build_report=report,
            project_hash="fake-hash",
            file_count=4,
            total_bytes=100,
            profile_hint=profile_hint,
        )

    def fake_apk(
        android_dir: str | Path,
        *,
        variant: str,
        clean: bool,
    ) -> SimpleNamespace:
        del variant, clean
        apk = Path(android_dir) / "app" / "build" / "fake.apk"
        apk.parent.mkdir(parents=True)
        apk.write_bytes(b"APK")
        return SimpleNamespace(
            apk=apk,
            application_id=application_id,
            output="BUILD SUCCESSFUL\n",
        )

    return fake_export, fake_apk


def _result(
    case: BenchmarkCase,
    *,
    valid: bool,
    fps: float | None = None,
    p95: float | None = None,
) -> dict[str, object]:
    profile = None
    if fps is not None:
        profile = {
            "effective_fps": fps,
            "frame_ms_p50": 8.3,
            "frame_ms_p95": p95,
            "frame_ms_p99": 9.1,
            "intervals_over_1_5_vsync": 0,
            "pss_kib_max": 140_000,
            "rss_kib_max": None,
            "cpu_total_capacity_pct_mean": 3.0,
            "cpu_total_capacity_pct_max": 4.0,
            "cpu_one_core_pct_mean": 24.0,
            "cpu_one_core_pct_max": 32.0,
            "gpu_c_max": None,
            "battery_c_max": 36.0,
            "thermal_status_max": 0,
        }
    return {
        "case": case.to_dict(),
        "status": "profiled" if valid else "invalid_runtime_proof",
        "valid": valid,
        "profile": profile,
    }


class PolarRenderBenchmarkHarnessTests(unittest.TestCase):
    def test_android_native_target_requests_sha1_build_id(self) -> None:
        cmake = (
            ROOT
            / "src"
            / "ugts_kc3"
            / "android_template"
            / "project"
            / "app"
            / "src"
            / "main"
            / "cpp"
            / "CMakeLists.txt"
        ).read_text(encoding="utf-8")
        self.assertIn("target_link_options(ugts_kc_native PRIVATE", cmake)
        self.assertIn('"-Wl,--build-id=sha1"', cmake)
        self.assertIn(
            '"-fdebug-prefix-map=${CMAKE_CURRENT_SOURCE_DIR}=/ugts-kc/source"',
            cmake,
        )
        self.assertIn(
            '"-fdebug-prefix-map=${CMAKE_CURRENT_BINARY_DIR}=/ugts-kc/build"',
            cmake,
        )
        self.assertIn("target_compile_options(native_app_glue PRIVATE", cmake)

    def test_matrix_and_case_names_are_stable(self) -> None:
        cases = benchmark_cases((256, 64))
        self.assertEqual(
            [case.name for case in cases],
            [
                "polar-0064-direct-off",
                "polar-0064-lut-off",
                "polar-0064-direct-subtle",
                "polar-0064-lut-subtle",
                "polar-0256-direct-off",
                "polar-0256-lut-off",
                "polar-0256-direct-subtle",
                "polar-0256-lut-subtle",
            ],
        )
        cpu = benchmark_cases((1024,), include_cpu=True)
        self.assertEqual(cpu[-1].name, "polar-1024-cpu-off")
        self.assertEqual(case_name(64, "lut", "subtle"), "polar-0064-lut-subtle")
        self.assertEqual(case_name(32, "cpu", "subtle"), "polar-0032-cpu-subtle")
        with self.assertRaisesRegex(ValueError, "count"):
            case_name(65, "lut", "off")

        burst = benchmark_cases(
            BURST_WORKLOAD_COUNTS,
            include_cpu=True,
            workload="burst",
        )
        self.assertEqual(len(burst), 18)
        self.assertEqual(burst[0].name, "polar-0032-direct-off")
        self.assertEqual(burst[-1].name, "polar-0384-cpu-subtle")

        glow = benchmark_cases(
            GLOW_WORKLOAD_COUNTS,
            include_cpu=True,
            workload="glow",
        )
        self.assertEqual(len(glow), 15)
        self.assertEqual(glow[0].name, "polar-0064-direct-off")
        self.assertEqual(glow[11].name, "polar-1024-lut-subtle")
        self.assertEqual(
            [case.name for case in glow[-3:]],
            [
                "polar-0064-cpu-off",
                "polar-0256-cpu-off",
                "polar-1024-cpu-off",
            ],
        )
        grow = benchmark_cases(
            GROW_WORKLOAD_COUNTS,
            include_cpu=True,
            workload="grow",
        )
        self.assertEqual(
            [case.name for case in grow],
            [case.name for case in glow],
        )

    def test_timing_bounds_match_profiler_contract(self) -> None:
        self.assertEqual(validate_timings(5, 30), (5.0, 30.0))
        self.assertEqual(validate_timings(0, 900), (0.0, 900.0))
        for warmup in (-0.1, 60.1):
            with self.assertRaisesRegex(ValueError, "warmup"):
                validate_timings(warmup, 30)
        for profile in (4.9, 900.1):
            with self.assertRaisesRegex(ValueError, "profile"):
                validate_timings(5, profile)

    def test_cli_exposes_the_bounded_glow_workload(self) -> None:
        parser = benchmark_harness.argument_parser()
        args = parser.parse_args(
            [
                "--workload",
                "glow",
                "--count",
                "64",
                "256",
                "1024",
                "--include-cpu",
                "--build-only",
            ]
        )
        self.assertEqual(args.workload, "glow")
        self.assertEqual(args.counts, [64, 256, 1024])
        grow_args = parser.parse_args(
            ["--workload", "grow", "--count", "64", "--build-only"]
        )
        self.assertEqual(grow_args.workload, "grow")
        help_text = parser.format_help()
        self.assertIn("KCPR v3 Ring field", help_text)
        self.assertIn("grow uses KCPR v4", help_text)
        self.assertIn("Glow and Grow add", help_text)
        self.assertIn("CPU/Bayer Off only", help_text)
        self.assertIn("Off only", help_text)

    def test_artifact_record_hashes_exact_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            artifact = root / "case" / "render_substrate.kcrp"
            artifact.parent.mkdir()
            data = b"KCRP392\0" + bytes(range(24))
            artifact.write_bytes(data)
            record = artifact_record(artifact, relative_to=root)
            self.assertEqual(record["relative_path"], "case/render_substrate.kcrp")
            self.assertEqual(record["bytes"], 32)
            self.assertEqual(record["sha256"], hashlib.sha256(data).hexdigest())
            json.dumps(record)

    def test_case_build_uses_short_temporary_source_and_resumes_from_evidence(
        self,
    ) -> None:
        case = BenchmarkCase(64, "direct", "off")
        captured: dict[str, Path] = {}
        fake_export, fake_apk = _fake_build_functions(case, captured)
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "canonical" / "run"
            run_dir.mkdir(parents=True)
            with (
                patch.object(
                    benchmark_harness,
                    "build_android_project",
                    side_effect=fake_export,
                ),
                patch.object(benchmark_harness, "build_apk", side_effect=fake_apk),
            ):
                stage = benchmark_harness._build_case(
                    run_dir,
                    case,
                    lambda *args, **kwargs: _FakeProject(),
                    seed=17,
                )

            android_dir = captured["android_dir"]
            self.assertEqual(android_dir.name, "a")
            self.assertTrue(android_dir.parent.name.startswith("kc392-"))
            self.assertFalse(android_dir.exists())
            case_dir = run_dir / "cases" / case.name
            self.assertFalse((case_dir / "android-project").exists())
            self.assertFalse(stage["android_source"]["retained"])
            for record in stage["artifacts"].values():
                self.assertTrue((run_dir / record["relative_path"]).is_file())
            attempt = json.loads(
                (case_dir / "build-attempt-001" / "build-attempt.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(attempt["status"], "complete")
            self.assertFalse(attempt["temporary_workspace"]["retained"])

            with (
                patch.object(
                    benchmark_harness,
                    "build_android_project",
                    side_effect=AssertionError("resume rebuilt Android source"),
                ),
                patch.object(
                    benchmark_harness,
                    "build_apk",
                    side_effect=AssertionError("resume rebuilt APK"),
                ),
            ):
                resumed = benchmark_harness._build_case(
                    run_dir,
                    case,
                    lambda *args, **kwargs: _FakeProject(),
                    seed=17,
                )
            self.assertEqual(resumed, stage)

    def test_failed_build_attempt_is_preserved_and_retry_is_append_only(self) -> None:
        case = BenchmarkCase(64, "direct", "off")
        captured: dict[str, Path] = {}
        fake_export, fake_apk = _fake_build_functions(case, captured)
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            run_dir.mkdir()
            with patch.object(
                benchmark_harness,
                "build_android_project",
                side_effect=RuntimeError("synthetic Gradle path failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic"):
                    benchmark_harness._build_case(
                        run_dir,
                        case,
                        lambda *args, **kwargs: _FakeProject(),
                        seed=17,
                    )
            case_dir = run_dir / "cases" / case.name
            first_attempt = case_dir / "build-attempt-001"
            failure = json.loads(
                (first_attempt / "build-attempt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(failure["status"], "failed")
            self.assertTrue((first_attempt / "error.txt").is_file())
            self.assertTrue((first_attempt / "project.json").is_file())

            with (
                patch.object(
                    benchmark_harness,
                    "build_android_project",
                    side_effect=fake_export,
                ),
                patch.object(benchmark_harness, "build_apk", side_effect=fake_apk),
            ):
                stage = benchmark_harness._build_case(
                    run_dir,
                    case,
                    lambda *args, **kwargs: _FakeProject(),
                    seed=17,
                )
            self.assertTrue((case_dir / "build-attempt-001").is_dir())
            second = json.loads(
                (case_dir / "build-attempt-002" / "build-attempt.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(second["status"], "complete")
            self.assertEqual(stage["kind"], "build-stage")

    def test_run_manifest_records_build_failure_and_resume_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output_root = Path(temporary) / "runs"
            with (
                patch.object(
                    benchmark_harness,
                    "load_lab_builder",
                    return_value=lambda *args, **kwargs: _FakeProject(),
                ),
                patch.object(
                    benchmark_harness,
                    "_build_case",
                    side_effect=RuntimeError("synthetic build stop"),
                ),
            ):
                with self.assertRaisesRegex(RuntimeError, "synthetic build stop"):
                    benchmark_harness.run_benchmark(
                        output_root=output_root,
                        counts=(64,),
                        seed=17,
                        build_only=True,
                    )
            run_dirs = tuple(path for path in output_root.iterdir() if path.is_dir())
            self.assertEqual(len(run_dirs), 1)
            manifest = json.loads(
                (run_dirs[0] / "run-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["status"], "build_failed")
            self.assertIn("synthetic build stop", manifest["interruption"])
            self.assertIn("--resume", manifest["resume_command"])
            self.assertTrue((run_dirs[0] / "comparison-summary.json").is_file())

    def test_device_toolchain_discovery_needs_no_android_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            sdk = Path(temporary) / "sdk"
            adb = sdk / "platform-tools" / "adb.exe"
            adb.parent.mkdir(parents=True)
            adb.write_bytes(b"fake")
            with (
                patch.dict(
                    os.environ,
                    {"ANDROID_SDK_ROOT": str(sdk)},
                    clear=True,
                ),
                patch.object(benchmark_harness.shutil, "which", return_value=None),
            ):
                toolchain = benchmark_harness._discover_device_toolchain()
            self.assertEqual(toolchain.sdk_root, sdk.resolve())
            self.assertEqual(toolchain.adb, adb.resolve())
            self.assertEqual(toolchain.gradle_command, ())

    def test_runtime_logcat_is_scoped_to_profile_pid(self) -> None:
        self.assertEqual(
            benchmark_harness._runtime_logcat_arguments(4321),
            (
                "logcat",
                "--pid=4321",
                "-d",
                "-v",
                "threadtime",
                "-s",
                "UGTS-KC392:I",
                "*:S",
            ),
        )
        for invalid in (0, -1, True):
            with self.assertRaisesRegex(ValueError, "PID"):
                benchmark_harness._runtime_logcat_arguments(invalid)

    def test_case_builder_passes_exact_settings_to_a_fake(self) -> None:
        captured: dict[str, object] = {}

        def fake_builder(
            count: int,
            *,
            polar_mode: str,
            bayer_mode: str,
            levels: int,
            strength: float,
            seed: int,
        ) -> str:
            captured.update(
                {
                    "count": count,
                    "polar_mode": polar_mode,
                    "bayer_mode": bayer_mode,
                    "levels": levels,
                    "strength": strength,
                    "seed": seed,
                }
            )
            return "fake-project"

        case = BenchmarkCase(256, "direct", "subtle")
        project = build_project_for_case(fake_builder, case, seed=123)
        self.assertEqual(project, "fake-project")
        self.assertEqual(
            captured,
            {
                "count": 256,
                "polar_mode": "direct",
                "bayer_mode": "subtle",
                "levels": 64,
                "strength": 0.30,
                "seed": 123,
            },
        )

    def test_recipe_workload_builder_keeps_one_ecs_prototype(self) -> None:
        builder = load_lab_builder(RECIPE_LAB_GENERATOR)
        project = build_project_for_case(
            builder,
            BenchmarkCase(1024, "lut", "subtle"),
            seed=123,
        )
        recipe = project.metadata["polar_recipe_lab"]
        self.assertEqual(recipe["ecs_prototype_count"], 1)
        self.assertEqual(recipe["display_instance_count"], 1024)
        self.assertFalse(recipe["generated_members_are_ecs_entities"])

    def test_burst_workload_builder_uses_kcpr_v2_and_one_ecs_prototype(self) -> None:
        builder = load_lab_builder(RECIPE_LAB_GENERATOR)
        project = build_project_for_case(
            builder,
            BenchmarkCase(128, "lut", "subtle"),
            seed=123,
            workload="burst",
        )
        recipe = project.metadata["polar_recipe_lab"]
        self.assertEqual(recipe["ecs_prototype_count"], 1)
        self.assertEqual(recipe["display_instance_count"], 128)
        self.assertEqual(recipe["preset"], "burst")
        self.assertEqual(
            next(
                node.metadata["polar_population"]
                for node in project.nodes
                if "polar_population" in node.metadata
            )["preset"],
            "burst",
        )

    def test_glow_workload_builder_freezes_kcpr_v3_ring_metadata(self) -> None:
        builder = load_lab_builder(RECIPE_LAB_GENERATOR)
        project = build_project_for_case(
            builder,
            BenchmarkCase(256, "lut", "subtle"),
            seed=123,
            workload="glow",
        )
        lab = project.metadata["polar_recipe_lab"]
        expected_glow = {
            "start_distance": 0.0,
            "end_distance": 4.0,
            "strength": 1.25,
        }
        self.assertEqual(
            {
                "ecs_prototype_count": lab["ecs_prototype_count"],
                "display_instance_count": lab["display_instance_count"],
                "generated_copy_count": lab["generated_copy_count"],
                "preset": lab["preset"],
                "generated_members_are_ecs_entities": lab[
                    "generated_members_are_ecs_entities"
                ],
                "glow_by_distance": lab["glow_by_distance"],
            },
            {
                "ecs_prototype_count": 1,
                "display_instance_count": 256,
                "generated_copy_count": 255,
                "preset": "ring",
                "generated_members_are_ecs_entities": False,
                "glow_by_distance": expected_glow,
            },
        )
        recipe = next(
            node.metadata["polar_population"]
            for node in project.nodes
            if "polar_population" in node.metadata
        )
        self.assertEqual(recipe["preset"], "ring")
        self.assertEqual(recipe["glow_by_distance"], expected_glow)
        inspection = inspect_polar_population_pack(
            compile_polar_population_pack_bytes(project)
        )
        self.assertEqual(inspection["format_version"], 3)
        self.assertEqual(inspection["recipe_count"], 1)
        self.assertEqual(inspection["total_instances"], 256)
        self.assertEqual(
            [operator["code"] for operator in inspection["operators"][-3:]],
            [0x0050, 0x0051, 0x0052],
        )
        benchmark_harness._validate_glow_project_proof(
            project, BenchmarkCase(256, "lut", "subtle")
        )
        benchmark_harness._validate_recipe_build_report(
            inspection,
            BenchmarkCase(256, "lut", "subtle"),
            "glow",
        )
        corruptions = []
        wrong_version = json.loads(json.dumps(inspection))
        wrong_version["format_version"] = 2
        corruptions.append(wrong_version)
        wrong_strength = json.loads(json.dumps(inspection))
        wrong_strength["recipes"][0]["glow_by_distance"]["strength"] = 1.0
        corruptions.append(wrong_strength)
        wrong_mask = json.loads(json.dumps(inspection))
        wrong_mask["recipes"][0]["operator_mask"] ^= 1 << 9
        corruptions.append(wrong_mask)
        wrong_meaning = json.loads(json.dumps(inspection))
        next(
            operator
            for operator in wrong_meaning["operators"]
            if operator["code"] == 0x0052
        )["meaning_hash"] = "0000000000000000"
        corruptions.append(wrong_meaning)
        for corruption in corruptions:
            with self.subTest(corruption=corruption["sha256"]):
                with self.assertRaisesRegex(RuntimeError, "KCPR v3|Glow"):
                    benchmark_harness._validate_recipe_build_report(
                        corruption,
                        BenchmarkCase(256, "lut", "subtle"),
                        "glow",
                    )

    def test_grow_workload_builder_freezes_kcpr_v4_one_ecs_metadata(self) -> None:
        builder = load_lab_builder(RECIPE_LAB_GENERATOR)
        case = BenchmarkCase(256, "lut", "subtle")
        project = build_project_for_case(
            builder,
            case,
            seed=123,
            workload="grow",
        )
        expected_glow = {
            "start_distance": 0.0,
            "end_distance": 4.0,
            "strength": 1.25,
            "grow_copies": True,
        }
        lab = project.metadata["polar_recipe_lab"]
        self.assertEqual(lab["ecs_prototype_count"], 1)
        self.assertEqual(lab["display_instance_count"], 256)
        self.assertEqual(lab["generated_copy_count"], 255)
        self.assertFalse(lab["generated_members_are_ecs_entities"])
        self.assertEqual(lab["glow_by_distance"], expected_glow)

        recipe = next(
            node.metadata["polar_population"]
            for node in project.nodes
            if "polar_population" in node.metadata
        )
        self.assertEqual(recipe["preset"], "ring")
        self.assertEqual(recipe["glow_by_distance"], expected_glow)
        inspection = inspect_polar_population_pack(
            compile_polar_population_pack_bytes(project)
        )
        self.assertEqual(inspection["format_version"], 4)
        self.assertEqual(inspection["native_consumer"], "android-kcpr392-v4")
        self.assertEqual(inspection["operator_count"], 9)
        self.assertEqual(inspection["recipes"][0]["operator_mask"], 0x1E3B)
        self.assertEqual(inspection["operators"][-1]["code"], 0x0053)
        self.assertEqual(inspection["recipes"][0]["generated_copy_count"], 255)
        benchmark_harness._validate_grow_project_proof(project, case)
        benchmark_harness._validate_recipe_build_report(inspection, case, "grow")

        corruptions = []
        wrong_version = json.loads(json.dumps(inspection))
        wrong_version["format_version"] = 3
        corruptions.append(wrong_version)
        missing_flag = json.loads(json.dumps(inspection))
        missing_flag["recipes"][0]["glow_by_distance"].pop("grow_copies")
        corruptions.append(missing_flag)
        wrong_mask = json.loads(json.dumps(inspection))
        wrong_mask["recipes"][0]["operator_mask"] ^= 1 << 12
        corruptions.append(wrong_mask)
        wrong_meaning = json.loads(json.dumps(inspection))
        next(
            operator
            for operator in wrong_meaning["operators"]
            if operator["code"] == 0x0053
        )["meaning_hash"] = "0000000000000000"
        corruptions.append(wrong_meaning)
        for corruption in corruptions:
            with self.subTest(corruption=corruption["sha256"]):
                with self.assertRaisesRegex(RuntimeError, "KCPR v4|Grow"):
                    benchmark_harness._validate_recipe_build_report(
                        corruption,
                        case,
                        "grow",
                    )

    def test_runtime_proof_rejects_silent_fallback_and_wrong_bayer(self) -> None:
        case = BenchmarkCase(64, "lut", "subtle")
        valid_log = (
            "08-29 I/UGTS-KC392: render substrate polar_requested=lut "
            "polar_effective=lut gpu_instances=64 gpu_profiles=1 gpu_batches=1 "
            "cpu_fallbacks=0 animation_fallbacks=0 polar_recipes=0 generated=0 "
            "generated_gpu=0 generated_cpu=0 reason=none "
            "bayer=subtle levels=64 strength=0.300\n"
        )
        proof = validate_runtime_proof(case, valid_log)
        self.assertTrue(proof["valid"])
        self.assertIsNone(proof["observed"]["polar_material"])
        fallback = valid_log.replace("polar_effective=lut", "polar_effective=cpu")
        fallback = fallback.replace("gpu_instances=64", "gpu_instances=0")
        self.assertFalse(validate_runtime_proof(case, fallback)["valid"])
        wrong_bayer = valid_log.replace("bayer=subtle", "bayer=off")
        self.assertFalse(validate_runtime_proof(case, wrong_bayer)["valid"])
        self.assertFalse(validate_runtime_proof(case, "game launched")["valid"])

    def test_runtime_proof_accepts_complete_optional_polar_material_telemetry(self) -> None:
        case = BenchmarkCase(64, "lut", "subtle")
        legacy = (
            "I/UGTS-KC392: render substrate polar_requested=lut "
            "polar_effective=lut gpu_instances=64 gpu_profiles=1 gpu_batches=1 "
            "cpu_fallbacks=0 animation_fallbacks=0 polar_recipes=0 generated=0 "
            "generated_gpu=0 generated_cpu=0 reason=none "
            "bayer=subtle levels=64 strength=0.300\n"
        )
        modern = legacy.replace(
            "reason=none ",
            "reason=none polar_material=off material_bands=1 "
            "material_strength=0.000 ",
        )
        proof = validate_runtime_proof(case, modern)
        self.assertTrue(proof["valid"], proof["errors"])
        self.assertEqual(proof["observed"]["polar_material"], "off")
        self.assertEqual(proof["observed"]["material_bands"], 1)
        self.assertEqual(proof["observed"]["material_strength"], 0.0)

        partial = modern.replace("material_strength=0.000 ", "")
        self.assertFalse(validate_runtime_proof(case, partial)["valid"])
        unknown = modern.replace("polar_material=off", "polar_material=ribbons")
        self.assertFalse(validate_runtime_proof(case, unknown)["valid"])
        wrong_bands = modern.replace("material_bands=1", "material_bands=2")
        self.assertFalse(validate_runtime_proof(case, wrong_bands)["valid"])
        wrong_strength = modern.replace(
            "material_strength=0.000", "material_strength=0.500"
        )
        self.assertFalse(validate_runtime_proof(case, wrong_strength)["valid"])

    def test_runtime_proof_requires_exact_recipe_expansion_counts(self) -> None:
        case = BenchmarkCase(64, "lut", "subtle")
        valid_log = (
            "I/UGTS-KC392: render substrate polar_requested=lut "
            "polar_effective=lut gpu_instances=64 gpu_profiles=1 gpu_batches=1 "
            "cpu_fallbacks=0 animation_fallbacks=0 polar_recipes=1 generated=63 "
            "generated_gpu=63 generated_cpu=0 reason=none "
            "bayer=subtle levels=64 strength=0.300\n"
            "I/UGTS-KC392: polar population generated_total=63 "
            "generated_visible=63 visible_gpu=63 visible_cpu=0 "
            "materialized=63 cartesian_composed=0"
        )
        self.assertTrue(
            validate_runtime_proof(case, valid_log, workload="recipe")["valid"]
        )
        missing_copy = valid_log.replace("generated_gpu=63", "generated_gpu=62")
        self.assertFalse(
            validate_runtime_proof(case, missing_copy, workload="recipe")["valid"]
        )
        self.assertFalse(validate_runtime_proof(case, valid_log)["valid"])
        cpu_fallback = valid_log + "\nrender substrate polar runtime fallback"
        self.assertFalse(
            validate_runtime_proof(case, cpu_fallback, workload="recipe")["valid"]
        )

    def test_runtime_proof_freezes_burst_batch_and_full_bayer_cpu_paths(self) -> None:
        lut_case = BenchmarkCase(32, "lut", "subtle")
        lut_log = (
            "I/UGTS-KC392: render substrate polar_requested=lut "
            "polar_effective=lut gpu_instances=32 gpu_profiles=1 gpu_batches=2 "
            "cpu_fallbacks=0 animation_fallbacks=0 polar_recipes=1 generated=31 "
            "generated_gpu=31 generated_cpu=0 reason=none "
            "bayer=subtle levels=64 strength=0.300\n"
            "I/UGTS-KC392: polar population generated_total=31 "
            "generated_visible=31 visible_gpu=31 visible_cpu=0 "
            "materialized=31 cartesian_composed=0"
        )
        self.assertTrue(
            validate_runtime_proof(lut_case, lut_log, workload="burst")["valid"]
        )
        self.assertFalse(
            validate_runtime_proof(
                lut_case,
                lut_log.replace("gpu_batches=2", "gpu_batches=1"),
                workload="burst",
            )["valid"]
        )

        cpu_case = BenchmarkCase(32, "cpu", "subtle")
        cpu_log = (
            "I/UGTS-KC392: render substrate polar_requested=cpu "
            "polar_effective=cpu gpu_instances=0 gpu_profiles=0 gpu_batches=0 "
            "cpu_fallbacks=32 animation_fallbacks=0 polar_recipes=1 generated=31 "
            "generated_gpu=0 generated_cpu=31 reason=requested_cpu "
            "bayer=subtle levels=64 strength=0.300\n"
            "I/UGTS-KC392: polar population generated_total=31 "
            "generated_visible=31 visible_gpu=0 visible_cpu=31 "
            "materialized=31 cartesian_composed=31"
        )
        self.assertTrue(
            validate_runtime_proof(cpu_case, cpu_log, workload="burst")["valid"]
        )

    def test_glow_runtime_proof_requires_v3_stride_and_no_generated_ecs(self) -> None:
        case = BenchmarkCase(64, "lut", "subtle")
        render_line = (
            "I/UGTS-KC392: render substrate polar_requested=lut "
            "polar_effective=lut gpu_instances=64 gpu_profiles=1 gpu_batches=1 "
            "cpu_fallbacks=0 animation_fallbacks=0 polar_recipes=1 generated=63 "
            "generated_gpu=63 generated_cpu=0 reason=none "
            "bayer=subtle levels=64 strength=0.300\n"
        )
        visibility_line = (
            "I/UGTS-KC392: polar population generated_total=63 "
            "generated_visible=63 visible_gpu=63 visible_cpu=0 "
            "materialized=63 cartesian_composed=0\n"
        )
        format_line = (
            "I/UGTS-KC392: polar population format_version=3 recipes=1 "
            "generated=63 glow_recipes=1 glow_instances=64 "
            "gpu_instance_stride_bytes=36 ecs_generated=false"
        )
        log = render_line + visibility_line + format_line
        proof = validate_runtime_proof(case, log, workload="glow")
        self.assertTrue(proof["valid"], proof["errors"])
        self.assertEqual(proof["expected"]["gpu_batches"], 1)
        self.assertEqual(
            proof["population_format_observed"],
            {
                "format_version": 3,
                "recipes": 1,
                "generated": 63,
                "glow_recipes": 1,
                "glow_instances": 64,
                "gpu_instance_stride_bytes": 36,
                "ecs_generated": False,
                "line": format_line.split(": ", 1)[1],
            },
        )
        self.assertFalse(
            validate_runtime_proof(
                case, render_line + visibility_line, workload="glow"
            )["valid"]
        )
        self.assertFalse(
            validate_runtime_proof(
                case,
                render_line + visibility_line + format_line + " unexpected=true",
                workload="glow",
            )["valid"]
        )
        self.assertFalse(
            validate_runtime_proof(
                case,
                render_line.replace("gpu_batches=1", "gpu_batches=2")
                + visibility_line
                + format_line,
                workload="glow",
            )["valid"]
        )
        for old, new in (
            ("format_version=3", "format_version=2"),
            ("recipes=1", "recipes=2"),
            ("generated=63", "generated=62"),
            ("glow_recipes=1", "glow_recipes=0"),
            ("glow_instances=64", "glow_instances=63"),
            ("gpu_instance_stride_bytes=36", "gpu_instance_stride_bytes=32"),
            ("ecs_generated=false", "ecs_generated=true"),
        ):
            with self.subTest(field=old):
                self.assertFalse(
                    validate_runtime_proof(
                        case,
                        render_line + visibility_line + format_line.replace(old, new),
                        workload="glow",
                    )["valid"]
                )

        cpu_case = BenchmarkCase(64, "cpu", "off")
        cpu_log = (
            "I/UGTS-KC392: render substrate polar_requested=cpu "
            "polar_effective=cpu gpu_instances=0 gpu_profiles=0 gpu_batches=0 "
            "cpu_fallbacks=64 animation_fallbacks=0 polar_recipes=1 generated=63 "
            "generated_gpu=0 generated_cpu=63 reason=requested_cpu "
            "bayer=off levels=2 strength=0.000\n"
            "I/UGTS-KC392: polar population generated_total=63 "
            "generated_visible=63 visible_gpu=0 visible_cpu=63 "
            "materialized=63 cartesian_composed=63\n"
            + format_line
        )
        self.assertTrue(
            validate_runtime_proof(cpu_case, cpu_log, workload="glow")["valid"]
        )

    def test_grow_runtime_proof_requires_v4_generated_only_counts(self) -> None:
        case = BenchmarkCase(64, "lut", "subtle")
        render_line = (
            "I/UGTS-KC392: render substrate polar_requested=lut "
            "polar_effective=lut gpu_instances=64 gpu_profiles=1 gpu_batches=1 "
            "cpu_fallbacks=0 animation_fallbacks=0 polar_recipes=1 generated=63 "
            "generated_gpu=63 generated_cpu=0 reason=none "
            "bayer=subtle levels=64 strength=0.300\n"
        )
        visibility_line = (
            "I/UGTS-KC392: polar population generated_total=63 "
            "generated_visible=63 visible_gpu=63 visible_cpu=0 "
            "materialized=63 cartesian_composed=0\n"
        )
        format_line = (
            "I/UGTS-KC392: polar population format_version=4 recipes=1 "
            "generated=63 glow_recipes=1 glow_instances=64 "
            "grow_recipes=1 grow_instances=63 "
            "gpu_instance_stride_bytes=36 ecs_generated=false"
        )
        log = render_line + visibility_line + format_line
        proof = validate_runtime_proof(case, log, workload="grow")
        self.assertTrue(proof["valid"], proof["errors"])
        self.assertEqual(proof["expected"]["gpu_batches"], 1)
        self.assertEqual(
            proof["population_format_expected"],
            {
                "format_version": 4,
                "recipes": 1,
                "generated": 63,
                "glow_recipes": 1,
                "glow_instances": 64,
                "grow_recipes": 1,
                "grow_instances": 63,
                "gpu_instance_stride_bytes": 36,
                "ecs_generated": False,
            },
        )
        self.assertFalse(
            validate_runtime_proof(
                case,
                render_line + visibility_line,
                workload="grow",
            )["valid"]
        )
        for old, new in (
            ("format_version=4", "format_version=3"),
            ("glow_instances=64", "glow_instances=63"),
            ("grow_recipes=1", "grow_recipes=0"),
            ("grow_instances=63", "grow_instances=64"),
            ("gpu_instance_stride_bytes=36", "gpu_instance_stride_bytes=40"),
            ("ecs_generated=false", "ecs_generated=true"),
        ):
            with self.subTest(field=old):
                self.assertFalse(
                    validate_runtime_proof(
                        case,
                        render_line + visibility_line + format_line.replace(old, new),
                        workload="grow",
                    )["valid"]
                )

    def test_summary_only_compares_valid_real_profiles(self) -> None:
        direct = BenchmarkCase(64, "direct", "off")
        lut = BenchmarkCase(64, "lut", "off")
        subtle_direct = BenchmarkCase(64, "direct", "subtle")
        results = [
            _result(direct, valid=True, fps=118.0, p95=9.5),
            _result(lut, valid=True, fps=120.0, p95=8.8),
            _result(subtle_direct, valid=False, fps=119.0, p95=9.0),
        ]
        summary = comparison_summary(results, generated_at="fixed")
        self.assertEqual(summary["generated_at"], "fixed")
        polar = next(
            item
            for item in summary["comparisons"]
            if item["kind"] == "lut_minus_direct"
            and item["count"] == 64
            and item["bayer_mode"] == "off"
        )
        self.assertTrue(polar["available"])
        self.assertEqual(polar["delta_candidate_minus_baseline"]["effective_fps"], 2.0)
        self.assertAlmostEqual(
            polar["delta_candidate_minus_baseline"]["frame_ms_p95"], -0.7
        )
        bayer = next(
            item
            for item in summary["comparisons"]
            if item["kind"] == "subtle_minus_off"
            and item["count"] == 64
            and item["polar_mode"] == "direct"
        )
        self.assertFalse(bayer["available"])
        self.assertEqual(bayer["delta_candidate_minus_baseline"], {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
