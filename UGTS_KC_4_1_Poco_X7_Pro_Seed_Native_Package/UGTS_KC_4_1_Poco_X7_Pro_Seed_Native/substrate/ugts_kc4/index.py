"""Deterministic 64-bit spatial keys and a compact reference index."""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable, Mapping

from .model import Vec3, as_vec3, vec_distance


@dataclass(frozen=True, slots=True)
class VoxelKeyProfile:
    """4-bit level plus three signed 20-bit cell coordinates."""

    id: str = "voxel20x3-level4-v1"
    origin: Vec3 = (0.0, 0.0, 0.0)
    cell_size: float = 0.25

    AXIS_BITS = 20
    LEVEL_BITS = 4
    AXIS_MASK = (1 << AXIS_BITS) - 1
    AXIS_BIAS = 1 << (AXIS_BITS - 1)
    LEVEL_MASK = (1 << LEVEL_BITS) - 1

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("voxel profile id is required")
        object.__setattr__(self, "origin", as_vec3(self.origin, "voxel.origin"))
        size = float(self.cell_size)
        if not math.isfinite(size) or size <= 0:
            raise ValueError("cell_size must be finite and positive")
        object.__setattr__(self, "cell_size", size)

    @property
    def min_index(self) -> int:
        return -self.AXIS_BIAS

    @property
    def max_index(self) -> int:
        return self.AXIS_BIAS - 1

    def indices(self, point: Vec3, level: int = 0) -> tuple[int, int, int]:
        point = as_vec3(point)
        if not 0 <= int(level) <= self.LEVEL_MASK:
            raise ValueError("voxel level is outside 4-bit range")
        size = self.cell_size * (2 ** int(level))
        return tuple(math.floor((point[i] - self.origin[i]) / size) for i in range(3))  # type: ignore[return-value]

    def encode_indices(self, ix: int, iy: int, iz: int, level: int = 0) -> int:
        if not 0 <= int(level) <= self.LEVEL_MASK:
            raise ValueError("voxel level is outside 4-bit range")
        values = (int(ix), int(iy), int(iz))
        if any(value < self.min_index or value > self.max_index for value in values):
            raise ValueError("voxel coordinate is outside signed 20-bit range")
        qx, qy, qz = (value + self.AXIS_BIAS for value in values)
        return (int(level) << 60) | (qx << 40) | (qy << 20) | qz

    def encode(self, point: Vec3, level: int = 0) -> int:
        return self.encode_indices(*self.indices(point, level), level=level)

    def decode_indices(self, word: int) -> tuple[int, int, int, int]:
        if not 0 <= int(word) < 1 << 64:
            raise ValueError("voxel key must be an unsigned 64-bit value")
        level = (word >> 60) & self.LEVEL_MASK
        qx = (word >> 40) & self.AXIS_MASK
        qy = (word >> 20) & self.AXIS_MASK
        qz = word & self.AXIS_MASK
        return qx - self.AXIS_BIAS, qy - self.AXIS_BIAS, qz - self.AXIS_BIAS, level

    def cell_bounds(self, word: int) -> tuple[Vec3, Vec3]:
        ix, iy, iz, level = self.decode_indices(word)
        size = self.cell_size * (2 ** level)
        minimum = (
            self.origin[0] + ix * size,
            self.origin[1] + iy * size,
            self.origin[2] + iz * size,
        )
        maximum = (minimum[0] + size, minimum[1] + size, minimum[2] + size)
        return minimum, maximum

    def cell_center(self, word: int) -> Vec3:
        minimum, maximum = self.cell_bounds(word)
        return tuple((minimum[i] + maximum[i]) / 2.0 for i in range(3))  # type: ignore[return-value]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "origin": list(self.origin), "cell_size": self.cell_size, "layout": "level4|x20|y20|z20"}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "VoxelKeyProfile":
        return cls(str(value.get("id", "voxel20x3-level4-v1")), tuple(value.get("origin", (0, 0, 0))), float(value.get("cell_size", 0.25)))


