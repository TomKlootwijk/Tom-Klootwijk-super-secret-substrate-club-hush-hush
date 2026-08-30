"""Bounded content-addressed display populations in packed polar space.

``polar_population`` is deliberately a render recipe attached to one real ECS
prototype.  Its generated members are :class:`PolarDisplayInstance` values;
they are never inserted into :class:`~ugts_kc3.mobile3d.GameWorld3D` and do not
receive colliders, tags, graphs, or gameplay identity.

Every member is random-access through the retained UGTS SplitMix64 lineage
schedule.  Cardinality is excluded only from the lineage namespace, so growing
64 -> 256 -> 1024 preserves the complete earlier prefix.  The separate recipe
content address includes cardinality and every recorded recipe input.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from numbers import Integral, Real
import struct
from typing import Any, Mapping

from .math3d import quat_from_axis_angle
from .packed_kinematics import (
    PackedKinematicComponent,
    PolarLookupTable,
    PolarPose,
)
from .polarpack import (
    PolarComponentSpec,
    PolarProfileSpec,
    collect_polar_project_spec,
    profile_lut_bytes,
    quantized_profile_lut,
)
from .renderpack import render_substrate_config_from_project
from .scatter import combine_seed, hash64, seed_unit_float, stable_id


POLAR_POPULATION_METADATA_KEY = "polar_population"
POLAR_POPULATION_PRESETS = ("ring", "spiral", "polar_field", "burst")
POLAR_POPULATION_PRESET_LABELS = {
    "ring": "Ring",
    "spiral": "Spiral",
    "polar_field": "Polar Field",
    "burst": "Radial Burst (loops)",
}

MAX_POLAR_POPULATION_RECIPES = 64
MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE = 4096
MAX_POLAR_POPULATION_TOTAL_INSTANCES = 16384
MAX_POLAR_BURST_RECIPES = 16
MAX_POLAR_BURST_INSTANCES_PER_RECIPE = 512
MAX_POLAR_BURST_TOTAL_INSTANCES = 2048
MIN_POLAR_BURST_DURATION_TICKS = 2
MAX_POLAR_BURST_DURATION_TICKS = 4096

_MASK64 = (1 << 64) - 1
_RHO_BITS = 20
_THETA_BITS = 18
_TICK_BITS = 14
_HEADING_BITS = 12
_HEADING_SHIFT = 0
_TICK_SHIFT = _HEADING_BITS
_THETA_SHIFT = _TICK_SHIFT + _TICK_BITS
_RHO_SHIFT = _THETA_SHIFT + _THETA_BITS
_GOLDEN_ANGLE_TURNS = 0.3819660112501051
_PARAMETER_STRUCT = struct.Struct("<8f")
_GLOW_PARAMETER_STRUCT = struct.Struct("<3f")
_ADDRESS_BYTES = 16
POLAR_POPULATION_MATH_SCHEDULE = (
    "v2: KCPR stores exact binary32 log-radius offsets; SplitMix lanes are exact "
    "24-bit binary32; each add/subtract/multiply/divide is rounded to binary32; "
    "spiral saturation is x/(1+x); fractional turns are added directly to extracted "
    "theta18/heading12 integer codes; the shared profile clamps and packs rho20"
)
POLAR_BURST_MATH_SCHEDULE = (
    "v1: zero start maps to the profile-clamped explicit core without log(0); "
    "duration ticks=floor(add32(div32(duration-seconds,fixed-dt),0.5)); "
    "age=k/(duration-1), rho=lerp(serialized-log-start,serialized-log-end,age), "
    "and envelope=4*age*(1-age), with every arithmetic stage rounded to binary32; "
    "SplitMix lanes 0/2/3/4 select group phase, direction variation, height, and "
    "size; local theta18/heading12 are absolute codes and tick14 stores k"
)
POLAR_GLOW_MATH_SCHEDULE = (
    "v1: zero start maps to the profile-clamped explicit core without log(0); "
    "center-rho=start+(end-start)*0.5 and inv-half-width=2/(end-start); "
    "phase12=floor(SplitMix lane 5*4096), shifted theta18 adds phase12<<6; "
    "pulse=1-u*u*(3-2*u), direction=0.5+0.5*UGLUT2-cosine, and bounded "
    "glow=(strength*pulse)*direction, with each arithmetic stage rounded to "
    "binary32 before lighting and the final Bayer presentation"
)
POLAR_GROW_COPIES_MATH_SCHEDULE = (
    "v1: display-scale-multiplier=clamp(add32(1,glow),1,5); only generated "
    "display copies multiply their authored display scale; the prototype, ECS, "
    "collider, picking, and gameplay scale stay unchanged; final Bayer only"
)
POLAR_MATERIAL_BANDS_MATH_SCHEDULE = (
    "v1: q=clamp(div32(sub32(rho,rho_min),sub32(rho_max,rho_min)),0,1); "
    "phase=div32(floor(splitmix-lane5*4096),4096); "
    "coordinate=add32(add32(mul32(bands,q),phase),mul32(0.25,add32(1,dir-x))); "
    "wave=sub32(coordinate,floor(coordinate)); band=sub32(1,abs(sub32(mul32(2,wave),1))); "
    "multiplier=add32(mul32(sub32(1,strength),1),mul32(strength,add32(0.5,band))); "
    "base-prime=base*multiplier, then Glow, then final Bayer"
)


class PolarPopulationError(ValueError):
    """Invalid polar-population authoring data or prototype ownership."""


@dataclass(frozen=True)
class PolarPopulationOperator:
    """One immutable operator meaning advertised by the compact sidecar."""

    code: int
    slot: int
    arity: int
    name: str
    meaning: str

    @property
    def meaning_hash(self) -> int:
        return hash64(self.meaning)

    @property
    def mask(self) -> int:
        return 1 << self.slot


POLAR_POPULATION_OPERATORS = (
    PolarPopulationOperator(
        0x0001,
        0,
        3,
        "splitmix64_lineage",
        "ugts.kc392.polar-population.splitmix64-lineage(seed,namespace,index).v1",
    ),
    PolarPopulationOperator(
        0x0010,
        1,
        3,
        "log_radius_multiplier",
        "ugts.kc392.polar-population.binary32-rho+=lerp(serialized-log-min,serialized-log-max,u);profile-clamp+pack20.v2",
    ),
    PolarPopulationOperator(
        0x0011,
        2,
        2,
        "saturating_spiral",
        "ugts.kc392.polar-population.binary32-spiral-x=index*radial-rate;u=x/(1+x).v2",
    ),
    PolarPopulationOperator(
        0x0012,
        6,
        4,
        "local_log_radius_cycle",
        "ugts.kc392.polar-population.binary32-age=(fixed-tick%duration)/(duration-1);local-rho=lerp(serialized-core-aware-log-start,serialized-log-end,age);profile-clamp+pack20;tick14=cycle-tick;wrap-snaps-previous.v1",
    ),
    PolarPopulationOperator(
        0x0020,
        3,
        3,
        "periodic_angle",
        "ugts.kc392.polar-population.binary32-turns=seeded-phase+index*step+seeded-jitter;theta18+heading12+=floor(frac(turns)*2^bits).v2",
    ),
    PolarPopulationOperator(
        0x0021,
        7,
        3,
        "seeded_local_direction",
        "ugts.kc392.polar-population.binary32-turns=seeded-phase+index*step+centered-lane2*jitter;local-theta18+heading12=floor(frac(turns)*2^bits).v1",
    ),
    PolarPopulationOperator(
        0x0030,
        4,
        2,
        "seeded_height",
        "ugts.kc392.polar-population.binary32-y+=centered-seeded-unit*height-span.v1",
    ),
    PolarPopulationOperator(
        0x0031,
        8,
        4,
        "parabolic_life_envelope",
        "ugts.kc392.polar-population.binary32-envelope=4*age*(1-age);y+=height*(0.5+lane3)*envelope;scale*=envelope.v1",
    ),
    PolarPopulationOperator(
        0x0040,
        5,
        3,
        "uniform_scale",
        "ugts.kc392.polar-population.binary32-scale*=lerp(scale-min,scale-max,seeded-unit).v1",
    ),
    PolarPopulationOperator(
        0x0050,
        9,
        3,
        "log_radius_pulse",
        "ugts.kc392.polar-population.binary32-d=rho-center_rho;u=clamp(abs(d)*inv_half_width,0,1);pulse=1-u*u*(3-2*u).v1",
    ),
    PolarPopulationOperator(
        0x0051,
        10,
        2,
        "seeded_material_phase",
        "ugts.kc392.polar-population.phase12=floor(splitmix64-unit(combine-seed(lineage,5))*4096)&4095;shifted-theta18=(theta18+(phase12<<6))&262143.v1",
    ),
    PolarPopulationOperator(
        0x0052,
        11,
        3,
        "polar_material_glow",
        "ugts.kc392.polar-population.binary32-direction=0.5+0.5*cosine(shifted-theta18);glow=clamp((strength*pulse)*direction,0,4);uglut2-or-direct-before-lighting;final-bayer-only.v1",
    ),
    PolarPopulationOperator(
        0x0053,
        12,
        2,
        "polar_display_scale_from_glow",
        "generated-display-scale*=clamp(1+glow_field,1,5);prototype-gameplay-unchanged;final-bayer-only.v1",
    ),
)

_OPERATOR_BY_CODE = {operator.code: operator for operator in POLAR_POPULATION_OPERATORS}
_OPERATOR_BY_NAME = {operator.name: operator for operator in POLAR_POPULATION_OPERATORS}
_COMMON_OPERATOR_NAMES = (
    "splitmix64_lineage",
    "log_radius_multiplier",
    "periodic_angle",
    "seeded_height",
    "uniform_scale",
)
_PRESET_OPERATOR_NAMES = {
    "ring": _COMMON_OPERATOR_NAMES,
    "spiral": (
        "splitmix64_lineage",
        "log_radius_multiplier",
        "saturating_spiral",
        "periodic_angle",
        "seeded_height",
        "uniform_scale",
    ),
    "polar_field": _COMMON_OPERATOR_NAMES,
    "burst": (
        "splitmix64_lineage",
        "local_log_radius_cycle",
        "seeded_local_direction",
        "parabolic_life_envelope",
        "uniform_scale",
    ),
}
_GLOW_OPERATOR_NAMES = (
    "log_radius_pulse",
    "seeded_material_phase",
    "polar_material_glow",
)
_GROW_COPIES_OPERATOR_NAME = "polar_display_scale_from_glow"

_PRESET_DEFAULTS: dict[str, dict[str, float]] = {
    "ring": {
        "radius_min": 1.0,
        "radius_max": 1.0,
        "radial_rate": 0.0,
        "angle_step_turns": _GOLDEN_ANGLE_TURNS,
        "angle_jitter_turns": 0.0,
        "height_spread": 0.0,
        "scale_min": 1.0,
        "scale_max": 1.0,
    },
    "spiral": {
        "radius_min": 1.0,
        "radius_max": 8.0,
        "radial_rate": 0.01,
        "angle_step_turns": 0.0625,
        "angle_jitter_turns": 0.005,
        "height_spread": 0.5,
        "scale_min": 0.85,
        "scale_max": 1.15,
    },
    "polar_field": {
        "radius_min": 0.125,
        "radius_max": 16.0,
        "radial_rate": 0.0,
        "angle_step_turns": _GOLDEN_ANGLE_TURNS,
        "angle_jitter_turns": 0.5,
        "height_spread": 2.0,
        "scale_min": 0.5,
        "scale_max": 1.5,
    },
    "burst": {
        "start_distance": 0.0,
        "end_distance": 4.0,
        "duration_seconds": 0.8,
        "angle_step_turns": _GOLDEN_ANGLE_TURNS,
        "angle_jitter_turns": 0.08,
        "height_arc": 1.0,
        "scale_min": 0.2,
        "scale_max": 0.45,
    },
}
_LEGACY_ALLOWED_KEYS = frozenset(
    {
        "preset",
        "instance_count",
        "seed",
        "radius_min",
        "radius_max",
        "radial_rate",
        "angle_step_turns",
        "angle_jitter_turns",
        "height_spread",
        "scale_min",
        "scale_max",
        "glow_by_distance",
    }
)
_BURST_ALLOWED_KEYS = frozenset(
    {
        "preset",
        "instance_count",
        "seed",
        "start_distance",
        "end_distance",
        "duration_seconds",
        "angle_step_turns",
        "angle_jitter_turns",
        "height_arc",
        "scale_min",
        "scale_max",
        "glow_by_distance",
    }
)
POLAR_POPULATION_V1_OPERATOR_CODES = frozenset(
    {0x0001, 0x0010, 0x0011, 0x0020, 0x0030, 0x0040}
)
POLAR_POPULATION_V2_OPERATOR_CODES = frozenset(
    {operator.code for operator in POLAR_POPULATION_OPERATORS if operator.code < 0x0050}
)
POLAR_POPULATION_V3_OPERATOR_CODES = frozenset(
    {operator.code for operator in POLAR_POPULATION_OPERATORS if operator.code <= 0x0052}
)
POLAR_POPULATION_V4_OPERATOR_CODES = frozenset(
    {operator.code for operator in POLAR_POPULATION_OPERATORS if operator.code <= 0x0053}
)
POLAR_GLOW_OPERATOR_MASK = sum(
    _OPERATOR_BY_NAME[name].mask for name in _GLOW_OPERATOR_NAMES
)
POLAR_GROW_COPIES_OPERATOR_MASK = _OPERATOR_BY_NAME[
    _GROW_COPIES_OPERATOR_NAME
].mask


def _f32(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise PolarPopulationError(f"{label} must be a finite number")
    try:
        result = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except (OverflowError, struct.error) as error:
        raise PolarPopulationError(f"{label} must fit a finite 32-bit number") from error
    if not math.isfinite(result):
        raise PolarPopulationError(f"{label} must fit a finite 32-bit number")
    # IEEE-754 has two zero encodings, but polar recipe operators give them
    # identical meaning.  Canonical authoring therefore always emits +0 so
    # behaviorally identical inputs cannot acquire different KCPR addresses.
    if result == 0.0:
        return 0.0
    return result


def _integer(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise PolarPopulationError(f"{label} must be a whole number")
    result = int(value)
    if not minimum <= result <= maximum:
        raise PolarPopulationError(f"{label} must be between {minimum} and {maximum}")
    return result


def operator_mask_for_preset(preset: str) -> int:
    try:
        names = _PRESET_OPERATOR_NAMES[preset]
    except KeyError as error:
        labels = ", ".join(POLAR_POPULATION_PRESET_LABELS.values())
        raise PolarPopulationError(f"Pattern must be one of: {labels}") from error
    result = 0
    for name in names:
        result |= _OPERATOR_BY_NAME[name].mask
    return result


@dataclass(frozen=True)
class PolarGlowByDistance:
    """Child-facing bounded material field attached to one display recipe."""

    start_distance: float
    end_distance: float
    strength: float
    grow_copies: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "start_distance",
            _f32(self.start_distance, "Glow start distance"),
        )
        object.__setattr__(
            self,
            "end_distance",
            _f32(self.end_distance, "Glow end distance"),
        )
        object.__setattr__(self, "strength", _f32(self.strength, "Glow strength"))
        if not isinstance(self.grow_copies, bool):
            raise PolarPopulationError("Grow glowing copies must be true or false")
        self.validate()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PolarGlowByDistance":
        if not isinstance(value, Mapping):
            raise PolarPopulationError("glow_by_distance must be an object")
        required = frozenset({"start_distance", "end_distance", "strength"})
        allowed = required | {"grow_copies"}
        unknown = sorted(str(key) for key in value if key not in allowed)
        if unknown:
            raise PolarPopulationError(
                "glow_by_distance has unknown field(s): " + ", ".join(unknown)
            )
        missing = sorted(required.difference(value))
        if missing:
            raise PolarPopulationError(
                "glow_by_distance is missing field(s): " + ", ".join(missing)
            )
        return cls(
            start_distance=value["start_distance"],
            end_distance=value["end_distance"],
            strength=value["strength"],
            grow_copies=value.get("grow_copies", False),
        )

    def validate(self) -> None:
        start_distance = _f32(self.start_distance, "Glow start distance")
        end_distance = _f32(self.end_distance, "Glow end distance")
        strength = _f32(self.strength, "Glow strength")
        if not isinstance(self.grow_copies, bool):
            raise PolarPopulationError("Grow glowing copies must be true or false")
        if start_distance < 0.0:
            raise PolarPopulationError("Glow start distance must be zero or greater")
        if end_distance <= start_distance:
            raise PolarPopulationError(
                "Glow end distance must be greater than its start distance"
            )
        if not 0.0 <= strength <= 4.0:
            raise PolarPopulationError("Glow strength must stay between 0 and 4")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        result: dict[str, Any] = {
            "start_distance": self.start_distance,
            "end_distance": self.end_distance,
            "strength": self.strength,
        }
        if self.grow_copies:
            result["grow_copies"] = True
        return result


def operator_mask_for_recipe(recipe: "PolarPopulationRecipe") -> int:
    """Return the preset mask plus only explicitly enabled modifiers."""

    result = operator_mask_for_preset(recipe.preset)
    if recipe.glow_by_distance is not None:
        result |= POLAR_GLOW_OPERATOR_MASK
        if recipe.glow_by_distance.grow_copies:
            result |= POLAR_GROW_COPIES_OPERATOR_MASK
    return result


@dataclass(frozen=True)
class PolarPopulationRecipe:
    """One bounded recipe; ``instance_count`` includes the authored prototype."""

    preset: str = "ring"
    instance_count: int = 64
    seed: int = 1
    radius_min: float = 1.0
    radius_max: float = 1.0
    radial_rate: float = 0.0
    angle_step_turns: float = _GOLDEN_ANGLE_TURNS
    angle_jitter_turns: float = 0.0
    height_spread: float = 0.0
    scale_min: float = 1.0
    scale_max: float = 1.0
    start_distance: float = 0.0
    end_distance: float = 4.0
    duration_seconds: float = 0.8
    height_arc: float = 1.0
    glow_by_distance: PolarGlowByDistance | None = None

    def __post_init__(self) -> None:
        # Direct dataclass construction is a supported authoring path.  Enter
        # the exact serialized binary32 domain immediately so preview,
        # addresses, KCPR bytes, and a future native consumer cannot diverge.
        if not isinstance(self.preset, str) or self.preset not in POLAR_POPULATION_PRESETS:
            labels = ", ".join(POLAR_POPULATION_PRESET_LABELS.values())
            raise PolarPopulationError(f"Pattern must be one of: {labels}")
        object.__setattr__(
            self,
            "instance_count",
            _integer(
                self.instance_count,
                "Objects in polar group",
                2,
                (
                    MAX_POLAR_BURST_INSTANCES_PER_RECIPE
                    if self.preset == "burst"
                    else MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE
                ),
            ),
        )
        object.__setattr__(
            self, "seed", _integer(self.seed, "World number", 0, _MASK64)
        )
        glow = self.glow_by_distance
        if isinstance(glow, Mapping):
            glow = PolarGlowByDistance.from_mapping(glow)
            object.__setattr__(self, "glow_by_distance", glow)
        elif glow is not None and not isinstance(glow, PolarGlowByDistance):
            raise PolarPopulationError("glow_by_distance must be an object")
        fields = (
            (
                ("start_distance", "Burst start distance"),
                ("end_distance", "Burst end distance"),
                ("duration_seconds", "Burst duration"),
                ("angle_step_turns", "Turn step"),
                ("angle_jitter_turns", "Turn variation"),
                ("height_arc", "Burst arc height"),
                ("scale_min", "Smallest size"),
                ("scale_max", "Largest size"),
            )
            if self.preset == "burst"
            else (
                ("radius_min", "Smallest radius multiplier"),
                ("radius_max", "Largest radius multiplier"),
                ("radial_rate", "Spiral growth rate"),
                ("angle_step_turns", "Turn step"),
                ("angle_jitter_turns", "Turn variation"),
                ("height_spread", "Height spread"),
                ("scale_min", "Smallest size"),
                ("scale_max", "Largest size"),
            )
        )
        for name, label in fields:
            object.__setattr__(self, name, _f32(getattr(self, name), label))
        self.validate()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "PolarPopulationRecipe":
        if not isinstance(value, Mapping):
            raise PolarPopulationError("metadata.polar_population must be an object")
        preset = value.get("preset", "ring")
        if not isinstance(preset, str) or preset not in POLAR_POPULATION_PRESETS:
            labels = ", ".join(POLAR_POPULATION_PRESET_LABELS.values())
            raise PolarPopulationError(f"Pattern must be one of: {labels}")
        allowed = _BURST_ALLOWED_KEYS if preset == "burst" else _LEGACY_ALLOWED_KEYS
        unknown = sorted(str(key) for key in value if key not in allowed)
        if unknown:
            raise PolarPopulationError(
                f"{preset} polar_population has unknown field(s): "
                + ", ".join(unknown)
            )
        defaults = _PRESET_DEFAULTS[preset]
        glow = (
            None
            if "glow_by_distance" not in value
            else PolarGlowByDistance.from_mapping(value["glow_by_distance"])
        )
        maximum = (
            MAX_POLAR_BURST_INSTANCES_PER_RECIPE
            if preset == "burst"
            else MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE
        )
        default_count = 32 if preset == "burst" else 64
        if preset == "burst":
            result = cls(
                preset=preset,
                instance_count=_integer(
                    value.get("instance_count", default_count),
                    "Objects in polar group",
                    2,
                    maximum,
                ),
                seed=_integer(value.get("seed", 1), "World number", 0, _MASK64),
                start_distance=_f32(
                    value.get("start_distance", defaults["start_distance"]),
                    "Burst start distance",
                ),
                end_distance=_f32(
                    value.get("end_distance", defaults["end_distance"]),
                    "Burst end distance",
                ),
                duration_seconds=_f32(
                    value.get("duration_seconds", defaults["duration_seconds"]),
                    "Burst duration",
                ),
                angle_step_turns=_f32(
                    value.get("angle_step_turns", defaults["angle_step_turns"]),
                    "Turn step",
                ),
                angle_jitter_turns=_f32(
                    value.get(
                        "angle_jitter_turns", defaults["angle_jitter_turns"]
                    ),
                    "Turn variation",
                ),
                height_arc=_f32(
                    value.get("height_arc", defaults["height_arc"]),
                    "Burst arc height",
                ),
                scale_min=_f32(
                    value.get("scale_min", defaults["scale_min"]),
                    "Smallest size",
                ),
                scale_max=_f32(
                    value.get("scale_max", defaults["scale_max"]),
                    "Largest size",
                ),
                glow_by_distance=glow,
            )
            result.validate()
            return result
        result = cls(
            preset=preset,
            instance_count=_integer(
                value.get("instance_count", default_count),
                "Objects in polar group",
                2,
                maximum,
            ),
            seed=_integer(value.get("seed", 1), "World number", 0, _MASK64),
            radius_min=_f32(
                value.get("radius_min", defaults["radius_min"]),
                "Smallest radius multiplier",
            ),
            radius_max=_f32(
                value.get("radius_max", defaults["radius_max"]),
                "Largest radius multiplier",
            ),
            radial_rate=_f32(
                value.get("radial_rate", defaults["radial_rate"]),
                "Spiral growth rate",
            ),
            angle_step_turns=_f32(
                value.get("angle_step_turns", defaults["angle_step_turns"]),
                "Turn step",
            ),
            angle_jitter_turns=_f32(
                value.get("angle_jitter_turns", defaults["angle_jitter_turns"]),
                "Turn variation",
            ),
            height_spread=_f32(
                value.get("height_spread", defaults["height_spread"]),
                "Height spread",
            ),
            scale_min=_f32(
                value.get("scale_min", defaults["scale_min"]),
                "Smallest size",
            ),
            scale_max=_f32(
                value.get("scale_max", defaults["scale_max"]),
                "Largest size",
            ),
            glow_by_distance=glow,
        )
        result.validate()
        return result

    @property
    def operator_mask(self) -> int:
        return operator_mask_for_recipe(self)

    @property
    def parameters(self) -> tuple[float, ...]:
        """Return the eight child-facing values for this discriminated recipe."""

        if self.preset == "burst":
            return (
                self.start_distance,
                self.end_distance,
                self.duration_seconds,
                self.angle_step_turns,
                self.angle_jitter_turns,
                self.height_arc,
                self.scale_min,
                self.scale_max,
            )
        return (
            self.radius_min,
            self.radius_max,
            self.radial_rate,
            self.angle_step_turns,
            self.angle_jitter_turns,
            self.height_spread,
            self.scale_min,
            self.scale_max,
        )

    @property
    def operator_parameters(self) -> tuple[float, ...]:
        """Return legacy runtime fields; Burst also needs its bound profile/tick."""

        if self.preset == "burst":
            raise PolarPopulationError(
                "Radial Burst operator parameters require its Movement profile "
                "and project fixed step"
            )
        return polar_population_operator_parameters(self)

    def validate(self) -> None:
        operator_mask_for_preset(self.preset)
        if self.glow_by_distance is not None:
            self.glow_by_distance.validate()
        _integer(
            self.instance_count,
            "Objects in polar group",
            2,
            (
                MAX_POLAR_BURST_INSTANCES_PER_RECIPE
                if self.preset == "burst"
                else MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE
            ),
        )
        _integer(self.seed, "World number", 0, _MASK64)
        if self.preset == "burst":
            (
                start_distance,
                end_distance,
                duration_seconds,
                angle_step,
                angle_jitter,
                height_arc,
                scale_min,
                scale_max,
            ) = tuple(
                _f32(value, label)
                for value, label in zip(
                    self.parameters,
                    (
                        "Burst start distance",
                        "Burst end distance",
                        "Burst duration",
                        "Turn step",
                        "Turn variation",
                        "Burst arc height",
                        "Smallest size",
                        "Largest size",
                    ),
                )
            )
            if start_distance < 0.0:
                raise PolarPopulationError(
                    "Burst start distance must be zero or greater"
                )
            if end_distance <= start_distance:
                raise PolarPopulationError(
                    "Burst end distance must be greater than its start distance"
                )
            if duration_seconds <= 0.0:
                raise PolarPopulationError("Burst duration must be greater than zero")
            if not -4.0 <= angle_step <= 4.0:
                raise PolarPopulationError("Turn step must stay between -4 and 4 turns")
            if not 0.0 <= angle_jitter <= 1.0:
                raise PolarPopulationError(
                    "Turn variation must stay between 0 and 1 turn"
                )
            if not 0.0 <= height_arc <= 1024.0:
                raise PolarPopulationError(
                    "Burst arc height must stay between 0 and 1024"
                )
            if not 0.05 <= scale_min <= scale_max <= 8.0:
                raise PolarPopulationError(
                    "Size range must stay between 0.05 and 8 (smallest <= largest)"
                )
            return
        parameters = tuple(
            _f32(value, label)
            for value, label in zip(
                self.parameters,
                (
                    "Smallest radius multiplier",
                    "Largest radius multiplier",
                    "Spiral growth rate",
                    "Turn step",
                    "Turn variation",
                    "Height spread",
                    "Smallest size",
                    "Largest size",
                ),
            )
        )
        (
            radius_min,
            radius_max,
            radial_rate,
            angle_step,
            angle_jitter,
            height_spread,
            scale_min,
            scale_max,
        ) = parameters
        if not 1.0 / 256.0 <= radius_min <= radius_max <= 256.0:
            raise PolarPopulationError(
                "Radius multipliers must stay between 1/256 and 256 (smallest <= largest)"
            )
        if not -4.0 <= angle_step <= 4.0:
            raise PolarPopulationError("Turn step must stay between -4 and 4 turns")
        if not 0.0 <= angle_jitter <= 1.0:
            raise PolarPopulationError("Turn variation must stay between 0 and 1 turn")
        if not 0.0 <= height_spread <= 1024.0:
            raise PolarPopulationError("Height spread must stay between 0 and 1024")
        if not 0.05 <= scale_min <= scale_max <= 8.0:
            raise PolarPopulationError(
                "Size range must stay between 0.05 and 8 (smallest <= largest)"
            )
        if self.preset == "spiral":
            if not 0.000001 <= radial_rate <= 1.0:
                raise PolarPopulationError(
                    "Spiral growth rate must stay between 0.000001 and 1"
                )
        elif radial_rate != 0.0:
            raise PolarPopulationError(
                f"{POLAR_POPULATION_PRESET_LABELS[self.preset]} keeps Spiral growth rate at 0"
            )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        if self.preset == "burst":
            result: dict[str, Any] = {
                "preset": self.preset,
                "instance_count": self.instance_count,
                "seed": self.seed,
                "start_distance": self.start_distance,
                "end_distance": self.end_distance,
                "duration_seconds": self.duration_seconds,
                "angle_step_turns": self.angle_step_turns,
                "angle_jitter_turns": self.angle_jitter_turns,
                "height_arc": self.height_arc,
                "scale_min": self.scale_min,
                "scale_max": self.scale_max,
            }
        else:
            result = {
                "preset": self.preset,
                "instance_count": self.instance_count,
                "seed": self.seed,
                "radius_min": self.radius_min,
                "radius_max": self.radius_max,
                "radial_rate": self.radial_rate,
                "angle_step_turns": self.angle_step_turns,
                "angle_jitter_turns": self.angle_jitter_turns,
                "height_spread": self.height_spread,
                "scale_min": self.scale_min,
                "scale_max": self.scale_max,
            }
        if self.glow_by_distance is not None:
            result["glow_by_distance"] = self.glow_by_distance.to_dict()
        return result


def validate_polar_population_operator_parameters(
    preset: str,
    parameters: tuple[float, ...] | list[float],
) -> tuple[float, ...]:
    """Validate and canonicalize the eight exact binary32 KCPR operator fields."""

    operator_mask_for_preset(preset)
    if len(parameters) != 8:
        raise PolarPopulationError("polar population needs exactly 8 operator parameters")
    labels = (
        (
            "Core-aware log start distance",
            "Log end distance",
            "Burst duration ticks",
            "Turn step",
            "Turn variation",
            "Burst arc height",
            "Smallest size",
            "Largest size",
        )
        if preset == "burst"
        else (
            "Smallest log radius offset",
            "Largest log radius offset",
            "Spiral growth rate",
            "Turn step",
            "Turn variation",
            "Height spread",
            "Smallest size",
            "Largest size",
        )
    )
    result = tuple(_f32(value, label) for value, label in zip(parameters, labels))
    if preset == "burst":
        (
            log_start,
            log_end,
            duration_ticks,
            angle_step,
            angle_jitter,
            height_arc,
            scale_min,
            scale_max,
        ) = result
        if log_start >= log_end:
            raise PolarPopulationError(
                "Burst log end distance must be greater than its start"
            )
        if (
            not duration_ticks.is_integer()
            or not MIN_POLAR_BURST_DURATION_TICKS
            <= int(duration_ticks)
            <= MAX_POLAR_BURST_DURATION_TICKS
        ):
            raise PolarPopulationError(
                "Burst duration ticks must be a whole number between "
                f"{MIN_POLAR_BURST_DURATION_TICKS} and "
                f"{MAX_POLAR_BURST_DURATION_TICKS}"
            )
        if not -4.0 <= angle_step <= 4.0:
            raise PolarPopulationError("Turn step must stay between -4 and 4 turns")
        if not 0.0 <= angle_jitter <= 1.0:
            raise PolarPopulationError(
                "Turn variation must stay between 0 and 1 turn"
            )
        if not 0.0 <= height_arc <= 1024.0:
            raise PolarPopulationError(
                "Burst arc height must stay between 0 and 1024"
            )
        if not 0.05 <= scale_min <= scale_max <= 8.0:
            raise PolarPopulationError(
                "Size range must stay between 0.05 and 8 (smallest <= largest)"
            )
        return result
    (
        log_radius_min,
        log_radius_max,
        radial_rate,
        angle_step,
        angle_jitter,
        height_spread,
        scale_min,
        scale_max,
    ) = result
    log_limit = _f32(math.log(256.0), "Log radius limit")
    if not -log_limit <= log_radius_min <= log_radius_max <= log_limit:
        raise PolarPopulationError(
            "Log radius offsets must stay inside log(1/256)..log(256) "
            "(smallest <= largest)"
        )
    if not -4.0 <= angle_step <= 4.0:
        raise PolarPopulationError("Turn step must stay between -4 and 4 turns")
    if not 0.0 <= angle_jitter <= 1.0:
        raise PolarPopulationError("Turn variation must stay between 0 and 1 turn")
    if not 0.0 <= height_spread <= 1024.0:
        raise PolarPopulationError("Height spread must stay between 0 and 1024")
    if not 0.05 <= scale_min <= scale_max <= 8.0:
        raise PolarPopulationError(
            "Size range must stay between 0.05 and 8 (smallest <= largest)"
        )
    if preset == "spiral":
        if not 0.000001 <= radial_rate <= 1.0:
            raise PolarPopulationError(
                "Spiral growth rate must stay between 0.000001 and 1"
            )
    elif radial_rate != 0.0:
        raise PolarPopulationError(
            f"{POLAR_POPULATION_PRESET_LABELS[preset]} keeps Spiral growth rate at 0"
        )
    return result


def validate_polar_glow_operator_parameters(
    parameters: tuple[float, ...] | list[float],
) -> tuple[float, float, float]:
    """Validate the exact three binary32 lanes stored in a KCPR v3 tail."""

    if len(parameters) != 3:
        raise PolarPopulationError("Glow by distance needs exactly 3 operator parameters")
    center_rho, inv_half_width, strength = (
        _f32(value, label)
        for value, label in zip(
            parameters,
            ("Glow center log radius", "Glow inverse half width", "Glow strength"),
        )
    )
    if inv_half_width <= 0.0:
        raise PolarPopulationError("Glow inverse half width must be greater than zero")
    if not 0.0 <= strength <= 4.0:
        raise PolarPopulationError("Glow strength must stay between 0 and 4")
    return center_rho, inv_half_width, strength


def polar_population_operator_parameters(
    recipe: PolarPopulationRecipe,
    *,
    profile: PolarProfileSpec | None = None,
    fixed_dt: float | None = None,
) -> tuple[float, ...]:
    """Compile child-facing values into exact no-libm runtime fields."""

    recipe.validate()
    if recipe.preset == "burst":
        if profile is None or fixed_dt is None:
            raise PolarPopulationError(
                "Radial Burst needs its Movement profile and project fixed step"
            )
        log_profile = profile.codec.profile
        r0 = _f32(log_profile.r0, "Movement reference radius")
        rho_min = _f32(log_profile.rho_min, "Movement minimum log radius")
        rho_max = _f32(log_profile.rho_max, "Movement maximum log radius")
        core_radius = _f32(log_profile.core_radius, "Movement core radius")
        fixed_step = _f32(fixed_dt, "Project fixed step")
        if fixed_step <= 0.0:
            raise PolarPopulationError("Project fixed step must be greater than zero")
        raw_core_rho = _f32(math.log(core_radius / r0), "Movement core log radius")
        core_rho = _f32(
            min(rho_max, max(rho_min, raw_core_rho)),
            "Profile-clamped core log radius",
        )
        effective_core_distance = _f32(
            r0 * math.exp(core_rho), "Effective Movement core distance"
        )
        if (
            recipe.start_distance == 0.0
            or recipe.start_distance == effective_core_distance
        ):
            log_start = core_rho
        else:
            if recipe.start_distance < effective_core_distance:
                raise PolarPopulationError(
                    "Burst start distance must be zero or at least the Movement "
                    f"profile core ({effective_core_distance:g})"
                )
            log_start = _f32(
                math.log(recipe.start_distance / r0), "Burst log start distance"
            )
        log_end = _f32(
            math.log(recipe.end_distance / r0), "Burst log end distance"
        )
        if log_start < rho_min or log_start > rho_max:
            raise PolarPopulationError(
                "Burst start distance is outside the Movement profile"
            )
        if log_end <= log_start or log_end > rho_max:
            raise PolarPopulationError(
                "Burst end distance must be greater than its effective start and "
                "inside the Movement profile"
            )
        duration_ratio = _div32(
            recipe.duration_seconds, fixed_step, "Burst duration tick ratio"
        )
        duration_ticks = int(
            math.floor(_add32(duration_ratio, 0.5, "Rounded Burst duration ticks"))
        )
        if not MIN_POLAR_BURST_DURATION_TICKS <= duration_ticks <= MAX_POLAR_BURST_DURATION_TICKS:
            raise PolarPopulationError(
                "Burst duration resolves to "
                f"{duration_ticks} fixed ticks; supported range is "
                f"{MIN_POLAR_BURST_DURATION_TICKS} to "
                f"{MAX_POLAR_BURST_DURATION_TICKS}"
            )
        return validate_polar_population_operator_parameters(
            recipe.preset,
            (
                log_start,
                log_end,
                _f32(duration_ticks, "Burst duration ticks"),
                recipe.angle_step_turns,
                recipe.angle_jitter_turns,
                recipe.height_arc,
                recipe.scale_min,
                recipe.scale_max,
            ),
        )
    return validate_polar_population_operator_parameters(
        recipe.preset,
        (
            _f32(math.log(recipe.radius_min), "Smallest log radius offset"),
            _f32(math.log(recipe.radius_max), "Largest log radius offset"),
            recipe.radial_rate,
            recipe.angle_step_turns,
            recipe.angle_jitter_turns,
            recipe.height_spread,
            recipe.scale_min,
            recipe.scale_max,
        ),
    )


def polar_glow_by_distance_operator_parameters(
    glow: PolarGlowByDistance | Mapping[str, Any],
    *,
    profile: PolarProfileSpec,
) -> tuple[float, float, float]:
    """Compile child distances into the canonical log-radius pulse lanes."""

    authored = (
        glow
        if isinstance(glow, PolarGlowByDistance)
        else PolarGlowByDistance.from_mapping(glow)
    )
    authored.validate()
    log_profile = profile.codec.profile
    r0 = _f32(log_profile.r0, "Movement reference radius")
    rho_min = _f32(log_profile.rho_min, "Movement minimum log radius")
    rho_max = _f32(log_profile.rho_max, "Movement maximum log radius")
    core_radius = _f32(log_profile.core_radius, "Movement core radius")
    raw_core_rho = _f32(math.log(core_radius / r0), "Movement core log radius")
    core_rho = _f32(
        min(rho_max, max(rho_min, raw_core_rho)),
        "Profile-clamped core log radius",
    )
    effective_core_distance = _f32(
        r0 * math.exp(core_rho), "Effective Movement core distance"
    )
    effective_max_distance = _f32(
        r0 * math.exp(rho_max), "Effective Movement maximum distance"
    )
    if (
        authored.start_distance == 0.0
        or authored.start_distance == effective_core_distance
    ):
        log_start = core_rho
    else:
        if authored.start_distance < effective_core_distance:
            raise PolarPopulationError(
                "Glow start distance must be zero or at least the Movement "
                f"profile core ({effective_core_distance:g})"
            )
        log_start = _f32(
            math.log(authored.start_distance / r0), "Glow log start distance"
        )
    if authored.end_distance > effective_max_distance:
        raise PolarPopulationError(
            "Glow end distance must stay inside the Movement profile "
            f"maximum ({effective_max_distance:g})"
        )
    log_end = (
        rho_max
        if authored.end_distance == effective_max_distance
        else _f32(math.log(authored.end_distance / r0), "Glow log end distance")
    )
    if log_start < rho_min or log_start > rho_max:
        raise PolarPopulationError(
            "Glow start distance is outside the Movement profile"
        )
    if log_end <= log_start or log_end > rho_max:
        raise PolarPopulationError(
            "Glow end distance must be greater than its effective start and "
            "inside the Movement profile"
        )
    span = _sub32(log_end, log_start, "Glow log radius span")
    center_rho = _add32(
        log_start,
        _mul32(span, 0.5, "Glow log radius half width"),
        "Glow center log radius",
    )
    inv_half_width = _div32(2.0, span, "Glow inverse half width")
    return validate_polar_glow_operator_parameters(
        (center_rho, inv_half_width, authored.strength)
    )


def polar_population_preset(
    preset: str, *, instance_count: int | None = None, seed: int = 1
) -> PolarPopulationRecipe:
    """Return one fully explicit child-facing bounded display recipe."""

    return PolarPopulationRecipe.from_mapping(
        {
            "preset": preset,
            "instance_count": (
                32 if preset == "burst" and instance_count is None
                else 64 if instance_count is None
                else instance_count
            ),
            "seed": seed,
        }
    )


@dataclass(frozen=True)
class PolarPopulationGroup:
    prototype_node_index: int
    prototype_id: str
    component: PackedKinematicComponent
    profile: PolarProfileSpec
    recipe: PolarPopulationRecipe
    operator_parameters: tuple[float, ...]
    root_seed: int
    profile_address: bytes
    prototype_address: bytes
    lineage_namespace: bytes
    content_address: bytes
    glow_parameters: tuple[float, float, float] | None = None


@dataclass(frozen=True)
class PolarPopulationProjectSpec:
    groups: tuple[PolarPopulationGroup, ...]
    root_seed: int = 0

    @property
    def total_instances(self) -> int:
        return sum(group.recipe.instance_count for group in self.groups)

    @property
    def generated_copies(self) -> int:
        return self.total_instances - len(self.groups)


@dataclass(frozen=True)
class PolarDisplayInstance:
    """Derived render data only; this value is intentionally not an ECS entity."""

    prototype_id: str
    index: int
    lineage: int
    profile_id: str
    pose_word: int
    motion_word: int
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    scale: tuple[float, float, float]
    velocity: tuple[float, float, float]
    local_pose: bool = False
    fixed_tick: int | None = None
    cycle_tick: int = 0
    age: float = 0.0
    envelope: float = 1.0
    previous_pose_word: int | None = None
    duration_ticks: int | None = None
    local_rho: float | None = None
    height_factor: float = 0.0
    base_scale_scalar: float = 1.0
    glow_sample: PolarGlowSample | None = None

    @property
    def display_id(self) -> str:
        return f"{self.prototype_id}__polar_display_{self.lineage:016x}"


@dataclass(frozen=True)
class PolarBurstPhase:
    """One exact fixed-tick sample of a looping Radial Burst recipe."""

    fixed_tick: int
    cycle_tick: int
    duration_ticks: int
    age: float
    rho: float
    envelope: float


@dataclass(frozen=True)
class PolarGlowSample:
    """One deterministic UGLUT2 reference sample for the material field."""

    phase12: int
    shifted_theta_code: int
    pulse: float
    direction: float
    glow: float
    display_scale_multiplier: float = 1.0


@dataclass(frozen=True)
class PolarMaterialSample:
    """Presentation-only log-polar coordinate and first Polar Bands result."""

    q: float
    direction_x: float
    direction_y: float
    phase12: int
    phase: float
    band: float
    multiplier: float


def _encoded_text(value: str) -> bytes:
    encoded = str(value).encode("utf-8")
    if not encoded or len(encoded) > 65535:
        raise PolarPopulationError("content-addressed prototype text must use 1..65535 UTF-8 bytes")
    return struct.pack("<H", len(encoded)) + encoded


def polar_profile_semantics_address(profile: PolarProfileSpec) -> bytes:
    """Return the 128-bit address of exact LUT and motion-profile semantics."""

    motion = profile.codec.motion_range
    payload = bytearray(b"KCPR392-profile-semantics-v1\0")
    payload.extend(_encoded_text(profile.id))
    payload.extend(
        struct.pack(
            "<4dI",
            motion.rho_velocity,
            motion.theta_velocity,
            motion.rho_acceleration,
            motion.theta_acceleration,
            profile.lut_resolution,
        )
    )
    try:
        lut = profile_lut_bytes(profile)
    except ValueError as error:
        raise PolarPopulationError(
            f"polar population profile {profile.id!r} is invalid: {error}"
        ) from error
    payload.extend(struct.pack("<I", len(lut)))
    payload.extend(lut)
    return hashlib.sha256(payload).digest()[:_ADDRESS_BYTES]


def polar_prototype_semantics_address(
    node: Any,
    component: PackedKinematicComponent,
    profile_address: bytes,
    mesh_address: bytes,
    material_address: bytes,
) -> bytes:
    """Address authored render/anchor inputs consumed by display generation."""

    if any(
        len(address) != _ADDRESS_BYTES
        for address in (profile_address, mesh_address, material_address)
    ):
        raise PolarPopulationError("prototype dependency addresses must contain 16 bytes")
    transform = getattr(node, "transform", None)
    if transform is None:
        raise PolarPopulationError(f"prototype {getattr(node, 'id', '')!r} has no transform")
    # Packed polar owns X/Z and facing, so ignored authored X/Z/rotation must
    # not churn identity.  Generated display members consume only authored Y,
    # scale, and Y velocity from the ordinary node transform/body.
    values = (
        transform.translation[1],
        *transform.scale,
        getattr(node, "velocity", (0.0, 0.0, 0.0))[1],
    )
    canonical_values = tuple(_f32(value, "Prototype transform") for value in values)
    payload = bytearray(b"KCPR392-prototype-semantics-v1\0")
    payload.extend(_encoded_text(str(getattr(node, "id", ""))))
    payload.extend(profile_address)
    payload.extend(mesh_address)
    payload.extend(material_address)
    payload.extend(
        struct.pack(
            "<QQ5f", component.pose_word, component.motion_word, *canonical_values
        )
    )
    return hashlib.sha256(payload).digest()[:_ADDRESS_BYTES]


def polar_asset_semantics_address(asset: Any, kind: str) -> bytes:
    """Address the exact canonical f32/u32 render lanes visible in KC3D392."""

    if kind == "mesh" and all(
        hasattr(asset, name) for name in ("vertices", "triangles", "resolved_normals")
    ):
        payload = bytearray(b"KCPR392-mesh-semantics-v1\0")
        vertices = tuple(asset.vertices)
        triangles = tuple(asset.triangles)
        normals = tuple(asset.resolved_normals())
        if len(normals) != len(vertices):
            raise PolarPopulationError(
                "polar population mesh normals must match its vertices"
            )
        payload.extend(struct.pack("<III", len(vertices), len(triangles), len(normals)))
        for vertex in vertices:
            payload.extend(
                struct.pack("<3f", *(_f32(value, "Mesh vertex") for value in vertex))
            )
        for triangle in triangles:
            if len(triangle) != 3 or any(
                isinstance(value, bool) or not isinstance(value, Integral)
                for value in triangle
            ):
                raise PolarPopulationError("polar population mesh triangle is invalid")
            try:
                payload.extend(struct.pack("<3I", *(int(value) for value in triangle)))
            except struct.error as error:
                raise PolarPopulationError(
                    "polar population mesh indices must fit unsigned 32-bit lanes"
                ) from error
        for normal in normals:
            payload.extend(
                struct.pack("<3f", *(_f32(value, "Mesh normal") for value in normal))
            )
    elif kind == "material" and all(
        hasattr(asset, name)
        for name in (
            "base_color",
            "metallic",
            "roughness",
            "emissive",
            "double_sided",
        )
    ):
        payload = bytearray(b"KCPR392-material-semantics-v1\0")
        values = (
            *asset.base_color,
            asset.metallic,
            asset.roughness,
            *asset.emissive,
        )
        payload.extend(
            struct.pack(
                "<9fB",
                *(_f32(value, "Material value") for value in values),
                1 if bool(asset.double_sided) else 0,
            )
        )
    else:
        raise PolarPopulationError(
            f"polar population {kind!r} has no canonical KC3D392 byte schedule"
        )
    return hashlib.sha256(payload).digest()[:_ADDRESS_BYTES]


def _operator_semantics_bytes(operator_mask: int) -> bytes:
    result = bytearray()
    for operator in POLAR_POPULATION_OPERATORS:
        if operator_mask & operator.mask:
            result.extend(struct.pack("<HQ", operator.code, operator.meaning_hash))
    return bytes(result)


def polar_recipe_record_addresses(
    *,
    preset: str,
    instance_count: int,
    recipe_seed: int,
    operator_parameters: tuple[float, ...] | list[float],
    profile_address: bytes,
    prototype_address: bytes,
    root_seed: int = 0,
    glow_parameters: tuple[float, ...] | list[float] | None = None,
    grow_copies: bool = False,
) -> tuple[bytes, bytes]:
    """Address one exact KCPR record without reconstructing UI multipliers.

    The first excludes only ``instance_count``.  The second includes it.
    Both include preset operator meanings, seed, profile/prototype semantics,
    and all eight canonical binary32 placement parameters.  The optional v3
    modifier changes only full content: its operator mask, meanings, and three
    binary32 lanes are appended without changing the spatial lineage digest.
    The v4 ``grow_copies`` modifier similarly changes only full content and
    reuses the exact v3 Glow lanes rather than adding a parameter.
    """

    operator_mask = operator_mask_for_preset(preset)
    instance_count = _integer(
        instance_count,
        "Objects in polar group",
        2,
        (
            MAX_POLAR_BURST_INSTANCES_PER_RECIPE
            if preset == "burst"
            else MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE
        ),
    )
    recipe_seed = _integer(recipe_seed, "World number", 0, _MASK64)
    parameters = validate_polar_population_operator_parameters(
        preset, operator_parameters
    )
    glow = (
        None
        if glow_parameters is None
        else validate_polar_glow_operator_parameters(glow_parameters)
    )
    if not isinstance(grow_copies, bool):
        raise PolarPopulationError("Grow glowing copies must be true or false")
    if grow_copies and glow is None:
        raise PolarPopulationError(
            "Grow glowing copies requires Glow by distance parameters"
        )
    root_seed = _integer(root_seed, "Render root seed", 0, _MASK64)
    if len(profile_address) != _ADDRESS_BYTES or len(prototype_address) != _ADDRESS_BYTES:
        raise PolarPopulationError("recipe dependency addresses must contain 16 bytes")
    preset_code = POLAR_POPULATION_PRESETS.index(preset) + 1
    address_version = 2 if preset == "burst" else 1
    shared = bytearray(
        f"KCPR392-lineage-semantics-v{address_version}\0".encode("ascii")
    )
    shared.extend(
        struct.pack(
            "<HHQQ",
            preset_code,
            operator_mask,
            root_seed,
            recipe_seed,
        )
    )
    shared.extend(profile_address)
    shared.extend(prototype_address)
    shared.extend(_PARAMETER_STRUCT.pack(*parameters))
    shared.extend(_operator_semantics_bytes(operator_mask))
    lineage_namespace = hashlib.sha256(shared).digest()[:_ADDRESS_BYTES]
    if glow is None:
        content = bytearray(
            f"KCPR392-full-recipe-content-v{address_version}\0".encode("ascii")
        )
        content.extend(shared)
    elif not grow_copies:
        full_operator_mask = operator_mask | POLAR_GLOW_OPERATOR_MASK
        content = bytearray(b"KCPR392-full-recipe-content-v3\0")
        content.extend(shared)
        content.extend(struct.pack("<H", full_operator_mask))
        content.extend(_GLOW_PARAMETER_STRUCT.pack(*glow))
        content.extend(_operator_semantics_bytes(POLAR_GLOW_OPERATOR_MASK))
    else:
        full_operator_mask = (
            operator_mask
            | POLAR_GLOW_OPERATOR_MASK
            | POLAR_GROW_COPIES_OPERATOR_MASK
        )
        content = bytearray(b"KCPR392-full-recipe-content-v4\0")
        content.extend(shared)
        content.extend(struct.pack("<H", full_operator_mask))
        content.extend(_GLOW_PARAMETER_STRUCT.pack(*glow))
        content.extend(
            _operator_semantics_bytes(
                POLAR_GLOW_OPERATOR_MASK | POLAR_GROW_COPIES_OPERATOR_MASK
            )
        )
    content.extend(struct.pack("<I", instance_count))
    content_address = hashlib.sha256(content).digest()[:_ADDRESS_BYTES]
    return lineage_namespace, content_address


def polar_recipe_addresses(
    recipe: PolarPopulationRecipe,
    profile_address: bytes,
    prototype_address: bytes,
    root_seed: int = 0,
    *,
    operator_parameters: tuple[float, ...] | list[float] | None = None,
    glow_parameters: tuple[float, ...] | list[float] | None = None,
) -> tuple[bytes, bytes]:
    """Return lineage/full addresses for one child-facing authored recipe."""

    recipe.validate()
    if recipe.glow_by_distance is None and glow_parameters is not None:
        raise PolarPopulationError(
            "Glow operator parameters require an enabled glow_by_distance modifier"
        )
    if recipe.glow_by_distance is not None and glow_parameters is None:
        raise PolarPopulationError(
            "Glow by distance addresses require its compiled Movement profile fields"
        )
    return polar_recipe_record_addresses(
        preset=recipe.preset,
        instance_count=recipe.instance_count,
        recipe_seed=recipe.seed,
        operator_parameters=(
            recipe.operator_parameters
            if operator_parameters is None
            else operator_parameters
        ),
        profile_address=profile_address,
        prototype_address=prototype_address,
        root_seed=root_seed,
        glow_parameters=glow_parameters,
        grow_copies=(
            False
            if recipe.glow_by_distance is None
            else recipe.glow_by_distance.grow_copies
        ),
    )


def _validated_polar_prototype(node: Any) -> None:
    node_id = str(getattr(node, "id", ""))
    metadata = getattr(node, "metadata", None)
    if not isinstance(metadata, Mapping):
        raise PolarPopulationError(f"node {node_id!r} metadata must be an object")
    if metadata.get("packed_kinematic") is None:
        raise PolarPopulationError(
            f"{node_id!r} needs a Movement Pattern before it can make a polar display population"
        )
    if metadata.get("scatter_population") is not None:
        raise PolarPopulationError(
            f"{node_id!r} cannot combine Populate Area with a polar display population"
        )
    if bool(getattr(node, "dynamic", False)):
        raise PolarPopulationError(
            f"{node_id!r} must be static because its Movement Pattern owns its position"
        )


def collect_polar_population_project_spec(project: Any) -> PolarPopulationProjectSpec:
    """Validate and collect canonical sparse polar render recipes."""

    nodes = tuple(getattr(project, "nodes", ()))
    has_recipe = False
    for node_index, node in enumerate(nodes):
        metadata = getattr(node, "metadata", None)
        if not isinstance(metadata, Mapping):
            raise PolarPopulationError(f"node {node_index} metadata must be an object")
        has_recipe = has_recipe or POLAR_POPULATION_METADATA_KEY in metadata
    if not has_recipe:
        return PolarPopulationProjectSpec((), 0)
    try:
        polar = collect_polar_project_spec(project)
    except ValueError as error:
        raise PolarPopulationError(
            f"invalid packed Movement Pattern dependency: {error}"
        ) from error
    try:
        render_config = render_substrate_config_from_project(project)
    except ValueError as error:
        raise PolarPopulationError(f"invalid Render root seed: {error}") from error
    root_seed = 0 if render_config is None else render_config.seed
    project_world = getattr(project, "world", None)
    fixed_dt = getattr(project_world, "fixed_dt", None)
    component_by_node = {item.node_index: item for item in polar.components}
    profile_by_id = {profile.id: profile for profile in polar.profiles}
    groups: list[PolarPopulationGroup] = []
    for node_index, node in enumerate(nodes):
        metadata = getattr(node, "metadata", None)
        if not isinstance(metadata, Mapping):
            raise PolarPopulationError(f"node {node_index} metadata must be an object")
        raw = metadata.get(POLAR_POPULATION_METADATA_KEY)
        if raw is None:
            continue
        if len(groups) >= MAX_POLAR_POPULATION_RECIPES:
            raise PolarPopulationError(
                f"projects support at most {MAX_POLAR_POPULATION_RECIPES} polar populations"
            )
        _validated_polar_prototype(node)
        component_spec: PolarComponentSpec | None = component_by_node.get(node_index)
        if component_spec is None:
            raise PolarPopulationError(
                f"{node.id!r} has no valid packed Movement Pattern component"
            )
        recipe = (
            PolarPopulationRecipe.from_mapping(raw.to_dict())
            if isinstance(raw, PolarPopulationRecipe)
            else PolarPopulationRecipe.from_mapping(raw)
        )
        recipe.validate()
        profile = profile_by_id[component_spec.component.profile_id]
        operator_parameters = polar_population_operator_parameters(
            recipe,
            profile=profile if recipe.preset == "burst" else None,
            fixed_dt=fixed_dt if recipe.preset == "burst" else None,
        )
        glow_parameters = (
            None
            if recipe.glow_by_distance is None
            else polar_glow_by_distance_operator_parameters(
                recipe.glow_by_distance,
                profile=profile,
            )
        )
        profile_address = polar_profile_semantics_address(profile)
        meshes = getattr(project, "meshes", {})
        materials = getattr(project, "materials", {})
        try:
            mesh = meshes[node.mesh_id]
            material = materials[node.material_id]
        except (KeyError, TypeError) as error:
            raise PolarPopulationError(
                f"{node.id!r} references missing render content"
            ) from error
        mesh_address = polar_asset_semantics_address(mesh, "mesh")
        material_address = polar_asset_semantics_address(material, "material")
        prototype_address = polar_prototype_semantics_address(
            node,
            component_spec.component,
            profile_address,
            mesh_address,
            material_address,
        )
        lineage_namespace, content_address = polar_recipe_addresses(
            recipe,
            profile_address,
            prototype_address,
            root_seed,
            operator_parameters=operator_parameters,
            glow_parameters=glow_parameters,
        )
        groups.append(
            PolarPopulationGroup(
                node_index,
                str(node.id),
                component_spec.component,
                profile,
                recipe,
                operator_parameters,
                root_seed,
                profile_address,
                prototype_address,
                lineage_namespace,
                content_address,
                glow_parameters,
            )
        )
    result = PolarPopulationProjectSpec(tuple(groups), root_seed)
    burst_groups = tuple(
        group for group in result.groups if group.recipe.preset == "burst"
    )
    if len(burst_groups) > MAX_POLAR_BURST_RECIPES:
        raise PolarPopulationError(
            f"projects support at most {MAX_POLAR_BURST_RECIPES} Radial Burst recipes"
        )
    burst_instances = sum(group.recipe.instance_count for group in burst_groups)
    if burst_instances > MAX_POLAR_BURST_TOTAL_INSTANCES:
        raise PolarPopulationError(
            f"Radial Burst recipes contain {burst_instances} display instances; "
            f"project limit is {MAX_POLAR_BURST_TOTAL_INSTANCES}"
        )
    if result.total_instances > MAX_POLAR_POPULATION_TOTAL_INSTANCES:
        raise PolarPopulationError(
            f"polar populations contain {result.total_instances} display instances; "
            f"project limit is {MAX_POLAR_POPULATION_TOTAL_INSTANCES}"
        )
    return result


def _namespace_u64(address: bytes) -> int:
    if len(address) != _ADDRESS_BYTES:
        raise PolarPopulationError("lineage namespace must contain 16 bytes")
    return combine_seed(
        int.from_bytes(address[:8], "little"),
        int.from_bytes(address[8:], "little"),
    )


def _lane(lineage: int, lane: int) -> float:
    return seed_unit_float(combine_seed(lineage, lane))


def polar_population_lineage(group: PolarPopulationGroup, index: int) -> int:
    """Return the count-independent lineage for prototype zero or any copy."""

    resolved_index = _integer(
        index,
        "Polar display index",
        0,
        group.recipe.instance_count - 1,
    )
    session_seed = combine_seed(group.root_seed, group.recipe.seed)
    namespace = _namespace_u64(group.lineage_namespace)
    return stable_id(session_seed, namespace, resolved_index)


def _add32(left: float, right: float, label: str) -> float:
    return _f32(_f32(left, label) + _f32(right, label), label)


def _sub32(left: float, right: float, label: str) -> float:
    return _f32(_f32(left, label) - _f32(right, label), label)


def _mul32(left: float, right: float, label: str) -> float:
    return _f32(_f32(left, label) * _f32(right, label), label)


def _div32(left: float, right: float, label: str) -> float:
    denominator = _f32(right, label)
    if denominator == 0.0:
        raise PolarPopulationError(f"{label} cannot divide by zero")
    return _f32(_f32(left, label) / denominator, label)


def _periodic_turn_code(turns: float, bits: int) -> int:
    """Quantize staged-f32 fractional turns without radians or libm trig."""

    value = _f32(turns, "Generated turn")
    whole = math.floor(value)
    fraction = _sub32(value, float(whole), "Fractional generated turn")
    scaled = _mul32(fraction, float(1 << bits), "Generated turn code")
    return int(math.floor(scaled)) & ((1 << bits) - 1)


def polar_material_phase12(lineage: int) -> int:
    """Derive the shared presentation-only phase from lineage lane 5."""

    resolved_lineage = _integer(lineage, "Polar display lineage", 0, _MASK64)
    scaled = _mul32(_lane(resolved_lineage, 5), 4096.0, "Polar material phase")
    return int(math.floor(scaled)) & ((1 << 12) - 1)


def polar_glow_phase12(lineage: int) -> int:
    """Compatibility name for the unchanged shared 12-bit material phase."""

    return polar_material_phase12(lineage)


def polar_material_bands_sample(
    *,
    lineage: int,
    rho: float,
    rho_min: float,
    rho_max: float,
    direction: tuple[float, float] | list[float],
    bands: int,
    strength: float,
) -> PolarMaterialSample:
    """Evaluate the canonical staged-f32 Polar Bands reference.

    ``direction`` is deliberately supplied by the placement path. Callers must
    reuse their existing Direct or UGLUT2 direction sample rather than sampling
    a second material-only lookup.
    """

    resolved_bands = _integer(bands, "Polar Material bands", 1, 32)
    if (
        not isinstance(strength, bool)
        and isinstance(strength, Real)
        and float(strength) == 0.0
        and math.copysign(1.0, float(strength)) < 0.0
    ):
        raise PolarPopulationError(
            "Polar Material strength must use finite positive zero through one"
        )
    resolved_strength = _f32(strength, "Polar Material strength")
    if not 0.0 <= resolved_strength <= 1.0 or (
        resolved_strength == 0.0
        and math.copysign(1.0, resolved_strength) < 0.0
    ):
        raise PolarPopulationError(
            "Polar Material strength must use finite positive zero through one"
        )
    if not isinstance(direction, (tuple, list)) or len(direction) != 2:
        raise PolarPopulationError("Polar Material direction requires two lanes")
    direction_x = _f32(direction[0], "Polar Material direction X")
    direction_y = _f32(direction[1], "Polar Material direction Y")
    if not -1.0001 <= direction_x <= 1.0001 or not -1.0001 <= direction_y <= 1.0001:
        raise PolarPopulationError("Polar Material direction is outside its unit bound")

    minimum = _f32(rho_min, "Polar Material rho minimum")
    maximum = _f32(rho_max, "Polar Material rho maximum")
    span = _sub32(maximum, minimum, "Polar Material rho span")
    if span <= 0.0:
        raise PolarPopulationError("Polar Material rho range must increase")
    normalized = _div32(
        _sub32(_f32(rho, "Polar Material rho"), minimum, "Polar Material rho offset"),
        span,
        "Polar Material normalized rho",
    )
    q = _f32(min(1.0, max(0.0, normalized)), "Clamped Polar Material rho")
    phase12 = polar_material_phase12(lineage)
    phase = _div32(float(phase12), 4096.0, "Polar Material unit phase")
    angular_warp = _mul32(
        0.25,
        _add32(1.0, direction_x, "Polar Material direction offset"),
        "Polar Material angular warp",
    )
    coordinate = _add32(
        _add32(
            _mul32(float(resolved_bands), q, "Polar Material radial bands"),
            phase,
            "Polar Material seeded radial coordinate",
        ),
        angular_warp,
        "Polar Material coordinate",
    )
    wave = _sub32(
        coordinate,
        float(math.floor(coordinate)),
        "Polar Material fractional coordinate",
    )
    triangle_distance = abs(
        _sub32(
            _mul32(2.0, wave, "Polar Material doubled wave"),
            1.0,
            "Polar Material centered wave",
        )
    )
    band = _sub32(1.0, triangle_distance, "Polar Material triangle band")
    multiplier = _add32(
        _mul32(
            _sub32(1.0, resolved_strength, "Polar Material inverse strength"),
            1.0,
            "Polar Material authored base weight",
        ),
        _mul32(
            resolved_strength,
            _add32(0.5, band, "Polar Material band range"),
            "Polar Material band weight",
        ),
        "Polar Material base multiplier",
    )
    return PolarMaterialSample(
        q=q,
        direction_x=direction_x,
        direction_y=direction_y,
        phase12=phase12,
        phase=phase,
        band=band,
        multiplier=multiplier,
    )


def polar_glow_by_distance_sample(
    parameters: tuple[float, ...] | list[float],
    *,
    lineage: int,
    rho: float,
    theta_code: int,
    lut: PolarLookupTable,
    grow_copies: bool = False,
) -> PolarGlowSample:
    """Evaluate the canonical quantized-UGLUT2 CPU/desktop glow reference."""

    if not isinstance(grow_copies, bool):
        raise PolarPopulationError("Grow glowing copies must be true or false")
    center_rho, inv_half_width, strength = (
        validate_polar_glow_operator_parameters(parameters)
    )
    resolved_rho = _f32(rho, "Glow sample log radius")
    resolved_theta_code = _integer(
        theta_code,
        "Glow sample theta code",
        0,
        (1 << _THETA_BITS) - 1,
    )
    phase12 = polar_glow_phase12(lineage)
    shifted_theta_code = (
        resolved_theta_code + (phase12 << (_THETA_BITS - 12))
    ) & ((1 << _THETA_BITS) - 1)

    distance = abs(
        _mul32(
            _sub32(resolved_rho, center_rho, "Glow log radius delta"),
            inv_half_width,
            "Glow normalized log radius",
        )
    )
    unit = _f32(min(1.0, max(0.0, distance)), "Clamped Glow distance")
    unit_squared = _mul32(unit, unit, "Glow squared distance")
    smooth = _mul32(
        unit_squared,
        _sub32(
            3.0,
            _mul32(2.0, unit, "Glow doubled distance"),
            "Glow smoothstep fall",
        ),
        "Glow smoothstep",
    )
    pulse = _sub32(1.0, smooth, "Glow radial pulse")

    angle_step = _div32(
        math.tau,
        float(1 << _THETA_BITS),
        "Glow theta18 angle step",
    )
    shifted_theta = _mul32(
        float(shifted_theta_code), angle_step, "Glow shifted angle"
    )
    _sine, cosine = lut.sin_cos(shifted_theta)
    direction = _add32(
        0.5,
        _mul32(0.5, _f32(cosine, "Glow UGLUT2 cosine"), "Glow cosine half"),
        "Glow direction factor",
    )
    direction = _f32(
        min(1.0, max(0.0, direction)), "Clamped Glow direction factor"
    )
    glow = _mul32(
        _mul32(strength, pulse, "Glow strengthened pulse"),
        direction,
        "Glow material value",
    )
    glow = _f32(min(4.0, max(0.0, glow)), "Clamped Glow material value")
    display_scale_multiplier = (
        _f32(1.0, "Generated display scale multiplier")
        if not grow_copies
        else _f32(
            min(
                5.0,
                max(
                    1.0,
                    _add32(1.0, glow, "Generated display scale multiplier"),
                ),
            ),
            "Clamped generated display scale multiplier",
        )
    )
    return PolarGlowSample(
        phase12=phase12,
        shifted_theta_code=shifted_theta_code,
        pulse=pulse,
        direction=direction,
        glow=glow,
        display_scale_multiplier=display_scale_multiplier,
    )


def polar_population_glow_sample(
    group: PolarPopulationGroup,
    *,
    index: int,
    pose_word: int,
    lut: PolarLookupTable | None = None,
) -> PolarGlowSample | None:
    """Evaluate a group's optional field without exposing packed lane offsets."""

    if group.glow_parameters is None:
        return None
    glow = group.recipe.glow_by_distance
    if glow is None:
        raise PolarPopulationError(
            "compiled Glow parameters require an enabled glow_by_distance modifier"
        )
    lineage = polar_population_lineage(group, index)
    codec = group.profile.codec
    pose = codec.unpack_pose(pose_word)
    theta_code = (pose_word >> _THETA_SHIFT) & ((1 << _THETA_BITS) - 1)
    selected_lut = lut or quantized_profile_lut(group.profile)
    if selected_lut.profile != codec.profile:
        raise PolarPopulationError(
            "Glow lookup table does not match the polar population profile"
        )
    return polar_glow_by_distance_sample(
        group.glow_parameters,
        lineage=lineage,
        rho=pose.rho,
        theta_code=theta_code,
        lut=selected_lut,
        grow_copies=glow.grow_copies,
    )


