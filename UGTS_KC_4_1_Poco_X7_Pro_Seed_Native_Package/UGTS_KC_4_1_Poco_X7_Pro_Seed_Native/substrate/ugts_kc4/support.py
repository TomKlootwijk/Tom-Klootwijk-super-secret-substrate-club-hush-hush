"""Local spatial support volumes and semantic compatibility gates."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Protocol

from .model import Observation, Vec3, as_vec3, vec_distance, vec_dot, vec_norm, vec_normalize, vec_sub


class SupportVolume(Protocol):
    id: str

    def contains(self, point: Vec3, error_bound: float = 0.0) -> bool: ...
    def to_dict(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class SphereSupport:
    id: str
    center: Vec3
    radius: float

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("support id is required")
        object.__setattr__(self, "center", as_vec3(self.center, "sphere.center"))
        radius = float(self.radius)
        if not math.isfinite(radius) or radius <= 0:
            raise ValueError("sphere radius must be finite and positive")
        object.__setattr__(self, "radius", radius)

    def contains(self, point: Vec3, error_bound: float = 0.0) -> bool:
        return vec_distance(self.center, as_vec3(point)) <= self.radius + max(0.0, float(error_bound))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": "sphere", "center": list(self.center), "radius": self.radius}


@dataclass(frozen=True, slots=True)
class AABBSupport:
    id: str
    minimum: Vec3
    maximum: Vec3

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("support id is required")
        minimum = as_vec3(self.minimum, "aabb.minimum")
        maximum = as_vec3(self.maximum, "aabb.maximum")
        if any(minimum[index] > maximum[index] for index in range(3)):
            raise ValueError("AABB minimum exceeds maximum")
        object.__setattr__(self, "minimum", minimum)
        object.__setattr__(self, "maximum", maximum)

    def contains(self, point: Vec3, error_bound: float = 0.0) -> bool:
        point = as_vec3(point)
        error = max(0.0, float(error_bound))
        return all(self.minimum[index] - error <= point[index] <= self.maximum[index] + error for index in range(3))

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "type": "aabb", "minimum": list(self.minimum), "maximum": list(self.maximum)}


@dataclass(frozen=True, slots=True)
class ConeFrustumSupport:
    """Finite cone support with near/far radial bounds and an angular cosine gate."""

    id: str
    apex: Vec3
    axis: Vec3
    near: float
    far: float
    cos_half_angle: float

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("support id is required")
        apex = as_vec3(self.apex, "cone.apex")
        axis = vec_normalize(as_vec3(self.axis, "cone.axis"))
        near = float(self.near)
        far = float(self.far)
        cosine = float(self.cos_half_angle)
        if not all(math.isfinite(value) for value in (near, far, cosine)):
            raise ValueError("cone parameters must be finite")
        if near < 0 or far <= near:
            raise ValueError("cone support requires 0 <= near < far")
        if not -1 <= cosine <= 1:
            raise ValueError("cos_half_angle must be in [-1,1]")
        object.__setattr__(self, "apex", apex)
        object.__setattr__(self, "axis", axis)
        object.__setattr__(self, "near", near)
        object.__setattr__(self, "far", far)
        object.__setattr__(self, "cos_half_angle", cosine)

    def contains(self, point: Vec3, error_bound: float = 0.0) -> bool:
        delta = vec_sub(as_vec3(point), self.apex)
        radius = vec_norm(delta)
        error = max(0.0, float(error_bound))
        if radius < self.near - error or radius > self.far + error:
            return False
        if radius <= 1e-12:
            return self.near <= error
        cosine = vec_dot(delta, self.axis) / radius
        angular_slack = min(1.0, error / max(radius, 1e-12))
        return cosine + angular_slack >= self.cos_half_angle

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "cone_frustum",
            "apex": list(self.apex),
            "axis": list(self.axis),
            "near": self.near,
            "far": self.far,
            "cos_half_angle": self.cos_half_angle,
        }


def support_from_dict(value: Mapping[str, Any]) -> SupportVolume:
    kind = value.get("type")
    if kind == "sphere":
        return SphereSupport(str(value["id"]), tuple(value["center"]), float(value["radius"]))
    if kind == "aabb":
        return AABBSupport(str(value["id"]), tuple(value["minimum"]), tuple(value["maximum"]))
    if kind == "cone_frustum":
        return ConeFrustumSupport(
            str(value["id"]), tuple(value["apex"]), tuple(value["axis"]),
            float(value["near"]), float(value["far"]), float(value["cos_half_angle"]),
        )
    raise ValueError(f"unknown support type: {kind}")


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    compatible: bool
    reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"compatible": self.compatible, "reasons": list(self.reasons)}


@dataclass(frozen=True, slots=True)
class CompatibilityPolicy:
    id: str
    required_tags: tuple[str, ...] = ()
    forbidden_tags: tuple[str, ...] = ()
    allowed_kinds: tuple[str, ...] = ()
    allowed_dynamic_states: tuple[str, ...] = ("static", "movable", "unknown")
    floor_id: str | None = None
    semantic_equals: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("compatibility policy id is required")
        object.__setattr__(self, "required_tags", tuple(sorted(set(map(str, self.required_tags)))))
        object.__setattr__(self, "forbidden_tags", tuple(sorted(set(map(str, self.forbidden_tags)))))
        object.__setattr__(self, "allowed_kinds", tuple(sorted(set(map(str, self.allowed_kinds)))))
        object.__setattr__(self, "allowed_dynamic_states", tuple(sorted(set(map(str, self.allowed_dynamic_states)))))
        object.__setattr__(self, "semantic_equals", tuple(sorted(self.semantic_equals, key=lambda item: str(item[0]))))
        overlap = set(self.required_tags) & set(self.forbidden_tags)
        if overlap:
            raise ValueError(f"tags cannot be both required and forbidden: {sorted(overlap)}")

    def evaluate(self, observation: Observation) -> CompatibilityResult:
        reasons: list[str] = []
        tags = set(observation.compatibility_tags)
        missing = sorted(set(self.required_tags) - tags)
        if missing:
            reasons.append("missing_tags:" + ",".join(missing))
        forbidden = sorted(set(self.forbidden_tags) & tags)
        if forbidden:
            reasons.append("forbidden_tags:" + ",".join(forbidden))
        if self.allowed_kinds and observation.kind not in self.allowed_kinds:
            reasons.append(f"kind_not_allowed:{observation.kind}")
        if self.allowed_dynamic_states and observation.dynamic_state not in self.allowed_dynamic_states:
            reasons.append(f"dynamic_state_not_allowed:{observation.dynamic_state}")
        if self.floor_id is not None and observation.floor_id != self.floor_id:
            reasons.append(f"floor_mismatch:{observation.floor_id}")
        for key, expected in self.semantic_equals:
            if observation.semantic.get(key) != expected:
                reasons.append(f"semantic_mismatch:{key}")
        return CompatibilityResult(not reasons, tuple(reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "required_tags": list(self.required_tags),
            "forbidden_tags": list(self.forbidden_tags),
            "allowed_kinds": list(self.allowed_kinds),
            "allowed_dynamic_states": list(self.allowed_dynamic_states),
            "floor_id": self.floor_id,
            "semantic_equals": {str(key): value for key, value in self.semantic_equals},
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CompatibilityPolicy":
        semantic = value.get("semantic_equals", {})
        semantic_items = tuple(semantic.items()) if isinstance(semantic, Mapping) else tuple(tuple(item) for item in semantic)
        return cls(
            id=str(value["id"]),
            required_tags=tuple(value.get("required_tags", ())),
            forbidden_tags=tuple(value.get("forbidden_tags", ())),
            allowed_kinds=tuple(value.get("allowed_kinds", ())),
            allowed_dynamic_states=tuple(value.get("allowed_dynamic_states", ("static", "movable", "unknown"))),
            floor_id=value.get("floor_id"),
            semantic_equals=semantic_items,
        )


@dataclass
class SupportRegistry:
    supports: dict[str, SupportVolume] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.supports = dict(self.supports)
        for key, support in self.supports.items():
            if key != support.id:
                raise ValueError(f"support dictionary key mismatch: {key} != {support.id}")

    def add(self, support: SupportVolume, *, replace: bool = False) -> None:
        if support.id in self.supports and not replace:
            raise ValueError(f"duplicate support id: {support.id}")
        self.supports[support.id] = support

    def require(self, support_id: str) -> SupportVolume:
        try:
            return self.supports[support_id]
        except KeyError as exc:
            raise KeyError(f"unknown support id: {support_id}") from exc

    def contains(self, support_id: str, point: Vec3, error_bound: float = 0.0) -> bool:
        return self.require(support_id).contains(point, error_bound)

    def to_dict(self) -> list[dict[str, Any]]:
        return [self.supports[key].to_dict() for key in sorted(self.supports)]

    @classmethod
    def from_dict(cls, values: list[Mapping[str, Any]]) -> "SupportRegistry":
        supports = [support_from_dict(value) for value in values]
        if len({support.id for support in supports}) != len(supports):
            raise ValueError("duplicate support IDs")
        return cls({support.id: support for support in supports})
