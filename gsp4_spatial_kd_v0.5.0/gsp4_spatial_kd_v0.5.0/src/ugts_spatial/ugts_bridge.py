from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import struct
from typing import Any

import numpy as np

from .geocell import EARTH_RADIUS_M, encode_morton_cell, local_enu_m, morton_grid_disk
from .graph import GraphPackage
from .schema import NODE_TYPE_NAMES, RELATION_SPECS, RELATION_TYPE_NAMES, NodeType, RelationType
from .utils import sha256_file, stable_u32, write_json

_G64 = struct.Struct("<12f4I")
_G32 = struct.Struct("<8I")


@dataclass(frozen=True)
class UGTSState:
    position: tuple[float, float, float]
    time: float
    axis: tuple[float, float, float]
    radius: float
    cone_cos: float
    phase: float
    guard_epsilon: float
    confidence_floor: float
    sheet: int
    orientation: int
    compatibility_mask: int
    lineage_seed: int


def pack_g64(state: UGTSState) -> bytes:
    payload = _G64.pack(
        *state.position,
        state.time,
        *state.axis,
        state.radius,
        state.cone_cos,
        state.phase,
        state.guard_epsilon,
        state.confidence_floor,
        state.sheet,
        state.orientation,
        state.compatibility_mask,
        state.lineage_seed,
    )
    if len(payload) != 64:
        raise AssertionError("G64 packing contract changed")
    return payload


def pack_g32(state: UGTSState) -> bytes:
    scalars = (
        *state.position,
        state.time,
        *state.axis,
        state.radius,
        state.cone_cos,
        state.phase,
        state.guard_epsilon,
        state.confidence_floor,
    )
    try:
        half_bytes = struct.pack("<12e", *scalars)
    except OverflowError as exc:
        raise ValueError(
            "a candidate cannot be represented as binary16; reduce the local query radius or use G64"
        ) from exc
    half_words = struct.unpack("<6I", half_bytes)
    topology = (
        (state.sheet & 0xFF)
        | ((state.orientation & 1) << 8)
        | ((state.compatibility_mask & 0xFFFF) << 9)
    ) & 0xFFFFFFFF
    payload = _G32.pack(*half_words, topology, state.lineage_seed)
    if len(payload) != 32:
        raise AssertionError("G32 packing contract changed")
    return payload


def unpack_g32_scalars(payload: bytes) -> tuple[float, ...]:
    words = _G32.unpack(payload)
    return tuple(float(value) for value in struct.unpack("<12e", struct.pack("<6I", *words[:6])))


def _broad_candidates(package: GraphPackage, latitude: float, longitude: float, radius_m: float) -> np.ndarray:
    resolution = int(package.metadata.get("spatial_index", {}).get("resolution", 14))
    side = 1 << resolution
    cell_height = math.pi * EARTH_RADIUS_M / side
    cell_width = 2.0 * math.pi * EARTH_RADIUS_M * max(0.05, math.cos(math.radians(latitude))) / side
    k = max(1, int(math.ceil(radius_m / max(1.0, min(cell_height, cell_width)))) + 1)
    center = encode_morton_cell(latitude, longitude, resolution)
    cells = np.asarray(morton_grid_disk(center, k), dtype=np.uint64)
    allowed_types = np.asarray(
        [
            int(NodeType.SPATIAL_ENTITY),
            int(NodeType.SENSOR),
            int(NodeType.OBSERVATION),
            int(NodeType.EVENT),
        ],
        dtype=np.int64,
    )
    return np.flatnonzero(np.isin(package.cell_id, cells) & np.isin(package.node_type, allowed_types))


def _source_relation_mask(node_type: int) -> int:
    mask = 0
    for relation, spec in RELATION_SPECS.items():
        if NodeType(node_type) in spec.source_types:
            mask |= 1 << relation
    return mask & 0xFFFF