def _polar_grown_display_scale(
    group: PolarPopulationGroup,
    *,
    index: int,
    pose_word: int,
    scale: tuple[float, float, float],
    lut: PolarLookupTable,
) -> tuple[tuple[float, float, float], PolarGlowSample | None]:
    """Apply and retain one shared field sample for a generated display copy."""

    glow = group.recipe.glow_by_distance
    if glow is None or not glow.grow_copies:
        return scale, None
    sample = polar_population_glow_sample(
        group,
        index=index,
        pose_word=pose_word,
        lut=lut,
    )
    if sample is None:  # pragma: no cover - guarded by compiled group invariants
        raise PolarPopulationError(
            "Grow glowing copies requires compiled Glow by distance parameters"
        )
    grown_scale = tuple(
        _mul32(value, sample.display_scale_multiplier, "Grown generated display scale")
        for value in scale
    )
    return grown_scale, sample  # type: ignore[return-value]


def polar_burst_phase(
    group: PolarPopulationGroup,
    fixed_tick: int | None = None,
) -> PolarBurstPhase:
    """Materialize one exact looping phase from serialized Burst fields.

    ``None`` is the authored-preview sample, deliberately placed at the
    integer midpoint of the serialized duration.  Runtime callers supply the
    authoritative fixed tick.  At a wrap (``cycle_tick == 0``), render
    interpolation must snap its previous pose to this same current pose rather
    than drawing a line back from the old outer edge.
    """

    if group.recipe.preset != "burst":
        raise PolarPopulationError("polar burst phase needs a Radial Burst recipe")
    (
        log_start,
        log_end,
        duration_value,
        _angle_step,
        _angle_jitter,
        _height_arc,
        _scale_min,
        _scale_max,
    ) = validate_polar_population_operator_parameters(
        "burst", group.operator_parameters
    )
    duration_ticks = int(duration_value)
    resolved_tick = (
        duration_ticks // 2
        if fixed_tick is None
        else _integer(fixed_tick, "Fixed tick", 0, _MASK64)
    )
    cycle_tick = resolved_tick % duration_ticks
    age = _div32(
        _f32(cycle_tick, "Burst cycle tick"),
        _f32(duration_ticks - 1, "Burst duration denominator"),
        "Burst age",
    )
    rho = _add32(
        log_start,
        _mul32(
            _sub32(log_end, log_start, "Burst log distance span"),
            age,
            "Burst log distance interpolation",
        ),
        "Burst log distance",
    )
    envelope = _mul32(
        _mul32(4.0, age, "Burst envelope rise"),
        _sub32(1.0, age, "Burst envelope fall"),
        "Burst envelope",
    )
    return PolarBurstPhase(
        fixed_tick=resolved_tick,
        cycle_tick=cycle_tick,
        duration_ticks=duration_ticks,
        age=age,
        rho=rho,
        envelope=envelope,
    )


