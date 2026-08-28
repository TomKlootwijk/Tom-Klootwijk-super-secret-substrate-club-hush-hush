from __future__ import annotations

import math
from typing import Sequence

import numpy as np
import torch

from .geocell import EARTH_RADIUS_M


def initial_bearing_radians(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return the initial great-circle bearing in radians, clockwise from north."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.atan2(y, x)


def pair_edge_attr_numpy(
    latitude: np.ndarray,
    longitude: np.ndarray,
    elevation: np.ndarray,
    node_time: np.ndarray,
    edge_index: np.ndarray,
) -> np.ndarray:
    """Build the fixed UGKG2 edge feature matrix for arbitrary node pairs."""
    edge_index = np.asarray(edge_index, dtype=np.int64)
    if edge_index.ndim != 2 or edge_index.shape[0] != 2:
        raise ValueError("edge_index must have shape [2,E]")
    count = edge_index.shape[1]
    result = np.zeros((count, 4), dtype=np.float32)
    for row, (source, target) in enumerate(zip(edge_index[0].tolist(), edge_index[1].tolist())):
        lat1 = float(latitude[source])
        lon1 = float(longitude[source])
        lat2 = float(latitude[target])
        lon2 = float(longitude[target])
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = p2 - p1
        dl = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
        horizontal = 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(max(0.0, a))))
        vertical = float(elevation[target]) - float(elevation[source])
        distance = math.hypot(horizontal, vertical)
        bearing = initial_bearing_radians(lat1, lon1, lat2, lon2)
        result[row] = (
            float(distance),
            float(math.sin(bearing)),
            float(math.cos(bearing)),
            float(abs(float(node_time[target]) - float(node_time[source]))),
        )
    return result


def pair_edge_attr_torch(graph: dict[str, torch.Tensor], edge_index: torch.Tensor) -> torch.Tensor:
    """GPU-capable version of :func:`pair_edge_attr_numpy`."""
    if edge_index.ndim != 2 or edge_index.shape[0] != 2:
        raise ValueError("edge_index must have shape [2,E]")
    source = edge_index[0]
    target = edge_index[1]
    dtype = graph["latitude"].dtype
    device = source.device
    lat1 = torch.deg2rad(graph["latitude"][source].to(dtype))
    lat2 = torch.deg2rad(graph["latitude"][target].to(dtype))
    lon_delta_deg = torch.remainder(
        graph["longitude"][target] - graph["longitude"][source] + 180.0, 360.0
    ) - 180.0
    lon_delta = torch.deg2rad(lon_delta_deg.to(dtype))
    delta_lat = lat2 - lat1
    a = torch.sin(delta_lat / 2.0).square() + torch.cos(lat1) * torch.cos(lat2) * torch.sin(
        lon_delta / 2.0
    ).square()
    horizontal = 2.0 * EARTH_RADIUS_M * torch.asin(torch.sqrt(a.clamp(0.0, 1.0)))
    vertical = graph["elevation"][target].to(dtype) - graph["elevation"][source].to(dtype)
    distance = torch.sqrt(horizontal.square() + vertical.square())
    y = torch.sin(lon_delta) * torch.cos(lat2)
    x = torch.cos(lat1) * torch.sin(lat2) - torch.sin(lat1) * torch.cos(lat2) * torch.cos(
        lon_delta
    )
    norm = torch.sqrt(x.square() + y.square()).clamp_min(torch.finfo(dtype).eps)
    sin_bearing = y / norm
    cos_bearing = x / norm
    delta_time = (graph["node_time"][target] - graph["node_time"][source]).abs().to(dtype)
    return torch.stack((distance, sin_bearing, cos_bearing, delta_time), dim=-1).to(
        device=device, dtype=torch.float32
    )


def candidate_edge_attr_from_origin(
    candidate_latitude: Sequence[float] | np.ndarray,
    candidate_longitude: Sequence[float] | np.ndarray,
    candidate_elevation: Sequence[float] | np.ndarray,
    candidate_time: Sequence[float] | np.ndarray,
    *,
    origin_latitude: float,
    origin_longitude: float,
    origin_elevation: float = 0.0,
    origin_time: float = 0.0,
) -> np.ndarray:
    lat = np.asarray(candidate_latitude, dtype=np.float64)
    lon = np.asarray(candidate_longitude, dtype=np.float64)
    elevation = np.asarray(candidate_elevation, dtype=np.float64)
    time = np.asarray(candidate_time, dtype=np.float64)
    result = np.zeros((lat.size, 4), dtype=np.float32)
    for i in range(lat.size):
        p1 = math.radians(origin_latitude)
        p2 = math.radians(float(lat[i]))
        dp = p2 - p1
        dl = math.radians(((float(lon[i]) - origin_longitude + 180.0) % 360.0) - 180.0)
        a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
        horizontal = 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(max(0.0, a))))
        vertical = float(elevation[i]) - origin_elevation
        distance = math.hypot(horizontal, vertical)
        bearing = initial_bearing_radians(
            origin_latitude, origin_longitude, float(lat[i]), float(lon[i])
        )
        result[i] = (
            distance,
            math.sin(bearing),
            math.cos(bearing),
            abs(float(time[i]) - origin_time),
        )
    return result
