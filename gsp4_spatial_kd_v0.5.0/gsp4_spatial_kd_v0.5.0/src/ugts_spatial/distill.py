from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .embeddings import Embedder
from .geocell import haversine_m
from .graph import GraphPackage
from .schema import (
    NODE_TYPE_NAMES,
    RELATION_SPECS,
    RELATION_TYPE_NAMES,
    NodeType,
    allowed_relations_for_types,
    relation_is_type_compatible,
)
from .spatial import pair_edge_attr_numpy
from .teacher import RelationCandidate, TeacherLabel
from .utils import stable_u64


def embed_graph(
    package: GraphPackage,
    embedder: Embedder,
    *,
    node_types: Sequence[int | NodeType] | None = None,
) -> GraphPackage:
    """Attach a reusable offline teacher cache to a graph package."""
    mask = np.ones(package.num_nodes, dtype=np.bool_)
    if node_types is not None:
        allowed = np.asarray([int(value) for value in node_types], dtype=np.int64)
        mask = np.isin(package.node_type, allowed)
    selected_texts = [package.texts[index] for index in np.flatnonzero(mask)]
    encoded = embedder.encode(selected_texts)
    if encoded.ndim != 2 or encoded.shape[0] != len(selected_texts):
        raise ValueError("embedder returned an invalid matrix")
    dimensions = encoded.shape[1] if encoded.ndim == 2 else 0
    full = np.zeros((package.num_nodes, dimensions), dtype=np.float32)
    if selected_texts:
        full[mask] = encoded
    return package.with_teacher_embeddings(
        full,
        mask,
        teacher_metadata={
            "backend": getattr(embedder, "name", type(embedder).__name__),
            "dimensions": dimensions,
            "selected_rows": int(np.count_nonzero(mask)),
            "role": "offline teacher embeddings distilled into the HGT/TGN student",
        },
    )


def _allowed_relation_names(source_type: int, target_type: int) -> tuple[str, ...]:
    return tuple(
        RELATION_TYPE_NAMES[relation]
        for relation in allowed_relations_for_types(
            source_type, target_type, semantic_teacher_only=True
        )
    )


def _candidate(
    package: GraphPackage,
    source: int,
    target: int,
    *,
    family: str,
    distance_m: float | None,
) -> RelationCandidate | None:
    allowed = _allowed_relation_names(
        int(package.node_type[source]), int(package.node_type[target])
    )
    if not allowed:
        return None
    source_id = int(package.node_id[source])
    target_id = int(package.node_id[target])
    candidate_id = (
        f"c-{stable_u64(f'{source_id}:{target_id}:{family}', namespace='ugts-teacher-candidate'):016x}"
    )
    return RelationCandidate(
        candidate_id=candidate_id,
        source_index=source,
        target_index=target,
        source_id=source_id,
        target_id=target_id,
        source_type=NODE_TYPE_NAMES[int(package.node_type[source])],
        target_type=NODE_TYPE_NAMES[int(package.node_type[target])],
        source_text=package.texts[source],
        target_text=package.texts[target],
        distance_m=distance_m,
        allowed_relations=allowed,
        deterministic_fields={
            "same_cell": bool(package.cell_id[source] == package.cell_id[target]),
            "source_time": float(package.node_time[source]),
            "target_time": float(package.node_time[target]),
            "geometry_must_be_verified": distance_m is not None,
            "teacher_is_not_event_authority": True,
        },
    )


def generate_relation_candidates(
    package: GraphPackage,
    *,
    max_distance_m: float = 5_000.0,
    concepts_per_source: int = 8,
    spatial_per_source: int = 4,
    max_candidates: int = 20_000,
) -> list[RelationCandidate]:
    """Generate a bounded teacher set without padding or all-pairs export."""
    if max_distance_m <= 0:
        raise ValueError("max_distance_m must be positive")
    concept_indices = np.flatnonzero(package.node_type == int(NodeType.CONCEPT))
    spatial_indices = np.flatnonzero(
        np.isin(
            package.node_type,
            np.asarray(
                [
                    int(NodeType.SPATIAL_ENTITY),
                    int(NodeType.SENSOR),
                    int(NodeType.OBSERVATION),
                    int(NodeType.EVENT),
                ],
                dtype=np.int64,
            ),
        )
    )
    candidates: list[RelationCandidate] = []
    for source in spatial_indices.tolist():
        concepts = concept_indices
        if package.teacher_dim > 0 and package.teacher_mask[source] and concepts.size:
            source_vector = package.teacher_x[source]
            scores = package.teacher_x[concepts] @ source_vector
            concepts = concepts[np.argsort(-scores)]
        for target in concepts[: max(0, concepts_per_source)].tolist():
            candidate = _candidate(
                package, source, target, family="ontology", distance_m=None
            )
            if candidate is not None:
                candidates.append(candidate)

        # Bounded pilot implementation. For large graphs, use the geocell
        # index and sample candidate neighborhoods rather than this loop.
        distances: list[tuple[float, int]] = []
        for target in spatial_indices.tolist():
            if target == source:
                continue
            distance = haversine_m(
                float(package.latitude[source]),
                float(package.longitude[source]),
                float(package.latitude[target]),
                float(package.longitude[target]),
            )
            if distance <= max_distance_m:
                distances.append((distance, target))
        for distance, target in sorted(distances)[: max(0, spatial_per_source)]:
            candidate = _candidate(
                package, source, target, family="spatial", distance_m=float(distance)
            )
            if candidate is not None:
                candidates.append(candidate)
        if max_candidates > 0 and len(candidates) >= max_candidates:
            return candidates[:max_candidates]
    return candidates