def polar_burst_phase_pair(
    group: PolarPopulationGroup,
    fixed_tick: int | None = None,
) -> tuple[PolarBurstPhase, PolarBurstPhase]:
    """Return ``(previous, current)`` phases with an explicit wrap snap."""

    current = polar_burst_phase(group, fixed_tick)
    if current.cycle_tick == 0:
        return current, current
    previous = polar_burst_phase(group, current.fixed_tick - 1)
    return previous, current


def _polar_burst_pose_word(
    codec: Any,
    phase: PolarBurstPhase,
    theta_code: int,
    heading_code: int,
) -> int:
    packed_rho_tick = codec.pack_pose(
        PolarPose(phase.rho, 0.0, phase.cycle_tick, 0.0)
    )
    rho_mask = ((1 << _RHO_BITS) - 1) << _RHO_SHIFT
    tick_mask = ((1 << _TICK_BITS) - 1) << _TICK_SHIFT
    return (
        (packed_rho_tick & (rho_mask | tick_mask))
        | (theta_code << _THETA_SHIFT)
        | (heading_code << _HEADING_SHIFT)
    )


def _polar_burst_instance(
    node: Any,
    group: PolarPopulationGroup,
    index: int,
    source: PackedKinematicComponent,
    selected_lut: PolarLookupTable,
    fixed_tick: int | None,
) -> PolarDisplayInstance:
    """Generate one render-only local Burst value around its real prototype."""

    (
        _log_start,
        _log_end,
        _duration_ticks,
        angle_step_turns,
        angle_jitter_turns,
        height_arc,
        scale_min,
        scale_max,
    ) = validate_polar_population_operator_parameters(
        "burst", group.operator_parameters
    )
    previous_phase, phase = polar_burst_phase_pair(group, fixed_tick)
    lineage = polar_population_lineage(group, index)
    phase_lineage = polar_population_lineage(group, 0)
    seeded_phase = _lane(phase_lineage, 0)
    turn_jitter = _mul32(
        _sub32(_lane(lineage, 2), 0.5, "Centered Burst turn lane"),
        angle_jitter_turns,
        "Burst turn variation",
    )
    stepped_turn = _mul32(float(index), angle_step_turns, "Burst turn step")
    turns = _add32(
        _add32(seeded_phase, stepped_turn, "Seeded Burst stepped turn"),
        turn_jitter,
        "Generated Burst turn",
    )
    theta_code = _periodic_turn_code(turns, _THETA_BITS)
    heading_code = _periodic_turn_code(turns, _HEADING_BITS)

    codec = group.profile.codec
    pose_word = _polar_burst_pose_word(
        codec, phase, theta_code, heading_code
    )
    previous_pose_word = _polar_burst_pose_word(
        codec, previous_phase, theta_code, heading_code
    )
    local_component = PackedKinematicComponent(pose_word, 0, source.profile_id)
    local_state = codec.cartesian_state(local_component, selected_lut)
    anchor_state = codec.cartesian_state(source, selected_lut)
    local_x, local_z = (
        _f32(value, "Decoded Burst local position")
        for value in local_state["position"]
    )
    anchor_x, anchor_z = (
        _f32(value, "Decoded Burst anchor position")
        for value in anchor_state["position"]
    )
    anchor_velocity_x, anchor_velocity_z = anchor_state["velocity"]
    anchor_pose = anchor_state["pose"]
    anchor_sine, anchor_cosine = (
        _f32(value, "Decoded Burst anchor heading")
        for value in selected_lut.sin_cos(anchor_pose.heading)
    )
    # This is the renderer's Y-up convention, also used for mesh facing:
    # +heading rotates local +X toward world -Z.
    world_x = _add32(
        _add32(
            anchor_x,
            _mul32(anchor_cosine, local_x, "Burst rotated local X cosine"),
            "Burst anchor plus local X",
        ),
        _mul32(anchor_sine, local_z, "Burst rotated local Z sine"),
        "Generated Burst X",
    )
    world_z = _add32(
        anchor_z,
        _sub32(
            _mul32(anchor_cosine, local_z, "Burst rotated local Z cosine"),
            _mul32(anchor_sine, local_x, "Burst rotated local X sine"),
            "Burst rotated local Z",
        ),
        "Generated Burst Z",
    )

    height_factor = _add32(
        0.5, _lane(lineage, 3), "Burst height factor"
    )
    height_offset = _mul32(
        _mul32(height_arc, height_factor, "Burst authored arc"),
        phase.envelope,
        "Burst displayed arc",
    )
    base_y = _f32(getattr(node, "transform").translation[1], "Prototype height")
    height = _add32(base_y, height_offset, "Generated Burst height")
    base_scalar = _add32(
        scale_min,
        _mul32(
            _lane(lineage, 4),
            _sub32(scale_max, scale_min, "Burst size span"),
            "Burst size interpolation",
        ),
        "Burst base size",
    )
    display_scalar = _mul32(
        base_scalar, phase.envelope, "Burst displayed size"
    )
    authored_scale = tuple(
        _f32(value, "Prototype scale") for value in getattr(node, "transform").scale
    )
    scale = tuple(
        _mul32(value, display_scalar, "Generated Burst scale")
        for value in authored_scale
    )
    scale, glow_sample = _polar_grown_display_scale(
        group,
        index=index,
        pose_word=pose_word,
        scale=scale,  # type: ignore[arg-type]
        lut=selected_lut,
    )
    heading_mask = (1 << _HEADING_BITS) - 1
    anchor_heading_code = source.pose_word & heading_mask
    combined_heading_code = (anchor_heading_code + heading_code) & heading_mask
    combined_heading_word = (
        local_component.pose_word & ~heading_mask
    ) | combined_heading_code
    combined_heading = codec.unpack_pose(combined_heading_word).heading
    rotation = tuple(
        _f32(value, "Generated Burst facing")
        for value in quat_from_axis_angle((0.0, 1.0, 0.0), combined_heading)
    )
    source_y_velocity = _f32(
        getattr(node, "velocity", (0.0, 0.0, 0.0))[1],
        "Prototype Y velocity",
    )
    return PolarDisplayInstance(
        prototype_id=group.prototype_id,
        index=index,
        lineage=lineage,
        profile_id=source.profile_id,
        pose_word=pose_word,
        motion_word=0,
        translation=(world_x, height, world_z),
        rotation=rotation,
        scale=scale,  # type: ignore[arg-type]
        velocity=(
            _f32(anchor_velocity_x, "Generated Burst X velocity"),
            source_y_velocity,
            _f32(anchor_velocity_z, "Generated Burst Z velocity"),
        ),
        local_pose=True,
        fixed_tick=phase.fixed_tick,
        cycle_tick=phase.cycle_tick,
        age=phase.age,
        envelope=phase.envelope,
        previous_pose_word=previous_pose_word,
        duration_ticks=phase.duration_ticks,
        local_rho=phase.rho,
        height_factor=height_factor,
        base_scale_scalar=base_scalar,
        glow_sample=glow_sample,
    )