@dataclass(frozen=True, slots=True)
class RayKeyProfile:
    """Log-depth/azimuth/elevation/time key inspired by SCLP, adapted to camera rays.

    Layout: depth20 | azimuth18 | elevation14 | modular_time12.
    """

    id: str = "ray-logpolar-20-18-14-12-v1"
    min_depth: float = 0.1
    max_depth: float = 100.0
    time_modulus: int = 4096

    DEPTH_BITS = 20
    AZIMUTH_BITS = 18
    ELEVATION_BITS = 14
    TIME_BITS = 12
    DEPTH_MASK = (1 << DEPTH_BITS) - 1
    AZIMUTH_MASK = (1 << AZIMUTH_BITS) - 1
    ELEVATION_MASK = (1 << ELEVATION_BITS) - 1
    TIME_MASK = (1 << TIME_BITS) - 1

    def __post_init__(self) -> None:
        minimum = float(self.min_depth)
        maximum = float(self.max_depth)
        if not all(math.isfinite(x) for x in (minimum, maximum)) or minimum <= 0 or maximum <= minimum:
            raise ValueError("ray key requires 0 < min_depth < max_depth")
        modulus = int(self.time_modulus)
        if modulus <= 0 or modulus > 1 << self.TIME_BITS:
            raise ValueError("time_modulus must fit the 12-bit field")
        object.__setattr__(self, "min_depth", minimum)
        object.__setattr__(self, "max_depth", maximum)
        object.__setattr__(self, "time_modulus", modulus)

    @staticmethod
    def _quantize_unit(value: float, states: int) -> int:
        return min(states - 1, max(0, int(math.floor(value * states))))

    def quantize(self, vector: Vec3, tick: int) -> tuple[int, int, int, int]:
        x, y, z = as_vec3(vector, "ray.vector")
        depth = math.sqrt(x * x + y * y + z * z)
        if depth < self.min_depth or depth > self.max_depth:
            raise ValueError("ray depth is outside the declared profile")
        rho = math.log(depth / self.min_depth) / math.log(self.max_depth / self.min_depth)
        azimuth = math.atan2(z, x)
        elevation = math.asin(max(-1.0, min(1.0, y / depth)))
        q_depth = self._quantize_unit(rho, 1 << self.DEPTH_BITS)
        q_azimuth = self._quantize_unit((azimuth + math.pi) / (2 * math.pi), 1 << self.AZIMUTH_BITS)
        q_elevation = self._quantize_unit((elevation + math.pi / 2) / math.pi, 1 << self.ELEVATION_BITS)
        q_time = int(tick) % self.time_modulus
        return q_depth, q_azimuth, q_elevation, q_time

    def pack_quantized(self, q_depth: int, q_azimuth: int, q_elevation: int, q_time: int) -> int:
        fields = (
            (q_depth, self.DEPTH_MASK, "depth"),
            (q_azimuth, self.AZIMUTH_MASK, "azimuth"),
            (q_elevation, self.ELEVATION_MASK, "elevation"),
            (q_time, self.TIME_MASK, "time"),
        )
        for value, mask, name in fields:
            if not 0 <= int(value) <= mask:
                raise ValueError(f"{name} field is outside its key width")
        return (int(q_depth) << 44) | (int(q_azimuth) << 26) | (int(q_elevation) << 12) | int(q_time)

    def encode(self, vector: Vec3, tick: int) -> int:
        return self.pack_quantized(*self.quantize(vector, tick))

    def unpack(self, word: int) -> tuple[int, int, int, int]:
        if not 0 <= int(word) < 1 << 64:
            raise ValueError("ray key must be an unsigned 64-bit value")
        return (
            (word >> 44) & self.DEPTH_MASK,
            (word >> 26) & self.AZIMUTH_MASK,
            (word >> 12) & self.ELEVATION_MASK,
            word & self.TIME_MASK,
        )

    def decode_center(self, word: int) -> tuple[float, float, float, int]:
        qd, qa, qe, qt = self.unpack(word)
        rho = (qd + 0.5) / (1 << self.DEPTH_BITS)
        depth = self.min_depth * math.exp(rho * math.log(self.max_depth / self.min_depth))
        azimuth = -math.pi + (qa + 0.5) * (2 * math.pi / (1 << self.AZIMUTH_BITS))
        elevation = -math.pi / 2 + (qe + 0.5) * (math.pi / (1 << self.ELEVATION_BITS))
        return depth, azimuth, elevation, qt

    def quantization_steps(self, depth: float) -> dict[str, float]:
        if not self.min_depth <= depth <= self.max_depth:
            raise ValueError("depth outside profile")
        delta_rho = math.log(self.max_depth / self.min_depth) / (1 << self.DEPTH_BITS)
        return {
            "relative_depth": math.exp(delta_rho) - 1.0,
            "azimuth_rad": 2 * math.pi / (1 << self.AZIMUTH_BITS),
            "elevation_rad": math.pi / (1 << self.ELEVATION_BITS),
            "approx_depth_m": depth * (math.exp(delta_rho) - 1.0),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "min_depth": self.min_depth,
            "max_depth": self.max_depth,
            "time_modulus": self.time_modulus,
            "layout": "depth20|azimuth18|elevation14|time12",
            "capacity": 1 << 64,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RayKeyProfile":
        return cls(
            str(value.get("id", "ray-logpolar-20-18-14-12-v1")),
            float(value.get("min_depth", 0.1)),
            float(value.get("max_depth", 100.0)),
            int(value.get("time_modulus", 4096)),
        )


@dataclass
class SpatialHashIndex:
    profile: VoxelKeyProfile
    cells: dict[int, set[str]] = field(default_factory=dict)
    positions: dict[str, Vec3] = field(default_factory=dict)

    def insert(self, item_id: str, position: Vec3) -> int:
        if not item_id:
            raise ValueError("item_id is required")
        if item_id in self.positions:
            self.remove(item_id)
        position = as_vec3(position)
        key = self.profile.encode(position)
        self.cells.setdefault(key, set()).add(item_id)
        self.positions[item_id] = position
        return key

    def remove(self, item_id: str) -> None:
        position = self.positions.pop(item_id, None)
        if position is None:
            return
        key = self.profile.encode(position)
        bucket = self.cells.get(key)
        if bucket is not None:
            bucket.discard(item_id)
            if not bucket:
                del self.cells[key]

    def query_sphere(self, center: Vec3, radius: float) -> list[str]:
        center = as_vec3(center)
        radius = float(radius)
        if not math.isfinite(radius) or radius < 0:
            raise ValueError("query radius must be finite and non-negative")
        minimum = tuple(center[i] - radius for i in range(3))
        maximum = tuple(center[i] + radius for i in range(3))
        min_indices = self.profile.indices(minimum)  # type: ignore[arg-type]
        max_indices = self.profile.indices(maximum)  # type: ignore[arg-type]
        candidates: set[str] = set()
        for ix in range(min_indices[0], max_indices[0] + 1):
            for iy in range(min_indices[1], max_indices[1] + 1):
                for iz in range(min_indices[2], max_indices[2] + 1):
                    try:
                        key = self.profile.encode_indices(ix, iy, iz)
                    except ValueError:
                        continue
                    candidates.update(self.cells.get(key, ()))
        return sorted(
            (item_id for item_id in candidates if vec_distance(self.positions[item_id], center) <= radius),
            key=lambda item_id: (vec_distance(self.positions[item_id], center), item_id),
        )

    def rebuild(self, values: Iterable[tuple[str, Vec3]]) -> None:
        self.cells.clear()
        self.positions.clear()
        for item_id, position in values:
            self.insert(item_id, position)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "items": [{"id": item_id, "position": list(self.positions[item_id])} for item_id in sorted(self.positions)],
            "occupied_cells": len(self.cells),
        }
