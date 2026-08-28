"""Spatial indexing and exact support/guard calculations.

H3 is an optional broad phase. The exact decision is always made with metric
geometry in a local frame, so an index cell is never treated as proof of a
spatial relation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from collections import defaultdict
from typing import Iterable, Sequence

import numpy as np

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp * 0.5) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl * 0.5) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def latlon_to_ecef(lat_deg: float, lon_deg: float, alt_m: float = 0.0) -> np.ndarray:
    # Spherical-Earth ECEF is sufficient for local support/candidate work here.
    lat = math.radians(lat_deg)
    lon = math.radians(lon_deg)
    r = EARTH_RADIUS_M + alt_m
    c = math.cos(lat)
    return np.asarray([r * c * math.cos(lon), r * c * math.sin(lon), r * math.sin(lat)], dtype=np.float64)


@dataclass(frozen=True)
class LocalFrame:
    lat0: float
    lon0: float
    alt0: float = 0.0

    def __post_init__(self) -> None:
        lat = math.radians(self.lat0)
        lon = math.radians(self.lon0)
        object.__setattr__(self, "_origin", latlon_to_ecef(self.lat0, self.lon0, self.alt0))
        object.__setattr__(self, "_east", np.asarray([-math.sin(lon), math.cos(lon), 0.0], dtype=np.float64))
        object.__setattr__(self, "_north", np.asarray([-math.sin(lat) * math.cos(lon), -math.sin(lat) * math.sin(lon), math.cos(lat)], dtype=np.float64))
        object.__setattr__(self, "_up", np.asarray([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)], dtype=np.float64))

    def to_enu(self, lat_deg: float, lon_deg: float, alt_m: float = 0.0) -> np.ndarray:
        d = latlon_to_ecef(lat_deg, lon_deg, alt_m) - self._origin
        return np.asarray([d @ self._east, d @ self._north, d @ self._up], dtype=np.float32)


def normalize3(v: Sequence[float]) -> np.ndarray:
    a = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(a))
    if not math.isfinite(n) or n <= 0.0:
        return np.asarray([0.0, 0.0, 1.0], dtype=np.float64)
    return a / n


@dataclass(frozen=True)
class SupportResult:
    distance_m: float
    cos_to_axis: float
    in_support: bool
    sdf_m: float
    guard_m: float
    guard_pass: bool


def cone_sphere_support(
    point_enu: Sequence[float],
    axis_enu: Sequence[float],
    radius_m: float,
    cone_cos: float,
    epsilon_m: float,
    guard_mode: str = "inside",
) -> SupportResult:
    p = np.asarray(point_enu, dtype=np.float64)
    r = float(np.linalg.norm(p))
    axis = normalize3(axis_enu)
    cos_to_axis = 1.0 if r <= 0.0 else float(np.dot(p / r, axis))
    in_support = bool(r <= radius_m and cos_to_axis >= cone_cos)
    sdf = r - radius_m
    if guard_mode == "inside":
        guard = sdf - epsilon_m
        guard_pass = guard <= 0.0
    elif guard_mode == "boundary":
        guard = abs(sdf) - epsilon_m
        guard_pass = guard <= 0.0
    else:
        raise ValueError("guard_mode must be 'inside' or 'boundary'")
    return SupportResult(r, cos_to_axis, in_support, sdf, guard, bool(guard_pass))


def _interleave_u32(x: int, y: int) -> int:
    # 32+32 Morton key. Works on non-negative biased grid coordinates.
    def part1(v: int) -> int:
        v &= 0xFFFFFFFF
        v = (v | (v << 16)) & 0x0000FFFF0000FFFF
        v = (v | (v << 8)) & 0x00FF00FF00FF00FF
        v = (v | (v << 4)) & 0x0F0F0F0F0F0F0F0F
        v = (v | (v << 2)) & 0x3333333333333333
        v = (v | (v << 1)) & 0x5555555555555555
        return v
    return (part1(y) << 1) | part1(x)


class SpatialIndexer:
    """Optional H3 index with a dependency-free Morton-grid fallback."""

    def __init__(self, resolution: int = 8, fallback_cell_deg: float = 0.02, prefer_h3: bool = True):
        self.resolution = int(resolution)
        self.fallback_cell_deg = float(fallback_cell_deg)
        self.backend = "morton-grid"
        self._h3 = None
        if prefer_h3:
            try:
                import h3  # type: ignore
                self._h3 = h3
                self.backend = "h3"
            except Exception:
                pass

    def cell(self, lat: float, lon: float) -> str:
        if self._h3 is not None:
            if hasattr(self._h3, "latlng_to_cell"):
                return str(self._h3.latlng_to_cell(lat, lon, self.resolution))
            return str(self._h3.geo_to_h3(lat, lon, self.resolution))
        x = int(math.floor((lon + 180.0) / self.fallback_cell_deg))
        y = int(math.floor((lat + 90.0) / self.fallback_cell_deg))
        return f"m{_interleave_u32(x, y):016x}:{x}:{y}"

    def neighborhood(self, cell: str, radius_m: float, latitude_hint: float = 52.5) -> set[str]:
        if self._h3 is not None:
            # Convert a metric radius to a conservative ring count using average edge length.
            try:
                if hasattr(self._h3, "average_hexagon_edge_length"):
                    edge_m = float(self._h3.average_hexagon_edge_length(self.resolution, unit="m"))
                else:
                    edge_m = float(self._h3.edge_length(self.resolution, unit="m"))
            except Exception:
                edge_m = 500.0
            k = max(0, int(math.ceil(radius_m / max(edge_m, 1.0))) + 1)
            if hasattr(self._h3, "grid_disk"):
                return {str(x) for x in self._h3.grid_disk(cell, k)}
            return {str(x) for x in self._h3.k_ring(cell, k)}
        _, xs, ys = cell.split(":")
        x0, y0 = int(xs), int(ys)
        lat_cell_m = 111_320.0 * self.fallback_cell_deg
        lon_cell_m = max(1.0, lat_cell_m * math.cos(math.radians(latitude_hint)))
        dx = int(math.ceil(radius_m / lon_cell_m)) + 1
        dy = int(math.ceil(radius_m / lat_cell_m)) + 1
        out: set[str] = set()
        for y in range(y0 - dy, y0 + dy + 1):
            for x in range(x0 - dx, x0 + dx + 1):
                out.add(f"m{_interleave_u32(x, y):016x}:{x}:{y}")
        return out

    def build_buckets(self, lat_lon: np.ndarray) -> tuple[list[str], dict[str, np.ndarray]]:
        cells = [self.cell(float(lat), float(lon)) for lat, lon in lat_lon[:, :2]]
        bucket_lists: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(cells):
            bucket_lists[c].append(i)
        buckets = {k: np.asarray(v, dtype=np.int64) for k, v in bucket_lists.items()}
        return cells, buckets

    def candidates(
        self,
        query_lat: float,
        query_lon: float,
        radius_m: float,
        cells: Sequence[str],
        buckets: dict[str, np.ndarray],
    ) -> np.ndarray:
        center = self.cell(query_lat, query_lon)
        neighbor_cells = self.neighborhood(center, radius_m, query_lat)
        chunks = [buckets[c] for c in neighbor_cells if c in buckets]
        if not chunks:
            return np.empty(0, dtype=np.int64)
        return np.unique(np.concatenate(chunks))
