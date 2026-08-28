from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Iterable
import zipfile

import numpy as np
import torch

from .graph import GraphPackage
from .schema import RELATION_TYPE_NAMES, RelationType, relation_is_type_compatible
from .utils import canonical_json, sha256_bytes


@dataclass
class TeacherEdgeSet:
    """Sparse edge probabilities supplied by ULTRA, an LLM teacher or rules."""

    source: np.ndarray
    target: np.ndarray
    relation: np.ndarray
    probability: np.ndarray
    weight: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    FORMAT = "UGTE1"

    def __post_init__(self) -> None:
        self.source = np.asarray(self.source, dtype=np.int64)
        self.target = np.asarray(self.target, dtype=np.int64)
        self.relation = np.asarray(self.relation, dtype=np.int64)
        self.probability = np.asarray(self.probability, dtype=np.float32)
        if self.weight is None:
            self.weight = np.ones(self.source.shape[0], dtype=np.float32)
        else:
            self.weight = np.asarray(self.weight, dtype=np.float32)
        self.metadata = dict(self.metadata)
        self.validate()

    @property
    def size(self) -> int:
        return int(self.source.shape[0])

    def validate(self, graph: GraphPackage | None = None) -> None:
        n = self.source.shape[0]
        for name, value in {
            "target": self.target,
            "relation": self.relation,
            "probability": self.probability,
            "weight": self.weight,
        }.items():
            if value.shape != (n,):
                raise ValueError(f"{name} must have shape [{n}]")
        if n and (self.source.min() < 0 or self.target.min() < 0 or self.relation.min() < 0):
            raise ValueError("teacher edge indices and relation IDs must be nonnegative")
        if not np.isfinite(self.probability).all() or not np.isfinite(self.weight).all():
            raise ValueError("teacher edge values must be finite")
        if not ((self.probability >= 0.0) & (self.probability <= 1.0)).all():
            raise ValueError("teacher probabilities must be in [0,1]")
        if not (self.weight >= 0.0).all():
            raise ValueError("teacher weights must be nonnegative")
        if graph is not None:
            if n and (self.source.max() >= graph.num_nodes or self.target.max() >= graph.num_nodes):
                raise ValueError("teacher edge references an out-of-range graph node")
            if n and self.relation.max() >= graph.num_relations:
                raise ValueError("teacher edge relation exceeds the graph relation vocabulary")
            for source, target, relation in zip(
                self.source.tolist(), self.target.tolist(), self.relation.tolist()
            ):
                if not relation_is_type_compatible(
                    int(relation), int(graph.node_type[source]), int(graph.node_type[target])
                ):
                    raise ValueError(
                        f"teacher edge is type-incompatible: source={source} relation={relation} target={target}"
                    )
            expected = self.metadata.get("graph_schema_hash")
            if expected and expected != graph.schema_hash:
                raise ValueError("teacher edge set and graph schema hashes differ")

    def to_torch(self, device: str | torch.device) -> dict[str, torch.Tensor]:
        selected = torch.device(device)
        return {
            "edge_index": torch.as_tensor(
                np.stack((self.source, self.target), axis=0), device=selected
            ),
            "edge_type": torch.as_tensor(self.relation, device=selected),
            "probability": torch.as_tensor(self.probability, device=selected),
            "weight": torch.as_tensor(self.weight, device=selected),
        }

    def summary(self) -> dict[str, Any]:
        relation_counts = {
            RELATION_TYPE_NAMES.get(int(relation), str(int(relation))): int(
                np.count_nonzero(self.relation == relation)
            )
            for relation in np.unique(self.relation)
        }
        return {
            "format": self.FORMAT,
            "edges": self.size,
            "positive_mean": float(self.probability.mean()) if self.size else float("nan"),
            "relations": relation_counts,
            "metadata": self.metadata,
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays_io = BytesIO()
        np.savez_compressed(
            arrays_io,
            source=self.source,
            target=self.target,
            relation=self.relation,
            probability=self.probability,
            weight=self.weight,
        )
        arrays_bytes = arrays_io.getvalue()
        metadata = {
            **self.metadata,
            "format": self.FORMAT,
            "size": self.size,
            "arrays_sha256": sha256_bytes(arrays_bytes),
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.writestr(
                "metadata.json",
                json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            )
            archive.writestr("arrays.npz", arrays_bytes, compress_type=zipfile.ZIP_STORED)

    @classmethod
    def load(cls, path: str | Path, *, graph: GraphPackage | None = None) -> "TeacherEdgeSet":
        with zipfile.ZipFile(path, "r") as archive:
            metadata = json.loads(archive.read("metadata.json").decode("utf-8"))
            if metadata.get("format") != cls.FORMAT:
                raise ValueError("unsupported teacher edge format")
            arrays_bytes = archive.read("arrays.npz")
            if metadata.get("arrays_sha256") != sha256_bytes(arrays_bytes):
                raise ValueError("teacher edge array hash mismatch")
            with np.load(BytesIO(arrays_bytes), allow_pickle=False) as arrays:
                values = {name: arrays[name] for name in arrays.files}
        for key in ("format", "size", "arrays_sha256"):
            metadata.pop(key, None)
        result = cls(metadata=metadata, **values)
        result.validate(graph)
        return result


def export_ultra_triples(graph: GraphPackage, directory: str | Path) -> dict[str, Any]:
    """Export graph triples in the simple text layout used by many KG tools.

    Each row is: source-entity<TAB>relation<TAB>target-entity. Entity names are
    stable unsigned node IDs, so ULTRA output can be imported without relying on
    row ordering.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    handles = {
        0: open(directory / "train.txt", "w", encoding="utf-8", newline="\n"),
        1: open(directory / "valid.txt", "w", encoding="utf-8", newline="\n"),
        2: open(directory / "test.txt", "w", encoding="utf-8", newline="\n"),
    }
    counts = {0: 0, 1: 0, 2: 0}
    try:
        for edge_position in range(graph.num_edges):
            source_index = int(graph.edge_index[0, edge_position])
            target_index = int(graph.edge_index[1, edge_position])
            split = max(int(graph.split[source_index]), int(graph.split[target_index]))
            relation = int(graph.edge_type[edge_position])
            handles[split].write(
                f"{int(graph.node_id[source_index])}\t{RELATION_TYPE_NAMES.get(relation, str(relation))}\t"
                f"{int(graph.node_id[target_index])}\n"
            )
            counts[split] += 1
    finally:
        for handle in handles.values():
            handle.close()
    manifest = {
        "format": "UGTS-ULTRA-EXPORT-1",
        "graph_schema_hash": graph.schema_hash,
        "entities": graph.num_nodes,
        "relations": len(RELATION_TYPE_NAMES),
        "triples": {
            "train": counts[0],
            "valid": counts[1],
            "test": counts[2],
        },
        "relation_dictionary": {str(key): value for key, value in RELATION_TYPE_NAMES.items()},
        "score_import_format": "source_id<TAB>relation_name_or_id<TAB>target_id<TAB>probability[<TAB>weight]",
    }
    (directory / "ugts_ultra_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def import_scored_triples(
    graph: GraphPackage,
    path: str | Path,
    *,
    teacher_name: str = "ULTRA-or-external-KG-teacher",
) -> TeacherEdgeSet:
    id_to_index = graph.node_index_by_id()
    relation_by_name = {name: relation for relation, name in RELATION_TYPE_NAMES.items()}
    source: list[int] = []
    target: list[int] = []
    relation: list[int] = []
    probability: list[float] = []
    weight: list[float] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            columns = line.rstrip("\n\r").split("\t")
            if len(columns) not in (4, 5):
                raise ValueError(f"score line {line_number} must have 4 or 5 tab-separated columns")
            source_id = int(columns[0], 0)
            target_id = int(columns[2], 0)
            if source_id not in id_to_index or target_id not in id_to_index:
                raise ValueError(f"score line {line_number} refers to an unknown node ID")
            relation_text = columns[1].strip().lower()
            if relation_text in relation_by_name:
                relation_id = int(relation_by_name[relation_text])
            else:
                relation_id = int(relation_text, 0)
            score = float(columns[3])
            if not 0.0 <= score <= 1.0:
                raise ValueError(f"score line {line_number} probability is outside [0,1]")
            source.append(id_to_index[source_id])
            target.append(id_to_index[target_id])
            relation.append(relation_id)
            probability.append(score)
            weight.append(float(columns[4]) if len(columns) == 5 else 1.0)
    return TeacherEdgeSet(
        source=np.asarray(source, dtype=np.int64),
        target=np.asarray(target, dtype=np.int64),
        relation=np.asarray(relation, dtype=np.int64),
        probability=np.asarray(probability, dtype=np.float32),
        weight=np.asarray(weight, dtype=np.float32),
        metadata={
            "graph_schema_hash": graph.schema_hash,
            "teacher": teacher_name,
            "source_file": str(path),
        },
    )


def teacher_edges_from_labels(
    graph: GraphPackage,
    labels: Iterable[dict[str, Any]],
    *,
    teacher_name: str,
) -> TeacherEdgeSet:
    id_to_index = graph.node_index_by_id()
    relation_by_name = {name: relation for relation, name in RELATION_TYPE_NAMES.items()}
    rows: list[tuple[int, int, int, float, float]] = []
    for label in labels:
        if bool(label.get("abstain", False)):
            continue
        relation_name = str(label["relation"]).strip().lower()
        if relation_name not in relation_by_name:
            raise ValueError(f"unknown relation in teacher label: {relation_name}")
        source_id = int(label["source_id"])
        target_id = int(label["target_id"])
        if source_id not in id_to_index or target_id not in id_to_index:
            raise ValueError("teacher label refers to an unknown node ID")
        confidence = float(label.get("confidence", 1.0))
        rows.append(
            (
                id_to_index[source_id],
                id_to_index[target_id],
                int(relation_by_name[relation_name]),
                confidence,
                float(label.get("weight", 1.0)),
            )
        )
    if not rows:
        arrays = [np.zeros(0, dtype=np.int64) for _ in range(3)]
        return TeacherEdgeSet(
            source=arrays[0],
            target=arrays[1],
            relation=arrays[2],
            probability=np.zeros(0, dtype=np.float32),
            weight=np.zeros(0, dtype=np.float32),
            metadata={"graph_schema_hash": graph.schema_hash, "teacher": teacher_name},
        )
    array = np.asarray(rows, dtype=np.float64)
    return TeacherEdgeSet(
        source=array[:, 0].astype(np.int64),
        target=array[:, 1].astype(np.int64),
        relation=array[:, 2].astype(np.int64),
        probability=array[:, 3].astype(np.float32),
        weight=array[:, 4].astype(np.float32),
        metadata={"graph_schema_hash": graph.schema_hash, "teacher": teacher_name},
    )


def merge_teacher_edge_set(
    graph: GraphPackage,
    teacher_edges: TeacherEdgeSet,
    *,
    minimum_probability: float = 0.70,
) -> GraphPackage:
    """Merge confident structural-teacher scores as weighted training edges.

    The merge never creates a verified event and rejects relations whose schema
    explicitly forbids semantic-teacher commitment.
    """
    from .schema import RELATION_SPECS, relation_is_type_compatible
    from .spatial import pair_edge_attr_numpy

    if not 0.0 <= minimum_probability <= 1.0:
        raise ValueError("minimum_probability must be in [0,1]")
    teacher_edges.validate(graph)
    existing = {
        (int(source), int(target), int(relation))
        for source, target, relation in zip(
            graph.edge_index[0].tolist(),
            graph.edge_index[1].tolist(),
            graph.edge_type.tolist(),
        )
    }
    rows: list[tuple[int, int, int, float, float]] = []
    for position in range(teacher_edges.size):
        probability = float(teacher_edges.probability[position])
        if probability < minimum_probability:
            continue
        source = int(teacher_edges.source[position])
        target = int(teacher_edges.target[position])
        relation = int(teacher_edges.relation[position])
        spec = RELATION_SPECS.get(relation)
        if spec is None or not spec.semantic_teacher_allowed:
            continue
        if not relation_is_type_compatible(
            relation, int(graph.node_type[source]), int(graph.node_type[target])
        ):
            continue
        key = (source, target, relation)
        if key in existing:
            continue
        timestamp = max(float(graph.node_time[source]), float(graph.node_time[target]))
        weight = probability * float(teacher_edges.weight[position])
        rows.append((source, target, relation, timestamp, weight))
        existing.add(key)
    if not rows:
        return graph
    edge_index = np.asarray(
        [[row[0] for row in rows], [row[1] for row in rows]], dtype=np.int64
    )
    edge_attr = pair_edge_attr_numpy(
        graph.latitude,
        graph.longitude,
        graph.elevation,
        graph.node_time,
        edge_index,
    )
    return graph.append_edges(
        edge_index,
        np.asarray([row[2] for row in rows], dtype=np.int64),
        edge_time=np.asarray([row[3] for row in rows], dtype=np.float64),
        edge_weight=np.asarray([row[4] for row in rows], dtype=np.float32),
        edge_attr=edge_attr,
        metadata_patch={
            "structural_teacher_merge": {
                "teacher": teacher_edges.metadata.get("teacher", "external"),
                "minimum_probability": minimum_probability,
                "accepted_edges": len(rows),
                "authority": "training supervision only; no verified events committed",
            }
        },
    )
