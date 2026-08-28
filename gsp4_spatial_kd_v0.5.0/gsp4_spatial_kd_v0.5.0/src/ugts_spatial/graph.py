from __future__ import annotations

from dataclasses import dataclass, field, replace
from io import BytesIO
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
import zipfile

import numpy as np
import torch

from .schema import NODE_TYPE_NAMES, RELATION_TYPE_NAMES, relation_is_type_compatible
from .utils import canonical_json, sha256_bytes, stable_u32


@dataclass
class GraphPackage:
    """Portable sparse heterogeneous graph container (``.ugkg``).

    Persistent entities occupy node rows. Variable-length observations and
    events are sparse nodes/edges and/or append-only novelty records, never a
    padded frame axis. The hot UGTS fields are explicit:

    ``sheet`` / ``orientation`` / ``compatibility_mask`` / ``lineage_seed``.

    ``edge_attr`` follows the fixed spatial contract:

    ``[distance_m, sin(bearing), cos(bearing), abs(delta_time_s)]``.
    """

    x: np.ndarray
    node_type: np.ndarray
    node_id: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    elevation: np.ndarray
    node_time: np.ndarray
    cell_id: np.ndarray
    split: np.ndarray
    edge_index: np.ndarray
    edge_type: np.ndarray
    edge_time: np.ndarray
    edge_weight: np.ndarray
    texts: list[str]
    keys: list[str] | None = None
    sheet: np.ndarray | None = None
    orientation: np.ndarray | None = None
    compatibility_mask: np.ndarray | None = None
    lineage_seed: np.ndarray | None = None
    edge_attr: np.ndarray | None = None
    teacher_x: np.ndarray | None = None
    teacher_mask: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    FORMAT = "UGKG2"
    LEGACY_FORMAT = "UGKG1"
    EDGE_ATTR_DIM = 4

    def __post_init__(self) -> None:
        self.x = np.asarray(self.x, dtype=np.float32)
        self.node_type = np.asarray(self.node_type, dtype=np.int64)
        self.node_id = np.asarray(self.node_id, dtype=np.uint64)
        self.latitude = np.asarray(self.latitude, dtype=np.float64)
        self.longitude = np.asarray(self.longitude, dtype=np.float64)
        self.elevation = np.asarray(self.elevation, dtype=np.float32)
        self.node_time = np.asarray(self.node_time, dtype=np.float64)
        self.cell_id = np.asarray(self.cell_id, dtype=np.uint64)
        self.split = np.asarray(self.split, dtype=np.int8)
        self.edge_index = np.asarray(self.edge_index, dtype=np.int64)
        self.edge_type = np.asarray(self.edge_type, dtype=np.int64)
        self.edge_time = np.asarray(self.edge_time, dtype=np.float64)
        self.edge_weight = np.asarray(self.edge_weight, dtype=np.float32)
        node_count = self.x.shape[0] if self.x.ndim == 2 else 0
        edge_count = self.edge_index.shape[1] if self.edge_index.ndim == 2 else 0

        if self.keys is None:
            self.keys = [f"node:{int(value):016x}" for value in self.node_id.tolist()]
        else:
            self.keys = [str(value) for value in self.keys]
        self.texts = [str(value) for value in self.texts]

        if self.sheet is None:
            self.sheet = np.zeros(node_count, dtype=np.uint8)
        else:
            self.sheet = np.asarray(self.sheet, dtype=np.uint8)
        if self.orientation is None:
            self.orientation = np.zeros(node_count, dtype=np.uint8)
        else:
            self.orientation = np.asarray(self.orientation, dtype=np.uint8)
        if self.compatibility_mask is None:
            self.compatibility_mask = np.full(node_count, 0xFFFF, dtype=np.uint16)
        else:
            self.compatibility_mask = np.asarray(self.compatibility_mask, dtype=np.uint16)
        if self.lineage_seed is None:
            self.lineage_seed = np.asarray(
                [stable_u32(key, namespace="ugts-lineage") for key in self.keys], dtype=np.uint32
            )
        else:
            self.lineage_seed = np.asarray(self.lineage_seed, dtype=np.uint32)

        if self.edge_attr is None:
            self.edge_attr = np.zeros((edge_count, self.EDGE_ATTR_DIM), dtype=np.float32)
        else:
            self.edge_attr = np.asarray(self.edge_attr, dtype=np.float32)
        if self.teacher_x is None:
            self.teacher_x = np.zeros((node_count, 0), dtype=np.float32)
        else:
            self.teacher_x = np.asarray(self.teacher_x, dtype=np.float32)
        if self.teacher_mask is None:
            self.teacher_mask = np.zeros(node_count, dtype=np.bool_)
        else:
            self.teacher_mask = np.asarray(self.teacher_mask, dtype=np.bool_)
        self.metadata = dict(self.metadata)
        self.validate()

    @property
    def num_nodes(self) -> int:
        return int(self.x.shape[0])

    @property
    def num_edges(self) -> int:
        return int(self.edge_index.shape[1])

    @property
    def input_dim(self) -> int:
        return int(self.x.shape[1])

    @property
    def edge_dim(self) -> int:
        return int(self.edge_attr.shape[1])

    @property
    def teacher_dim(self) -> int:
        return int(self.teacher_x.shape[1])

    @property
    def num_node_types(self) -> int:
        return int(self.node_type.max(initial=-1)) + 1

    @property
    def num_relations(self) -> int:
        # The compact ABI reserves the complete 4-bit relation vocabulary even
        # when a pilot graph does not instantiate every relation.
        return max(16, int(self.edge_type.max(initial=-1)) + 1)

    def validate(self, *, strict_types: bool = True) -> None:
        if self.x.ndim != 2:
            raise ValueError("x must have shape [nodes, features]")
        n = self.x.shape[0]
        node_vectors = {
            "node_type": self.node_type,
            "node_id": self.node_id,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation": self.elevation,
            "node_time": self.node_time,
            "cell_id": self.cell_id,
            "split": self.split,
            "sheet": self.sheet,
            "orientation": self.orientation,
            "compatibility_mask": self.compatibility_mask,
            "lineage_seed": self.lineage_seed,
            "teacher_mask": self.teacher_mask,
        }
        for name, array in node_vectors.items():
            if array.shape != (n,):
                raise ValueError(f"{name} must have shape [{n}]")
        if len(self.texts) != n or len(self.keys) != n:
            raise ValueError(f"keys/texts must contain {n} rows")
        if len(set(self.keys)) != n:
            raise ValueError("node keys must be unique")
        if np.unique(self.node_id).size != n:
            raise ValueError("node_id values must be unique")
        if self.teacher_x.ndim != 2 or self.teacher_x.shape[0] != n:
            raise ValueError("teacher_x must have shape [nodes, teacher_features]")
        if self.edge_index.ndim != 2 or self.edge_index.shape[0] != 2:
            raise ValueError("edge_index must have shape [2, edges]")
        e = self.edge_index.shape[1]
        for name, array in {
            "edge_type": self.edge_type,
            "edge_time": self.edge_time,
            "edge_weight": self.edge_weight,
        }.items():
            if array.shape != (e,):
                raise ValueError(f"{name} must have shape [{e}]")
        if self.edge_attr.ndim != 2 or self.edge_attr.shape != (e, self.EDGE_ATTR_DIM):
            raise ValueError(f"edge_attr must have shape [{e},{self.EDGE_ATTR_DIM}]")
        if e and (self.edge_index.min() < 0 or self.edge_index.max() >= n):
            raise ValueError("edge_index contains an out-of-range node")
        for name, array in {
            "x": self.x,
            "teacher_x": self.teacher_x,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "elevation": self.elevation,
            "node_time": self.node_time,
            "edge_time": self.edge_time,
            "edge_weight": self.edge_weight,
            "edge_attr": self.edge_attr,
        }.items():
            if array.size and not np.isfinite(array).all():
                raise ValueError(f"{name} contains non-finite values")
        if not ((self.latitude >= -90.0) & (self.latitude <= 90.0)).all():
            raise ValueError("latitude is outside [-90,90]")
        if not ((self.longitude >= -180.0) & (self.longitude <= 180.0)).all():
            raise ValueError("longitude is outside [-180,180]")
        if np.any(self.edge_weight < 0):
            raise ValueError("edge_weight must be nonnegative")
        if np.any(self.orientation > 1):
            raise ValueError("orientation must be a one-bit class")
        if not np.isin(self.split, np.asarray([0, 1, 2], dtype=np.int8)).all():
            raise ValueError("split values must be 0=train, 1=validation or 2=test")
        if strict_types and e:
            for src, dst, rel in zip(
                self.edge_index[0].tolist(), self.edge_index[1].tolist(), self.edge_type.tolist()
            ):
                if int(rel) in RELATION_TYPE_NAMES and not relation_is_type_compatible(
                    int(rel), int(self.node_type[src]), int(self.node_type[dst])
                ):
                    raise ValueError(
                        f"type-incompatible edge relation={rel} src_type={self.node_type[src]} "
                        f"dst_type={self.node_type[dst]}"
                    )

    def schema_descriptor(self) -> dict[str, Any]:
        # JSON object keys are strings. Normalize enum dictionaries before
        # hashing so save/load round trips preserve the exact ABI hash.
        node_types = {
            str(key): str(value)
            for key, value in self.metadata.get("node_types", NODE_TYPE_NAMES).items()
        }
        relation_types = {
            str(key): str(value)
            for key, value in self.metadata.get("relation_types", RELATION_TYPE_NAMES).items()
        }
        return {
            "format": self.FORMAT,
            "input_dim": self.input_dim,
            "edge_dim": self.edge_dim,
            "teacher_dim": self.teacher_dim,
            "num_node_types": self.num_node_types,
            "num_relations": self.num_relations,
            "node_types": node_types,
            "relation_types": relation_types,
            "ontology_version": self.metadata.get("ontology_version", "ugts-geo-ontology-v1"),
            "edge_attr_contract": list(self.metadata.get(
                "edge_attr_contract",
                ["distance_m", "sin_bearing", "cos_bearing", "abs_delta_time_s"],
            )),
            "hot_state_contract": [
                "sheet:uint8",
                "orientation:uint8",
                "compatibility_mask:uint16",
                "lineage_seed:uint32",
            ],
        }

    @property
    def schema_hash(self) -> str:
        return sha256_bytes(canonical_json(self.schema_descriptor()))

    def summary(self) -> dict[str, Any]:
        node_names = self.metadata.get("node_types", NODE_TYPE_NAMES)
        relation_names = self.metadata.get("relation_types", RELATION_TYPE_NAMES)

        def resolve(mapping: Mapping[Any, Any], value: int) -> str:
            return str(mapping.get(str(value), mapping.get(value, value)))

        node_counts = {
            resolve(node_names, int(t)): int(np.count_nonzero(self.node_type == t))
            for t in sorted(set(self.node_type.tolist()))
        }
        relation_counts = {
            resolve(relation_names, int(r)): int(np.count_nonzero(self.edge_type == r))
            for r in sorted(set(self.edge_type.tolist()))
        }
        array_bytes = sum(
            int(array.nbytes)
            for array in (
                self.x,
                self.teacher_x,
                self.teacher_mask,
                self.node_type,
                self.node_id,
                self.latitude,
                self.longitude,
                self.elevation,
                self.node_time,
                self.cell_id,
                self.split,
                self.sheet,
                self.orientation,
                self.compatibility_mask,
                self.lineage_seed,
                self.edge_index,
                self.edge_type,
                self.edge_time,
                self.edge_weight,
                self.edge_attr,
            )
        )
        return {
            "format": self.FORMAT,
            "schema_hash": self.schema_hash,
            "nodes": self.num_nodes,
            "edges": self.num_edges,
            "input_dim": self.input_dim,
            "edge_dim": self.edge_dim,
            "teacher_dim": self.teacher_dim,
            "teacher_rows": int(np.count_nonzero(self.teacher_mask)),
            "array_bytes": array_bytes,
            "bytes_per_node_plus_edge": array_bytes / max(1, self.num_nodes + self.num_edges),
            "node_counts": node_counts,
            "relation_counts": relation_counts,
            "split_counts": {
                "train": int(np.count_nonzero(self.split == 0)),
                "validation": int(np.count_nonzero(self.split == 1)),
                "test": int(np.count_nonzero(self.split == 2)),
            },
            "time_range": [
                float(self.node_time.min(initial=0.0)),
                float(self.node_time.max(initial=0.0)),
            ],
            "metadata": self.metadata,
        }

    def key_index(self) -> dict[str, int]:
        return {key: index for index, key in enumerate(self.keys)}

    def node_index_by_id(self) -> dict[int, int]:
        return {int(value): index for index, value in enumerate(self.node_id.tolist())}

    def index_for(self, value: int | str) -> int:
        if isinstance(value, str):
            try:
                return self.key_index()[value]
            except KeyError as exc:
                raise KeyError(f"node key not found: {value}") from exc
        matches = np.flatnonzero(self.node_id == np.uint64(value))
        if matches.size != 1:
            raise KeyError(f"node ID not found: {value}")
        return int(matches[0])

    def with_teacher_embeddings(
        self,
        embeddings: np.ndarray,
        mask: np.ndarray | None = None,
        *,
        teacher_metadata: Mapping[str, Any] | None = None,
    ) -> "GraphPackage":
        embeddings = np.asarray(embeddings, dtype=np.float32)
        if embeddings.ndim != 2 or embeddings.shape[0] != self.num_nodes:
            raise ValueError("embeddings must have shape [num_nodes, teacher_dim]")
        if mask is None:
            mask = np.ones(self.num_nodes, dtype=np.bool_)
        else:
            mask = np.asarray(mask, dtype=np.bool_)
            if mask.shape != (self.num_nodes,):
                raise ValueError("teacher mask has wrong shape")
        metadata = dict(self.metadata)
        if teacher_metadata is not None:
            metadata["teacher"] = dict(teacher_metadata)
        return replace(self, teacher_x=embeddings, teacher_mask=mask, metadata=metadata)

    def append_edges(
        self,
        edge_index: np.ndarray,
        edge_type: np.ndarray,
        *,
        edge_time: np.ndarray | None = None,
        edge_weight: np.ndarray | None = None,
        edge_attr: np.ndarray | None = None,
        metadata_patch: Mapping[str, Any] | None = None,
        deduplicate: bool = True,
    ) -> "GraphPackage":
        edge_index = np.asarray(edge_index, dtype=np.int64)
        edge_type = np.asarray(edge_type, dtype=np.int64)
        if edge_index.ndim != 2 or edge_index.shape[0] != 2:
            raise ValueError("new edge_index must have shape [2,E]")
        count = edge_index.shape[1]
        if edge_type.shape != (count,):
            raise ValueError("new edge_type has wrong shape")
        if edge_time is None:
            edge_time = np.zeros(count, dtype=np.float64)
        else:
            edge_time = np.asarray(edge_time, dtype=np.float64)
        if edge_weight is None:
            edge_weight = np.ones(count, dtype=np.float32)
        else:
            edge_weight = np.asarray(edge_weight, dtype=np.float32)
        if edge_attr is None:
            edge_attr = np.zeros((count, self.EDGE_ATTR_DIM), dtype=np.float32)
        else:
            edge_attr = np.asarray(edge_attr, dtype=np.float32)
        if edge_time.shape != (count,) or edge_weight.shape != (count,):
            raise ValueError("new edge scalar arrays have wrong shape")
        if edge_attr.shape != (count, self.EDGE_ATTR_DIM):
            raise ValueError("new edge_attr has wrong shape")
        keep = np.ones(count, dtype=np.bool_)
        if deduplicate:
            existing = {
                (int(src), int(rel), int(dst))
                for src, dst, rel in zip(
                    self.edge_index[0].tolist(), self.edge_index[1].tolist(), self.edge_type.tolist()
                )
            }
            for i, (src, dst, rel) in enumerate(
                zip(edge_index[0].tolist(), edge_index[1].tolist(), edge_type.tolist())
            ):
                key = (int(src), int(rel), int(dst))
                if key in existing:
                    keep[i] = False
                else:
                    existing.add(key)
        metadata = dict(self.metadata)
        if metadata_patch:
            metadata.update(dict(metadata_patch))
        return replace(
            self,
            edge_index=np.concatenate((self.edge_index, edge_index[:, keep]), axis=1),
            edge_type=np.concatenate((self.edge_type, edge_type[keep])),
            edge_time=np.concatenate((self.edge_time, edge_time[keep])),
            edge_weight=np.concatenate((self.edge_weight, edge_weight[keep])),
            edge_attr=np.concatenate((self.edge_attr, edge_attr[keep]), axis=0),
            metadata=metadata,
        )

    def cell_lookup(self) -> dict[int, np.ndarray]:
        return {
            int(cell): np.flatnonzero(self.cell_id == cell).astype(np.int64)
            for cell in np.unique(self.cell_id)
        }

    def subgraph(self, node_indices: Sequence[int]) -> "GraphPackage":
        indices = np.unique(np.asarray(node_indices, dtype=np.int64))
        if indices.ndim != 1 or indices.size == 0:
            raise ValueError("subgraph requires at least one node")
        if indices.min() < 0 or indices.max() >= self.num_nodes:
            raise ValueError("subgraph node index is out of range")
        remap = np.full(self.num_nodes, -1, dtype=np.int64)
        remap[indices] = np.arange(indices.size, dtype=np.int64)
        edge_keep = (remap[self.edge_index[0]] >= 0) & (remap[self.edge_index[1]] >= 0)
        sub_edges = remap[self.edge_index[:, edge_keep]]
        metadata = dict(self.metadata)
        metadata["parent_schema_hash"] = self.schema_hash
        metadata["subgraph_nodes"] = int(indices.size)
        return GraphPackage(
            x=self.x[indices],
            teacher_x=self.teacher_x[indices],
            teacher_mask=self.teacher_mask[indices],
            node_type=self.node_type[indices],
            node_id=self.node_id[indices],
            latitude=self.latitude[indices],
            longitude=self.longitude[indices],
            elevation=self.elevation[indices],
            node_time=self.node_time[indices],
            cell_id=self.cell_id[indices],
            split=self.split[indices],
            sheet=self.sheet[indices],
            orientation=self.orientation[indices],
            compatibility_mask=self.compatibility_mask[indices],
            lineage_seed=self.lineage_seed[indices],
            edge_index=sub_edges,
            edge_type=self.edge_type[edge_keep],
            edge_time=self.edge_time[edge_keep],
            edge_weight=self.edge_weight[edge_keep],
            edge_attr=self.edge_attr[edge_keep],
            keys=[self.keys[i] for i in indices.tolist()],
            texts=[self.texts[i] for i in indices.tolist()],
            metadata=metadata,
        )

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays = BytesIO()
        np.savez_compressed(
            arrays,
            x=self.x,
            teacher_x=self.teacher_x,
            teacher_mask=self.teacher_mask,
            node_type=self.node_type,
            node_id=self.node_id,
            latitude=self.latitude,
            longitude=self.longitude,
            elevation=self.elevation,
            node_time=self.node_time,
            cell_id=self.cell_id,
            split=self.split,
            sheet=self.sheet,
            orientation=self.orientation,
            compatibility_mask=self.compatibility_mask,
            lineage_seed=self.lineage_seed,
            edge_index=self.edge_index,
            edge_type=self.edge_type,
            edge_time=self.edge_time,
            edge_weight=self.edge_weight,
            edge_attr=self.edge_attr,
        )
        metadata = dict(self.metadata)
        metadata.update(
            {
                "format": self.FORMAT,
                "schema_hash": self.schema_hash,
                "num_nodes": self.num_nodes,
                "num_edges": self.num_edges,
                "input_dim": self.input_dim,
                "edge_dim": self.edge_dim,
                "teacher_dim": self.teacher_dim,
            }
        )
        node_bytes = "".join(
            json.dumps(
                {"index": i, "key": key, "text": text},
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
            for i, (key, text) in enumerate(zip(self.keys, self.texts))
        ).encode("utf-8")
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr(
                "metadata.json",
                json.dumps(metadata, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            )
            zf.writestr("arrays.npz", arrays.getvalue(), compress_type=zipfile.ZIP_STORED)
            zf.writestr("nodes.jsonl", node_bytes)

    @classmethod
    def load(cls, path: str | Path) -> "GraphPackage":
        path = Path(path)
        with zipfile.ZipFile(path, "r") as zf:
            metadata = json.loads(zf.read("metadata.json").decode("utf-8"))
            file_format = metadata.get("format")
            if file_format not in {cls.FORMAT, cls.LEGACY_FORMAT}:
                raise ValueError(f"unsupported graph format: {file_format!r}")
            with np.load(BytesIO(zf.read("arrays.npz")), allow_pickle=False) as arrays:
                values = {name: arrays[name] for name in arrays.files}
            keys: list[str] = []
            texts: list[str] = []
            if "nodes.jsonl" in zf.namelist():
                for line in zf.read("nodes.jsonl").decode("utf-8").splitlines():
                    if not line:
                        continue
                    row = json.loads(line)
                    if int(row["index"]) != len(texts):
                        raise ValueError("nodes.jsonl is not in contiguous order")
                    keys.append(str(row["key"]))
                    texts.append(str(row["text"]))
            else:
                for line in zf.read("texts.jsonl").decode("utf-8").splitlines():
                    if not line:
                        continue
                    row = json.loads(line)
                    if int(row["index"]) != len(texts):
                        raise ValueError("texts.jsonl is not in contiguous order")
                    texts.append(str(row["text"]))
                keys = [f"legacy:{int(value):016x}" for value in values["node_id"].tolist()]
        stored_hash = metadata.pop("schema_hash", None)
        for key in ("format", "num_nodes", "num_edges", "input_dim", "edge_dim", "teacher_dim"):
            metadata.pop(key, None)
        edge_count = values["edge_index"].shape[1]
        node_count = values["x"].shape[0]
        values.setdefault("edge_attr", np.zeros((edge_count, cls.EDGE_ATTR_DIM), dtype=np.float32))
        values.setdefault("sheet", np.zeros(node_count, dtype=np.uint8))
        values.setdefault("orientation", np.zeros(node_count, dtype=np.uint8))
        values.setdefault("compatibility_mask", np.full(node_count, 0xFFFF, dtype=np.uint16))
        values.setdefault(
            "lineage_seed",
            np.asarray([stable_u32(key, namespace="ugts-lineage") for key in keys], dtype=np.uint32),
        )
        graph = cls(keys=keys, texts=texts, metadata=metadata, **values)
        # Legacy UGKG1 hashes used a smaller descriptor and cannot be compared
        # to the upgraded hot-state ABI.
        if file_format == cls.FORMAT and stored_hash is not None and stored_hash != graph.schema_hash:
            raise ValueError("graph schema hash mismatch")
        return graph

    def to_torch(self, device: torch.device | str = "cpu") -> dict[str, torch.Tensor]:
        device = torch.device(device)
        return {
            "x": torch.as_tensor(self.x, device=device),
            "teacher_x": torch.as_tensor(self.teacher_x, device=device),
            "teacher_mask": torch.as_tensor(self.teacher_mask, device=device),
            "node_type": torch.as_tensor(self.node_type, device=device),
            # Signed views preserve all bits; these IDs are not used for
            # arithmetic inside the model.
            "node_id": torch.as_tensor(self.node_id.view(np.int64), device=device),
            "latitude": torch.as_tensor(self.latitude, device=device),
            "longitude": torch.as_tensor(self.longitude, device=device),
            "elevation": torch.as_tensor(self.elevation, device=device),
            "node_time": torch.as_tensor(self.node_time, device=device),
            "cell_id": torch.as_tensor(self.cell_id.view(np.int64), device=device),
            "split": torch.as_tensor(self.split, device=device),
            "sheet": torch.as_tensor(self.sheet.astype(np.int64), device=device),
            "orientation": torch.as_tensor(self.orientation.astype(np.int64), device=device),
            "compatibility_mask": torch.as_tensor(self.compatibility_mask.astype(np.int64), device=device),
            "lineage_seed": torch.as_tensor(self.lineage_seed.astype(np.int64), device=device),
            "edge_index": torch.as_tensor(self.edge_index, device=device),
            "edge_type": torch.as_tensor(self.edge_type, device=device),
            "edge_time": torch.as_tensor(self.edge_time, device=device),
            "edge_weight": torch.as_tensor(self.edge_weight, device=device),
            "edge_attr": torch.as_tensor(self.edge_attr, device=device),
        }
