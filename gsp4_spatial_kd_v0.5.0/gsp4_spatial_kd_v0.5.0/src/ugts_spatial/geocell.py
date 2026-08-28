from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Protocol

import numpy as np

EARTH_RADIUS_M = 6_371_008.8
_MAX_RESOLUTION = 26
_RESOLUTION_SHIFT = 58
_MORTON_MASK = (1 << _RESOLUTION_SHIFT) - 1


def _interleave2(x: int, y: int, resolution: int) -> int:
    out = 0
    for bit in range(resolution):
        out |= ((x >> bit) & 1) << (2 * bit)
        out |= ((y >> bit) & 1) << (2 * bit + 1)
    return out


def _deinterleave2(code: int, resolution: int) -> tuple[int, int]:
    x = 0
    y = 0
    for bit in range(resolution):
        x |= ((code >> (2 * bit)) & 1) << bit
        y |= ((code >> (2 * bit + 1)) & 1) << bit
    return x, y


def encode_morton_cell(latitude: float, longitude: float, resolution: int = 14) -> int:
    """Encode WGS84 latitude/longitude into a deterministic 64-bit Morton cell.

    This is a dependency-free rectangular broad-phase index. It is not H3 and
    does not claim equal-area or hexagonal geometry. Exact distance/guard tests
    must still be performed after candidate lookup.
    """
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise ValueError("latitude and longitude must be finite")
    if not 1 <= resolution <= _MAX_RESOLUTION:
        raise ValueError(f"resolution must be in [1,{_MAX_RESOLUTION}]")
    latitude = min(90.0, max(-90.0, latitude))
    longitude = ((longitude + 180.0) % 360.0) - 180.0
    side = 1 << resolution
    x = int(math.floor((longitude + 180.0) / 360.0 * side)) % side
    y = int(math.floor((latitude + 90.0) / 180.0 * side))
    y = min(side - 1, max(0, y))
    return (resolution << _RESOLUTION_SHIFT) | _interleave2(x, y, resolution)


def decode_morton_cell(cell_id: int) -> tuple[float, float, int]:
    resolution = int(cell_id >> _RESOLUTION_SHIFT)
    if not 1 <= resolution <= _MAX_RESOLUTION:
        raise ValueError("invalid Morton geocell resolution")
    code = int(cell_id & _MORTON_MASK)
    x, y = _deinterleave2(code, resolution)
    side = 1 << resolution
    longitude = ((x + 0.5) / side) * 360.0 - 180.0
    latitude = ((y + 0.5) / side) * 180.0 - 90.0
    return latitude, longitude, resolution


def morton_cell_xy(cell_id: int) -> tuple[int, int, int]:
    resolution = int(cell_id >> _RESOLUTION_SHIFT)
    if not 1 <= resolution <= _MAX_RESOLUTION:
        raise ValueError("invalid Morton geocell resolution")
    x, y = _deinterleave2(int(cell_id & _MORTON_MASK), resolution)
    return x, y, resolution


def morton_cell_from_xy(x: int, y: int, resolution: int) -> int:
    side = 1 << resolution
    x %= side
    y = min(side - 1, max(0, y))
    return (resolution << _RESOLUTION_SHIFT) | _interleave2(x, y, resolution)


def morton_grid_disk(cell_id: int, k: int) -> list[int]:
    if k < 0:
        raise ValueError("k must be nonnegative")
    x, y, resolution = morton_cell_xy(cell_id)
    cells: list[int] = []
    for dy in range(-k, k + 1):
        for dx in range(-k, k + 1):
            cells.append(morton_cell_from_xy(x + dx, y + dy, resolution))
    return cells


def morton_cell_size_m(cell_id: int, latitude: float | None = None) -> tuple[float, float]:
    lat_center, _, resolution = decode_morton_cell(cell_id)
    lat = lat_center if latitude is None else float(latitude)
    side = 1 << resolution
    height = math.pi * EARTH_RADIUS_M / side
    width = 2.0 * math.pi * EARTH_RADIUS_M * max(1e-6, math.cos(math.radians(lat))) / side
    return width, height


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def local_enu_m(
    latitude: np.ndarray | float,
    longitude: np.ndarray | float,
    origin_latitude: float,
    origin_longitude: float,
    elevation_m: np.ndarray | float | None = None,
    origin_elevation_m: float = 0.0,
) -> np.ndarray:
    """Approximate local east/north/up coordinates for bounded local queries."""
    lat = np.asarray(latitude, dtype=np.float64)
    lon = np.asarray(longitude, dtype=np.float64)
    dlat = np.radians(lat - origin_latitude)
    dlon_deg = (lon - origin_longitude + 180.0) % 360.0 - 180.0
    dlon = np.radians(dlon_deg)
    east = EARTH_RADIUS_M * dlon * math.cos(math.radians(origin_latitude))
    north = EARTH_RADIUS_M * dlat
    if elevation_m is None:
        up = np.zeros_like(east)
    else:
        up = np.asarray(elevation_m, dtype=np.float64) - float(origin_elevation_m)
    return np.stack((east, north, up), axis=-1)


