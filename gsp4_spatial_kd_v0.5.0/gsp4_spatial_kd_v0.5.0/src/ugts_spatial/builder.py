from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np

from .embeddings import HashEmbedder
from .geocell import encode_morton_cell
from .graph import GraphPackage
from .schema import (
    NODE_TYPE_NAMES,
    RELATION_TYPE_NAMES,
    NodeType,
    RelationType,
    node_compatibility_mask,
)
from .spatial import pair_edge_attr_numpy
from .utils import stable_u32, stable_u64


@dataclass
class _NodeRow:
    key: str
    node_type: int
    text: str
    latitude: float
    longitude: float
    elevation: float
    timestamp: float
    cell_id: int
    split: int
    sheet: int
    orientation: int
    compatibility_mask: int
    lineage_seed: int
    value: float = 0.0
    confidence: float = 1.0
    active: float = 1.0
    lineage_depth: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class _EdgeRow:
    source: int
    target: int
    relation: int
    timestamp: float
    weight: float


class GraphBuilder:
    """Deterministic builder for sparse UGKG2 heterogeneous graphs.

    Variable-length observations are ordinary sparse rows. No frame padding or
    maximum-point tensor is created.
    """

    def __init__(
        self,
        *,
        name: str,
        source: str,
        morton_resolution: int = 14,
        input_dim: int = 32,
        teacher_dim: int = 64,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if input_dim < 16:
            raise ValueError("input_dim must be at least 16")
        if teacher_dim < 0:
            raise ValueError("teacher_dim must be nonnegative")
        self.name = name
        self.source = source
        self.morton_resolution = morton_resolution
        self.input_dim = input_dim
        self.teacher_dim = teacher_dim
        self.nodes: list[_NodeRow] = []
        self.edges: list[_EdgeRow] = []
        self.key_to_index: dict[str, int] = {}
        self.metadata = dict(metadata or {})

    def add_node(
        self,
        key: str,
        node_type: int | NodeType,
        text: str,
        *,
        latitude: float,
        longitude: float,
        elevation: float = 0.0,
        timestamp: float = 0.0,
        cell_id: int | None = None,
        split: int = 0,
        sheet: int = 0,
        orientation: int = 0,
        compatibility_mask: int | None = None,
        lineage_seed: int | None = None,
        value: float = 0.0,
        confidence: float = 1.0,
        active: float = 1.0,
        lineage_depth: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        key = str(key)
        if key in self.key_to_index:
            raise ValueError(f"duplicate node key: {key}")
        if split not in (0, 1, 2):
            raise ValueError("split must be 0, 1 or 2")
        if sheet not in range(256):
            raise ValueError("sheet must fit uint8")
        if orientation not in (0, 1):
            raise ValueError("orientation must be 0 or 1")
        node_type_value = int(node_type)
        if cell_id is None:
            cell_id = encode_morton_cell(latitude, longitude, self.morton_resolution)
        if compatibility_mask is None:
            compatibility_mask = node_compatibility_mask(node_type_value)
        if lineage_seed is None:
            lineage_seed = stable_u32(key, namespace="ugts-lineage")
        row = _NodeRow(
            key=key,
            node_type=node_type_value,
            text=str(text),
            latitude=float(latitude),
            longitude=float(longitude),
            elevation=float(elevation),
            timestamp=float(timestamp),
            cell_id=int(cell_id),
            split=int(split),
            sheet=int(sheet),
            orientation=int(orientation),
            compatibility_mask=int(compatibility_mask) & 0xFFFF,
            lineage_seed=int(lineage_seed) & 0xFFFFFFFF,
            value=float(value),
            confidence=float(confidence),
            active=float(active),
            lineage_depth=float(lineage_depth),
            metadata=dict(metadata or {}),
        )
        index = len(self.nodes)
        self.nodes.append(row)
        self.key_to_index[key] = index
        return index

    def index(self, key_or_index: str | int) -> int:
        if isinstance(key_or_index, str):
            return self.key_to_index[key_or_index]
        index = int(key_or_index)
        if not 0 <= index < len(self.nodes):
            raise IndexError(index)
        return index

    def add_edge(
        self,
        source: str | int,
        target: str | int,
        relation: int | RelationType,
        *,
        timestamp: float = 0.0,
        weight: float = 1.0,
        symmetric: bool = False,
    ) -> None:
        src = self.index(source)
        dst = self.index(target)
        rel = int(relation)
        if not 0 <= rel < 16:
            raise ValueError("relation must fit the 4-bit UGTS vocabulary")
        if weight < 0 or not math.isfinite(weight):
            raise ValueError("edge weight must be finite and nonnegative")
        self.edges.append(_EdgeRow(src, dst, rel, float(timestamp), float(weight)))
        if symmetric and src != dst:
            self.edges.append(_EdgeRow(dst, src, rel, float(timestamp), float(weight)))

    def _features(self) -> np.ndarray:
        n = len(self.nodes)
        lexical_dim = self.input_dim - 16
        lexical = HashEmbedder(max(lexical_dim, 1)).encode([row.text for row in self.nodes])
        x = np.zeros((n, self.input_dim), dtype=np.float32)
        if n == 0:
            return x
        timestamps = np.asarray([row.timestamp for row in self.nodes], dtype=np.float64)
        positive_time = timestamps[timestamps > 0]
        time_origin = float(positive_time.min()) if positive_time.size else 0.0
        for i, row in enumerate(self.nodes):
            lat_r = math.radians(row.latitude)
            lon_r = math.radians(row.longitude)
            delta_time = max(0.0, row.timestamp - time_origin) if row.timestamp > 0 else 0.0
            cell_low = row.cell_id & 0xFFFF
            cell_high = (row.cell_id >> 16) & 0xFFFF
            x[i, :16] = np.asarray(
                [
                    1.0,
                    row.latitude / 90.0,
                    row.longitude / 180.0,
                    float(np.clip(row.elevation / 1000.0, -4.0, 12.0)),
                    math.sin(lat_r),
                    math.cos(lat_r),
                    math.sin(lon_r),
                    math.cos(lon_r),
                    math.log1p(delta_time) / 24.0,
                    1.0 if row.timestamp > 0 else 0.0,
                    row.node_type / max(1.0, float(len(NodeType) - 1)),
                    cell_low / 65535.0,
                    cell_high / 65535.0,
                    float(np.tanh(row.value)),
                    float(np.clip(row.confidence, 0.0, 1.0)),
                    float(
                        np.clip(
                            row.active
                            + 0.05 * row.lineage_depth
                            + 0.01 * row.sheet
                            + 0.01 * row.orientation,
                            -2.0,
                            2.0,
                        )
                    ),
                ],
                dtype=np.float32,
            )
            if lexical_dim > 0:
                x[i, 16:] = lexical[i, :lexical_dim]
        return x

    def build(self) -> GraphPackage:
        if not self.nodes:
            raise ValueError("graph must contain at least one node")
        x = self._features()
        texts = [row.text for row in self.nodes]
        keys = [row.key for row in self.nodes]
        if self.teacher_dim > 0:
            teacher_x = HashEmbedder(self.teacher_dim).encode(texts)
            teacher_mask = np.ones(len(self.nodes), dtype=np.bool_)
        else:
            teacher_x = np.zeros((len(self.nodes), 0), dtype=np.float32)
            teacher_mask = np.zeros(len(self.nodes), dtype=np.bool_)
        if self.edges:
            edge_index = np.asarray(
                [[edge.source for edge in self.edges], [edge.target for edge in self.edges]],
                dtype=np.int64,
            )
            edge_type = np.asarray([edge.relation for edge in self.edges], dtype=np.int64)
            edge_time = np.asarray([edge.timestamp for edge in self.edges], dtype=np.float64)
            edge_weight = np.asarray([edge.weight for edge in self.edges], dtype=np.float32)
        else:
            edge_index = np.zeros((2, 0), dtype=np.int64)
            edge_type = np.zeros(0, dtype=np.int64)
            edge_time = np.zeros(0, dtype=np.float64)
            edge_weight = np.zeros(0, dtype=np.float32)

        latitude = np.asarray([row.latitude for row in self.nodes], dtype=np.float64)
        longitude = np.asarray([row.longitude for row in self.nodes], dtype=np.float64)
        elevation = np.asarray([row.elevation for row in self.nodes], dtype=np.float32)
        node_time = np.asarray([row.timestamp for row in self.nodes], dtype=np.float64)
        edge_attr = pair_edge_attr_numpy(latitude, longitude, elevation, node_time, edge_index)
        metadata = {
            "name": self.name,
            "source": self.source,
            "ontology_version": "ugts-geo-ontology-v1",
            "node_types": NODE_TYPE_NAMES,
            "relation_types": RELATION_TYPE_NAMES,
            "spatial_index": {
                "backend": "morton",
                "resolution": self.morton_resolution,
                "role": "broad-phase only; exact metric/guard follows",
            },
            "edge_attr_contract": [
                "distance_m",
                "sin_bearing",
                "cos_bearing",
                "abs_delta_time_s",
            ],
            "teacher": {
                "backend": "hash-lexical-v1",
                "dimensions": self.teacher_dim,
                "role": "smoke-test teacher; replace with downloaded embedding model",
            },
            "variable_length": True,
            "identity_contract": "persistent node_id + lineage_seed + ordered novelty",
            "node_metadata": {
                str(i): row.metadata for i, row in enumerate(self.nodes) if row.metadata
            },
            **self.metadata,
        }
        return GraphPackage(
            x=x,
            teacher_x=teacher_x,
            teacher_mask=teacher_mask,
            node_type=np.asarray([row.node_type for row in self.nodes], dtype=np.int64),
            node_id=np.asarray(
                [stable_u64(row.key, namespace="ugts-spatial-node") for row in self.nodes],
                dtype=np.uint64,
            ),
            latitude=latitude,
            longitude=longitude,
            elevation=elevation,
            node_time=node_time,
            cell_id=np.asarray([row.cell_id for row in self.nodes], dtype=np.uint64),
            split=np.asarray([row.split for row in self.nodes], dtype=np.int8),
            sheet=np.asarray([row.sheet for row in self.nodes], dtype=np.uint8),
            orientation=np.asarray([row.orientation for row in self.nodes], dtype=np.uint8),
            compatibility_mask=np.asarray(
                [row.compatibility_mask for row in self.nodes], dtype=np.uint16
            ),
            lineage_seed=np.asarray([row.lineage_seed for row in self.nodes], dtype=np.uint32),
            edge_index=edge_index,
            edge_type=edge_type,
            edge_time=edge_time,
            edge_weight=edge_weight,
            edge_attr=edge_attr,
            keys=keys,
            texts=texts,
            metadata=metadata,
        )
