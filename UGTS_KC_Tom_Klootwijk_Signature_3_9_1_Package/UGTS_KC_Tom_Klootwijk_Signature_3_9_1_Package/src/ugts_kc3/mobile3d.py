"""UGTS-KC 3.9.1 mobile-3D records, device profiles and deterministic game oracle.

The JSON model is authoritative for authoring and validation.  Native Android rendering is a
separate downstream adapter implemented by :mod:`ugts_kc3.androidexport`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

from .geometry import Mesh
from .materials import PBRMaterial
from .math3d import (
    EPS, add, compose_trs, cross, dot, norm, normalize, quat_from_axis_angle,
    quat_mul, quat_normalize, scale as vscale, sub,
)
from .scene import Asset, Scene, SceneMetadata, SceneNode

Vec3 = tuple[float, float, float]
Quat = tuple[float, float, float, float]
Color3 = tuple[float, float, float]
Color4 = tuple[float, float, float, float]
MOBILE3D_SCHEMA = "ugts-kc-mobile-3d-project-3.9.1"

TAG_PLAYER = 1 << 0
TAG_COLLECTIBLE = 1 << 1
TAG_GOAL = 1 << 2
TAG_DECORATIVE = 1 << 3
TAG_HAZARD = 1 << 4
TAG_MAP = {
    "player": TAG_PLAYER,
    "collectible": TAG_COLLECTIBLE,
    "goal": TAG_GOAL,
    "decorative": TAG_DECORATIVE,
    "hazard": TAG_HAZARD,
}


def _normalized_json(value: Any) -> Any:
    """Normalize numerically equivalent JSON values before hashing."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite value in canonical JSON")
        return int(value) if value.is_integer() else value
    if isinstance(value, int):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalized_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_normalized_json(item) for item in value]
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(
        _normalized_json(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("utf-8")


def _values(value: Sequence[float], count: int, label: str) -> tuple[float, ...]:
    if len(value) != count:
        raise ValueError(f"{label} requires {count} values")
    result = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in result):
        raise ValueError(f"{label} must be finite")
    return result


def _positive(value: float, label: str, allow_zero: bool = False) -> float:
    result = float(value)
    if not math.isfinite(result) or result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{label} must be {'nonnegative' if allow_zero else 'positive'}")
    return result


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else hi if value > hi else value


def tag_mask(tags: Sequence[str]) -> int:
    result = 0
    for tag in tags:
        result |= TAG_MAP.get(tag, 0)
    return result


@dataclass(frozen=True)
class Transform3DRecord:
    translation: Vec3 = (0.0, 0.0, 0.0)
    rotation: Quat = (1.0, 0.0, 0.0, 0.0)
    scale: Vec3 = (1.0, 1.0, 1.0)

    def validate(self) -> None:
        _values(self.translation, 3, "translation")
        quat_normalize(_values(self.rotation, 4, "rotation"))
        scale = _values(self.scale, 3, "scale")
        if any(abs(v) <= EPS for v in scale):
            raise ValueError("scale components must be nonzero")

    def matrix(self):
        self.validate()
        return compose_trs(self.translation, self.rotation, self.scale)

    def to_dict(self) -> dict[str, Any]:
        return {
            "translation": list(self.translation),
            "rotation": list(self.rotation),
            "scale": list(self.scale),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Transform3DRecord":
        data = data or {}
        return cls(
            _values(data.get("translation", (0, 0, 0)), 3, "translation"),
            _values(data.get("rotation", (1, 0, 0, 0)), 4, "rotation"),
            _values(data.get("scale", (1, 1, 1)), 3, "scale"),
        )


@dataclass(frozen=True)
class Material3DRecord:
    id: str
    base_color: Color4 = (0.8, 0.8, 0.8, 1.0)
    metallic: float = 0.0
    roughness: float = 0.5
    emissive: Color3 = (0.0, 0.0, 0.0)
    double_sided: bool = False

    def validate(self) -> None:
        if not self.id:
            raise ValueError("material id required")
        base = _values(self.base_color, 4, "base_color")
        emissive = _values(self.emissive, 3, "emissive")
        if any(v < 0 or v > 1 for v in base) or any(v < 0 for v in emissive):
            raise ValueError("material colors outside supported range")
        if not 0 <= self.metallic <= 1 or not 0 <= self.roughness <= 1:
            raise ValueError("metallic and roughness must be in [0,1]")

    def to_pbr(self) -> PBRMaterial:
        self.validate()
        return PBRMaterial(
            self.id, self.base_color, self.metallic, self.roughness,
            self.emissive, double_sided=self.double_sided,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "base_color": list(self.base_color),
            "metallic": self.metallic,
            "roughness": self.roughness,
            "emissive": list(self.emissive),
            "double_sided": self.double_sided,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Material3DRecord":
        return cls(
            str(data["id"]),
            _values(data.get("base_color", (0.8, 0.8, 0.8, 1)), 4, "base_color"),
            float(data.get("metallic", 0)),
            float(data.get("roughness", 0.5)),
            _values(data.get("emissive", (0, 0, 0)), 3, "emissive"),
            bool(data.get("double_sided", False)),
        )


def _computed_normals(
    vertices: Sequence[Vec3], triangles: Sequence[tuple[int, int, int]]
) -> tuple[Vec3, ...]:
    sums = [[0.0, 0.0, 0.0] for _ in vertices]
    for ia, ib, ic in triangles:
        face = cross(sub(vertices[ib], vertices[ia]), sub(vertices[ic], vertices[ia]))
        if norm(face) <= EPS:
            continue
        for index in (ia, ib, ic):
            for axis in range(3):
                sums[index][axis] += face[axis]
    return tuple((0.0, 1.0, 0.0) if norm(v) <= EPS else normalize(v) for v in sums)


@dataclass(frozen=True)
class Mesh3DRecord:
    id: str
    vertices: tuple[Vec3, ...]
    triangles: tuple[tuple[int, int, int], ...]
    normals: tuple[Vec3, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("mesh id required")
        self.to_mesh().validate()

    def resolved_normals(self) -> tuple[Vec3, ...]:
        return self.normals or _computed_normals(self.vertices, self.triangles)

    def to_mesh(self) -> Mesh:
        return Mesh(self.vertices, self.triangles, self.normals, metadata=dict(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vertices": [list(v) for v in self.vertices],
            "triangles": [list(t) for t in self.triangles],
            "normals": [list(n) for n in self.normals],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Mesh3DRecord":
        return cls(
            str(data["id"]),
            tuple(_values(v, 3, "vertex") for v in data["vertices"]),
            tuple(tuple(int(i) for i in tri) for tri in data["triangles"]),
            tuple(_values(n, 3, "normal") for n in data.get("normals", [])),
            dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class Collider3DRecord:
    shape: str = "none"
    radius: float = 0.5
    half_extents: Vec3 = (0.5, 0.5, 0.5)
    sensor: bool = False

    def validate(self) -> None:
        if self.shape not in {"none", "sphere", "box"}:
            raise ValueError("collider shape must be none, sphere or box")
        if self.shape == "sphere":
            _positive(self.radius, "collider radius")
        if self.shape == "box" and any(
            v <= 0 for v in _values(self.half_extents, 3, "half_extents")
        ):
            raise ValueError("box half_extents must be positive")

    def bounding_radius(self, scale: Vec3 = (1, 1, 1)) -> float:
        if self.shape == "none":
            return 0.0
        if self.shape == "sphere":
            return self.radius * max(abs(v) for v in scale)
        return math.sqrt(
            sum((self.half_extents[i] * abs(scale[i])) ** 2 for i in range(3))
        )

    def vertical_extent(self, scale: Vec3 = (1, 1, 1)) -> float:
        if self.shape == "none":
            return 0.0
        if self.shape == "sphere":
            return self.radius * abs(scale[1])
        return self.half_extents[1] * abs(scale[1])

    def to_dict(self) -> dict[str, Any]:
        return {
            "shape": self.shape,
            "radius": self.radius,
            "half_extents": list(self.half_extents),
            "sensor": self.sensor,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Collider3DRecord":
        data = data or {"shape": "none"}
        return cls(
            str(data.get("shape", "none")),
            float(data.get("radius", 0.5)),
            _values(data.get("half_extents", (0.5, 0.5, 0.5)), 3, "half_extents"),
            bool(data.get("sensor", False)),
        )


@dataclass(frozen=True)
class Node3DRecord:
    id: str
    mesh_id: str
    material_id: str
    transform: Transform3DRecord = Transform3DRecord()
    velocity: Vec3 = (0.0, 0.0, 0.0)
    angular_velocity: Vec3 = (0.0, 0.0, 0.0)
    collider: Collider3DRecord = Collider3DRecord()
    dynamic: bool = False
    mass: float = 1.0
    restitution: float = 0.35
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate(self) -> None:
        if not self.id or not self.mesh_id or not self.material_id:
            raise ValueError("node id, mesh_id and material_id required")
        self.transform.validate()
        _values(self.velocity, 3, "velocity")
        _values(self.angular_velocity, 3, "angular_velocity")
        self.collider.validate()
        _positive(self.mass, "mass")
        if not 0 <= self.restitution <= 1:
            raise ValueError("restitution must be in [0,1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "mesh_id": self.mesh_id,
            "material_id": self.material_id,
            "transform": self.transform.to_dict(),
            "velocity": list(self.velocity),
            "angular_velocity": list(self.angular_velocity),
            "collider": self.collider.to_dict(),
            "dynamic": self.dynamic,
            "mass": self.mass,
            "restitution": self.restitution,
            "tags": list(self.tags),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Node3DRecord":
        return cls(
            str(data["id"]), str(data["mesh_id"]), str(data["material_id"]),
            Transform3DRecord.from_dict(data.get("transform")),
            _values(data.get("velocity", (0, 0, 0)), 3, "velocity"),
            _values(data.get("angular_velocity", (0, 0, 0)), 3, "angular_velocity"),
            Collider3DRecord.from_dict(data.get("collider")),
            bool(data.get("dynamic", False)), float(data.get("mass", 1)),
            float(data.get("restitution", 0.35)),
            tuple(str(tag) for tag in data.get("tags", [])),
            dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class Camera3DRecord:
    position: Vec3 = (8.0, 5.0, 10.0)
    target: Vec3 = (0.0, 1.0, 0.0)
    up: Vec3 = (0.0, 1.0, 0.0)
    vertical_fov_degrees: float = 55.0
    near: float = 0.05
    far: float = 250.0

    def validate(self) -> None:
        position = _values(self.position, 3, "camera position")
        target = _values(self.target, 3, "camera target")
        up = _values(self.up, 3, "camera up")
        if norm(sub(target, position)) <= EPS or norm(up) <= EPS:
            raise ValueError("camera vectors are degenerate")
        if not 10 <= self.vertical_fov_degrees <= 140:
            raise ValueError("camera FOV outside supported range")
        if self.near <= 0 or self.far <= self.near:
            raise ValueError("camera clip range invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": list(self.position), "target": list(self.target),
            "up": list(self.up), "vertical_fov_degrees": self.vertical_fov_degrees,
            "near": self.near, "far": self.far,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "Camera3DRecord":
        data = data or {}
        return cls(
            _values(data.get("position", (8, 5, 10)), 3, "camera position"),
            _values(data.get("target", (0, 1, 0)), 3, "camera target"),
            _values(data.get("up", (0, 1, 0)), 3, "camera up"),
            float(data.get("vertical_fov_degrees", 55)),
            float(data.get("near", 0.05)), float(data.get("far", 250)),
        )


@dataclass(frozen=True)
class DirectionalLight3DRecord:
    direction: Vec3 = (-0.4, -1.0, -0.25)
    color: Color3 = (1.0, 0.96, 0.9)
    intensity: float = 1.25
    ambient: float = 0.18

    def validate(self) -> None:
        if norm(_values(self.direction, 3, "light direction")) <= EPS:
            raise ValueError("light direction is degenerate")
        if any(v < 0 for v in _values(self.color, 3, "light color")):
            raise ValueError("light color invalid")
        _positive(self.intensity, "light intensity", True)
        if not 0 <= self.ambient <= 1:
            raise ValueError("ambient must be in [0,1]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": list(self.direction), "color": list(self.color),
            "intensity": self.intensity, "ambient": self.ambient,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "DirectionalLight3DRecord":
        data = data or {}
        return cls(
            _values(data.get("direction", (-0.4, -1, -0.25)), 3, "light direction"),
            _values(data.get("color", (1, 0.96, 0.9)), 3, "light color"),
            float(data.get("intensity", 1.25)), float(data.get("ambient", 0.18)),
        )


@dataclass(frozen=True)
class QualityTier3D:
    id: str
    target_fps: int
    render_scale: float
    max_visible_nodes: int
    msaa_samples: int = 0
    post_processing: bool = True
    shadow_quality: int = 0

    def validate(self) -> None:
        if not self.id:
            raise ValueError("quality id required")
        if self.target_fps not in {30, 40, 45, 60, 72, 90, 120, 144}:
            raise ValueError("unsupported target_fps")
        if not 0.45 <= self.render_scale <= 1:
            raise ValueError("render_scale must be in [0.45,1]")
        if self.max_visible_nodes < 1:
            raise ValueError("max_visible_nodes must be positive")
        if self.msaa_samples not in {0, 2, 4, 8} or not 0 <= self.shadow_quality <= 3:
            raise ValueError("quality fields invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "target_fps": self.target_fps,
            "render_scale": self.render_scale,
            "max_visible_nodes": self.max_visible_nodes,
            "msaa_samples": self.msaa_samples,
            "post_processing": self.post_processing,
            "shadow_quality": self.shadow_quality,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "QualityTier3D":
        return cls(
            str(data["id"]), int(data["target_fps"]), float(data["render_scale"]),
            int(data["max_visible_nodes"]), int(data.get("msaa_samples", 0)),
            bool(data.get("post_processing", True)),
            int(data.get("shadow_quality", 0)),
        )


@dataclass(frozen=True)
class AndroidTargetProfile:
    id: str
    label: str
    min_sdk: int = 26
    target_sdk: int = 36
    compile_sdk: int = 36
    preferred_abis: tuple[str, ...] = ("arm64-v8a",)
    required_gles: tuple[int, int] = (3, 0)
    vulkan_optional: bool = True
    target_refresh_hz: int = 60
    memory_floor_mb: int = 3072
    device_hints: tuple[str, ...] = ()
    gpu_hints: tuple[str, ...] = ()
    default_quality: str = "balanced"

    def validate(self) -> None:
        if not self.id or not self.label:
            raise ValueError("target id and label required")
        if not 21 <= self.min_sdk <= self.target_sdk <= self.compile_sdk:
            raise ValueError("Android SDK levels invalid")
        if not self.preferred_abis or not set(self.preferred_abis) <= {
            "arm64-v8a", "armeabi-v7a", "x86_64"
        }:
            raise ValueError("unsupported Android ABI")
        if self.required_gles < (3, 0):
            raise ValueError("OpenGL ES 3.0 is required")
        if self.target_refresh_hz not in {30, 45, 60, 72, 90, 120, 144}:
            raise ValueError("unsupported refresh target")
        if self.memory_floor_mb < 1024:
            raise ValueError("memory floor too low")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "label": self.label, "min_sdk": self.min_sdk,
            "target_sdk": self.target_sdk, "compile_sdk": self.compile_sdk,
            "preferred_abis": list(self.preferred_abis),
            "required_gles": list(self.required_gles),
            "vulkan_optional": self.vulkan_optional,
            "target_refresh_hz": self.target_refresh_hz,
            "memory_floor_mb": self.memory_floor_mb,
            "device_hints": list(self.device_hints),
            "gpu_hints": list(self.gpu_hints),
            "default_quality": self.default_quality,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AndroidTargetProfile":
        gles = tuple(int(v) for v in data.get("required_gles", (3, 0)))
        if len(gles) != 2:
            raise ValueError("required_gles requires major/minor")
        return cls(
            str(data["id"]), str(data.get("label", data["id"])),
            int(data.get("min_sdk", 26)), int(data.get("target_sdk", 36)),
            int(data.get("compile_sdk", 36)),
            tuple(str(v) for v in data.get("preferred_abis", ["arm64-v8a"])),
            (gles[0], gles[1]), bool(data.get("vulkan_optional", True)),
            int(data.get("target_refresh_hz", 60)),
            int(data.get("memory_floor_mb", 3072)),
            tuple(str(v) for v in data.get("device_hints", [])),
            tuple(str(v) for v in data.get("gpu_hints", [])),
            str(data.get("default_quality", "balanced")),
        )


@dataclass(frozen=True)
class DeviceCapabilities3D:
    model: str = "unknown"
    manufacturer: str = "unknown"
    gpu_renderer: str = "unknown"
    ram_mb: int = 4096
    cpu_cores: int = 4
    gles_major: int = 3
    gles_minor: int = 0
    display_refresh_hz: float = 60.0

    def validate(self) -> None:
        if self.ram_mb < 512 or self.cpu_cores < 1:
            raise ValueError("RAM/core count invalid")
        if self.gles_major < 2 or self.display_refresh_hz <= 0:
            raise ValueError("graphics/display capabilities invalid")


@dataclass(frozen=True)
class SelectedDeviceProfile3D:
    profile_id: str
    quality_id: str
    target_fps: int
    render_scale: float
    reason: str


def select_device_profile(
    capabilities: DeviceCapabilities3D,
    profiles: Sequence[AndroidTargetProfile],
    quality_tiers: Sequence[QualityTier3D],
    requested: str = "auto",
) -> SelectedDeviceProfile3D:
    capabilities.validate()
    profile_by_id = {profile.id: profile for profile in profiles}
    quality_by_id = {quality.id: quality for quality in quality_tiers}
    if not profile_by_id or not quality_by_id:
        raise ValueError("profiles and quality tiers required")
    if requested != "auto":
        if requested not in profile_by_id:
            raise KeyError(requested)
        selected = profile_by_id[requested]
        reason = "explicit profile request"
    else:
        model = f"{capabilities.manufacturer} {capabilities.model}".lower()
        gpu = capabilities.gpu_renderer.lower()
        scored: list[tuple[int, int, str, AndroidTargetProfile, str]] = []
        for profile in profiles:
            score = 0
            reasons: list[str] = []
            poco_match = (
                "poco x7 pro" in model
                or any(hint.lower() in model for hint in profile.device_hints)
                or any(hint.lower() in gpu for hint in profile.gpu_hints)
            )
            if profile.id == "poco_x7_pro_12gb":
                score += 100 if poco_match else -25
                if poco_match:
                    reasons.append("POCO/Mali-G720 signature match")
            if capabilities.ram_mb >= profile.memory_floor_mb:
                score += 15
                reasons.append("RAM floor met")
            else:
                score -= 80
            if (capabilities.gles_major, capabilities.gles_minor) >= profile.required_gles:
                score += 15
            else:
                score -= 120
            if capabilities.display_refresh_hz + 1 >= profile.target_refresh_hz:
                score += 5
            scored.append(
                (score, profile.memory_floor_mb, profile.id, profile,
                 ", ".join(reasons) or "generic capability match")
            )
        _, _, _, selected, reason = max(scored)
    quality = quality_by_id.get(selected.default_quality)
    if quality is None:
        raise KeyError(selected.default_quality)
    target_fps = min(
        quality.target_fps,
        selected.target_refresh_hz,
        max(30, int(round(capabilities.display_refresh_hz))),
    )
    return SelectedDeviceProfile3D(
        selected.id, quality.id, target_fps, quality.render_scale, reason
    )


@dataclass
class AdaptiveQualityController3D:
    quality_ids: tuple[str, ...]
    current_index: int = 0
    low_fps_seconds: float = 0.0
    recovery_seconds: float = 0.0

    @property
    def current(self) -> str:
        if not self.quality_ids:
            raise ValueError("quality_ids required")
        return self.quality_ids[self.current_index]

    def update(
        self, frame_fps: float, target_fps: float, thermal_status: int, dt: float
    ) -> str:
        if not self.quality_ids or dt < 0:
            raise ValueError("quality ids and nonnegative dt required")
        stressed = thermal_status >= 3 or frame_fps < target_fps * 0.82
        comfortable = thermal_status <= 1 and frame_fps >= target_fps * 0.96
        self.low_fps_seconds = (
            self.low_fps_seconds + dt
            if stressed else max(0.0, self.low_fps_seconds - dt * 0.5)
        )
        self.recovery_seconds = self.recovery_seconds + dt if comfortable else 0.0
        if self.low_fps_seconds >= 1.5 and self.current_index < len(self.quality_ids) - 1:
            self.current_index += 1
            self.low_fps_seconds = self.recovery_seconds = 0.0
        elif self.recovery_seconds >= 8.0 and self.current_index > 0:
            self.current_index -= 1
            self.recovery_seconds = 0.0
        return self.current


@dataclass(frozen=True)
class World3DSettings:
    fixed_dt: float = 1 / 120
    gravity: Vec3 = (0.0, -9.81, 0.0)
    floor_y: float = 0.0
    bounds_min: Vec3 = (-24.0, -8.0, -24.0)
    bounds_max: Vec3 = (24.0, 28.0, 24.0)
    player_speed: float = 6.0
    jump_speed: float = 7.5

    def validate(self) -> None:
        if not 1 / 1000 <= self.fixed_dt <= 1 / 15:
            raise ValueError("fixed_dt outside supported range")
        _values(self.gravity, 3, "gravity")
        lo = _values(self.bounds_min, 3, "bounds_min")
        hi = _values(self.bounds_max, 3, "bounds_max")
        if any(lo[i] >= hi[i] for i in range(3)):
            raise ValueError("world bounds invalid")
        _positive(self.player_speed, "player_speed", True)
        _positive(self.jump_speed, "jump_speed", True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixed_dt": self.fixed_dt, "gravity": list(self.gravity),
            "floor_y": self.floor_y, "bounds_min": list(self.bounds_min),
            "bounds_max": list(self.bounds_max),
            "player_speed": self.player_speed, "jump_speed": self.jump_speed,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "World3DSettings":
        data = data or {}
        return cls(
            float(data.get("fixed_dt", 1 / 120)),
            _values(data.get("gravity", (0, -9.81, 0)), 3, "gravity"),
            float(data.get("floor_y", 0)),
            _values(data.get("bounds_min", (-24, -8, -24)), 3, "bounds_min"),
            _values(data.get("bounds_max", (24, 28, 24)), 3, "bounds_max"),
            float(data.get("player_speed", 6)),
            float(data.get("jump_speed", 7.5)),
        )


@dataclass(frozen=True)
class ProjectIssue3D:
    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity, "code": self.code,
            "path": self.path, "message": self.message,
        }


@dataclass(frozen=True)
class ProjectValidation3D:
    passed: bool
    issues: tuple[ProjectIssue3D, ...]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "ugts-kc-mobile-3d-validation-3.9.1",
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
            "metrics": self.metrics,
        }


@dataclass
class Mobile3DProject:
    id: str
    title: str
    author: str
    meshes: dict[str, Mesh3DRecord]
    materials: dict[str, Material3DRecord]
    nodes: tuple[Node3DRecord, ...]
    camera: Camera3DRecord = Camera3DRecord()
    light: DirectionalLight3DRecord = DirectionalLight3DRecord()
    quality_tiers: tuple[QualityTier3D, ...] = ()
    target_profiles: tuple[AndroidTargetProfile, ...] = ()
    world: World3DSettings = World3DSettings()
    start_quality: str = "balanced"
    background: Color4 = (0.018, 0.03, 0.055, 1.0)
    schema: str = MOBILE3D_SCHEMA
    edition: str = "3.9.1 - Tom Klootwijk Signature Edition"
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self, raise_on_error: bool = True) -> ProjectValidation3D:
        issues: list[ProjectIssue3D] = []

        def error(code: str, path: str, message: str) -> None:
            issues.append(ProjectIssue3D("error", code, path, message))

        if self.schema != MOBILE3D_SCHEMA:
            error("schema.unsupported", "schema", f"expected {MOBILE3D_SCHEMA}")
        if not self.id or not self.title:
            error("project.identity", "id/title", "project id and title required")
        for label, value in (
            ("camera", self.camera), ("light", self.light), ("world", self.world)
        ):
            try:
                value.validate()
            except ValueError as exc:
                error(f"{label}.invalid", label, str(exc))
        try:
            bg = _values(self.background, 4, "background")
            if any(v < 0 or v > 1 for v in bg):
                raise ValueError("background must be in [0,1]")
        except ValueError as exc:
            error("background.invalid", "background", str(exc))
        for key, mesh in self.meshes.items():
            if key != mesh.id:
                error("mesh.key", f"meshes.{key}", "key differs from id")
            try:
                mesh.validate()
            except ValueError as exc:
                error("mesh.invalid", f"meshes.{key}", str(exc))
        for key, material in self.materials.items():
            if key != material.id:
                error("material.key", f"materials.{key}", "key differs from id")
            try:
                material.validate()
            except ValueError as exc:
                error("material.invalid", f"materials.{key}", str(exc))
        node_ids: set[str] = set()
        for index, node in enumerate(self.nodes):
            path = f"nodes[{index}]"
            if node.id in node_ids:
                error("node.duplicate", path, node.id)
            node_ids.add(node.id)
            try:
                node.validate()
            except ValueError as exc:
                error("node.invalid", path, str(exc))
            if node.mesh_id not in self.meshes:
                error("mesh.unknown", f"{path}.mesh_id", node.mesh_id)
            if node.material_id not in self.materials:
                error("material.unknown", f"{path}.material_id", node.material_id)
        quality_ids: set[str] = set()
        for index, tier in enumerate(self.quality_tiers):
            try:
                tier.validate()
            except ValueError as exc:
                error("quality.invalid", f"quality_tiers[{index}]", str(exc))
            if tier.id in quality_ids:
                error("quality.duplicate", f"quality_tiers[{index}]", tier.id)
            quality_ids.add(tier.id)
        if self.start_quality not in quality_ids:
            error("quality.start", "start_quality", self.start_quality)
        target_ids: set[str] = set()
        for index, target in enumerate(self.target_profiles):
            try:
                target.validate()
            except ValueError as exc:
                error("target.invalid", f"target_profiles[{index}]", str(exc))
            if target.id in target_ids:
                error("target.duplicate", f"target_profiles[{index}]", target.id)
            target_ids.add(target.id)
            if target.default_quality not in quality_ids:
                error(
                    "target.quality",
                    f"target_profiles[{index}].default_quality",
                    target.default_quality,
                )
        if not self.target_profiles:
            error("target.missing", "target_profiles", "at least one target required")
        metrics = {
            "mesh_count": len(self.meshes),
            "material_count": len(self.materials),
            "node_count": len(self.nodes),
            "dynamic_node_count": sum(node.dynamic for node in self.nodes),
            "vertex_count": sum(len(mesh.vertices) for mesh in self.meshes.values()),
            "triangle_count": sum(len(mesh.triangles) for mesh in self.meshes.values()),
            "quality_tier_count": len(self.quality_tiers),
            "target_profile_count": len(self.target_profiles),
        }
        report = ProjectValidation3D(not issues, tuple(issues), metrics)
        if raise_on_error and not report.passed:
            raise ValueError(
                "; ".join(f"{i.code}@{i.path}: {i.message}" for i in issues)
            )
        return report

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "id": self.id, "title": self.title,
            "author": self.author, "edition": self.edition,
            "background": list(self.background), "camera": self.camera.to_dict(),
            "light": self.light.to_dict(), "world": self.world.to_dict(),
            "start_quality": self.start_quality,
            "quality_tiers": [tier.to_dict() for tier in self.quality_tiers],
            "target_profiles": [profile.to_dict() for profile in self.target_profiles],
            "materials": [
                self.materials[key].to_dict() for key in sorted(self.materials)
            ],
            "meshes": [self.meshes[key].to_dict() for key in sorted(self.meshes)],
            "nodes": [node.to_dict() for node in self.nodes],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(
        cls, data: Mapping[str, Any], validate: bool = True
    ) -> "Mobile3DProject":
        project = cls(
            str(data["id"]), str(data["title"]), str(data.get("author", "")),
            {
                str(item["id"]): Mesh3DRecord.from_dict(item)
                for item in data.get("meshes", [])
            },
            {
                str(item["id"]): Material3DRecord.from_dict(item)
                for item in data.get("materials", [])
            },
            tuple(Node3DRecord.from_dict(item) for item in data.get("nodes", [])),
            Camera3DRecord.from_dict(data.get("camera")),
            DirectionalLight3DRecord.from_dict(data.get("light")),
            tuple(
                QualityTier3D.from_dict(item)
                for item in data.get("quality_tiers", [])
            ),
            tuple(
                AndroidTargetProfile.from_dict(item)
                for item in data.get("target_profiles", [])
            ),
            World3DSettings.from_dict(data.get("world")),
            str(data.get("start_quality", "balanced")),
            _values(data.get("background", (0.018, 0.03, 0.055, 1)), 4, "background"),
            str(data.get("schema", MOBILE3D_SCHEMA)),
            str(
                data.get(
                    "edition", "3.9.1 - Tom Klootwijk Signature Edition"
                )
            ),
            dict(data.get("metadata", {})),
        )
        if validate:
            project.validate()
        return project

    @classmethod
    def load(
        cls, path: str | Path, validate: bool = True
    ) -> "Mobile3DProject":
        return cls.from_dict(json.loads(Path(path).read_text("utf-8")), validate)

    def write(self, path: str | Path) -> Path:
        self.validate()
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n")
        return path

    def content_hash(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()

    def material_map(self) -> dict[str, PBRMaterial]:
        return {key: value.to_pbr() for key, value in self.materials.items()}

    def to_scene(self) -> Scene:
        """Convert to the retained scene model without losing per-node materials."""
        self.validate()
        scene = Scene(
            SceneMetadata(
                schema_version="3.9.1",
                determinism_profile="mobile-3d-reference",
            )
        )
        asset_ids: dict[tuple[str, str], str] = {}
        for node in self.nodes:
            key = (node.mesh_id, node.material_id)
            if key in asset_ids:
                continue
            record = self.meshes[node.mesh_id]
            asset_id = f"{node.mesh_id}__{node.material_id}"
            asset_ids[key] = asset_id
            scene.add_asset(
                Asset(
                    asset_id,
                    Mesh(
                        record.vertices, record.triangles, record.resolved_normals()
                    ),
                    node.material_id,
                    metadata={"source_mesh_id": node.mesh_id},
                )
            )
        for node in self.nodes:
            scene.add_node(
                SceneNode(
                    node.id,
                    asset_ids[(node.mesh_id, node.material_id)],
                    local_transform=node.transform.matrix(),
                    tags=frozenset(node.tags),
                    metadata={
                        **node.metadata,
                        "material_id": node.material_id,
                        "source_mesh_id": node.mesh_id,
                        "dynamic": node.dynamic,
                        "velocity": list(node.velocity),
                        "angular_velocity": list(node.angular_velocity),
                    },
                )
            )
        return scene

    def instantiate_world(self) -> "GameWorld3D":
        self.validate()
        return GameWorld3D.from_project(self)


@dataclass(frozen=True)
class InputFrame3D:
    move_x: float = 0.0
    move_z: float = 0.0
    look_x: float = 0.0
    look_y: float = 0.0
    jump: bool = False
    action: bool = False

    def normalized(self) -> "InputFrame3D":
        x, z = float(self.move_x), float(self.move_z)
        length = math.hypot(x, z)
        if length > 1:
            x, z = x / length, z / length
        return InputFrame3D(
            _clamp(x, -1, 1), _clamp(z, -1, 1),
            _clamp(float(self.look_x), -1, 1),
            _clamp(float(self.look_y), -1, 1),
            bool(self.jump), bool(self.action),
        )


@dataclass
class EntityState3D:
    id: str
    mesh_id: str
    material_id: str
    position: Vec3
    rotation: Quat
    scale: Vec3
    velocity: Vec3
    angular_velocity: Vec3
    collider: Collider3DRecord
    dynamic: bool
    mass: float
    restitution: float
    tags: tuple[str, ...]
    grounded: bool = False
    alive: bool = True

    @classmethod
    def from_node(cls, node: Node3DRecord) -> "EntityState3D":
        return cls(
            node.id, node.mesh_id, node.material_id,
            node.transform.translation, quat_normalize(node.transform.rotation),
            node.transform.scale, node.velocity, node.angular_velocity,
            node.collider, node.dynamic, node.mass, node.restitution, node.tags,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "mesh_id": self.mesh_id,
            "material_id": self.material_id,
            "position": list(self.position), "rotation": list(self.rotation),
            "scale": list(self.scale), "velocity": list(self.velocity),
            "angular_velocity": list(self.angular_velocity),
            "collider": self.collider.to_dict(), "dynamic": self.dynamic,
            "mass": self.mass, "restitution": self.restitution,
            "tags": list(self.tags), "grounded": self.grounded,
            "alive": self.alive,
        }


@dataclass(frozen=True)
class WorldEvent3D:
    tick: int
    kind: str
    entity_a: str
    entity_b: str | None = None
    data: dict[str, Any] = field(default_factory=dict, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tick": self.tick, "kind": self.kind,
            "entity_a": self.entity_a, "entity_b": self.entity_b,
            "data": self.data,
        }


class GameWorld3D:
    """Small deterministic sphere-approximation arcade physics/gameplay reference."""

    def __init__(self, settings: World3DSettings = World3DSettings()):
        settings.validate()
        self.settings = settings
        self.entities: dict[str, EntityState3D] = {}
        self.tick = 0
        self.time = 0.0
        self.events: list[WorldEvent3D] = []
        self.state: dict[str, Any] = {
            "score": 0, "finished": False, "health": 3
        }

    @classmethod
    def from_project(cls, project: Mobile3DProject) -> "GameWorld3D":
        world = cls(project.world)
        for node in project.nodes:
            world.spawn(EntityState3D.from_node(node))
        return world

    def spawn(self, entity: EntityState3D) -> None:
        if entity.id in self.entities:
            raise ValueError(f"duplicate entity {entity.id}")
        self.entities[entity.id] = entity

    def require(self, entity_id: str) -> EntityState3D:
        if entity_id not in self.entities:
            raise KeyError(entity_id)
        return self.entities[entity_id]

    def _emit(
        self, kind: str, a: str, b: str | None = None, **data: Any
    ) -> None:
        self.events.append(WorldEvent3D(self.tick, kind, a, b, data))

    def _player(self, frame: InputFrame3D) -> None:
        frame = frame.normalized()
        for key in sorted(self.entities):
            entity = self.entities[key]
            if entity.alive and "player" in entity.tags:
                entity.velocity = (
                    frame.move_x * self.settings.player_speed,
                    entity.velocity[1],
                    frame.move_z * self.settings.player_speed,
                )
                if frame.jump and entity.grounded:
                    entity.velocity = (
                        entity.velocity[0], self.settings.jump_speed,
                        entity.velocity[2],
                    )
                    entity.grounded = False
                    self._emit("jump", entity.id)

    def _integrate(self) -> None:
        dt = self.settings.fixed_dt
        for key in sorted(self.entities):
            entity = self.entities[key]
            if not entity.alive:
                continue
            if entity.dynamic:
                entity.velocity = add(
                    entity.velocity, vscale(self.settings.gravity, dt)
                )
                entity.position = add(
                    entity.position, vscale(entity.velocity, dt)
                )
            angular_speed = norm(entity.angular_velocity)
            if angular_speed > EPS:
                axis = vscale(entity.angular_velocity, 1 / angular_speed)
                entity.rotation = quat_normalize(
                    quat_mul(
                        quat_from_axis_angle(axis, angular_speed * dt),
                        entity.rotation,
                    )
                )

    def _floor_bounds(self) -> None:
        lo, hi = self.settings.bounds_min, self.settings.bounds_max
        for key in sorted(self.entities):
            entity = self.entities[key]
            if not entity.alive or not entity.dynamic:
                continue
            extent_y = entity.collider.vertical_extent(entity.scale)
            if entity.position[1] - extent_y < self.settings.floor_y:
                entity.position = (
                    entity.position[0], self.settings.floor_y + extent_y,
                    entity.position[2],
                )
                if entity.velocity[1] < 0:
                    bounce = -entity.velocity[1] * entity.restitution
                    entity.velocity = (
                        entity.velocity[0], 0.0 if bounce < 0.08 else bounce,
                        entity.velocity[2],
                    )
                    self._emit("floor_contact", entity.id)
                entity.grounded = abs(entity.velocity[1]) < 0.1
            else:
                entity.grounded = False
            p, v = list(entity.position), list(entity.velocity)
            radius = entity.collider.bounding_radius(entity.scale)
            for axis in (0, 2):
                minimum, maximum = lo[axis] + radius, hi[axis] - radius
                if p[axis] < minimum:
                    p[axis], v[axis] = minimum, abs(v[axis]) * entity.restitution
                    self._emit("bounds_contact", entity.id, axis=axis, side="min")
                elif p[axis] > maximum:
                    p[axis], v[axis] = maximum, -abs(v[axis]) * entity.restitution
                    self._emit("bounds_contact", entity.id, axis=axis, side="max")
            entity.position, entity.velocity = tuple(p), tuple(v)

    def _pairs(self) -> None:
        ids = [key for key in sorted(self.entities) if self.entities[key].alive]
        for index, a_id in enumerate(ids):
            a = self.entities[a_id]
            ra = a.collider.bounding_radius(a.scale)
            if ra <= 0 or a.collider.sensor:
                continue
            for b_id in ids[index + 1:]:
                b = self.entities[b_id]
                rb = b.collider.bounding_radius(b.scale)
                if rb <= 0 or b.collider.sensor or (not a.dynamic and not b.dynamic):
                    continue
                delta = sub(b.position, a.position)
                distance, target = norm(delta), ra + rb
                if distance >= target:
                    continue
                normal = (
                    (1.0, 0.0, 0.0)
                    if distance <= EPS else vscale(delta, 1 / distance)
                )
                penetration = target - distance
                inv_a = 1 / a.mass if a.dynamic else 0
                inv_b = 1 / b.mass if b.dynamic else 0
                total = inv_a + inv_b
                if total <= EPS:
                    continue
                if a.dynamic:
                    a.position = sub(
                        a.position, vscale(normal, penetration * inv_a / total)
                    )
                if b.dynamic:
                    b.position = add(
                        b.position, vscale(normal, penetration * inv_b / total)
                    )
                relative = dot(sub(b.velocity, a.velocity), normal)
                if relative < 0:
                    impulse = (
                        -(1 + min(a.restitution, b.restitution))
                        * relative / total
                    )
                    if a.dynamic:
                        a.velocity = sub(
                            a.velocity, vscale(normal, impulse * inv_a)
                        )
                    if b.dynamic:
                        b.velocity = add(
                            b.velocity, vscale(normal, impulse * inv_b)
                        )
                self._emit("collision", a_id, b_id, penetration=penetration)

    def _gameplay(self) -> None:
        players = [
            entity for entity in self.entities.values()
            if entity.alive and "player" in entity.tags
        ]
        for key in sorted(self.entities):
            entity = self.entities[key]
            if not entity.alive:
                continue
            radius = entity.collider.bounding_radius(entity.scale)
            for player in players:
                touching = norm(sub(player.position, entity.position)) <= (
                    player.collider.bounding_radius(player.scale) + radius
                )
                if not touching:
                    continue
                if "collectible" in entity.tags:
                    entity.alive = False
                    self.state["score"] = int(self.state["score"]) + 1
                    self._emit(
                        "collected", player.id, entity.id,
                        score=self.state["score"],
                    )
                elif "goal" in entity.tags:
                    self.state["finished"] = True
                    self._emit("goal", player.id, entity.id)
                elif "hazard" in entity.tags:
                    self.state["health"] = max(
                        0, int(self.state["health"]) - 1
                    )
                    self._emit(
                        "damage", player.id, entity.id,
                        health=self.state["health"],
                    )

    def step(
        self, frame: InputFrame3D | None = None, steps: int = 1
    ) -> tuple[WorldEvent3D, ...]:
        if steps < 1:
            raise ValueError("steps must be positive")
        start = len(self.events)
        frame = frame or InputFrame3D()
        for _ in range(steps):
            self.tick += 1
            self._player(frame)
            self._integrate()
            self._floor_bounds()
            self._pairs()
            self._gameplay()
            self.time = self.tick * self.settings.fixed_dt
        return tuple(self.events[start:])

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": "ugts-kc-game-world-3d-snapshot-3.9.1",
            "tick": self.tick, "time": self.time,
            "settings": self.settings.to_dict(), "state": self.state,
            "entities": [
                self.entities[key].to_dict() for key in sorted(self.entities)
            ],
            "events": [event.to_dict() for event in self.events],
        }

    def state_hash(self) -> str:
        return hashlib.sha256(_canonical(self.snapshot())).hexdigest()

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.snapshot(), indent=2, sort_keys=True) + "\n")
        return path


def cube_mesh3d(mesh_id: str = "cube", size: float = 1.0) -> Mesh3DRecord:
    h = _positive(size, "cube size") * 0.5
    faces = (
        ((0, 0, 1), ((-h, -h, h), (h, -h, h), (h, h, h), (-h, h, h))),
        ((0, 0, -1), ((h, -h, -h), (-h, -h, -h), (-h, h, -h), (h, h, -h))),
        ((1, 0, 0), ((h, -h, h), (h, -h, -h), (h, h, -h), (h, h, h))),
        ((-1, 0, 0), ((-h, -h, -h), (-h, -h, h), (-h, h, h), (-h, h, -h))),
        ((0, 1, 0), ((-h, h, h), (h, h, h), (h, h, -h), (-h, h, -h))),
        ((0, -1, 0), ((-h, -h, -h), (h, -h, -h), (h, -h, h), (-h, -h, h))),
    )
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    triangles: list[tuple[int, int, int]] = []
    for normal, points in faces:
        base = len(vertices)
        vertices.extend(points)
        normals.extend((normal,) * 4)
        triangles.extend(
            ((base, base + 1, base + 2), (base, base + 2, base + 3))
        )
    return Mesh3DRecord(
        mesh_id, tuple(vertices), tuple(triangles), tuple(normals),
        {"primitive": "cube", "size": h * 2},
    )


def plane_mesh3d(
    mesh_id: str = "plane", width: float = 1, depth: float = 1
) -> Mesh3DRecord:
    x = _positive(width, "plane width") * 0.5
    z = _positive(depth, "plane depth") * 0.5
    return Mesh3DRecord(
        mesh_id,
        ((-x, 0, -z), (x, 0, -z), (x, 0, z), (-x, 0, z)),
        ((0, 1, 2), (0, 2, 3)),
        ((0, 1, 0),) * 4,
        {"primitive": "plane"},
    )


def pyramid_mesh3d(
    mesh_id: str = "pyramid", size: float = 1, height: float = 1.4
) -> Mesh3DRecord:
    h = _positive(size, "pyramid size") * 0.5
    y = _positive(height, "pyramid height")
    vertices = (
        (-h, 0, -h), (h, 0, -h), (h, 0, h), (-h, 0, h), (0, y, 0)
    )
    triangles = (
        (0, 2, 1), (0, 3, 2), (0, 1, 4),
        (1, 2, 4), (2, 3, 4), (3, 0, 4),
    )
    return Mesh3DRecord(
        mesh_id, vertices, triangles, _computed_normals(vertices, triangles),
        {"primitive": "pyramid"},
    )


def uv_sphere_mesh3d(
    mesh_id: str = "sphere", radius: float = 0.5,
    segments: int = 20, rings: int = 12,
) -> Mesh3DRecord:
    radius = _positive(radius, "sphere radius")
    if segments < 3 or rings < 2:
        raise ValueError("sphere segments/rings too small")
    vertices: list[Vec3] = []
    normals: list[Vec3] = []
    for ring in range(rings + 1):
        phi = math.pi * ring / rings
        y, ring_radius = math.cos(phi), math.sin(phi)
        for segment in range(segments + 1):
            theta = math.tau * segment / segments
            normal = (
                ring_radius * math.cos(theta), y,
                ring_radius * math.sin(theta),
            )
            normals.append(normal)
            vertices.append(vscale(normal, radius))
    triangles: list[tuple[int, int, int]] = []
    stride = segments + 1
    for ring in range(rings):
        for segment in range(segments):
            a, b = ring * stride + segment, (ring + 1) * stride + segment
            if ring > 0:
                triangles.append((a, b, a + 1))
            if ring < rings - 1:
                triangles.append((a + 1, b, b + 1))
    return Mesh3DRecord(
        mesh_id, tuple(vertices), tuple(triangles), tuple(normals),
        {"primitive": "uv_sphere", "radius": radius},
    )
