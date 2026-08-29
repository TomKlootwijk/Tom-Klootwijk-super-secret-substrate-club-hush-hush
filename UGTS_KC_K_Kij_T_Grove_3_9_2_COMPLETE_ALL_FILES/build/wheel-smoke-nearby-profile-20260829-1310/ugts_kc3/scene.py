"""Scene, asset and instance composition layer for KC Two Hands 3.0."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import copy
import hashlib
import json
from typing import Any, Iterable

from .geometry import Mesh
from .math3d import mat4_identity, mat4_mul
from .spatial import AABB


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _matrix_to_lists(matrix):
    return [[float(v) for v in row] for row in matrix]


def _matrix_from(value):
    if len(value) != 4 or any(len(row) != 4 for row in value):
        raise ValueError("expected a 4x4 transform")
    return tuple(tuple(float(v) for v in row) for row in value)


@dataclass(frozen=True)
class SceneMetadata:
    schema_version: str = "3.0.0"
    units_per_meter: float = 1.0
    up_axis: str = "Y"
    handedness: str = "right"
    time_unit: str = "seconds"
    working_color_space: str = "scene-linear"
    determinism_profile: str = "tolerance-certified"

    def validate(self):
        if self.units_per_meter <= 0:
            raise ValueError("units_per_meter must be positive")
        if self.up_axis not in {"X", "Y", "Z"}:
            raise ValueError("up_axis must be X, Y or Z")
        if self.handedness not in {"left", "right"}:
            raise ValueError("handedness must be left or right")


@dataclass(frozen=True)
class Asset:
    id: str
    mesh: Mesh
    material_id: str | None = None
    source_pattern_id: str | None = None
    schema_hash: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate(self):
        if not self.id:
            raise ValueError("asset id required")
        self.mesh.validate()

    def content_hash(self) -> str:
        payload = {
            "mesh": {
                "vertices": self.mesh.vertices,
                "triangles": self.mesh.triangles,
                "normals": self.mesh.normals,
                "uvs": self.mesh.uvs,
                "metadata": self.mesh.metadata,
            },
            "material_id": self.material_id,
            "source_pattern_id": self.source_pattern_id,
            "schema_hash": self.schema_hash,
            "metadata": self.metadata,
        }
        return hashlib.sha256(_canonical_json(payload)).hexdigest()


@dataclass(frozen=True)
class SceneNode:
    id: str
    asset_id: str | None = None
    parent_id: str | None = None
    local_transform: tuple = field(default_factory=mat4_identity)
    visible: bool = True
    tags: frozenset[str] = frozenset()
    layer: str = "default"
    lineage: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict, compare=False)

    def validate(self):
        if not self.id:
            raise ValueError("node id required")
        _matrix_from(self.local_transform)


@dataclass(frozen=True)
class SceneLayer:
    name: str
    opinions: dict[str, dict[str, Any]] = field(default_factory=dict)
    muted: bool = False


class Scene:
    def __init__(self, metadata: SceneMetadata | None = None):
        self.metadata = metadata or SceneMetadata()
        self.metadata.validate()
        self.assets: dict[str, Asset] = {}
        self.nodes: dict[str, SceneNode] = {}
        self.layers: list[SceneLayer] = []
        self.variant_selection: dict[str, str] = {}
        self.migration_history: list[dict[str, Any]] = []

    def clone(self) -> "Scene":
        return copy.deepcopy(self)

    def add_asset(self, asset: Asset, replace_existing: bool = False) -> str:
        asset.validate()
        if asset.id in self.assets and not replace_existing:
            raise ValueError(f"asset already exists: {asset.id}")
        self.assets[asset.id] = asset
        return asset.content_hash()

    def add_node(self, node: SceneNode, replace_existing: bool = False) -> None:
        node.validate()
        if node.id in self.nodes and not replace_existing:
            raise ValueError(f"node already exists: {node.id}")
        if node.asset_id is not None and node.asset_id not in self.assets:
            raise KeyError(f"unknown asset: {node.asset_id}")
        if node.parent_id is not None and node.parent_id not in self.nodes:
            raise KeyError(f"unknown parent: {node.parent_id}")
        old = self.nodes.get(node.id)
        self.nodes[node.id] = node
        try:
            self._assert_acyclic()
        except Exception:
            if old is None:
                del self.nodes[node.id]
            else:
                self.nodes[node.id] = old
            raise

    def update_node(self, node_id: str, **changes) -> SceneNode:
        if node_id not in self.nodes:
            raise KeyError(node_id)
        candidate = replace(self.nodes[node_id], **changes)
        self.add_node(candidate, replace_existing=True)
        return candidate

    def set_parent(self, node_id: str, parent_id: str | None) -> None:
        if parent_id is not None and parent_id not in self.nodes:
            raise KeyError(parent_id)
        self.update_node(node_id, parent_id=parent_id)

    def _assert_acyclic(self) -> None:
        for node_id in self.nodes:
            seen = set()
            current = node_id
            while current is not None:
                if current in seen:
                    raise ValueError(f"scene hierarchy cycle involving {current}")
                seen.add(current)
                parent = self.nodes[current].parent_id
                current = parent

    def world_transform(self, node_id: str):
        if node_id not in self.nodes:
            raise KeyError(node_id)
        chain = []
        current = node_id
        while current is not None:
            chain.append(self.nodes[current].local_transform)
            current = self.nodes[current].parent_id
        out = mat4_identity()
        for local in reversed(chain):
            out = mat4_mul(out, local)
        return out

    def children(self, node_id: str | None = None) -> tuple[str, ...]:
        return tuple(sorted(n.id for n in self.nodes.values() if n.parent_id == node_id))

    def instances(self, asset_id: str) -> tuple[str, ...]:
        if asset_id not in self.assets:
            raise KeyError(asset_id)
        return tuple(sorted(n.id for n in self.nodes.values() if n.asset_id == asset_id))

    def add_layer(self, layer: SceneLayer) -> None:
        if any(existing.name == layer.name for existing in self.layers):
            raise ValueError(f"layer already exists: {layer.name}")
        self.layers.append(layer)

    def composed_node(self, node_id: str) -> SceneNode:
        if node_id not in self.nodes:
            raise KeyError(node_id)
        node = self.nodes[node_id]
        changes: dict[str, Any] = {}
        for layer in self.layers:
            if not layer.muted:
                changes.update(layer.opinions.get(node_id, {}))
        return replace(node, **changes) if changes else node

    def node_bounds(self, node_id: str, composed: bool = True) -> AABB | None:
        node = self.composed_node(node_id) if composed else self.nodes[node_id]
        if not node.visible or node.asset_id is None:
            return None
        mesh = self.assets[node.asset_id].mesh
        return AABB(*mesh.bounds()).transformed(self.world_transform(node_id))

    def scene_bounds(self) -> AABB | None:
        boxes = [box for node_id in self.nodes if (box := self.node_bounds(node_id)) is not None]
        if not boxes:
            return None
        out = boxes[0]
        for box in boxes[1:]:
            out = out.union(box)
        return out

    def migrate(self, target_version: str, description: str) -> None:
        old = self.metadata.schema_version
        self.migration_history.append({"from": old, "to": target_version, "description": description})
        self.metadata = replace(self.metadata, schema_version=target_version)

    def to_dict(self, include_geometry: bool = True) -> dict[str, Any]:
        assets = []
        for asset in sorted(self.assets.values(), key=lambda a: a.id):
            item = {
                "id": asset.id,
                "material_id": asset.material_id,
                "source_pattern_id": asset.source_pattern_id,
                "schema_hash": asset.schema_hash,
                "content_hash": asset.content_hash(),
                "metadata": asset.metadata,
            }
            if include_geometry:
                item["mesh"] = {
                    "vertices": asset.mesh.vertices,
                    "triangles": asset.mesh.triangles,
                    "normals": asset.mesh.normals,
                    "uvs": asset.mesh.uvs,
                    "metadata": asset.mesh.metadata,
                }
            assets.append(item)
        nodes = [
            {
                "id": n.id,
                "asset_id": n.asset_id,
                "parent_id": n.parent_id,
                "local_transform": _matrix_to_lists(n.local_transform),
                "visible": n.visible,
                "tags": sorted(n.tags),
                "layer": n.layer,
                "lineage": list(n.lineage),
                "metadata": n.metadata,
            }
            for n in sorted(self.nodes.values(), key=lambda n: n.id)
        ]
        return {
            "metadata": self.metadata.__dict__,
            "assets": assets,
            "nodes": nodes,
            "layers": [layer.__dict__ for layer in self.layers],
            "variant_selection": self.variant_selection,
            "migration_history": self.migration_history,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        metadata = SceneMetadata(**data.get("metadata", {}))
        scene = cls(metadata)
        for item in data.get("assets", []):
            mesh_data = item.get("mesh")
            if mesh_data is None:
                raise ValueError("from_dict requires embedded geometry")
            mesh = Mesh(
                tuple(tuple(map(float, p)) for p in mesh_data["vertices"]),
                tuple(tuple(map(int, tri)) for tri in mesh_data["triangles"]),
                tuple(tuple(map(float, n)) for n in mesh_data.get("normals", [])),
                tuple(tuple(map(float, uv)) for uv in mesh_data.get("uvs", [])),
                mesh_data.get("metadata", {}),
            )
            scene.add_asset(
                Asset(
                    item["id"],
                    mesh,
                    item.get("material_id"),
                    item.get("source_pattern_id"),
                    item.get("schema_hash"),
                    item.get("metadata", {}),
                )
            )
        pending = list(data.get("nodes", []))
        while pending:
            progress = False
            for item in pending[:]:
                if item.get("parent_id") is None or item["parent_id"] in scene.nodes:
                    scene.add_node(
                        SceneNode(
                            id=item["id"],
                            asset_id=item.get("asset_id"),
                            parent_id=item.get("parent_id"),
                            local_transform=_matrix_from(item.get("local_transform", mat4_identity())),
                            visible=bool(item.get("visible", True)),
                            tags=frozenset(item.get("tags", [])),
                            layer=item.get("layer", "default"),
                            lineage=tuple(item.get("lineage", [])),
                            metadata=item.get("metadata", {}),
                        )
                    )
                    pending.remove(item)
                    progress = True
            if not progress:
                raise ValueError("unresolvable parent references in scene")
        for layer_data in data.get("layers", []):
            scene.add_layer(SceneLayer(layer_data["name"], layer_data.get("opinions", {}), layer_data.get("muted", False)))
        scene.variant_selection.update(data.get("variant_selection", {}))
        scene.migration_history.extend(data.get("migration_history", []))
        return scene

    def content_hash(self) -> str:
        return hashlib.sha256(_canonical_json(self.to_dict(include_geometry=True))).hexdigest()
