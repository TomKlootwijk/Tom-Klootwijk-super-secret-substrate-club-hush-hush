from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import time
from typing import Any

import numpy as np
import torch

from .geocell import EARTH_RADIUS_M, make_spatial_index
from .graph import GraphPackage
from .model import UGTSSpatialModel
from .novelty import NoveltyLog
from .schema import (
    RELATION_SPECS,
    RELATION_TYPE_NAMES,
    RelationType,
    relation_is_type_compatible,
)
from .spatial import candidate_edge_attr_from_origin
from .utils import stable_u64, torch_device, write_json


@dataclass(frozen=True)
class QueryConfig:
    """One query-first UGTS relation/event request.

    The GNN supplies a calibrated candidate confidence. Geometry, topology
    compatibility and the finite guard remain explicit deterministic gates.
    """

    source_node_id: int
    relation: int = int(RelationType.NEAR)
    radius_m: float = 10_000.0
    bearing_degrees: float | None = None
    half_angle_degrees: float = 180.0
    guard_mode: str = "inside"
    epsilon_m: float = 1.0
    confidence_min: float = 0.50
    max_candidates: int = 100_000
    max_events: int = 1000
    timestamp: float = 0.0
    require_same_sheet: bool = True
    require_same_orientation: bool = True
    precision: str = "float32"

    def validate(self) -> None:
        if self.radius_m <= 0:
            raise ValueError("radius_m must be positive")
        if not 0.0 < self.half_angle_degrees <= 180.0:
            raise ValueError("half_angle_degrees must be in (0,180]")
        if self.guard_mode not in {"inside", "shell"}:
            raise ValueError("guard_mode must be inside or shell")
        if self.epsilon_m < 0:
            raise ValueError("epsilon_m must be nonnegative")
        if not 0.0 <= self.confidence_min <= 1.0:
            raise ValueError("confidence_min must be in [0,1]")
        if self.max_candidates <= 0 or self.max_events <= 0:
            raise ValueError("candidate and event limits must be positive")
        if self.precision not in {"float32", "float16", "bf16"}:
            raise ValueError("precision must be float32, float16 or bf16")
        if int(self.relation) not in RELATION_SPECS:
            raise ValueError(f"unknown relation ID: {self.relation}")


@dataclass
class QueryExecution:
    summary: dict[str, Any]
    events: list[dict[str, Any]]
    timings_ms: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "UGTS-SPATIAL-QUERY-2",
            "summary": self.summary,
            "timings_ms": self.timings_ms,
            "events": self.events,
        }

    def save(self, path: str | Path) -> None:
        write_json(path, self.to_dict())


def relation_from_value(value: str | int) -> int:
    if isinstance(value, int):
        return int(value)
    text = str(value).strip().lower()
    by_name = {name: key for key, name in RELATION_TYPE_NAMES.items()}
    if text in by_name:
        return int(by_name[text])
    return int(text, 0)


def encode_graph(
    graph: GraphPackage,
    model: UGTSSpatialModel,
    device: torch.device,
    *,
    precision: str = "float32",
) -> torch.Tensor:
    tensors = graph.to_torch(device)
    precision = precision.lower()
    if device.type == "cuda" and precision in {"float16", "bf16"}:
        dtype = torch.float16 if precision == "float16" else torch.bfloat16
        with torch.no_grad(), torch.autocast("cuda", dtype=dtype):
            state = model(tensors)["node_state"]
    else:
        with torch.no_grad():
            state = model(tensors)["node_state"]
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    return state


def _geometric_candidates(
    graph: GraphPackage, source_index: int, radius_m: float
) -> np.ndarray:
    spatial = graph.metadata.get("spatial_index", {})
    backend = str(spatial.get("backend", "morton"))
    resolution = int(spatial.get("resolution", 14 if backend == "morton" else 8))
    index = make_spatial_index(backend, resolution)
    source_cell = int(graph.cell_id[source_index])
    if source_cell == 0:
        raise ValueError("source node does not have a spatial cell")
    ring = index.ring_for_radius(
        source_cell, float(graph.latitude[source_index]), radius_m
    )
    allowed_cells = set(index.neighbors(source_cell, ring))
    lookup = graph.cell_lookup()
    rows = [lookup[cell] for cell in allowed_cells if cell in lookup]
    if not rows:
        return np.zeros(0, dtype=np.int64)
    candidates = np.unique(np.concatenate(rows))
    return candidates[candidates != source_index]


