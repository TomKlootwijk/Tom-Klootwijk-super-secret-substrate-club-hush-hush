"""Generate deterministic real-ECS packed-polar substrate workloads.

The checked-in authoring project uses 64 ordinary static scene nodes.  Larger
variants deliberately create more ordinary nodes; this module never substitutes
scatter/instancing metadata for the ECS workload being measured.
"""

from __future__ import annotations

import argparse
import json
import math
from numbers import Integral
from pathlib import Path
import sys


EXAMPLE_DIR = Path(__file__).resolve().parent
ROOT = EXAMPLE_DIR.parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ugts_kc3.math3d import quat_from_axis_angle  # noqa: E402
from ugts_kc3.mobile3d import (  # noqa: E402
    AndroidTargetProfile,
    Camera3DRecord,
    DirectionalLight3DRecord,
    Material3DRecord,
    Mobile3DProject,
    Node3DRecord,
    QualityTier3D,
    Transform3DRecord,
    World3DSettings,
    cube_mesh3d,
    plane_mesh3d,
    pyramid_mesh3d,
)
from ugts_kc3.packed_kinematics import (  # noqa: E402
    LogPolarProfile,
    MotionRange,
    PackedKinematicCodec,
    PolarLookupTable,
    PolarMotion,
    PolarPose,
)
from ugts_kc3.polarpack import PolarProfileSpec, quantized_profile_lut  # noqa: E402
from ugts_kc3.renderpack import (  # noqa: E402
    BAYER_MODES,
    POLAR_RENDER_MODES,
    compile_render_substrate_pack_bytes,
)
from ugts_kc3.visual_graph import GraphLink, GraphNode, VisualGraph  # noqa: E402


WORKLOAD_COUNTS = (64, 256, 1024)
DEFAULT_COUNT = 64
DEFAULT_SEED = 0x5EED3920C0DEC0DE
PROFILE_ID = "shared_orbit_profile"
GRAPH_ID = "periodic_owner_relative_reverse"
LUT_RESOLUTION = 256
TIMER_SECONDS = 1.0
RING_COUNT = 8
UINT64_MASK = (1 << 64) - 1


def splitmix64(value: int) -> int:
    """Return one SplitMix64-style output with explicit uint64 wrapping."""

    value = (int(value) + 0x9E3779B97F4A7C15) & UINT64_MASK
    value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & UINT64_MASK
    value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & UINT64_MASK
    return (value ^ (value >> 31)) & UINT64_MASK


def derived_word(seed: int, entity_index: int, channel: int) -> int:
    """Derive a stable independent stream word for one entity property."""

    mixed_index = (entity_index + 1) * 0xD1B54A32D192ED03
    mixed_channel = (channel + 1) * 0xABC98388FB8FAC03
    return splitmix64((seed ^ mixed_index ^ mixed_channel) & UINT64_MASK)


def unit_float(word: int) -> float:
    """Map a uint64 to the deterministic binary64 unit interval [0, 1)."""

    return (int(word) >> 11) * (1.0 / (1 << 53))


def reverse_graph() -> VisualGraph:
    """One owner-relative graph definition reused by every polar mover."""

    return VisualGraph(
        GRAPH_ID,
        (
            GraphNode(
                "timer",
                "event.timer",
                {"seconds": TIMER_SECONDS, "repeat": True},
                (0.0, 40.0),
            ),
            GraphNode(
                "read_turn_speed",
                "value.polar_movement",
                {
                    "entity": None,
                    "field": "turns_per_second",
                    "default": 0.0,
                },
                (0.0, 245.0),
            ),
            GraphNode(
                "reverse_number",
                "math.multiply",
                {"b": -1.0},
                (330.0, 245.0),
            ),
            GraphNode(
                "write_turn_speed",
                "action.set_polar_movement",
                {
                    "entity": None,
                    "field": "turns_per_second",
                },
                (650.0, 40.0),
            ),
        ),
        (
            GraphLink("timer", "out", "write_turn_speed", "in"),
            GraphLink("read_turn_speed", "value", "reverse_number", "a"),
            GraphLink("reverse_number", "result", "write_turn_speed", "value"),
        ),
        {
            "title": "Reverse this orbit every second",
            "beginner": True,
            "android_supported": True,
            "owner_relative": True,
            "proof": (
                "Timer reads this object's friendly polar turn speed, multiplies "
                "it by -1, then writes it back through dedicated Movement blocks."
            ),
        },
    )