def polar_population_instance(
    node: Any,
    group: PolarPopulationGroup,
    index: int,
    *,
    component: PackedKinematicComponent | None = None,
    lut: PolarLookupTable | None = None,
    fixed_tick: int | None = None,
) -> PolarDisplayInstance:
    """Generate one independent display member; index zero is the ECS prototype."""

    recipe = group.recipe
    if not 1 <= index < recipe.instance_count:
        raise PolarPopulationError("polar display index is outside its generated range")
    source = component or group.component
    if source.profile_id != group.profile.id:
        raise PolarPopulationError("polar display component changed to an incompatible profile")
    codec = group.profile.codec
    selected_lut = lut or quantized_profile_lut(group.profile)
    if recipe.preset == "burst":
        return _polar_burst_instance(
            node,
            group,
            index,
            source,
            selected_lut,
            fixed_tick,
        )
    base_pose = codec.unpack_pose(source.pose_word)
    (
        log_min,
        log_max,
        radial_rate,
        angle_step_turns,
        angle_jitter_turns,
        height_spread,
        scale_min,
        scale_max,
    ) = validate_polar_population_operator_parameters(
        recipe.preset, group.operator_parameters
    )
    lineage = polar_population_lineage(group, index)

    if recipe.preset == "spiral":
        spiral_x = _mul32(float(index), radial_rate, "Spiral x")
        radial_unit = _div32(
            spiral_x,
            _add32(1.0, spiral_x, "Spiral denominator"),
            "Spiral radial unit",
        )
    else:
        radial_unit = _lane(lineage, 1)
    log_span = _sub32(log_max, log_min, "Log radius span")
    log_multiplier = _add32(
        log_min,
        _mul32(log_span, radial_unit, "Log radius interpolation"),
        "Log radius multiplier",
    )
    rho = _add32(base_pose.rho, log_multiplier, "Generated log radius")

    phase_lineage = polar_population_lineage(group, 0)
    seeded_phase = _lane(phase_lineage, 0)
    turn_jitter = _mul32(
        _sub32(_lane(lineage, 2), 0.5, "Centered turn lane"),
        angle_jitter_turns,
        "Turn variation",
    )
    stepped_turn = _mul32(float(index), angle_step_turns, "Turn step")
    turns = _add32(
        _add32(seeded_phase, stepped_turn, "Seeded stepped turn"),
        turn_jitter,
        "Generated turn",
    )
    theta_mask = (1 << _THETA_BITS) - 1
    heading_mask = (1 << _HEADING_BITS) - 1
    base_theta_code = (source.pose_word >> _THETA_SHIFT) & theta_mask
    base_heading_code = (source.pose_word >> _HEADING_SHIFT) & heading_mask
    theta_code = (
        base_theta_code + _periodic_turn_code(turns, _THETA_BITS)
    ) & theta_mask
    heading_code = (
        base_heading_code + _periodic_turn_code(turns, _HEADING_BITS)
    ) & heading_mask
    packed_rho = codec.pack_pose(PolarPose(rho, 0.0, 0, 0))
    rho_mask = ((1 << _RHO_BITS) - 1) << _RHO_SHIFT
    tick_mask = ((1 << _TICK_BITS) - 1) << _TICK_SHIFT
    pose_word = (
        (packed_rho & rho_mask)
        | (theta_code << _THETA_SHIFT)
        | (source.pose_word & tick_mask)
        | (heading_code << _HEADING_SHIFT)
    )
    display_component = PackedKinematicComponent(
        pose_word, source.motion_word, source.profile_id
    )
    state = codec.cartesian_state(display_component, selected_lut)
    x, z = state["position"]
    velocity_x, velocity_z = state["velocity"]
    base_y = _f32(getattr(node, "transform").translation[1], "Prototype height")
    height = _add32(
        base_y,
        _mul32(
            _sub32(_lane(lineage, 3), 0.5, "Centered height lane"),
            height_spread,
            "Height variation",
        ),
        "Generated height",
    )
    scalar = _add32(
        scale_min,
        _mul32(
            _lane(lineage, 4),
            _sub32(scale_max, scale_min, "Size span"),
            "Size interpolation",
        ),
        "Generated size",
    )
    authored_scale = tuple(
        _f32(value, "Prototype scale") for value in getattr(node, "transform").scale
    )
    scale = tuple(
        _mul32(value, scalar, "Generated scale") for value in authored_scale
    )
    scale, glow_sample = _polar_grown_display_scale(
        group,
        index=index,
        pose_word=pose_word,
        scale=scale,  # type: ignore[arg-type]
        lut=selected_lut,
    )
    pose = state["pose"]
    rotation = tuple(
        _f32(value, "Generated facing")
        for value in quat_from_axis_angle((0.0, 1.0, 0.0), pose.heading)
    )
    source_y_velocity = _f32(getattr(node, "velocity", (0.0, 0.0, 0.0))[1], "Prototype Y velocity")
    return PolarDisplayInstance(
        prototype_id=group.prototype_id,
        index=index,
        lineage=lineage,
        profile_id=source.profile_id,
        pose_word=pose_word,
        motion_word=source.motion_word,
        translation=(_f32(x, "Generated X"), height, _f32(z, "Generated Z")),
        rotation=rotation,
        scale=scale,  # type: ignore[arg-type]
        velocity=(
            _f32(velocity_x, "Generated X velocity"),
            source_y_velocity,
            _f32(velocity_z, "Generated Z velocity"),
        ),
        glow_sample=glow_sample,
    )