def export_ugts_candidates(
    package: GraphPackage,
    output_prefix: str | Path,
    *,
    latitude: float,
    longitude: float,
    radius_m: float,
    origin_elevation_m: float = 0.0,
    source_index: int | None = None,
    axis: tuple[float, float, float] = (0.0, 0.0, 1.0),
    cone_half_angle_deg: float = 180.0,
    guard_epsilon_m: float = 5.0,
    confidence_floor: float = 0.0,
    query_time: float | None = None,
    mode_bit: int = int(RelationType.INSTANCE_OF),
    maximum_candidates: int = 1_048_576,
) -> dict[str, Any]:
    if not 0 <= mode_bit <= 15:
        raise ValueError("mode_bit must fit the UGTS 16-bit compatibility mask")
    if radius_m <= 0.0 or guard_epsilon_m < 0.0:
        raise ValueError("radius must be positive and guard nonnegative")
    axis_array = np.asarray(axis, dtype=np.float64)
    norm = float(np.linalg.norm(axis_array))
    axis_array = np.asarray([0.0, 0.0, 1.0]) if norm <= 0.0 else axis_array / norm
    candidates = _broad_candidates(package, latitude, longitude, radius_m)
    if source_index is not None:
        if source_index < 0 or source_index >= package.num_nodes:
            raise IndexError("source_index is outside the graph")
        candidates = candidates[candidates != int(source_index)]
    if maximum_candidates > 0:
        candidates = candidates[:maximum_candidates]
    positions = local_enu_m(
        package.latitude[candidates],
        package.longitude[candidates],
        latitude,
        longitude,
        package.elevation[candidates],
        float(origin_elevation_m),
    )
    event_time_absolute = (
        float(query_time) if query_time is not None else float(np.max(package.node_time))
    )
    # G32 stores time as binary16. Absolute Unix seconds do not fit; the ABI
    # therefore uses a query-local temporal chart and records its origin in the
    # exchange metadata. The exported candidate time is zero at the query.
    time_origin = event_time_absolute
    event_time = 0.0
    cone_cos = math.cos(math.radians(cone_half_angle_deg))
    states: list[UGTSState] = []
    for row, node in enumerate(candidates.tolist()):
        position = tuple(float(value) for value in positions[row])
        states.append(
            UGTSState(
                position=position,
                time=event_time,
                axis=tuple(float(value) for value in axis_array),
                radius=float(radius_m),
                cone_cos=float(cone_cos),
                phase=float(math.atan2(position[1], position[0])),
                guard_epsilon=float(guard_epsilon_m),
                confidence_floor=float(confidence_floor),
                sheet=1,
                orientation=0,
                compatibility_mask=_source_relation_mask(int(package.node_type[node])),
                lineage_seed=stable_u32(str(int(package.node_id[node])), namespace="ugts-g64-lineage"),
            )
        )

    output_prefix = Path(output_prefix)
    output_prefix.parent.mkdir(parents=True, exist_ok=True)
    g64_path = output_prefix.with_suffix(".g64.bin")
    g32_path = output_prefix.with_suffix(".g32.bin")
    exchange_path = output_prefix.with_suffix(".exchange.json")
    manifest_path = output_prefix.with_suffix(".manifest.json")
    with open(g64_path, "wb") as fh:
        for state in states:
            fh.write(pack_g64(state))
    g32_scalars: list[tuple[float, ...]] = []
    with open(g32_path, "wb") as fh:
        for state in states:
            payload = pack_g32(state)
            fh.write(payload)
            g32_scalars.append(unpack_g32_scalars(payload))

    max_position_error = 0.0
    max_scalar_error = 0.0
    for state, decoded in zip(states, g32_scalars):
        position_error = math.sqrt(
            sum((state.position[index] - decoded[index]) ** 2 for index in range(3))
        )
        max_position_error = max(max_position_error, position_error)
        reference = (
            *state.position,
            state.time,
            *state.axis,
            state.radius,
            state.cone_cos,
            state.phase,
            state.guard_epsilon,
            state.confidence_floor,
        )
        max_scalar_error = max(
            max_scalar_error,
            max(abs(float(a) - float(b)) for a, b in zip(reference, decoded)),
        )

    exchange = {
        "schema": "UGTS-GN-1.1",
        "profile": "G64_E32",
        "encoder_variant": "standard",
        "query": {
            "target_sheet": 1,
            "target_orientation": 0,
            "mode_bit": int(mode_bit),
            "commit": False,
            "precision": "float32",
        },
        "candidates": [asdict(state) for state in states],
        "metadata": {
            "source_graph_schema_hash": package.schema_hash,
            "origin_latitude": latitude,
            "origin_longitude": longitude,
            "origin_elevation_m": float(origin_elevation_m),
            "source_index": source_index,
            "time_origin_absolute": time_origin,
            "time_coordinate_convention": "query-local seconds; state.time=absolute_time-time_origin",
            "candidate_indices": [int(value) for value in candidates.tolist()],
            "candidate_node_types": [NODE_TYPE_NAMES[int(package.node_type[value])] for value in candidates],
            "relation_name": RELATION_TYPE_NAMES.get(mode_bit, str(mode_bit)),
            "binary_g64": g64_path.name,
            "binary_g32": g32_path.name,
        },
    }
    # JSON schema calls positions arrays, while dataclasses serialize tuples;
    # tuples are emitted as JSON arrays by the standard encoder.
    write_json(exchange_path, exchange)
    manifest = {
        "format": "UGTS-SPATIAL-BRIDGE-1",
        "candidate_count": len(states),
        "g64_bytes": g64_path.stat().st_size,
        "g32_bytes": g32_path.stat().st_size,
        "g64_sha256": sha256_file(g64_path),
        "g32_sha256": sha256_file(g32_path),
        "exchange_sha256": sha256_file(exchange_path),
        "g32_max_position_error_m": max_position_error,
        "g32_max_scalar_absolute_error": max_scalar_error,
        "declared_guard_epsilon_m": guard_epsilon_m,
        "g32_precision_within_guard": bool(max_position_error <= guard_epsilon_m),
        "portable_contract": "SPIR-V/shader source plus ABI; driver caches remain vendor-specific",
    }
    write_json(manifest_path, manifest)
    return {
        **manifest,
        "paths": {
            "g64": str(g64_path),
            "g32": str(g32_path),
            "exchange": str(exchange_path),
            "manifest": str(manifest_path),
        },
    }
