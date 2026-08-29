"""Compact deterministic static populations for Mobile3D scenes.

``Populate Area`` is intentionally a render-decoration component, not a
gameplay spawner.  One authored prototype remains the authoritative node and
the other instances are addressed independently from a UGTS 4.1-compatible
SplitMix64 schedule.  Increasing a population therefore preserves every
existing instance and the authoring JSON never expands into copied nodes.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct
from typing import Any, Mapping

from .math3d import quat_mul, quat_normalize


SCATTER_METADATA_KEY = "scatter_population"
MAX_SCATTER_GROUPS = 64
MAX_SCATTER_INSTANCES_PER_GROUP = 256
MAX_SCATTER_TOTAL_INSTANCES = 1024

_MASK64 = (1 << 64) - 1
_GOLDEN64 = 0x9E3779B97F4A7C15
_FNV64_OFFSET = 0xCBF29CE484222325
_FNV64_PRIME = 0x100000001B3
_GAMEPLAY_TAGS = frozenset({"player", "collectible", "goal", "hazard"})
_ALLOWED_KEYS = frozenset(
    {"instance_count", "seed", "size", "scale_min", "scale_max", "random_yaw"}
)


class ScatterError(ValueError):
    """Invalid Populate Area authoring data or an unsafe prototype."""


def _u64(value: int) -> int:
    return int(value) & _MASK64


def splitmix64(value: int) -> int:
    """Return the UGTS 4.1 SplitMix64 permutation for ``value``."""

    value = _u64(value + _GOLDEN64)
    value = _u64((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9)
    value = _u64((value ^ (value >> 27)) * 0x94D049BB133111EB)
    return _u64(value ^ (value >> 31))


def hash64(text: str, seed: int = _FNV64_OFFSET) -> int:
    """Hash UTF-8 text with the small UGTS 4.1 namespace contract."""

    encoded = str(text).encode("utf-8")
    value = _u64(seed)
    for byte in encoded:
        value = _u64((value ^ byte) * _FNV64_PRIME)
    return splitmix64(value ^ len(encoded))


def combine_seed(seed: int, value: int) -> int:
    seed = _u64(seed)
    mixed = _u64(splitmix64(value) + _GOLDEN64 + _u64(seed << 6) + (seed >> 2))
    return splitmix64(seed ^ mixed)


def stable_id(session_seed: int, namespace_id: int, address: int) -> int:
    """Random-access lineage id; no previous instance is consulted."""

    return combine_seed(combine_seed(session_seed, namespace_id), address)


def f32(value: float) -> float:
    """Round once to the native binary32 layout domain."""

    try:
        result = struct.unpack("<f", struct.pack("<f", float(value)))[0]
    except (OverflowError, struct.error) as error:
        raise ScatterError("population value is outside the binary32 range") from error
    if not math.isfinite(result):
        raise ScatterError("population value must be finite")
    return result


def seed_unit_float(value: int) -> float:
    """Return the exact 24-bit unit interval value used by the native port."""

    upper = splitmix64(value) >> 40
    return f32(upper / 16777216.0)


@dataclass(frozen=True)
class ScatterPopulation:
    """One sparse render-only population recipe attached to a prototype."""

    instance_count: int = 8
    seed: int = 1
    size: tuple[float, float, float] = (8.0, 0.0, 8.0)
    scale_min: float = 0.85
    scale_max: float = 1.15
    random_yaw: bool = True

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ScatterPopulation":
        if not isinstance(value, Mapping):
            raise ScatterError("metadata.scatter_population must be an object")
        unknown = sorted(str(key) for key in value if key not in _ALLOWED_KEYS)
        if unknown:
            raise ScatterError(
                "scatter_population has unknown field(s): " + ", ".join(unknown)
            )
        raw_count = value.get("instance_count", 8)
        raw_seed = value.get("seed", 1)
        if isinstance(raw_count, bool) or not isinstance(raw_count, int):
            raise ScatterError("Objects in group must be an integer")
        if isinstance(raw_seed, bool) or not isinstance(raw_seed, int):
            raise ScatterError("World number must be an integer")
        raw_size = value.get("size", (8.0, 0.0, 8.0))
        if not isinstance(raw_size, (list, tuple)) or len(raw_size) != 3:
            raise ScatterError("Area size needs width, height and depth")
        try:
            size = tuple(f32(item) for item in raw_size)
            scale_min = f32(value.get("scale_min", 0.85))
            scale_max = f32(value.get("scale_max", 1.15))
        except (TypeError, ValueError) as error:
            raise ScatterError("Area and size variation must be finite numbers") from error
        raw_yaw = value.get("random_yaw", True)
        if not isinstance(raw_yaw, bool):
            raise ScatterError("Turn copies randomly must be true or false")
        result = cls(raw_count, raw_seed, size, scale_min, scale_max, raw_yaw)
        result.validate()
        return result

    def validate(self) -> None:
        if not 2 <= self.instance_count <= MAX_SCATTER_INSTANCES_PER_GROUP:
            raise ScatterError(
                f"Objects in group must be between 2 and {MAX_SCATTER_INSTANCES_PER_GROUP}"
            )
        if not 0 <= self.seed <= 0xFFFFFFFF:
            raise ScatterError("World number must be between 0 and 4294967295")
        if len(self.size) != 3 or any(not math.isfinite(v) or v < 0 for v in self.size):
            raise ScatterError("Area size must be finite and nonnegative")
        if self.size[0] <= 0 and self.size[2] <= 0:
            raise ScatterError("Area width or depth must be greater than zero")
        if (
            not math.isfinite(self.scale_min)
            or not math.isfinite(self.scale_max)
            or not 0.05 <= self.scale_min <= 8.0
            or not 0.05 <= self.scale_max <= 8.0
            or self.scale_min > self.scale_max
        ):
            raise ScatterError("Size variation must stay between 0.05 and 8.0 (min <= max)")
        if not isinstance(self.random_yaw, bool):
            raise ScatterError("Turn copies randomly must be true or false")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "instance_count": self.instance_count,
            "seed": self.seed,
            "size": list(self.size),
            "scale_min": self.scale_min,
            "scale_max": self.scale_max,
            "random_yaw": self.random_yaw,
        }


@dataclass(frozen=True)
class ScatterGroup:
    prototype_node_index: int
    prototype_id: str
    population: ScatterPopulation


@dataclass(frozen=True)
class ScatterProjectSpec:
    groups: tuple[ScatterGroup, ...]

    @property
    def total_instances(self) -> int:
        return sum(group.population.instance_count for group in self.groups)

    @property
    def generated_copies(self) -> int:
        return self.total_instances - len(self.groups)


@dataclass(frozen=True)
class ScatterInstance:
    """One derived binary32 transform; index zero is always authored instead."""

    index: int
    lineage: int
    translation: tuple[float, float, float]
    rotation: tuple[float, float, float, float]
    scale: tuple[float, float, float]
    yaw_radians: float


def _is_zero_vector(value: Any) -> bool:
    try:
        return len(value) == 3 and all(float(item) == 0.0 for item in value)
    except (TypeError, ValueError):
        return False


def _validate_prototype(node: Any) -> None:
    node_id = str(getattr(node, "id", ""))
    if bool(getattr(node, "dynamic", False)):
        raise ScatterError(f"{node_id!r} must be static before it can Populate Area")
    collider = getattr(node, "collider", None)
    if collider is not None and (
        str(getattr(collider, "shape", "none")) != "none"
        or bool(getattr(collider, "sensor", False))
    ):
        raise ScatterError(f"{node_id!r} cannot Populate Area while it has a collider or Trigger Area")
    if not _is_zero_vector(getattr(node, "velocity", (0, 0, 0))) or not _is_zero_vector(
        getattr(node, "angular_velocity", (0, 0, 0))
    ):
        raise ScatterError(f"{node_id!r} must stop moving before it can Populate Area")
    tags = {str(tag) for tag in getattr(node, "tags", ())}
    unsafe = sorted(tags & _GAMEPLAY_TAGS)
    if unsafe:
        raise ScatterError(
            f"{node_id!r} cannot Populate Area with gameplay tag(s): " + ", ".join(unsafe)
        )
    metadata = getattr(node, "metadata", {})
    if not isinstance(metadata, Mapping):
        raise ScatterError(f"{node_id!r} metadata must be an object")
    if metadata.get("visual_graph") is not None:
        raise ScatterError(f"{node_id!r} cannot Populate Area while Logic Blocks are attached")
    if metadata.get("packed_kinematic") is not None:
        raise ScatterError(f"{node_id!r} cannot Populate Area while a Movement Pattern is attached")


def validate_scatter_prototype(node: Any) -> None:
    """Public editor-facing safety check for a prospective prototype."""

    _validate_prototype(node)


def collect_scatter_project_spec(project: Any) -> ScatterProjectSpec:
    """Return the canonical sparse population view without recursive validation."""

    groups: list[ScatterGroup] = []
    nodes = tuple(getattr(project, "nodes", ()))
    authored_ids = {str(getattr(node, "id", "")) for node in nodes}
    derived_ids: set[str] = set()
    for node_index, node in enumerate(nodes):
        metadata = getattr(node, "metadata", {})
        if not isinstance(metadata, Mapping):
            raise ScatterError(f"node {node_index} metadata must be an object")
        raw = metadata.get(SCATTER_METADATA_KEY)
        if raw is None:
            continue
        if len(groups) >= MAX_SCATTER_GROUPS:
            raise ScatterError(f"projects support at most {MAX_SCATTER_GROUPS} populated areas")
        _validate_prototype(node)
        population = (
            raw if isinstance(raw, ScatterPopulation) else ScatterPopulation.from_mapping(raw)
        )
        population.validate()
        group = ScatterGroup(node_index, str(node.id), population)
        for instance in scatter_instances(node, group):
            derived_id = scatter_instance_id(group.prototype_id, instance.lineage)
            if derived_id in authored_ids or derived_id in derived_ids:
                raise ScatterError(f"derived population id collides with an authored node: {derived_id}")
            derived_ids.add(derived_id)
        groups.append(group)
    result = ScatterProjectSpec(tuple(groups))
    if result.total_instances > MAX_SCATTER_TOTAL_INSTANCES:
        raise ScatterError(
            f"populated areas contain {result.total_instances} objects; project limit is "
            f"{MAX_SCATTER_TOTAL_INSTANCES}"
        )
    return result


def _lane(lineage: int, lane: int) -> float:
    return seed_unit_float(combine_seed(lineage, lane))


def scatter_instance(node: Any, group: ScatterGroup, index: int) -> ScatterInstance:
    """Generate one independently addressable instance (index must be >= 1)."""

    population = group.population
    population.validate()
    if not 1 <= index < population.instance_count:
        raise ScatterError("population instance index is outside its generated range")
    transform = getattr(node, "transform", None)
    if transform is None:
        raise ScatterError(f"prototype {group.prototype_id!r} has no transform")
    # The native runtime reads prototype transforms from KC3D, whose TRS
    # fields are binary32.  Authoring records retain Python floats, so round
    # the complete prototype transform before *any* derived math.  Deferring
    # this until the generated result is packed changes quaternion
    # normalization and can move otherwise ordinary decimals (for example
    # 0.1) by one ULP relative to Android.
    base_translation = tuple(f32(value) for value in transform.translation)
    base_rotation = tuple(f32(value) for value in transform.rotation)
    base_scale = tuple(f32(value) for value in transform.scale)
    namespace = hash64(group.prototype_id)
    lineage = stable_id(population.seed, namespace, index)
    offset = tuple(
        f32((_lane(lineage, lane) - 0.5) * population.size[axis])
        for axis, lane in enumerate((1, 2, 3))
    )
    translation = tuple(
        f32(base_translation[axis] + offset[axis]) for axis in range(3)
    )
    scalar = f32(
        population.scale_min
        + _lane(lineage, 4) * (population.scale_max - population.scale_min)
    )
    scale = tuple(f32(base_scale[axis] * scalar) for axis in range(3))
    yaw = f32(_lane(lineage, 5) * (2.0 * math.pi)) if population.random_yaw else 0.0
    base = quat_normalize(base_rotation)
    if yaw:
        half = float(yaw) * 0.5
        yaw_quat = (math.cos(half), 0.0, math.sin(half), 0.0)
        rotation = quat_normalize(quat_mul(yaw_quat, base))
    else:
        rotation = base
    rotation32 = tuple(f32(value) for value in rotation)
    return ScatterInstance(index, lineage, translation, rotation32, scale, yaw)


def scatter_instances(node: Any, group: ScatterGroup) -> tuple[ScatterInstance, ...]:
    """Generate only copies 2..N; the prototype remains copy 1."""

    return tuple(
        scatter_instance(node, group, index)
        for index in range(1, group.population.instance_count)
    )


def scatter_instance_id(prototype_id: str, lineage: int) -> str:
    return f"{prototype_id}__population_{_u64(lineage):016x}"


__all__ = [
    "MAX_SCATTER_GROUPS",
    "MAX_SCATTER_INSTANCES_PER_GROUP",
    "MAX_SCATTER_TOTAL_INSTANCES",
    "SCATTER_METADATA_KEY",
    "ScatterError",
    "ScatterGroup",
    "ScatterInstance",
    "ScatterPopulation",
    "ScatterProjectSpec",
    "collect_scatter_project_spec",
    "combine_seed",
    "f32",
    "hash64",
    "scatter_instance",
    "scatter_instance_id",
    "scatter_instances",
    "seed_unit_float",
    "splitmix64",
    "stable_id",
    "validate_scatter_prototype",
]