class SpatialIndex(Protocol):
    name: str
    resolution: int

    def cell(self, latitude: float, longitude: float) -> int: ...

    def neighbors(self, cell_id: int, k: int) -> list[int]: ...

    def center(self, cell_id: int) -> tuple[float, float]: ...

    def ring_for_radius(self, cell_id: int, latitude: float, radius_m: float) -> int: ...


@dataclass(frozen=True)
class MortonSpatialIndex:
    resolution: int = 14
    name: str = "morton"

    def cell(self, latitude: float, longitude: float) -> int:
        return encode_morton_cell(latitude, longitude, self.resolution)

    def neighbors(self, cell_id: int, k: int) -> list[int]:
        return morton_grid_disk(int(cell_id), k)

    def center(self, cell_id: int) -> tuple[float, float]:
        latitude, longitude, _ = decode_morton_cell(int(cell_id))
        return latitude, longitude

    def ring_for_radius(self, cell_id: int, latitude: float, radius_m: float) -> int:
        if radius_m < 0:
            raise ValueError("radius_m must be nonnegative")
        width, height = morton_cell_size_m(int(cell_id), latitude)
        return max(0, int(math.ceil(radius_m / max(1.0, min(width, height)))) + 1)


@dataclass(frozen=True)
class H3SpatialIndex:
    resolution: int = 8
    name: str = "h3"

    def _module(self):
        try:
            import h3  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("H3 backend requires `pip install h3`") from exc
        return h3

    def cell(self, latitude: float, longitude: float) -> int:
        h3 = self._module()
        return int(h3.str_to_int(h3.latlng_to_cell(latitude, longitude, self.resolution)))

    def neighbors(self, cell_id: int, k: int) -> list[int]:
        h3 = self._module()
        source = h3.int_to_str(int(cell_id))
        return [int(h3.str_to_int(value)) for value in h3.grid_disk(source, k)]

    def center(self, cell_id: int) -> tuple[float, float]:
        h3 = self._module()
        latitude, longitude = h3.cell_to_latlng(h3.int_to_str(int(cell_id)))
        return float(latitude), float(longitude)

    def ring_for_radius(self, cell_id: int, latitude: float, radius_m: float) -> int:
        del cell_id, latitude
        h3 = self._module()
        edge_m = float(h3.average_hexagon_edge_length(self.resolution, unit="m"))
        # Grid distance is not a metric circle; this is only broad-phase sizing.
        return max(0, int(math.ceil(radius_m / max(1.0, 1.5 * edge_m))) + 1)


def make_spatial_index(backend: str = "morton", resolution: int | None = None) -> SpatialIndex:
    backend = backend.lower()
    if backend == "morton":
        return MortonSpatialIndex(14 if resolution is None else resolution)
    if backend == "h3":
        return H3SpatialIndex(8 if resolution is None else resolution)
    raise ValueError(f"unknown spatial backend: {backend}")


def initial_cell_k_for_radius(
    radius_m: float,
    *,
    backend: str,
    resolution: int,
    latitude: float = 52.5,
) -> int:
    """Conservative first guess for a broad-phase neighborhood radius.

    The exact haversine guard is always applied after this broad phase. The
    estimate therefore affects candidate count, not geometric correctness, as
    long as callers add a one-cell safety margin (this function already does).
    """
    if radius_m < 0:
        raise ValueError("radius_m must be nonnegative")
    backend = backend.lower()
    if backend == "h3":
        try:
            import h3  # type: ignore

            edge_m = float(h3.average_hexagon_edge_length(resolution, unit="m"))
            return max(1, int(math.ceil(radius_m / max(edge_m, 1.0))) + 1)
        except Exception:
            # Safe fallback for missing/older H3 bindings.
            return max(1, int(math.ceil(radius_m / 500.0)) + 1)
    if backend == "morton":
        side = 1 << resolution
        lat_height = math.pi * EARTH_RADIUS_M / side
        lon_width = 2.0 * math.pi * EARTH_RADIUS_M * max(0.1, math.cos(math.radians(latitude))) / side
        cell_span = max(1.0, min(lat_height, lon_width))
        return max(1, int(math.ceil(radius_m / cell_span)) + 1)
    raise ValueError(f"unknown spatial backend: {backend}")