def _profile() -> tuple[LogPolarProfile, MotionRange, PackedKinematicCodec]:
    profile = LogPolarProfile(
        r0=6.0,
        rho_min=math.log(2.35 / 6.0),
        rho_max=math.log(13.25 / 6.0),
        core_radius=1.0e-4,
    )
    ranges = MotionRange(
        rho_velocity=0.25,
        theta_velocity=math.tau * 0.35,
        rho_acceleration=0.5,
        theta_acceleration=math.tau * 0.7,
    )
    return profile, ranges, PackedKinematicCodec(profile, ranges)


def _render_settings(
    polar_mode: str,
    bayer_mode: str,
    levels: int | None,
    strength: float | None,
    seed: int,
) -> dict[str, object]:
    if polar_mode not in POLAR_RENDER_MODES:
        raise ValueError(f"polar mode must be one of {', '.join(POLAR_RENDER_MODES)}")
    if bayer_mode not in BAYER_MODES:
        raise ValueError(f"Bayer mode must be one of {', '.join(BAYER_MODES)}")
    defaults = {
        "off": (2, 0.0),
        "subtle": (64, 0.30),
        "retro": (4, 1.0),
        "custom": (24, 0.55),
    }
    default_levels, default_strength = defaults[bayer_mode]
    return {
        "polar_mode": polar_mode,
        "bayer_mode": bayer_mode,
        "levels": default_levels if levels is None else int(levels),
        "strength": default_strength if strength is None else float(strength),
        "seed": int(seed),
    }


def _environment_nodes() -> tuple[Node3DRecord, ...]:
    """A restrained non-polar frame so the orbit workload remains the subject."""

    return (
        Node3DRecord(
            "environment_floor",
            "lab_floor",
            "floor_ink",
            Transform3DRecord((0.0, 0.0, 0.0)),
            tags=("decorative",),
            metadata={"role": "nonpolar_environment"},
        ),
        Node3DRecord(
            "environment_core",
            "core_spire",
            "core_neon",
            Transform3DRecord((0.0, 0.02, 0.0), scale=(0.82, 1.0, 0.82)),
            tags=("decorative",),
            metadata={"role": "nonpolar_environment"},
        ),
        Node3DRecord(
            "environment_core_cap",
            "neon_bar",
            "edge_neon",
            Transform3DRecord((0.0, 4.55, 0.0), scale=(0.42, 0.08, 0.42)),
            tags=("decorative",),
            metadata={"role": "nonpolar_environment"},
        ),
        Node3DRecord(
            "environment_axis_x",
            "neon_bar",
            "edge_neon",
            Transform3DRecord((0.0, 0.025, 0.0), scale=(13.6, 0.025, 0.018)),
            tags=("decorative",),
            metadata={"role": "nonpolar_environment"},
        ),
        Node3DRecord(
            "environment_axis_z",
            "neon_bar",
            "edge_neon",
            Transform3DRecord((0.0, 0.026, 0.0), scale=(0.018, 0.025, 13.6)),
            tags=("decorative",),
            metadata={"role": "nonpolar_environment"},
        ),
    )


