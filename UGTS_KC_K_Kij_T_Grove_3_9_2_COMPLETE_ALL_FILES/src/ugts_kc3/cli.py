"""Command-line project creation, validation, simulation and export tools."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .androidexport import (
    build_android_project,
    inspect_scene_pack,
    write_mobile3d_gltf,
    write_scene_pack,
)
from .androidbuild import (
    build_apk,
    install_apk,
    list_android_devices,
    profile_android_app,
    supported_variants,
)
from .mobile3d import InputFrame3D, Mobile3DProject
from .project import GameProject
from .templates import (
    blank_vector_game_project,
    elizabeth_vector_quest_project,
    first_steps_project,
)
from .templates3d import (
    blank_mobile3d_project,
    first_steps_mobile3d_project,
    tom_signature_arena_project,
)
from .vector2d import write_vector_svg
from .version import __codename__, __edition__, __version__
from .packed_kinematics import (
    LogPolarProfile,
    PolarLookupTable,
    pack_ecs_document,
    unpack_ecs_document,
)
from .webexport import build_html5


def _positive_step_count(value: str) -> int:
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("steps must be a whole number") from exc
    if count < 1:
        raise argparse.ArgumentTypeError("steps must be at least 1")
    return count


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ugts-kc",
        description=f"UGTS-KC {__version__} — {__codename__} game-creation tools",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="show runtime and edition information")

    editor = sub.add_parser("editor", help="launch the UGTS desktop editor")
    editor.add_argument("project", type=Path, nargs="?")

    new = sub.add_parser("new", help="create a starter 2D vector-game project")
    new.add_argument("directory", type=Path)
    new.add_argument("--title", default="My KC Signature Game")
    new.add_argument("--author", default="")
    new.add_argument(
        "--template",
        choices=("first-steps", "blank", "elizabeth-quest"),
        default="first-steps",
    )
    new.add_argument("--build", action="store_true", help="also build an HTML5 dist directory")

    validate = sub.add_parser("validate", help="validate a 2D project.json file")
    validate.add_argument("project", type=Path)
    validate.add_argument("--json", action="store_true", dest="as_json")

    build = sub.add_parser("build-web", help="build a browser-playable HTML5 game")
    build.add_argument("project", type=Path)
    build.add_argument("output", type=Path)
    build.add_argument("--bundle", action="store_true", help="write runtime JavaScript separately")
    build.add_argument("--no-clean", action="store_true")

    simulate = sub.add_parser("simulate", help="run a headless deterministic 2D simulation")
    simulate.add_argument("project", type=Path)
    simulate.add_argument("--scene")
    simulate.add_argument("--steps", type=_positive_step_count, default=120)
    simulate.add_argument("--move-x", type=float, default=0.0)
    simulate.add_argument("--move-y", type=float, default=0.0)
    simulate.add_argument("--dash-at", type=int, default=-1)
    simulate.add_argument("--json", action="store_true", dest="as_json")

    svg = sub.add_parser("export-svg", help="write every vector asset as SVG")
    svg.add_argument("project", type=Path)
    svg.add_argument("output", type=Path)
    svg.add_argument("--background")

    demo = sub.add_parser("demo", help="write and build Elizabeth's Vector Garden demo")
    demo.add_argument("directory", type=Path)
    demo.add_argument("--author", default="Tom Klootwijk")

    new3d = sub.add_parser("new-3d", help="create a mobile 3D project")
    new3d.add_argument("directory", type=Path)
    new3d.add_argument("--title", default="My UGTS-KC Mobile 3D Game")
    new3d.add_argument("--author", default="")
    new3d.add_argument(
        "--template",
        choices=("first-steps", "blank", "signature-arena"),
        default="first-steps",
    )
    new3d.add_argument("--android", action="store_true", help="also materialize the native Android project")
    new3d.add_argument("--profile", default="auto")

    validate3d = sub.add_parser("validate-3d", help="validate a mobile 3D project")
    validate3d.add_argument("project", type=Path)
    validate3d.add_argument("--json", action="store_true", dest="as_json")

    simulate3d = sub.add_parser("simulate-3d", help="run deterministic 3D arcade simulation")
    simulate3d.add_argument("project", type=Path)
    simulate3d.add_argument("--steps", type=_positive_step_count, default=240)
    simulate3d.add_argument("--move-x", type=float, default=0.0)
    simulate3d.add_argument("--move-z", type=float, default=-1.0)
    simulate3d.add_argument("--jump-at", type=int, default=-1)
    simulate3d.add_argument("--json", action="store_true", dest="as_json")

    pack3d = sub.add_parser("pack-3d", help="compile a KC3D392 native binary scene")
    pack3d.add_argument("project", type=Path)
    pack3d.add_argument("output", type=Path)
    pack3d.add_argument("--inspect", action="store_true")

    gltf3d = sub.add_parser("export-gltf3d", help="export a mobile 3D project through the retained glTF path")
    gltf3d.add_argument("project", type=Path)
    gltf3d.add_argument("output", type=Path)

    android = sub.add_parser("build-android", help="materialize a native Android Studio source project")
    android.add_argument("project", type=Path)
    android.add_argument("output", type=Path)
    android.add_argument("--profile", default="auto")
    android.add_argument("--no-clean", action="store_true")
    android.add_argument(
        "--debug-assets", action="store_true",
        help="package authoring JSON/inspection evidence into the APK for debugging",
    )
    android.add_argument(
        "--apk", action="store_true",
        help="compile an APK after generating the Android project",
    )
    android.add_argument(
        "--install", action="store_true",
        help="compile and install on the selected ADB device",
    )
    android.add_argument(
        "--variant", choices=supported_variants(), default="poco-debug",
        help="Gradle flavor/build type used by --apk or --install",
    )
    android.add_argument("--serial", help="ADB serial used by --install")
    android.add_argument(
        "--gradle-clean", action="store_true",
        help="run Gradle clean before compiling the APK",
    )

    devices = sub.add_parser(
        "android-devices", help="list attached Android Debug Bridge devices"
    )
    devices.add_argument("--json", action="store_true", dest="as_json")

    phone_profile = sub.add_parser(
        "profile-android",
        help="measure a running Android game's frames, memory and thermals",
    )
    phone_profile.add_argument("application_id")
    phone_profile.add_argument("--seconds", type=float, default=30.0)
    phone_profile.add_argument("--sample-seconds", type=float, default=5.0)
    phone_profile.add_argument("--serial")
    phone_profile.add_argument("--json", action="store_true", dest="as_json")
    phone_profile.add_argument("--output", type=Path)

    pack_ecs = sub.add_parser(
        "pack-ecs", help="compress project/ECS/graph JSON into a small UGECS1 file"
    )
    pack_ecs.add_argument("source", type=Path)
    pack_ecs.add_argument("output", type=Path)

    unpack_ecs = sub.add_parser(
        "unpack-ecs", help="restore a UGECS1 file to readable JSON"
    )
    unpack_ecs.add_argument("source", type=Path)
    unpack_ecs.add_argument("output", type=Path)

    polar_lut = sub.add_parser(
        "make-polar-lut",
        help="build a compact shared binary16 log-encoded polar LUT",
    )
    polar_lut.add_argument("output", type=Path)
    polar_lut.add_argument("--resolution", type=int, default=256)
    polar_lut.add_argument("--rho-min", type=float, default=-12.0)
    polar_lut.add_argument("--rho-max", type=float, default=12.0)

    chrono = sub.add_parser(
        "compile-chrono-video",
        help=(
            "compile exact video timing, a separate log-polar GPU LUT, and "
            "proposal-only chrono-spatial evidence"
        ),
    )
    chrono.add_argument("source", type=Path)
    chrono.add_argument("output", type=Path)
    chrono.add_argument("--backend", choices=("auto", "cuda", "cpu"), default="auto")
    chrono.add_argument("--theta-bins", type=int, default=1024)
    chrono.add_argument("--rho-bins", type=int, default=512)
    chrono.add_argument("--sample-stride", type=int, default=4)
    chrono.add_argument("--tile-size", type=int, default=64)
    chrono.add_argument("--batch-size", type=int, default=8)
    chrono.add_argument("--max-vram-mib", type=int, default=1536)
    chrono.add_argument(
        "--target-kind",
        choices=("scene", "human"),
        default="scene",
        help="user-declared specialization; human adds no learned body completion",
    )
    chrono.add_argument(
        "--embed-source-for-phone",
        action="store_true",
        help=(
            "copy an MP4 byte-for-byte into the bundle and emit its exact-PTS "
            "on-phone runtime timeline"
        ),
    )
    chrono.add_argument("--json", action="store_true", dest="as_json")

    verify_chrono = sub.add_parser(
        "verify-chrono-video",
        help="verify a chrono-video bundle, hashes, exact PTS ledger, and authority guards",
    )
    verify_chrono.add_argument("bundle", type=Path)
    verify_chrono.add_argument(
        "--no-source-bytes",
        action="store_true",
        help="verify the bundle without requiring its external authoritative MP4",
    )
    verify_chrono.add_argument("--output", type=Path)
    verify_chrono.add_argument("--json", action="store_true", dest="as_json")

    return parser


def _print_2d_report(project: GameProject, as_json: bool) -> int:
    report = project.validate(raise_on_error=False)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"{'PASS' if report.passed else 'FAIL'}: {project.metadata.title} ({project.metadata.id})")
        for key, value in report.metrics.items():
            print(f"  {key}: {value}")
        for issue in report.issues:
            print(f"  {issue.severity.upper()} {issue.code} {issue.path}: {issue.message}")
    return 0 if report.passed else 2


def _print_3d_report(project: Mobile3DProject, as_json: bool) -> int:
    report = project.validate(raise_on_error=False)
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    else:
        print(f"{'PASS' if report.passed else 'FAIL'}: {project.title} ({project.id})")
        for key, value in report.metrics.items():
            print(f"  {key}: {value}")
        for issue in report.issues:
            print(f"  {issue.severity.upper()} {issue.code} {issue.path}: {issue.message}")
    return 0 if report.passed else 2


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "info":
            print(f"UGTS-KC {__version__}")
            print(f"Edition: {__edition__}")
            print("2D: vector art, deterministic game world, collision, animation, tilemaps, audio and HTML5 export")
            print("3D: validated mobile scene projects, deterministic arcade physics, glTF/KC3D scene packs and native Android NDK/GLES3 source export")
            print("Android: POCO X7 Pro 12 GB signature profile plus high, balanced and compatibility device tiers")
            print("Chrono video: exact-PTS observation/proposal compiler with separate CVLUT1 log-polar GPU cache")
            print("4D geometry: no metric or hidden-surface reconstruction is claimed without bounded physical evidence")
            return 0

        if args.command == "editor":
            try:
                from .editor import run_editor
            except ImportError as exc:
                raise RuntimeError(
                    "the desktop editor requires PySide6 (pip install PySide6)"
                ) from exc
            return int(run_editor(args.project))

        if args.command == "android-devices":
            devices = list_android_devices()
            payload = [device.__dict__ | {"ready": device.ready} for device in devices]
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            elif not devices:
                print("No ADB devices attached.")
            else:
                for device in devices:
                    label = f" ({device.model})" if device.model else ""
                    print(f"{device.serial}\t{device.state}{label}")
            return 0

        if args.command == "profile-android":
            result = profile_android_app(
                args.application_id,
                serial=args.serial,
                seconds=args.seconds,
                sample_seconds=args.sample_seconds,
            )
            payload = result.to_dict()
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(result.summary)
                print(
                    f"  {result.effective_fps:.2f} FPS · "
                    f"p95 {result.frame_ms_p95:.2f} ms · "
                    f"{result.frame_intervals} measured intervals"
                )
                if result.pss_kib_max is not None:
                    print(f"  peak process memory {result.pss_kib_max / 1024:.1f} MiB PSS")
                if result.cpu_one_core_pct_mean is not None:
                    phone_share = (
                        f" · {result.cpu_total_capacity_pct_mean:.1f}% of the whole phone"
                        if result.cpu_total_capacity_pct_mean is not None
                        else ""
                    )
                    print(
                        "  average CPU "
                        f"{result.cpu_one_core_pct_mean:.1f}% of one core{phone_share}"
                    )
                if result.gpu_render_ms_mean_since_renderer_start is not None:
                    maximum = (
                        f" · max {result.gpu_render_ms_max_since_renderer_start:.3f} ms"
                        if result.gpu_render_ms_max_since_renderer_start is not None
                        else ""
                    )
                    print(
                        "  GPU drawing since renderer start: average "
                        f"{result.gpu_render_ms_mean_since_renderer_start:.3f} ms{maximum} "
                        "(non-blocking timer)"
                    )
                elif result.gpu_timer_supported is False:
                    print("  GPU drawing timer unsupported; no estimate reported")
                if result.gpu_c_max is not None:
                    print(f"  peak reported GPU temperature {result.gpu_c_max:.1f} °C")
                for warning in result.warnings:
                    print(f"  ! {warning}")
                if args.output is not None:
                    print(f"  saved {args.output}")
            return 0

        if args.command == "pack-ecs":
            document = json.loads(args.source.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("ECS source root must be a JSON object")
            payload = pack_ecs_document(document)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(payload)
            ratio = len(payload) / max(1, args.source.stat().st_size)
            print(f"{args.output} ({len(payload)} bytes, {ratio:.1%} of source)")
            return 0

        if args.command == "unpack-ecs":
            document = unpack_ecs_document(args.source.read_bytes())
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(document, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            print(args.output)
            return 0

        if args.command == "make-polar-lut":
            table = PolarLookupTable.generate(
                LogPolarProfile(rho_min=args.rho_min, rho_max=args.rho_max),
                args.resolution,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(table.to_bytes())
            print(f"{args.output} ({args.output.stat().st_size} bytes)")
            return 0

        if args.command == "compile-chrono-video":
            # Kept lazy so the ordinary engine CLI does not require video,
            # OpenCV, NumPy, PyAV, or CUDA packages at import time.
            from .chrono_video import ChronoVideoProfile, compile_chrono_video

            result = compile_chrono_video(
                args.source,
                args.output,
                ChronoVideoProfile(
                    theta_bins=args.theta_bins,
                    rho_bins=args.rho_bins,
                    sample_stride=args.sample_stride,
                    tile_size=args.tile_size,
                    batch_size=args.batch_size,
                    max_vram_mib=args.max_vram_mib,
                    target_kind=args.target_kind,
                    embed_source_for_phone=args.embed_source_for_phone,
                ),
                backend=args.backend,
            )
            payload = result.to_dict()
            if args.as_json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(result.manifest)
                print(
                    f"{result.decoded_frames} exact-PTS frames; "
                    f"{result.analyzed_frames} analyzed; {result.compute_backend}; "
                    f"{result.elapsed_seconds:.3f} s"
                )
                if result.cuda_peak_mib is not None:
                    print(f"CUDA peak allocated: {result.cuda_peak_mib:.1f} MiB")
                print(f"editable scene: {result.project}")
            return 0

        if args.command == "verify-chrono-video":
            from .chrono_video import verify_chrono_bundle

            report = verify_chrono_bundle(
                args.bundle, verify_source_bytes=not args.no_source_bytes
            )
            if args.output is not None:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(
                    json.dumps(report, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            if args.as_json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(f"PASS: {report['bundle']}")
                print(
                    f"  {report['observation_count']} exact-PTS observations; "
                    f"{report['proposal_count']} proposal slices; "
                    f"{report['asset_count']} hash-verified assets"
                )
                print(f"  geometry: {report['geometry_status']}")
            return 0

        if args.command == "new":
            if args.template == "elizabeth-quest":
                project = elizabeth_vector_quest_project(args.author)
            elif args.template == "blank":
                project = blank_vector_game_project(args.title, args.author)
            else:
                project = first_steps_project(args.title, args.author)
            args.directory.mkdir(parents=True, exist_ok=True)
            project_path = project.write(args.directory / "project.json")
            (args.directory / "README.md").write_text(
                f"# {project.metadata.title}\n\n```bash\npython -m ugts_kc3 validate project.json\npython -m ugts_kc3 build-web project.json dist\n```\n",
                encoding="utf-8",
            )
            print(project_path)
            if args.build:
                print(build_html5(project, args.directory / "dist").entrypoint)
            return 0

        if args.command == "validate":
            return _print_2d_report(GameProject.load(args.project, validate=False), args.as_json)

        if args.command == "build-web":
            result = build_html5(GameProject.load(args.project), args.output, single_file=not args.bundle, clean=not args.no_clean)
            print(result.entrypoint)
            print(f"{len(result.files)} files, {result.total_bytes} bytes, project {result.project_hash[:12]}")
            return 0

        if args.command == "simulate":
            project = GameProject.load(args.project)
            world = project.instantiate_world(args.scene)
            previous = None
            for step in range(args.steps):
                values = {"move_x": args.move_x, "move_y": args.move_y, "dash": 1.0 if step == args.dash_at else 0.0}
                frame = project.input_map.frame_from_actions(values, previous)
                world.step(frame)
                previous = frame
            summary = {"schema": "ugts-kc-headless-summary-3.9.2", "dimension": "2D", "steps": args.steps, "tick": world.tick, "time": world.time, "entities": len(world.entities), "state": world.state, "events": len(world.events), "state_hash": world.state_hash()}
            print(json.dumps(summary, indent=2, sort_keys=True) if args.as_json else "\n".join(f"{k}: {v}" for k, v in summary.items()))
            return 0

        if args.command == "export-svg":
            project = GameProject.load(args.project)
            args.output.mkdir(parents=True, exist_ok=True)
            for asset in project.vector_assets:
                write_vector_svg(asset, args.output / f"{asset.id}.svg", args.background, padding=8)
            print(f"wrote {len(project.vector_assets.assets)} SVG assets to {args.output}")
            return 0

        if args.command == "demo":
            args.directory.mkdir(parents=True, exist_ok=True)
            project = elizabeth_vector_quest_project(args.author)
            project.write(args.directory / "project.json")
            print(build_html5(project, args.directory / "dist").entrypoint)
            return 0

        if args.command == "new-3d":
            if args.template == "signature-arena":
                project = tom_signature_arena_project(args.author)
            elif args.template == "blank":
                project = blank_mobile3d_project(args.title, args.author)
            else:
                project = first_steps_mobile3d_project(args.title, args.author)
            args.directory.mkdir(parents=True, exist_ok=True)
            path = project.write(args.directory / "project.json")
            print(path)
            if args.android:
                result = build_android_project(project, args.directory / "android", args.profile)
                print(result.output_dir)
            return 0

        if args.command == "validate-3d":
            return _print_3d_report(Mobile3DProject.load(args.project, validate=False), args.as_json)

        if args.command == "simulate-3d":
            project = Mobile3DProject.load(args.project)
            world = project.instantiate_world()
            for step in range(args.steps):
                frame = InputFrame3D(args.move_x, args.move_z, jump=(step == args.jump_at))
                world.step(frame)
            summary = {"schema": "ugts-kc-headless-summary-3.9.2", "dimension": "3D", "steps": args.steps, "tick": world.tick, "time": world.time, "entities": len(world.entities), "state": world.state, "events": len(world.events), "state_hash": world.state_hash()}
            print(json.dumps(summary, indent=2, sort_keys=True) if args.as_json else "\n".join(f"{k}: {v}" for k, v in summary.items()))
            return 0

        if args.command == "pack-3d":
            project = Mobile3DProject.load(args.project)
            path = write_scene_pack(project, args.output)
            print(path)
            if args.inspect:
                print(json.dumps(inspect_scene_pack(path), indent=2, sort_keys=True))
            return 0

        if args.command == "export-gltf3d":
            write_mobile3d_gltf(Mobile3DProject.load(args.project), args.output)
            print(args.output)
            return 0

        if args.command == "build-android":
            result = build_android_project(
                Mobile3DProject.load(args.project),
                args.output,
                args.profile,
                clean=not args.no_clean,
                include_authoring_assets=args.debug_assets,
                asset_source_root=args.project.resolve().parent,
            )
            print(result.output_dir)
            print(f"{result.file_count} files, {result.total_bytes} bytes, project {result.project_hash[:12]}")
            if args.apk or args.install:
                compiled = build_apk(
                    result.output_dir,
                    args.variant,
                    clean=args.gradle_clean,
                )
                print(compiled.apk)
                if args.install:
                    installed = install_apk(compiled.apk, serial=args.serial)
                    print(f"installed on {installed.serial}")
            return 0

        raise AssertionError("unreachable command")
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
