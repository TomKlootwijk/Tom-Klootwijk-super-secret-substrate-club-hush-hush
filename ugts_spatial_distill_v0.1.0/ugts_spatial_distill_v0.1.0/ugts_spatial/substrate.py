"""UGTS query-first gate over distilled graph embeddings.

The GNN proposes semantic compatibility. Committed records still pass explicit
support, ontology compatibility and a deterministic geometric guard. The output
is an append-only novelty/event log, not a padded frame.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
import time
from typing import Any, Iterable

import numpy as np
import torch

from .graph import SparseTemporalGraph
from .ids import lineage_update, u32_hex, u64_hex
from .ontology import Ontology
from .spatial import LocalFrame, SpatialIndexer, cone_sphere_support, haversine_m
from .tensor_data import graph_to_tensors
from .training import load_checkpoint


@dataclass(frozen=True)
class SpatialQuery:
    source_index: int
    relation_id: int
    radius_m: float = 10_000.0
    cone_axis_enu: tuple[float, float, float] = (0.0, 1.0, 0.0)
    cone_cos: float = -1.0
    epsilon_m: float = 1.0
    semantic_threshold: float = 0.5
    query_time: float = 0.0
    max_results: int = 256
    broad_phase: bool = True


@dataclass(frozen=True)
class VerifiedRelationEvent:
    sequence: int
    source_index: int
    target_index: int
    source_id: str
    target_id: str
    relation_id: int
    relation: str
    distance_m: float
    cos_to_axis: float
    sdf_m: float
    guard_m: float
    semantic_probability: float
    support: bool
    compatible: bool
    guard_pass: bool
    verified: bool
    route: int
    parent_lineage: str
    lineage: str
    query_time: float
    source_text: str
    target_text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite_spatial_mask(graph: SparseTemporalGraph) -> np.ndarray:
    return np.isfinite(graph.node_coords).all(axis=1) & (np.abs(graph.node_coords[:, 0]) <= 90.0) & (np.abs(graph.node_coords[:, 1]) <= 180.0)


def _candidate_indices(
    graph: SparseTemporalGraph,
    ontology: Ontology,
    query: SpatialQuery,
    indexer: SpatialIndexer,
) -> np.ndarray:
    relation = ontology.rel_by_id[query.relation_id]
    allowed_type = np.isin(graph.node_types, np.asarray(relation.target_types, dtype=graph.node_types.dtype))
    allowed_type[query.source_index] = False
    source_coord = graph.node_coords[query.source_index]
    spatial_guard = relation.guard in {"distance", "inside", "boundary", "event"}
    if query.broad_phase and spatial_guard:
        spatial = _finite_spatial_mask(graph)
        pool = np.flatnonzero(allowed_type & spatial)
        if not len(pool):
            return pool
        cells, buckets_local = indexer.build_buckets(graph.node_coords[pool, :2])
        # buckets use local pool offsets; convert back to graph indices.
        buckets = {k: pool[v] for k, v in buckets_local.items()}
        candidates = indexer.candidates(float(source_coord[0]), float(source_coord[1]), query.radius_m + max(0.0, query.epsilon_m), cells, buckets)
        return candidates[allowed_type[candidates]]
    return np.flatnonzero(allowed_type)


def run_spatial_query(
    graph: SparseTemporalGraph,
    ontology: Ontology,
    model: torch.nn.Module,
    query: SpatialQuery,
    device: str | torch.device = "cpu",
    indexer: SpatialIndexer | None = None,
) -> list[VerifiedRelationEvent]:
    if not 0 <= query.source_index < graph.num_nodes:
        raise IndexError("source_index out of range")
    if query.radius_m <= 0.0:
        raise ValueError("radius_m must be positive")
    if not -1.0 <= query.cone_cos <= 1.0:
        raise ValueError("cone_cos must be in [-1,1]")
    relation = ontology.rel_by_id[query.relation_id]
    source_type = int(graph.node_types[query.source_index])
    if source_type not in relation.source_types:
        raise ValueError(f"source node type is invalid for relation {relation.name}")

    device = torch.device(device)
    indexer = indexer or SpatialIndexer(prefer_h3=True)
    candidates = _candidate_indices(graph, ontology, query, indexer)
    if candidates.size == 0:
        return []
    batch = graph_to_tensors(graph, device)
    model = model.to(device)
    model.eval()
    with torch.no_grad():
        h, _ = model.encode(
            batch["node_features"], batch["node_type"], batch["edge_src"], batch["edge_dst"],
            batch["edge_type"], batch["edge_time"], batch["edge_weight"], batch["event_entity"],
            batch["event_type"], batch["event_time"], batch["event_value"], query.query_time,
        )

    source_coord = graph.node_coords[query.source_index]
    frame = LocalFrame(float(source_coord[0]), float(source_coord[1]), float(source_coord[2]))
    distances = np.asarray([
        haversine_m(float(source_coord[0]), float(source_coord[1]), float(graph.node_coords[i, 0]), float(graph.node_coords[i, 1]))
        for i in candidates
    ], dtype=np.float32)
    src_tensor = torch.full((len(candidates),), query.source_index, device=device, dtype=torch.long)
    dst_tensor = torch.as_tensor(candidates, device=device, dtype=torch.long)
    rel_tensor = torch.full((len(candidates),), query.relation_id, device=device, dtype=torch.long)
    distance_tensor = torch.as_tensor(distances, device=device, dtype=torch.float32)
    time_tensor = torch.full((len(candidates),), float(query.query_time), device=device, dtype=torch.float32)
    with torch.no_grad():
        logits = model.decode_links(h, src_tensor, dst_tensor, rel_tensor, distance_tensor, time_tensor, query.query_time)
        probabilities = torch.sigmoid(logits.float()).cpu().numpy()

    parent_lineage = int(graph.lineage_seed[query.source_index])
    records: list[VerifiedRelationEvent] = []
    for target, distance, probability in zip(candidates.tolist(), distances.tolist(), probabilities.tolist()):
        target_type = int(graph.node_types[target])
        compatible = ontology.compatible(query.relation_id, source_type, target_type)
        spatial_guard = relation.guard in {"distance", "inside", "boundary", "event"}
        if spatial_guard:
            point = frame.to_enu(*map(float, graph.node_coords[target]))
            guard_mode = "boundary" if relation.guard == "boundary" else "inside"
            support = cone_sphere_support(point, query.cone_axis_enu, query.radius_m, query.cone_cos, query.epsilon_m, guard_mode)
            in_support = support.in_support
            guard_pass = support.guard_pass
            sdf_m = support.sdf_m
            guard_m = support.guard_m
            cos_to_axis = support.cos_to_axis
        else:
            in_support = True
            guard_pass = True
            sdf_m = 0.0
            guard_m = 0.0
            cos_to_axis = 1.0
        verified = bool(in_support and compatible and guard_pass and probability >= query.semantic_threshold)
        route = (relation.mode_bit ^ ontology.node_by_id[source_type].sheet ^ ontology.node_by_id[target_type].sheet) & 0x3
        payload = {
            "target_id": int(graph.node_ids[target]),
            "relation": query.relation_id,
            "distance_m": round(float(distance), 4),
            "semantic_probability": round(float(probability), 7),
            "verified": verified,
            "route": route,
            "query_time": float(query.query_time),
        }
        lineage = lineage_update(parent_lineage, int(graph.node_ids[query.source_index]), len(records), query.relation_id, payload)
        records.append(VerifiedRelationEvent(
            sequence=len(records),
            source_index=query.source_index,
            target_index=target,
            source_id=u64_hex(int(graph.node_ids[query.source_index])),
            target_id=u64_hex(int(graph.node_ids[target])),
            relation_id=query.relation_id,
            relation=relation.name,
            distance_m=float(distance),
            cos_to_axis=float(cos_to_axis),
            sdf_m=float(sdf_m),
            guard_m=float(guard_m),
            semantic_probability=float(probability),
            support=bool(in_support),
            compatible=bool(compatible),
            guard_pass=bool(guard_pass),
            verified=verified,
            route=route,
            parent_lineage=u32_hex(parent_lineage),
            lineage=u32_hex(lineage),
            query_time=float(query.query_time),
            source_text=graph.texts[query.source_index],
            target_text=graph.texts[target],
        ))
    records.sort(key=lambda x: (-int(x.verified), -x.semantic_probability, x.distance_m, x.target_index))
    return records[: query.max_results]


def append_verified_novelty(path: str | Path, events: Iterable[VerifiedRelationEvent], *, checkpoint_sha256: str | None = None) -> int:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("a", encoding="utf-8", newline="\n") as f:
        for event in events:
            if not event.verified:
                continue
            record = {
                "format": "UGTS-SPATIAL-NOVELTY-1",
                "written_unix": time.time(),
                "checkpoint_sha256": checkpoint_sha256,
                **event.to_dict(),
            }
            f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def query_from_checkpoint(
    graph_dir: str | Path,
    ontology_path: str | Path,
    checkpoint_path: str | Path,
    query: SpatialQuery,
    device: str = "auto",
) -> list[VerifiedRelationEvent]:
    chosen = "cuda" if device == "auto" and torch.cuda.is_available() else ("cpu" if device == "auto" else device)
    graph = SparseTemporalGraph.load(graph_dir, mmap=False, verify_hashes=True)
    ontology = Ontology.load(ontology_path)
    model, _ = load_checkpoint(checkpoint_path, chosen)
    return run_spatial_query(graph, ontology, model, query, chosen)