def _mover_node(
    index: int,
    seed: int,
    codec: PackedKinematicCodec,
    lut: PolarLookupTable,
) -> Node3DRecord:
    radius_word = derived_word(seed, index, 0)
    angle_word = derived_word(seed, index, 1)
    speed_word = derived_word(seed, index, 2)
    scale_word = derived_word(seed, index, 3)
    tick_word = derived_word(seed, index, 4)

    ring = index % RING_COUNT
    radius = 2.75 + ring * 1.34 + (unit_float(radius_word) - 0.5) * 0.24
    angle = math.tau * unit_float(angle_word)
    direction = -1.0 if speed_word & 1 else 1.0
    turns_per_second = direction * (0.035 + 0.09 * unit_float(speed_word))
    scale = 0.28 + 0.20 * unit_float(scale_word)
    height = 0.78 + ring * 0.54
    heading = (angle + direction * math.pi * 0.5) % math.tau

    packed = codec.component(
        PolarPose(
            math.log(radius / codec.profile.r0),
            angle,
            int(tick_word & 0x3FFF),
            heading,
        ),
        PolarMotion(theta_velocity=turns_per_second * math.tau),
        profile_id=PROFILE_ID,
    )
    state = codec.cartesian_state(packed, lut)
    x, z = state["position"]
    authored_heading = state["pose"].heading
    return Node3DRecord(
        f"orbit_mover_{index:04d}",
        "orbit_shard",
        "orbit_cyan",
        Transform3DRecord(
            (x, height, z),
            quat_from_axis_angle((0.0, 1.0, 0.0), authored_heading),
            (scale, scale, scale),
        ),
        tags=("decorative",),
        metadata={
            "packed_kinematic": packed.to_dict(),
            "visual_graph": GRAPH_ID,
            "lab_ring": ring,
            "lab_seed_index": index,
        },
    )


def build_project(
    count: int = DEFAULT_COUNT,
    *,
    polar_mode: str = "auto",
    bayer_mode: str = "subtle",
    levels: int | None = None,
    strength: float | None = None,
    seed: int = DEFAULT_SEED,
) -> Mobile3DProject:
    """Build one exact 64/256/1024 real-ECS workload via public records."""

    if (
        isinstance(count, bool)
        or not isinstance(count, Integral)
        or int(count) not in WORKLOAD_COUNTS
    ):
        raise ValueError(f"count must be one of {WORKLOAD_COUNTS}")
    count = int(count)
    if (
        isinstance(seed, bool)
        or not isinstance(seed, Integral)
        or not 0 <= int(seed) <= UINT64_MASK
    ):
        raise ValueError("seed must be an unsigned 64-bit integer")
    seed = int(seed)
    profile, ranges, codec = _profile()
    profile_spec = PolarProfileSpec(PROFILE_ID, codec, LUT_RESOLUTION)
    lut = quantized_profile_lut(profile_spec)
    graph = reverse_graph()
    graph.validate()

    meshes = {
        "orbit_shard": pyramid_mesh3d("orbit_shard", 0.72, 1.28),
        "lab_floor": plane_mesh3d("lab_floor", 31.0, 31.0),
        "core_spire": pyramid_mesh3d("core_spire", 1.7, 4.5),
        "neon_bar": cube_mesh3d("neon_bar", 1.0),
    }
    materials = {
        "orbit_cyan": Material3DRecord(
            "orbit_cyan",
            (0.075, 0.78, 0.96, 1.0),
            0.34,
            0.23,
            (0.018, 0.20, 0.32),
        ),
        "floor_ink": Material3DRecord(
            "floor_ink",
            (0.009, 0.018, 0.043, 1.0),
            0.12,
            0.88,
            (0.0, 0.004, 0.012),
        ),
        "core_neon": Material3DRecord(
            "core_neon",
            (0.76, 0.055, 0.43, 1.0),
            0.26,
            0.24,
            (0.31, 0.012, 0.15),
        ),
        "edge_neon": Material3DRecord(
            "edge_neon",
            (0.20, 0.52, 1.0, 1.0),
            0.40,
            0.18,
            (0.035, 0.16, 0.40),
        ),
    }
    movers = tuple(_mover_node(index, seed, codec, lut) for index in range(count))
    substrate_render = _render_settings(
        polar_mode, bayer_mode, levels, strength, seed
    )
    project = Mobile3DProject(
        "packed_polar_gpu_lab_3d",
        f"Packed Polar Substrate Lab — {count} real ECS movers",
        "UGTS-KC substrate lab",
        meshes,
        materials,
        _environment_nodes() + movers,
        Camera3DRecord(
            (18.5, 12.5, 20.5),
            (0.0, 2.7, 0.0),
            (0.0, 1.0, 0.0),
            52.0,
            0.05,
            90.0,
        ),
        DirectionalLight3DRecord(
            (-0.42, -1.0, -0.28),
            (0.72, 0.86, 1.0),
            1.25,
            0.18,
        ),
        (
            QualityTier3D("lab_120", 120, 1.0, 2048, 2, True, 0),
            QualityTier3D("lab_60", 60, 0.82, 2048, 0, True, 0),
        ),
        (
            AndroidTargetProfile(
                "poco_x7_pro_12gb",
                "POCO X7 Pro 12 GB / Mali-G720",
                preferred_abis=("arm64-v8a",),
                target_refresh_hz=120,
                memory_floor_mb=10240,
                device_hints=("POCO X7 Pro",),
                gpu_hints=("Mali-G720",),
                default_quality="lab_120",
            ),
        ),
        World3DSettings(
            fixed_dt=1.0 / 120.0,
            gravity=(0.0, 0.0, 0.0),
            floor_y=-2.0,
            bounds_min=(-18.0, -3.0, -18.0),
            bounds_max=(18.0, 10.0, 18.0),
            player_speed=0.0,
            jump_speed=0.0,
        ),
        "lab_120",
        (0.0025, 0.005, 0.014, 1.0),
        metadata={
            "packed_kinematic_profiles": {
                PROFILE_ID: {
                    "profile": profile.to_dict(),
                    "motion_range": ranges.to_dict(),
                    "lut_resolution": LUT_RESOLUTION,
                }
            },
            "visual_graphs": [graph.to_dict()],
            "substrate_render": substrate_render,
            "polar_lab": {
                "real_ecs_mover_count": count,
                "environment_node_count": len(_environment_nodes()),
                "generator": "generate_variants.py",
                "generator_seed": seed,
                "shared_mover_mesh": "orbit_shard",
                "shared_mover_material": "orbit_cyan",
                "measurement_status": "authoring substrate; phone GPU proof still required",
            },
        },
    )
    project.validate()
    render_pack = compile_render_substrate_pack_bytes(project)
    if len(render_pack) != 32:
        raise AssertionError("render-substrate pack must remain exactly 32 bytes")
    return project


