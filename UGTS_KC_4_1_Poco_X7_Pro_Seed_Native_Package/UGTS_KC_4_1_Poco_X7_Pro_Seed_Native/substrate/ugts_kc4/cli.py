"""Command-line workflow for UGTS-KC 4.0 spatial evidence projects."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .export import build_offline_html, write_geojson
from .ledger import SpatialLedger
from .project import SpatialEvidenceProject
from .templates import run_safe_route_demo, safe_route_demo_project
from .topology import RouteGraph
from .version import __android_status__, __edition__, __mechanism_range__, __schema__, __version__


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ugts-spatial", description=__edition__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("info", help="print release identity and capability boundary")

    new = sub.add_parser("new", help="write the SafeRoute spatial evidence template")
    new.add_argument("directory", type=Path)
    new.add_argument("--author", default="Tom Klootwijk")

    validate = sub.add_parser("validate", help="validate a spatial evidence project")
    validate.add_argument("project", type=Path)
    validate.add_argument("--json", action="store_true", dest="as_json")

    demo = sub.add_parser("demo", help="run the checked-in SafeRoute + DamageDelta vertical slice")
    demo.add_argument("directory", type=Path)
    demo.add_argument("--author", default="Tom Klootwijk")
    demo.add_argument("--json", action="store_true", dest="as_json")

    inspect = sub.add_parser("inspect-ledger", help="inspect a ledger and verify its hashes")
    inspect.add_argument("ledger", type=Path)
    inspect.add_argument("--json", action="store_true", dest="as_json")

    route = sub.add_parser("route", help="run a declared route policy against a ledger")
    route.add_argument("project", type=Path)
    route.add_argument("ledger", type=Path)
    route.add_argument("start")
    route.add_argument("goal")
    route.add_argument("--policy", default="wheelchair-reference")
    route.add_argument("--json", action="store_true", dest="as_json")

    export = sub.add_parser("export-html", help="create a self-contained offline HTML report")
    export.add_argument("project", type=Path)
    export.add_argument("ledger", type=Path)
    export.add_argument("output", type=Path)

    geo = sub.add_parser("export-geojson", help="write a GeoJSON projection of a ledger")
    geo.add_argument("ledger", type=Path)
    geo.add_argument("output", type=Path)

    sub.add_parser("android-status", help="show the explicit 4.0 Android deferral boundary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "info":
            print(__edition__)
            print(f"Runtime version: {__version__}")
            print(f"Project schema: {__schema__}")
            print(f"Mechanism delta: {__mechanism_range__}")
            print("Core: capture profiles, uncertainty, support/compatibility verification, stable map identity, routes, change ledger, replay and offline export")
            print(f"Android: {__android_status__}")
            return 0

        if args.command == "new":
            args.directory.mkdir(parents=True, exist_ok=True)
            project = safe_route_demo_project(args.author)
            path = project.write(args.directory / "project.json")
            (args.directory / "README.md").write_text(
                "# UGTS-KC 4.0 spatial project\n\n"
                "```bash\nugts-spatial validate project.json\nugts-spatial demo build\n```\n",
                encoding="utf-8",
            )
            print(path)
            return 0

        if args.command == "validate":
            project = SpatialEvidenceProject.load(args.project, validate=False)
            report = project.validate()
            if args.as_json:
                print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            else:
                print(f"{'PASS' if report.passed else 'FAIL'}: {project.metadata.title}")
                for key, value in report.metrics.items():
                    print(f"  {key}: {value}")
                for issue in report.issues:
                    print(f"  {issue.severity.upper()} {issue.code} {issue.path}: {issue.message}")
            return 0 if report.passed else 2

        if args.command == "demo":
            summary = run_safe_route_demo(args.directory, args.author)
            if args.as_json:
                print(json.dumps(summary, indent=2, sort_keys=True))
            else:
                print(args.directory / "offline_report.html")
                print(f"events: {summary['total_events']}")
                print(f"route before: {summary['baseline_route']['node_path']}")
                print(f"route after: {summary['changed_route']['node_path']}")
                print(f"state hash: {summary['state_hash']}")
            return 0

        if args.command == "inspect-ledger":
            ledger = SpatialLedger.load(args.ledger)
            summary = {
                "sequence": ledger.sequence,
                "nodes": len(ledger.map_state.nodes),
                "edges": len(ledger.map_state.edges),
                "state_hash": ledger.state_hash(),
                "event_stream_hash": ledger.event_stream_hash(),
                "checkpoints": len(ledger.checkpoints),
                "rejected": len(ledger.rejected),
            }
            print(json.dumps(summary, indent=2, sort_keys=True) if args.as_json else "\n".join(f"{key}: {value}" for key, value in summary.items()))
            return 0

        if args.command == "route":
            project = SpatialEvidenceProject.load(args.project)
            ledger = SpatialLedger.load(args.ledger)
            policy = project.route_policy_map.get(args.policy)
            if policy is None:
                raise ValueError(f"unknown route policy: {args.policy}")
            result = RouteGraph(ledger.map_state).shortest_path(args.start, args.goal, policy)
            print(json.dumps(result.to_dict(), indent=2, sort_keys=True) if args.as_json else f"{result.reason}: {' -> '.join(result.node_path)} (cost={result.cost})")
            return 0 if result.found else 3

        if args.command == "export-html":
            project = SpatialEvidenceProject.load(args.project)
            ledger = SpatialLedger.load(args.ledger)
            print(build_offline_html(project, ledger, args.output))
            return 0

        if args.command == "export-geojson":
            ledger = SpatialLedger.load(args.ledger)
            print(write_geojson(args.output, ledger.map_state))
            return 0

        if args.command == "android-status":
            print("UGTS-KC 4.0 does not implement or retune a phone-specific Android app.")
            print("The attached 3.9.1 NativeActivity/C++20/EGL/OpenGL ES 3.0 implementation is retained unchanged under android/ and src/ugts_kc3/android_template/ as a frozen reference.")
            print("Future device work must begin from that validated source and only after the spatial substrate interfaces are frozen.")
            return 0

        raise AssertionError("unreachable command")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