def polar_population_instances(
    node: Any,
    group: PolarPopulationGroup,
    *,
    component: PackedKinematicComponent | None = None,
    fixed_tick: int | None = None,
) -> tuple[PolarDisplayInstance, ...]:
    """Generate copies 2..N as render data without touching the ECS world."""

    lut = quantized_profile_lut(group.profile)
    return tuple(
        polar_population_instance(
            node,
            group,
            index,
            component=component,
            lut=lut,
            fixed_tick=fixed_tick,
        )
        for index in range(1, group.recipe.instance_count)
    )


def operators_for_mask(mask: int) -> tuple[PolarPopulationOperator, ...]:
    supported = sum(operator.mask for operator in POLAR_POPULATION_OPERATORS)
    if mask & ~supported:
        raise PolarPopulationError("polar population operator mask has unsupported bits")
    return tuple(
        operator for operator in POLAR_POPULATION_OPERATORS if mask & operator.mask
    )


__all__ = [
    "MAX_POLAR_BURST_INSTANCES_PER_RECIPE",
    "MAX_POLAR_BURST_RECIPES",
    "MAX_POLAR_BURST_TOTAL_INSTANCES",
    "MAX_POLAR_BURST_DURATION_TICKS",
    "MIN_POLAR_BURST_DURATION_TICKS",
    "MAX_POLAR_POPULATION_INSTANCES_PER_RECIPE",
    "MAX_POLAR_POPULATION_RECIPES",
    "MAX_POLAR_POPULATION_TOTAL_INSTANCES",
    "POLAR_POPULATION_METADATA_KEY",
    "POLAR_BURST_MATH_SCHEDULE",
    "POLAR_GLOW_MATH_SCHEDULE",
    "POLAR_GLOW_OPERATOR_MASK",
    "POLAR_GROW_COPIES_MATH_SCHEDULE",
    "POLAR_GROW_COPIES_OPERATOR_MASK",
    "POLAR_MATERIAL_BANDS_MATH_SCHEDULE",
    "POLAR_POPULATION_MATH_SCHEDULE",
    "POLAR_POPULATION_OPERATORS",
    "POLAR_POPULATION_PRESETS",
    "POLAR_POPULATION_PRESET_LABELS",
    "POLAR_POPULATION_V1_OPERATOR_CODES",
    "POLAR_POPULATION_V2_OPERATOR_CODES",
    "POLAR_POPULATION_V3_OPERATOR_CODES",
    "POLAR_POPULATION_V4_OPERATOR_CODES",
    "PolarBurstPhase",
    "PolarDisplayInstance",
    "PolarGlowByDistance",
    "PolarGlowSample",
    "PolarMaterialSample",
    "PolarPopulationError",
    "PolarPopulationGroup",
    "PolarPopulationOperator",
    "PolarPopulationProjectSpec",
    "PolarPopulationRecipe",
    "collect_polar_population_project_spec",
    "operator_mask_for_preset",
    "operator_mask_for_recipe",
    "operators_for_mask",
    "polar_burst_phase",
    "polar_burst_phase_pair",
    "polar_glow_by_distance_operator_parameters",
    "polar_glow_by_distance_sample",
    "polar_glow_phase12",
    "polar_material_bands_sample",
    "polar_material_phase12",
    "polar_population_instance",
    "polar_population_instances",
    "polar_population_glow_sample",
    "polar_population_lineage",
    "polar_population_operator_parameters",
    "polar_population_preset",
    "polar_asset_semantics_address",
    "polar_profile_semantics_address",
    "polar_prototype_semantics_address",
    "polar_recipe_addresses",
    "polar_recipe_record_addresses",
    "validate_polar_glow_operator_parameters",
    "validate_polar_population_operator_parameters",
]
