"""Launch ``python -m ugts_kc3.editor [project.json]``."""
from __future__ import annotations

import argparse

from . import run_editor


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ugts_kc3.editor",
        description="Open UGTS Studio, the visual 2D/mobile-3D project editor.",
    )
    parser.add_argument("project", nargs="?", help="optional project.json to open")
    args = parser.parse_args()
    return run_editor(args.project)


if __name__ == "__main__":
    raise SystemExit(main())