def write_relation_candidates(
    path: str | Path, candidates: Iterable[RelationCandidate]
) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for candidate in candidates:
            fh.write(json.dumps(asdict(candidate), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_relation_candidates(path: str | Path) -> list[RelationCandidate]:
    result: list[RelationCandidate] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                result.append(RelationCandidate.from_dict(json.loads(line)))
    return result


def merge_teacher_labels(
    package: GraphPackage,
    candidates: Sequence[RelationCandidate],
    labels: Sequence[TeacherLabel],
    *,
    minimum_confidence: float = 0.70,
) -> GraphPackage:
    """Merge semantic labels as weighted training edges.

    This operation does not create verified UGTS events. Geometry and guarded
    transition relations remain subject to the runtime deterministic gate.
    """
    candidate_map = {candidate.candidate_id: candidate for candidate in candidates}
    relation_lookup = {name: relation for relation, name in RELATION_TYPE_NAMES.items()}
    id_to_index = package.node_index_by_id()
    existing = {
        (int(src), int(dst), int(rel))
        for src, dst, rel in zip(
            package.edge_index[0].tolist(),
            package.edge_index[1].tolist(),
            package.edge_type.tolist(),
        )
    }
    appended: list[tuple[int, int, int, float, float]] = []
    accepted_models: set[str] = set()
    for label in labels:
        if label.abstain or label.confidence < minimum_confidence:
            continue
        candidate = candidate_map.get(label.candidate_id)
        if candidate is None:
            raise ValueError(f"label references unknown candidate {label.candidate_id}")
        if label.source_id != candidate.source_id or label.target_id != candidate.target_id:
            raise ValueError("teacher label/candidate node IDs differ")
        if label.relation not in relation_lookup:
            raise ValueError(f"unknown relation name in teacher label: {label.relation}")
        relation = int(relation_lookup[label.relation])
        spec = RELATION_SPECS[relation]
        if not spec.semantic_teacher_allowed:
            raise ValueError(f"relation {label.relation} cannot be committed by a semantic teacher")
        if candidate.source_id not in id_to_index or candidate.target_id not in id_to_index:
            raise ValueError("teacher candidate refers to a node not present in the graph")
        source = id_to_index[candidate.source_id]
        target = id_to_index[candidate.target_id]
        key = (source, target, relation)
        if key in existing:
            continue
        if not relation_is_type_compatible(
            relation, int(package.node_type[source]), int(package.node_type[target])
        ):
            raise ValueError("teacher label violates ontology type compatibility")
        timestamp = max(float(package.node_time[source]), float(package.node_time[target]))
        appended.append((source, target, relation, timestamp, label.confidence))
        existing.add(key)
        accepted_models.add(label.teacher_model)
    if not appended:
        return package

    extra_index = np.asarray(
        [[row[0] for row in appended], [row[1] for row in appended]], dtype=np.int64
    )
    edge_time = np.asarray([row[3] for row in appended], dtype=np.float64)
    edge_weight = np.asarray([row[4] for row in appended], dtype=np.float32)
    edge_attr = pair_edge_attr_numpy(
        package.latitude,
        package.longitude,
        package.elevation,
        package.node_time,
        extra_index,
    )
    return package.append_edges(
        extra_index,
        np.asarray([row[2] for row in appended], dtype=np.int64),
        edge_time=edge_time,
        edge_weight=edge_weight,
        edge_attr=edge_attr,
        metadata_patch={
            "teacher_relation_distillation": {
                "accepted_edges": len(appended),
                "minimum_confidence": minimum_confidence,
                "teacher_models": sorted(accepted_models),
                "authority": (
                    "semantic supervision only; exact support, compatibility and guard "
                    "remain authoritative"
                ),
            }
        },
        deduplicate=True,
    )