def _candidate_indices(
    graph: GraphPackage,
    source_index: int,
    relation: int,
    radius_m: float,
    maximum: int,
) -> np.ndarray:
    spec = RELATION_SPECS[relation]
    source_type = int(graph.node_type[source_index])
    if spec.requires_geometry:
        candidates = _geometric_candidates(graph, source_index, radius_m)
    else:
        candidates = np.arange(graph.num_nodes, dtype=np.int64)
        candidates = candidates[candidates != source_index]
    type_mask = np.fromiter(
        (
            relation_is_type_compatible(
                relation, source_type, int(graph.node_type[target])
            )
            for target in candidates.tolist()
        ),
        dtype=np.bool_,
        count=candidates.size,
    )
    candidates = candidates[type_mask]
    if candidates.size > maximum:
        # Stable ordering makes replay deterministic. For a production graph,
        # hierarchical subgraph sampling should replace this bounded slice.
        candidates = candidates[:maximum]
    return candidates


def _local_enu_torch(
    latitude: torch.Tensor,
    longitude: torch.Tensor,
    elevation: torch.Tensor,
    *,
    origin_latitude: float,
    origin_longitude: float,
    origin_elevation: float,
) -> torch.Tensor:
    latitude_rad = torch.deg2rad(latitude)
    origin_latitude_rad = math.radians(origin_latitude)
    dlat = latitude_rad - origin_latitude_rad
    dlon_degrees = torch.remainder(longitude - origin_longitude + 180.0, 360.0) - 180.0
    dlon = torch.deg2rad(dlon_degrees)
    east = EARTH_RADIUS_M * dlon * math.cos(origin_latitude_rad)
    north = EARTH_RADIUS_M * dlat
    up = elevation - origin_elevation
    return torch.stack((east, north, up), dim=-1)


def _lineage_hash(
    graph: GraphPackage,
    source_index: int,
    target_index: int,
    relation: int,
    timestamp: float,
) -> int:
    payload = (
        f"{graph.schema_hash}:{int(graph.lineage_seed[source_index])}:"
        f"{int(graph.lineage_seed[target_index])}:{relation}:{timestamp:.9f}"
    )
    return stable_u64(payload, namespace="ugts-spatial-lineage")


