"""Sparse, variable-length temporal graph storage.

The directory format stores one NumPy array per field, enabling memory mapping and
avoiding padded frame tensors. Text and novelty records are separate appendable
JSONL files. Graph edges and events may have arbitrary lengths.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .ids import stable_u64, stable_u32, u64_hex

FORMAT = "UGTS-SPARSE-TEMPORAL-GRAPH-1"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class SparseTemporalGraph:
    node_ids: np.ndarray
    node_types: np.ndarray
    node_coords: np.ndarray
    node_features: np.ndarray
    lineage_seed: np.ndarray
    texts: list[str]
    edge_src: np.ndarray
    edge_dst: np.ndarray
    edge_type: np.ndarray
    edge_time: np.ndarray
    edge_weight: np.ndarray
    edge_flags: np.ndarray
    event_entity: np.ndarray
    event_time: np.ndarray
    event_type: np.ndarray
    event_value: np.ndarray
    event_flags: np.ndarray
    ex_src: np.ndarray
    ex_dst: np.ndarray
    ex_relation: np.ndarray
    ex_label: np.ndarray
    ex_teacher_prob: np.ndarray
    ex_time: np.ndarray
    ex_distance_m: np.ndarray
    ex_split: np.ndarray
    teacher_embeddings: np.ndarray | None = None
    teacher_mask: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        n = len(self.node_ids)
        if self.node_ids.dtype != np.uint64:
            raise ValueError("node_ids must be uint64")
        if self.node_types.shape != (n,):
            raise ValueError("node_types shape mismatch")
        if self.node_coords.shape != (n, 3):
            raise ValueError("node_coords must be [N,3] lat/lon/alt")
        if self.node_features.ndim != 2 or self.node_features.shape[0] != n:
            raise ValueError("node_features must be [N,F]")
        if self.lineage_seed.shape != (n,):
            raise ValueError("lineage_seed shape mismatch")
        if len(self.texts) != n:
            raise ValueError("texts length mismatch")
        e = len(self.edge_src)
        for name, arr in {
            "edge_dst": self.edge_dst,
            "edge_type": self.edge_type,
            "edge_time": self.edge_time,
            "edge_weight": self.edge_weight,
            "edge_flags": self.edge_flags,
        }.items():
            if len(arr) != e:
                raise ValueError(f"{name} length mismatch")
        if e and (self.edge_src.min() < 0 or self.edge_dst.min() < 0 or self.edge_src.max() >= n or self.edge_dst.max() >= n):
            raise ValueError("edge index out of range")
        m = len(self.event_entity)
        for name, arr in {
            "event_time": self.event_time,
            "event_type": self.event_type,
            "event_value": self.event_value,
            "event_flags": self.event_flags,
        }.items():
            if len(arr) != m:
                raise ValueError(f"{name} length mismatch")
        if self.event_value.shape != (m, 4):
            raise ValueError("event_value must be [M,4]")
        q = len(self.ex_src)
        for name, arr in {
            "ex_dst": self.ex_dst,
            "ex_relation": self.ex_relation,
            "ex_label": self.ex_label,
            "ex_teacher_prob": self.ex_teacher_prob,
            "ex_time": self.ex_time,
            "ex_distance_m": self.ex_distance_m,
            "ex_split": self.ex_split,
        }.items():
            if len(arr) != q:
                raise ValueError(f"{name} length mismatch")
        if self.teacher_embeddings is not None:
            if self.teacher_embeddings.ndim != 2 or self.teacher_embeddings.shape[0] != n:
                raise ValueError("teacher_embeddings must be [N,D]")
            if self.teacher_mask is None or self.teacher_mask.shape != (n,):
                raise ValueError("teacher_mask is required with teacher_embeddings")
        if len(np.unique(self.node_ids)) != n:
            raise ValueError("node ids are not unique")

    @property
    def num_nodes(self) -> int:
        return len(self.node_ids)

    @property
    def num_edges(self) -> int:
        return len(self.edge_src)

    @property
    def num_events(self) -> int:
        return len(self.event_entity)

    @property
    def num_examples(self) -> int:
        return len(self.ex_src)

    @property
    def feature_dim(self) -> int:
        return int(self.node_features.shape[1])

    def save(self, directory: str | Path) -> Path:
        self.validate()
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        arrays: dict[str, np.ndarray] = {
            "node_ids": self.node_ids,
            "node_types": self.node_types,
            "node_coords": self.node_coords,
            "node_features": self.node_features,
            "lineage_seed": self.lineage_seed,
            "edge_src": self.edge_src,
            "edge_dst": self.edge_dst,
            "edge_type": self.edge_type,
            "edge_time": self.edge_time,
            "edge_weight": self.edge_weight,
            "edge_flags": self.edge_flags,
            "event_entity": self.event_entity,
            "event_time": self.event_time,
            "event_type": self.event_type,
            "event_value": self.event_value,
            "event_flags": self.event_flags,
            "ex_src": self.ex_src,
            "ex_dst": self.ex_dst,
            "ex_relation": self.ex_relation,
            "ex_label": self.ex_label,
            "ex_teacher_prob": self.ex_teacher_prob,
            "ex_time": self.ex_time,
            "ex_distance_m": self.ex_distance_m,
            "ex_split": self.ex_split,
        }
        if self.teacher_embeddings is not None:
            arrays["teacher_embeddings"] = self.teacher_embeddings
            arrays["teacher_mask"] = self.teacher_mask.astype(np.bool_, copy=False)
        files: dict[str, dict[str, Any]] = {}
        for name, arr in arrays.items():
            path = root / f"{name}.npy"
            np.save(path, arr, allow_pickle=False)
            files[path.name] = {"sha256": _sha256(path), "shape": list(arr.shape), "dtype": str(arr.dtype)}
        text_path = root / "texts.jsonl"
        with text_path.open("w", encoding="utf-8", newline="\n") as f:
            for node_id, text in zip(self.node_ids, self.texts):
                f.write(json.dumps({"node_id": u64_hex(int(node_id)), "text": text}, ensure_ascii=False) + "\n")
        files[text_path.name] = {"sha256": _sha256(text_path), "records": len(self.texts)}
        manifest = {
            "format": FORMAT,
            "counts": {"nodes": self.num_nodes, "edges": self.num_edges, "events": self.num_events, "examples": self.num_examples},
            "feature_dim": self.feature_dim,
            "teacher_dim": 0 if self.teacher_embeddings is None else int(self.teacher_embeddings.shape[1]),
            "metadata": self.metadata,
            "files": files,
        }
        manifest_path = root / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return root

    @classmethod
    def load(cls, directory: str | Path, mmap: bool = False, verify_hashes: bool = False) -> "SparseTemporalGraph":
        root = Path(directory)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("format") != FORMAT:
            raise ValueError(f"unsupported graph format: {manifest.get('format')}")
        if verify_hashes:
            for name, item in manifest["files"].items():
                if _sha256(root / name) != item["sha256"]:
                    raise ValueError(f"hash mismatch: {name}")
        mode = "r" if mmap else None
        def load(name: str) -> np.ndarray:
            return np.load(root / f"{name}.npy", mmap_mode=mode, allow_pickle=False)
        texts = [json.loads(line)["text"] for line in (root / "texts.jsonl").read_text(encoding="utf-8").splitlines() if line]
        teacher_path = root / "teacher_embeddings.npy"
        graph = cls(
            node_ids=load("node_ids"), node_types=load("node_types"), node_coords=load("node_coords"),
            node_features=load("node_features"), lineage_seed=load("lineage_seed"), texts=texts,
            edge_src=load("edge_src"), edge_dst=load("edge_dst"), edge_type=load("edge_type"),
            edge_time=load("edge_time"), edge_weight=load("edge_weight"), edge_flags=load("edge_flags"),
            event_entity=load("event_entity"), event_time=load("event_time"), event_type=load("event_type"),
            event_value=load("event_value"), event_flags=load("event_flags"),
            ex_src=load("ex_src"), ex_dst=load("ex_dst"), ex_relation=load("ex_relation"),
            ex_label=load("ex_label"), ex_teacher_prob=load("ex_teacher_prob"), ex_time=load("ex_time"),
            ex_distance_m=load("ex_distance_m"), ex_split=load("ex_split"),
            teacher_embeddings=load("teacher_embeddings") if teacher_path.exists() else None,
            teacher_mask=load("teacher_mask") if teacher_path.exists() else None,
            metadata=manifest.get("metadata", {}),
        )
        graph.validate()
        return graph


class GraphBuilder:
    def __init__(self, feature_dim: int = 16):
        self.feature_dim = feature_dim
        self.nodes: list[dict[str, Any]] = []
        self.node_index: dict[int, int] = {}
        self.edges: list[tuple[int, int, int, float, float, int]] = []
        self.events: list[tuple[int, float, int, tuple[float, float, float, float], int]] = []
        self.examples: list[tuple[int, int, int, float, float, float, float, int]] = []
        self.teacher_vectors: dict[int, np.ndarray] = {}
        self.metadata: dict[str, Any] = {}

    def add_node(
        self,
        namespace: str,
        external_id: str | int,
        node_type: int,
        lat: float,
        lon: float,
        alt: float = 0.0,
        features: Iterable[float] | None = None,
        text: str = "",
    ) -> int:
        stable = stable_u64(namespace, external_id)
        if stable in self.node_index:
            return self.node_index[stable]
        feat = np.zeros(self.feature_dim, dtype=np.float32)
        if features is not None:
            values = np.asarray(list(features), dtype=np.float32)
            if values.size > self.feature_dim:
                raise ValueError("too many node features")
            feat[: values.size] = values
        index = len(self.nodes)
        self.node_index[stable] = index
        self.nodes.append({
            "id": stable,
            "type": int(node_type),
            "coord": (float(lat), float(lon), float(alt)),
            "features": feat,
            "lineage": stable_u32(namespace, external_id),
            "text": text,
        })
        return index

    def add_edge(self, src: int, dst: int, relation: int, time: float = 0.0, weight: float = 1.0, flags: int = 0) -> None:
        self.edges.append((int(src), int(dst), int(relation), float(time), float(weight), int(flags)))

    def add_event(self, entity: int, time: float, event_type: int, values: Iterable[float] = (), flags: int = 0) -> None:
        v = list(values)
        if len(v) > 4:
            raise ValueError("at most four event values")
        v.extend([0.0] * (4 - len(v)))
        self.events.append((int(entity), float(time), int(event_type), tuple(float(x) for x in v), int(flags)))

    def add_example(
        self,
        src: int,
        dst: int,
        relation: int,
        label: float,
        teacher_prob: float,
        time: float,
        distance_m: float,
        split: int,
    ) -> None:
        self.examples.append((int(src), int(dst), int(relation), float(label), float(teacher_prob), float(time), float(distance_m), int(split)))

    def set_teacher_vector(self, node: int, vector: np.ndarray) -> None:
        self.teacher_vectors[int(node)] = np.asarray(vector, dtype=np.float32)

    def build(self) -> SparseTemporalGraph:
        n = len(self.nodes)
        if not n:
            raise ValueError("graph has no nodes")
        node_ids = np.asarray([x["id"] for x in self.nodes], dtype=np.uint64)
        node_types = np.asarray([x["type"] for x in self.nodes], dtype=np.int16)
        node_coords = np.asarray([x["coord"] for x in self.nodes], dtype=np.float64)
        node_features = np.stack([x["features"] for x in self.nodes]).astype(np.float32)
        lineage = np.asarray([x["lineage"] for x in self.nodes], dtype=np.uint32)
        texts = [x["text"] for x in self.nodes]
        if self.edges:
            e = np.asarray(self.edges, dtype=np.float64)
            edge_src = e[:, 0].astype(np.int64); edge_dst = e[:, 1].astype(np.int64); edge_type = e[:, 2].astype(np.int16)
            edge_time = e[:, 3].astype(np.float64); edge_weight = e[:, 4].astype(np.float32); edge_flags = e[:, 5].astype(np.uint16)
        else:
            edge_src = np.empty(0, np.int64); edge_dst = np.empty(0, np.int64); edge_type = np.empty(0, np.int16)
            edge_time = np.empty(0, np.float64); edge_weight = np.empty(0, np.float32); edge_flags = np.empty(0, np.uint16)
        if self.events:
            event_entity = np.asarray([x[0] for x in self.events], np.int64)
            event_time = np.asarray([x[1] for x in self.events], np.float64)
            event_type = np.asarray([x[2] for x in self.events], np.int16)
            event_value = np.asarray([x[3] for x in self.events], np.float32)
            event_flags = np.asarray([x[4] for x in self.events], np.uint16)
        else:
            event_entity = np.empty(0, np.int64); event_time = np.empty(0, np.float64); event_type = np.empty(0, np.int16)
            event_value = np.empty((0, 4), np.float32); event_flags = np.empty(0, np.uint16)
        if self.examples:
            ex_src = np.asarray([x[0] for x in self.examples], np.int64); ex_dst = np.asarray([x[1] for x in self.examples], np.int64)
            ex_relation = np.asarray([x[2] for x in self.examples], np.int16); ex_label = np.asarray([x[3] for x in self.examples], np.float32)
            ex_teacher_prob = np.asarray([x[4] for x in self.examples], np.float32); ex_time = np.asarray([x[5] for x in self.examples], np.float64)
            ex_distance_m = np.asarray([x[6] for x in self.examples], np.float32); ex_split = np.asarray([x[7] for x in self.examples], np.uint8)
        else:
            ex_src = np.empty(0, np.int64); ex_dst = np.empty(0, np.int64); ex_relation = np.empty(0, np.int16)
            ex_label = np.empty(0, np.float32); ex_teacher_prob = np.empty(0, np.float32); ex_time = np.empty(0, np.float64)
            ex_distance_m = np.empty(0, np.float32); ex_split = np.empty(0, np.uint8)
        teacher_embeddings = None; teacher_mask = None
        if self.teacher_vectors:
            dims = {v.shape for v in self.teacher_vectors.values()}
            if len(dims) != 1:
                raise ValueError("teacher vectors have inconsistent dimensions")
            d = next(iter(dims))[0]
            teacher_embeddings = np.zeros((n, d), dtype=np.float16)
            teacher_mask = np.zeros(n, dtype=np.bool_)
            for i, v in self.teacher_vectors.items():
                teacher_embeddings[i] = v.astype(np.float16)
                teacher_mask[i] = True
        graph = SparseTemporalGraph(
            node_ids, node_types, node_coords, node_features, lineage, texts,
            edge_src, edge_dst, edge_type, edge_time, edge_weight, edge_flags,
            event_entity, event_time, event_type, event_value, event_flags,
            ex_src, ex_dst, ex_relation, ex_label, ex_teacher_prob, ex_time, ex_distance_m, ex_split,
            teacher_embeddings, teacher_mask, self.metadata,
        )
        graph.validate()
        return graph
