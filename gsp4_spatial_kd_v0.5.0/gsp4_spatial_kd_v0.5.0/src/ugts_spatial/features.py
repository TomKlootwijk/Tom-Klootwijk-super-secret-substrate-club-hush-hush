from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from .embeddings import HashEmbedder
from .geocell import EARTH_RADIUS_M


def bearing_radians(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dl = math.radians(((lon2 - lon1 + 180.0) % 360.0) - 180.0)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.atan2(y, x)


def edge_attributes_np(
    latitude: np.ndarray,
    longitude: np.ndarray,
    node_time: np.ndarray,
    edge_index: np.ndarray,
) -> np.ndarray:
    """Compute UGKG edge attributes for a set of global node pairs."""
    edge_index = np.asarray(edge_index, dtype=np.int64)
    if edge_index.ndim != 2 or edge_index.shape[0] != 2:
        raise ValueError("edge_index must have shape [2,E]")
    src = edge_index[0]
    dst = edge_index[1]
    lat1 = np.radians(np.asarray(latitude, dtype=np.float64)[src])
    lat2 = np.radians(np.asarray(latitude, dtype=np.float64)[dst])
    lon1 = np.radians(np.asarray(longitude, dtype=np.float64)[src])
    lon2 = np.radians(np.asarray(longitude, dtype=np.float64)[dst])
    dlat = lat2 - lat1
    dlon = (lon2 - lon1 + math.pi) % (2.0 * math.pi) - math.pi
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2.0) ** 2
    distance = 2.0 * EARTH_RADIUS_M * np.arcsin(np.minimum(1.0, np.sqrt(np.maximum(0.0, a))))
    y = np.sin(dlon) * np.cos(lat2)
    x = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(dlon)
    bearing = np.arctan2(y, x)
    delta_time = np.abs(np.asarray(node_time, dtype=np.float64)[src] - np.asarray(node_time, dtype=np.float64)[dst])
    return np.stack(
        (
            distance.astype(np.float32),
            np.sin(bearing).astype(np.float32),
            np.cos(bearing).astype(np.float32),
            delta_time.astype(np.float32),
        ),
        axis=1,
    )


def build_node_features(
    *,
    texts: Sequence[str],
    node_type: np.ndarray,
    latitude: np.ndarray,
    longitude: np.ndarray,
    elevation: np.ndarray,
    node_time: np.ndarray,
    scalar_value: np.ndarray | None = None,
    uncertainty: np.ndarray | None = None,
    population: np.ndarray | None = None,
    active: np.ndarray | None = None,
    feature_dim: int = 32,
    center_latitude: float | None = None,
    center_longitude: float | None = None,
) -> np.ndarray:
    """Create compact numeric+lexical input features without a language model."""
    n = len(texts)
    if feature_dim < 16:
        raise ValueError("feature_dim must be at least 16")
    node_type = np.asarray(node_type, dtype=np.int64)
    latitude = np.asarray(latitude, dtype=np.float64)
    longitude = np.asarray(longitude, dtype=np.float64)
    elevation = np.asarray(elevation, dtype=np.float64)
    node_time = np.asarray(node_time, dtype=np.float64)
    if any(array.shape != (n,) for array in (node_type, latitude, longitude, elevation, node_time)):
        raise ValueError("node vectors and texts must have equal length")
    scalar_value = np.zeros(n, dtype=np.float64) if scalar_value is None else np.asarray(scalar_value, dtype=np.float64)
    uncertainty = np.zeros(n, dtype=np.float64) if uncertainty is None else np.asarray(uncertainty, dtype=np.float64)
    population = np.zeros(n, dtype=np.float64) if population is None else np.asarray(population, dtype=np.float64)
    active = np.ones(n, dtype=np.float64) if active is None else np.asarray(active, dtype=np.float64)
    if any(array.shape != (n,) for array in (scalar_value, uncertainty, population, active)):
        raise ValueError("optional node vectors have wrong length")

    center_latitude = float(np.median(latitude)) if center_latitude is None else float(center_latitude)
    center_longitude = float(np.median(longitude)) if center_longitude is None else float(center_longitude)
    numeric_dim = 12
    lexical_dim = feature_dim - numeric_dim
    lexical = HashEmbedder(dimensions=lexical_dim).encode(list(texts))
    features = np.zeros((n, feature_dim), dtype=np.float32)
    features[:, 0] = ((latitude - center_latitude) / 1.0).astype(np.float32)
    wrapped_lon = (longitude - center_longitude + 180.0) % 360.0 - 180.0
    features[:, 1] = (wrapped_lon / 1.0).astype(np.float32)
    features[:, 2] = np.tanh(elevation / 100.0).astype(np.float32)
    features[:, 3] = np.sin(node_time / 86_400.0 * 2.0 * math.pi).astype(np.float32)
    features[:, 4] = np.cos(node_time / 86_400.0 * 2.0 * math.pi).astype(np.float32)
    features[:, 5] = np.tanh(scalar_value).astype(np.float32)
    features[:, 6] = np.clip(uncertainty, 0.0, 1.0).astype(np.float32)
    features[:, 7] = np.clip(active, 0.0, 1.0).astype(np.float32)
    features[:, 8] = (np.log1p(np.maximum(population, 0.0)) / 20.0).astype(np.float32)
    features[:, 9] = (node_type / max(1, int(node_type.max(initial=1)))).astype(np.float32)
    features[:, 10] = np.sin(np.radians(latitude)).astype(np.float32)
    features[:, 11] = np.cos(np.radians(latitude)).astype(np.float32)
    features[:, numeric_dim:] = lexical
    return features


def spatial_splits(latitude: np.ndarray, longitude: np.ndarray, *, validation_fraction: float = 0.15, test_fraction: float = 0.15) -> np.ndarray:
    """Assign contiguous geographic holdouts instead of random row splits."""
    latitude = np.asarray(latitude, dtype=np.float64)
    longitude = np.asarray(longitude, dtype=np.float64)
    if latitude.shape != longitude.shape:
        raise ValueError("latitude/longitude shapes differ")
    n = latitude.size
    if n == 0:
        return np.zeros(0, dtype=np.int8)
    # A deterministic southwest-to-northeast projection forms contiguous bands.
    lat_scale = max(float(np.ptp(latitude)), 1e-9)
    lon_scale = max(float(np.ptp(longitude)), 1e-9)
    order_value = (latitude - latitude.min()) / lat_scale + (longitude - longitude.min()) / lon_scale
    order = np.argsort(order_value, kind="stable")
    split = np.zeros(n, dtype=np.int8)
    n_test = max(1, int(round(n * test_fraction))) if n >= 10 else max(0, n // 5)
    n_valid = max(1, int(round(n * validation_fraction))) if n >= 10 else max(0, n // 5)
    if n_valid + n_test >= n:
        n_valid = max(0, n // 5)
        n_test = max(0, n // 5)
    if n_valid:
        split[order[-(n_valid + n_test) : -n_test if n_test else None]] = 1
    if n_test:
        split[order[-n_test:]] = 2
    return split
