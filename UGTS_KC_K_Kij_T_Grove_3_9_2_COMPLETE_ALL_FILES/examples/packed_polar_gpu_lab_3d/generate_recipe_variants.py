"""Generate the tiny one-prototype KCPR version of the packed-polar lab.

Unlike ``generate_variants.py``, which deliberately creates N real ECS movers
for ECS scaling tests, this builder keeps one mover and derives the remaining
display members from one content-addressed polar recipe.  It is the compact
render-substrate workload; generated members never become ECS entities.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from dataclasses import replace
import json
from numbers import Integral
from pathlib import Path
import sys


EXAMPLE_DIR = Path(__file__).resolve().parent
ROOT = EXAMPLE_DIR.parents[1]
SRC = ROOT / "src"
if str(EXAMPLE_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_DIR))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import generate_variants as authored_lab  # noqa: E402
from ugts_kc3.mobile3d import Mobile3DProject  # noqa: E402
from ugts_kc3.polar_population import (  # noqa: E402
    POLAR_POPULATION_PRESETS,
    PolarPopulationRecipe,
    operators_for_mask,
    polar_population_preset,
)
from ugts_kc3.polar_population_pack import (  # noqa: E402
    POLAR_POPULATION_RECIPE_BYTES,
    compile_polar_population_pack_bytes,
    inspect_polar_population_pack,
)
from ugts_kc3.polarpack import compile_polar_pack_bytes  # noqa: E402


LEGACY_WORKLOAD_COUNTS = authored_lab.WORKLOAD_COUNTS
BURST_WORKLOAD_COUNTS = (32, 128, 384)
WORKLOAD_COUNTS = tuple(sorted({*LEGACY_WORKLOAD_COUNTS, *BURST_WORKLOAD_COUNTS}))
DEFAULT_COUNT = authored_lab.DEFAULT_COUNT
DEFAULT_SEED = authored_lab.DEFAULT_SEED
DEFAULT_RECIPE_SEED = 0x504F4C4152393201
UINT64_MASK = (1 << 64) - 1
GROW_ONE_CLICK_PROFILE = "grow-burst-128-lut-subtle-glow-0-4-1.25-v1"


def build_project(
    count: int | None = None,
    *,
    polar_mode: str = "auto",
    bayer_mode: str = "subtle",
    levels: int | None = None,
    strength: float | None = None,
    seed: int = DEFAULT_SEED,
    recipe_seed: int = DEFAULT_RECIPE_SEED,
    preset: str = "ring",
    glow_by_distance: bool = False,
    grow_glowing_copies: bool = False,
    glow_start_distance: float = 0.0,
    glow_end_distance: float = 4.0,
    glow_strength: float = 1.25,
):
    """Build one bounded display workload from one real ECS prototype."""

    if preset not in POLAR_POPULATION_PRESETS:
        raise ValueError(f"preset must be one of {', '.join(POLAR_POPULATION_PRESETS)}")
    if grow_glowing_copies and not glow_by_distance:
        raise ValueError("grow_glowing_copies requires glow_by_distance")
    if count is None:
        count = BURST_WORKLOAD_COUNTS[0] if preset == "burst" else DEFAULT_COUNT
    allowed_counts = (
        BURST_WORKLOAD_COUNTS if preset == "burst" else LEGACY_WORKLOAD_COUNTS
    )
    if (
        isinstance(count, bool)
        or not isinstance(count, Integral)
        or int(count) not in allowed_counts
    ):
        raise ValueError(f"count for {preset!r} must be one of {allowed_counts}")
    if (
        isinstance(recipe_seed, bool)
        or not isinstance(recipe_seed, Integral)
        or not 0 <= int(recipe_seed) <= UINT64_MASK
    ):
        raise ValueError("recipe seed must be an unsigned 64-bit integer")
    # Reuse the exact camera, mesh, material, profile, graph and KCRP settings
    # from the authored-ECS A/B lab. Only representation/count changes.
    project = authored_lab.build_project(
        DEFAULT_COUNT,
        polar_mode=polar_mode,
        bayer_mode=bayer_mode,
        levels=levels,
        strength=strength,
        seed=seed,
    )
    prototype = next(node for node in project.nodes if node.id == "orbit_mover_0000")
    environment = tuple(
        node
        for node in project.nodes
        if node.metadata.get("role") == "nonpolar_environment"
    )
    recipe = polar_population_preset(
        preset,
        instance_count=int(count),
        seed=int(recipe_seed),
    )
    if glow_by_distance:
        recipe_data = recipe.to_dict()
        recipe_data["glow_by_distance"] = {
            "start_distance": glow_start_distance,
            "end_distance": glow_end_distance,
            "strength": glow_strength,
        } | ({"grow_copies": True} if grow_glowing_copies else {})
        recipe = PolarPopulationRecipe.from_mapping(recipe_data)
    prototype = replace(
        prototype,
        metadata={
            **prototype.metadata,
            "polar_population": recipe.to_dict(),
        },
    )
    project = replace(
        project,
        id="packed_polar_recipe_lab_3d",
        title=(
            f"Packed Polar Grow Lab — {int(count)} displays from one ECS mover"
            if grow_glowing_copies
            else f"Packed Polar Glow Lab — {int(count)} displays from one ECS mover"
            if glow_by_distance
            else (
                f"Packed Polar Burst Lab — {int(count)} displays from one ECS mover"
                if preset == "burst"
                else f"Packed Polar Recipe Lab — {int(count)} displays from one ECS mover"
            )
        ),
        nodes=environment + (prototype,),
        metadata={
            key: value for key, value in project.metadata.items() if key != "polar_lab"
        }
        | {
            "polar_recipe_lab": {
                "ecs_prototype_count": 1,
                "display_instance_count": int(count),
                "generated_copy_count": int(count) - 1,
                "preset": preset,
                "root_seed": int(seed),
                "recipe_seed": int(recipe_seed),
                "generated_members_are_ecs_entities": False,
                "generator": "generate_recipe_variants.py",
            }
            | (
                {
                    "glow_by_distance": {
                        "start_distance": float(glow_start_distance),
                        "end_distance": float(glow_end_distance),
                        "strength": float(glow_strength),
                    }
                    | ({"grow_copies": True} if grow_glowing_copies else {})
                }
                if glow_by_distance
                else {}
            )
        },
    )
    project.validate()
    packed = compile_polar_pack_bytes(project)
    recipe_pack = compile_polar_population_pack_bytes(project)
    if not packed:
        raise AssertionError("recipe prototype must retain one KCPK component")
    expected_recipe_size = (
        32
        + len(operators_for_mask(recipe.operator_mask)) * 16
        + POLAR_POPULATION_RECIPE_BYTES
    )
    if len(recipe_pack) != expected_recipe_size:
        raise AssertionError(
            f"unexpected KCPR size: {len(recipe_pack)} != {expected_recipe_size}"
        )
    return project


def _uint64(text: str) -> int:
    value = int(text, 0)
    if not 0 <= value <= UINT64_MASK:
        raise argparse.ArgumentTypeError("value must fit uint64")
    return value


def _validate_existing_grow_project(
    path: Path,
) -> tuple[Mobile3DProject, Mapping[str, object]]:
    """Fail closed unless ``path`` is a valid one-prototype KCPR v4 Grow lab."""

    if not path.is_file():
        raise ValueError(f"Grow lab project does not exist: {path}")
    project = Mobile3DProject.load(path)
    inspection = inspect_polar_population_pack(
        compile_polar_population_pack_bytes(project),
        node_count=len(project.nodes),
    )
    recipes = inspection.get("recipes")
    recipe = recipes[0] if isinstance(recipes, list) and len(recipes) == 1 else None
    recipe_glow = recipe.get("glow_by_distance") if isinstance(recipe, Mapping) else None
    lab = project.metadata.get("polar_recipe_lab")
    lab_glow = lab.get("glow_by_distance") if isinstance(lab, Mapping) else None
    render = project.metadata.get("substrate_render")
    if (
        inspection.get("format_version") != 4
        or inspection.get("recipe_count") != 1
        or inspection.get("ecs_prototype_count") != 1
        or inspection.get("generated_members_are_ecs_entities") is not False
        or not isinstance(recipe_glow, Mapping)
        or recipe_glow.get("grow_copies") is not True
        or not isinstance(lab, Mapping)
        or lab.get("ecs_prototype_count") != 1
        or lab.get("generated_members_are_ecs_entities") is not False
        or not isinstance(lab_glow, Mapping)
        or lab_glow.get("grow_copies") is not True
    ):
        raise ValueError(
            "existing project is not a one-prototype KCPR v4 Grow-glowing-copies lab"
        )
    legacy_exact_profile = (
        inspection.get("total_instances") == 128
        and inspection.get("generated_copy_count") == 127
        and isinstance(recipe, Mapping)
        and recipe.get("preset") == "burst"
        and recipe.get("instance_count") == 128
        and lab.get("display_instance_count") == 128
        and lab.get("generated_copy_count") == 127
        and lab.get("preset") == "burst"
        and (
            lab_glow.get("start_distance"),
            lab_glow.get("end_distance"),
            lab_glow.get("strength"),
        )
        == (0.0, 4.0, 1.25)
        and isinstance(render, Mapping)
        and render.get("polar_mode") == "lut"
        and render.get("bayer_mode") == "subtle"
    )
    if (
        lab.get("one_click_profile") != GROW_ONE_CLICK_PROFILE
        and not legacy_exact_profile
    ):
        raise ValueError(
            "existing Grow project does not belong to the 128 Burst/LUT/subtle "
            "one-click lab"
        )
    return project, inspection


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a one-prototype, content-addressed polar display workload."
    )
    parser.add_argument("--count", type=int, choices=WORKLOAD_COUNTS)
    parser.add_argument("--preset", choices=POLAR_POPULATION_PRESETS, default="ring")
    parser.add_argument(
        "--polar-mode", choices=authored_lab.POLAR_RENDER_MODES, default="auto"
    )
    parser.add_argument(
        "--bayer-mode", choices=authored_lab.BAYER_MODES, default="subtle"
    )
    parser.add_argument("--levels", type=int)
    parser.add_argument("--strength", type=float)
    parser.add_argument("--seed", type=_uint64, default=DEFAULT_SEED)
    parser.add_argument("--recipe-seed", type=_uint64, default=DEFAULT_RECIPE_SEED)
    parser.add_argument(
        "--glow-by-distance",
        action="store_true",
        help="add the optional seeded UGLUT2 material glow band",
    )
    parser.add_argument(
        "--grow-glowing-copies",
        action="store_true",
        help=(
            "grow generated display copies by the same bounded Glow field; "
            "requires --glow-by-distance"
        ),
    )
    parser.add_argument("--glow-start-distance", type=float, default=0.0)
    parser.add_argument("--glow-end-distance", type=float, default=4.0)
    parser.add_argument("--glow-strength", type=float, default=1.25)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--validate-existing",
        action="store_true",
        help="validate an existing --output Grow lab without rewriting it",
    )
    args = parser.parse_args()
    if args.validate_existing:
        if args.output is None:
            parser.error("--validate-existing requires --output")
        try:
            project, inspection = _validate_existing_grow_project(args.output)
        except (OSError, TypeError, ValueError) as error:
            parser.error(f"existing Grow lab failed validation: {error}")
        print(
            json.dumps(
                {
                    "output": str(args.output.resolve()),
                    "status": "validated",
                    "format_version": inspection["format_version"],
                    "ecs_prototypes": inspection["ecs_prototype_count"],
                    "display_instances": inspection["total_instances"],
                    "generated_copies": inspection["generated_copy_count"],
                    "content_sha256": project.content_hash(),
                    "kcpr_sha256": inspection["sha256"],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    count = (
        BURST_WORKLOAD_COUNTS[0]
        if args.count is None and args.preset == "burst"
        else DEFAULT_COUNT
        if args.count is None
        else args.count
    )
    project = build_project(
        count,
        polar_mode=args.polar_mode,
        bayer_mode=args.bayer_mode,
        levels=args.levels,
        strength=args.strength,
        seed=args.seed,
        recipe_seed=args.recipe_seed,
        preset=args.preset,
        glow_by_distance=args.glow_by_distance,
        grow_glowing_copies=args.grow_glowing_copies,
        glow_start_distance=args.glow_start_distance,
        glow_end_distance=args.glow_end_distance,
        glow_strength=args.glow_strength,
    )
    if (
        args.grow_glowing_copies
        and args.preset == "burst"
        and count == 128
        and args.polar_mode == "lut"
        and args.bayer_mode == "subtle"
        and (
            args.glow_start_distance,
            args.glow_end_distance,
            args.glow_strength,
        )
        == (0.0, 4.0, 1.25)
    ):
        project.metadata["polar_recipe_lab"][
            "one_click_profile"
        ] = GROW_ONE_CLICK_PROFILE
        project.validate()
    output = args.output or (
        ROOT
        / "build"
        / "packed-polar-recipe-lab"
        / (
            f"{count}-{args.preset}-{args.polar_mode}-{args.bayer_mode}"
            f"{'-grow' if args.grow_glowing_copies else '-glow' if args.glow_by_distance else ''}.json"
        )
    )
    project.write(output)
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "ecs_prototypes": 1,
                "display_instances": count,
                "generated_copies": count - 1,
                "preset": args.preset,
                "glow_by_distance": args.glow_by_distance,
                "grow_glowing_copies": args.grow_glowing_copies,
                "polar_mode": args.polar_mode,
                "bayer_mode": args.bayer_mode,
                "content_sha256": project.content_hash(),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