def execute_query(
    graph: GraphPackage,
    config: QueryConfig,
    *,
    model: UGTSSpatialModel | None = None,
    device: torch.device | str = "cpu",
    encoded_state: torch.Tensor | None = None,
    novelty_log: NoveltyLog | None = None,
) -> QueryExecution:
    config.validate()
    start_total = time.perf_counter()
    try:
        source_index = graph.index_for(int(config.source_node_id))
    except KeyError as exc:
        raise ValueError(str(exc)) from exc
    source_type = int(graph.node_type[source_index])
    relation = int(config.relation)
    relation_spec = RELATION_SPECS[relation]

    candidate_start = time.perf_counter()
    candidate_index_np = _candidate_indices(
        graph,
        source_index,
        relation,
        config.radius_m + config.epsilon_m,
        config.max_candidates,
    )
    candidate_ms = (time.perf_counter() - candidate_start) * 1000.0

    selected_device = device if isinstance(device, torch.device) else torch_device(str(device))
    candidate_indices = torch.as_tensor(
        candidate_index_np, dtype=torch.int64, device=selected_device
    )
    if candidate_indices.numel() == 0:
        return QueryExecution(
            summary={
                "query": asdict(config),
                "source_index": source_index,
                "source_type": source_type,
                "source_text": graph.texts[source_index],
                "relation_name": RELATION_TYPE_NAMES[relation],
                "candidates": 0,
                "supported": 0,
                "compatible": 0,
                "guard_survivors": 0,
                "verified": 0,
                "model_used": model is not None,
                "device": str(selected_device),
            },
            events=[],
            timings_ms={
                "candidate_lookup": candidate_ms,
                "model_encode": 0.0,
                "gate": 0.0,
                "total": (time.perf_counter() - start_total) * 1000.0,
            },
        )

    gate_start = time.perf_counter()
    if relation_spec.requires_geometry:
        latitude = torch.as_tensor(
            graph.latitude[candidate_index_np], dtype=torch.float64, device=selected_device
        )
        longitude = torch.as_tensor(
            graph.longitude[candidate_index_np], dtype=torch.float64, device=selected_device
        )
        elevation = torch.as_tensor(
            graph.elevation[candidate_index_np], dtype=torch.float64, device=selected_device
        )
        enu = _local_enu_torch(
            latitude,
            longitude,
            elevation,
            origin_latitude=float(graph.latitude[source_index]),
            origin_longitude=float(graph.longitude[source_index]),
            origin_elevation=float(graph.elevation[source_index]),
        )
        distance = torch.linalg.vector_norm(enu, dim=-1).float()
        radial_support = distance <= (config.radius_m + config.epsilon_m)
        if config.bearing_degrees is None or config.half_angle_degrees >= 180.0:
            angular_support = torch.ones_like(radial_support)
            cosine_to_axis = torch.ones_like(distance)
        else:
            bearing = math.radians(config.bearing_degrees)
            axis = torch.tensor(
                [math.sin(bearing), math.cos(bearing), 0.0],
                dtype=enu.dtype,
                device=selected_device,
            )
            direction = enu / torch.linalg.vector_norm(enu, dim=-1).clamp_min(1e-6).unsqueeze(-1)
            cosine_to_axis = (direction * axis).sum(dim=-1).float()
            angular_support = cosine_to_axis >= math.cos(
                math.radians(config.half_angle_degrees)
            )
        support = radial_support & angular_support
        sdf = distance - config.radius_m
        if config.guard_mode == "shell":
            guard = torch.abs(sdf) - config.epsilon_m
        else:
            guard = sdf - config.epsilon_m
        guard_survivor = guard <= 0.0
        candidate_attr_np = candidate_edge_attr_from_origin(
            graph.latitude[candidate_index_np],
            graph.longitude[candidate_index_np],
            graph.elevation[candidate_index_np],
            graph.node_time[candidate_index_np],
            origin_latitude=float(graph.latitude[source_index]),
            origin_longitude=float(graph.longitude[source_index]),
            origin_elevation=float(graph.elevation[source_index]),
            origin_time=float(graph.node_time[source_index]),
        )
    else:
        distance = torch.zeros(candidate_indices.numel(), device=selected_device)
        cosine_to_axis = torch.ones_like(distance)
        support = torch.ones_like(distance, dtype=torch.bool)
        sdf = torch.zeros_like(distance)
        guard = torch.zeros_like(distance)
        guard_survivor = torch.ones_like(distance, dtype=torch.bool)
        candidate_attr_np = np.zeros((candidate_index_np.size, 4), dtype=np.float32)

    relation_bit = np.uint16(1 << relation)
    target_types = graph.node_type[candidate_index_np]
    type_compatible_np = np.fromiter(
        (
            relation_is_type_compatible(relation, source_type, int(value))
            for value in target_types.tolist()
        ),
        dtype=np.bool_,
        count=target_types.size,
    )
    mask_compatible_np = (
        (np.uint16(graph.compatibility_mask[source_index]) & relation_bit) != 0
    ) & ((graph.compatibility_mask[candidate_index_np] & relation_bit) != 0)
    sheet_compatible_np = (
        graph.sheet[candidate_index_np] == graph.sheet[source_index]
        if config.require_same_sheet
        else np.ones(candidate_index_np.size, dtype=np.bool_)
    )
    orientation_compatible_np = (
        graph.orientation[candidate_index_np] == graph.orientation[source_index]
        if config.require_same_orientation
        else np.ones(candidate_index_np.size, dtype=np.bool_)
    )
    compatibility_np = (
        type_compatible_np
        & np.asarray(mask_compatible_np, dtype=np.bool_)
        & np.asarray(sheet_compatible_np, dtype=np.bool_)
        & np.asarray(orientation_compatible_np, dtype=np.bool_)
    )
    compatibility = torch.as_tensor(compatibility_np, device=selected_device)

    encode_ms = 0.0
    if model is None:
        confidence = torch.ones_like(distance, dtype=torch.float32)
        logits = torch.full_like(distance, float("inf"), dtype=torch.float32)
    else:
        if encoded_state is None:
            encode_start = time.perf_counter()
            encoded_state = encode_graph(
                graph, model, selected_device, precision=config.precision
            )
            encode_ms = (time.perf_counter() - encode_start) * 1000.0
        source_tensor = torch.full_like(candidate_indices, source_index)
        relation_tensor = torch.full_like(candidate_indices, relation)
        edge_index = torch.stack((source_tensor, candidate_indices), dim=0)
        edge_attr = torch.as_tensor(
            candidate_attr_np, dtype=torch.float32, device=selected_device
        )
        with torch.no_grad():
            logits = model.score_edges(
                encoded_state, edge_index, relation_tensor, edge_attr
            ).float()
            confidence = torch.sigmoid(logits)

    verified = support & compatibility & guard_survivor & (
        confidence >= config.confidence_min
    )
    verified_positions = torch.nonzero(verified, as_tuple=False).flatten()
    if verified_positions.numel() > config.max_events:
        ranked = torch.argsort(confidence[verified_positions], descending=True)
        verified_positions = verified_positions[ranked[: config.max_events]]
    if selected_device.type == "cuda":
        torch.cuda.synchronize(selected_device)
    gate_ms = (time.perf_counter() - gate_start) * 1000.0

    positions_cpu = verified_positions.detach().cpu().numpy().astype(np.int64)
    distance_cpu = distance.detach().cpu().numpy()
    sdf_cpu = sdf.detach().cpu().numpy()
    guard_cpu = guard.detach().cpu().numpy()
    confidence_cpu = confidence.detach().cpu().numpy()
    cosine_cpu = cosine_to_axis.detach().cpu().numpy()
    logits_cpu = logits.detach().cpu().numpy()
    events: list[dict[str, Any]] = []
    for position in positions_cpu.tolist():
        target_index = int(candidate_index_np[position])
        source_node_id = int(graph.node_id[source_index])
        target_node_id = int(graph.node_id[target_index])
        lineage_hash = _lineage_hash(
            graph, source_index, target_index, relation, config.timestamp
        )
        route = int(
            (
                lineage_hash
                ^ int(graph.lineage_seed[source_index])
                ^ int(graph.lineage_seed[target_index])
                ^ relation
            )
            & 0x3
        )
        event = {
            "source_index": source_index,
            "target_index": target_index,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation": relation,
            "relation_name": RELATION_TYPE_NAMES.get(relation, str(relation)),
            "distance_m": float(distance_cpu[position]),
            "cosine_to_axis": float(cosine_cpu[position]),
            "sdf_m": float(sdf_cpu[position]),
            "guard_m": float(guard_cpu[position]),
            "model_logit": float(logits_cpu[position]),
            "confidence": float(confidence_cpu[position]),
            "route": route,
            "lineage_hash": lineage_hash,
            "target_type": int(graph.node_type[target_index]),
            "target_key": graph.keys[target_index],
            "target_text": graph.texts[target_index],
        }
        events.append(event)
        if novelty_log is not None:
            novelty_log.append_verified(
                timestamp=config.timestamp,
                relation=relation,
                source_id=source_node_id,
                target_id=target_node_id,
                value=float(distance_cpu[position]),
                confidence=float(confidence_cpu[position]),
                lineage_hash=lineage_hash,
                flags=route,
            )

    supported = int(support.sum().item())
    compatible = int((support & compatibility).sum().item())
    guard_survivors = int((support & compatibility & guard_survivor).sum().item())
    candidate_count = int(candidate_indices.numel())
    summary = {
        "query": asdict(config),
        "source_index": source_index,
        "source_type": source_type,
        "source_key": graph.keys[source_index],
        "source_text": graph.texts[source_index],
        "relation_name": RELATION_TYPE_NAMES.get(relation, str(relation)),
        "requires_geometry": relation_spec.requires_geometry,
        "requires_guard": relation_spec.requires_guard,
        "candidates": candidate_count,
        "supported": supported,
        "compatible": compatible,
        "guard_survivors": guard_survivors,
        "verified": len(events),
        "support_rejection_gain": float(candidate_count / max(1, supported)),
        "compatibility_rejection_gain": float(supported / max(1, compatible)),
        "event_yield": float(len(events) / max(1, candidate_count)),
        "model_used": model is not None,
        "device": str(selected_device),
        "novelty_committed": novelty_log is not None,
    }
    return QueryExecution(
        summary=summary,
        events=events,
        timings_ms={
            "candidate_lookup": candidate_ms,
            "model_encode": encode_ms,
            "gate": gate_ms,
            "total": (time.perf_counter() - start_total) * 1000.0,
        },
    )