def _parse_uint64(text: str) -> int:
    value = int(text, 0)
    if not 0 <= value <= UINT64_MASK:
        raise argparse.ArgumentTypeError("seed must fit uint64")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic packed-polar real-ECS workload."
    )
    parser.add_argument("--count", type=int, choices=WORKLOAD_COUNTS, default=64)
    parser.add_argument(
        "--polar-mode", choices=POLAR_RENDER_MODES, default="auto"
    )
    parser.add_argument("--bayer-mode", choices=BAYER_MODES, default="subtle")
    parser.add_argument("--levels", type=int)
    parser.add_argument("--strength", type=float)
    parser.add_argument("--seed", type=_parse_uint64, default=DEFAULT_SEED)
    parser.add_argument(
        "--output",
        type=Path,
        help=(
            "JSON destination. Default settings refresh project.json; other "
            "settings default to build/packed-polar-gpu-lab/."
        ),
    )
    args = parser.parse_args()
    project = build_project(
        args.count,
        polar_mode=args.polar_mode,
        bayer_mode=args.bayer_mode,
        levels=args.levels,
        strength=args.strength,
        seed=args.seed,
    )
    is_checked_default = (
        args.count == DEFAULT_COUNT
        and args.polar_mode == "auto"
        and args.bayer_mode == "subtle"
        and args.levels is None
        and args.strength is None
        and args.seed == DEFAULT_SEED
    )
    output = args.output
    if output is None:
        output = (
            EXAMPLE_DIR / "project.json"
            if is_checked_default
            else ROOT
            / "build"
            / "packed-polar-gpu-lab"
            / f"{args.count}-{args.polar_mode}-{args.bayer_mode}.json"
        )
    project.write(output)
    print(
        json.dumps(
            {
                "output": str(output.resolve()),
                "real_ecs_movers": args.count,
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
