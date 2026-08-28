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
from .game_input import InputFrame
from .mobile3d import InputFrame3D, Mobile3DProject
from .project import GameProject
from .templates import blank_vector_game_project, elizabeth_vector_quest_project
from .templates3d import blank_mobile3d_project, tom_signature_arena_project
from .vector2d import write_vector_svg
from .version import __codename__, __edition__, __version__
from .webexport import build_html5


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ugts-kc",
        description=f"UGTS-KC {__version__} — {__codename__} game-creation tools",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="show runtime and edition information")

    new = sub.add_parser("new", help="create a starter 2D vector-game project")
    new.add_argument("directory", type=Path)
    new.add_argument("--title", default="My KC Signature Game")
    new.add_argument("--author", default="")
    new.add_argument("--template", choices=("blank", "elizabeth-quest"), default="blank")
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
    simulate.add_argument("--steps", type=int, default=120)
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
    new3d.add_argument("--author", default="Tom Klootwijk")
    new3d.add_argument("--template", choices=("blank", "signature-arena"), default="blank")
    new3d.add_argument("--android", action="store_true", help="also materialize the native Android project")
    new3d.add_argument("--profile", default="auto")

    validate3d = sub.add_parser("validate-3d", help="validate a mobile 3D project")
    validate3d.add_argument("project", type=Path)
    validate3d.add_argument("--json", action="store_true", dest="as_json")

    simulate3d = sub.add_parser("simulate-3d", help="run deterministic 3D arcade simulation")
    simulate3d.add_argument("project", type=Path)
    simulate3d.add_argument("--steps", type=int, default=240)
    simulate3d.add_argument("--move-x", type=float, default=0.0)
    simulate3d.add_argument("--move-z", type=float, default=-1.0)
    simulate3d.add_argument("--jump-at", type=int, default=-1)
    simulate3d.add_argument("--json", action="store_true", dest="as_json")

    pack3d = sub.add_parser("pack-3d", help="compile a KC3D391 native binary scene")
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
            print("4D: design-contract TODO only; no 4D runtime is claimed in 3.9.1")
            return 0

        if args.command == "new":
            project = elizabeth_vector_quest_project(args.author) if args.template == "elizabeth-quest" else blank_vector_game_project(args.title, args.author)
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
            summary = {"schema": "ugts-kc-headless-summary-3.9.1", "dimension": "2D", "steps": args.steps, "tick": world.tick, "time": world.time, "entities": len(world.entities), "state": world.state, "events": len(world.events), "state_hash": world.state_hash()}
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
            project = tom_signature_arena_project(args.author) if args.template == "signature-arena" else blank_mobile3d_project(args.title, args.author)
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
            summary = {"schema": "ugts-kc-headless-summary-3.9.1", "dimension": "3D", "steps": args.steps, "tick": world.tick, "time": world.time, "entities": len(world.entities), "state": world.state, "events": len(world.events), "state_hash": world.state_hash()}
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
            result = build_android_project(Mobile3DProject.load(args.project), args.output, args.profile, clean=not args.no_clean)
            print(result.output_dir)
            print(f"{result.file_count} files, {result.total_bytes} bytes, project {result.project_hash[:12]}")
            return 0

        raise AssertionError("unreachable command")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
