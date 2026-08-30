"""Compact linked multi-object Saved Scenes for mobile 3D authoring.

Saved Scenes deliberately remain an authoring layer.  A definition stores
parent-local ECS records once and each placement stores only a stable id plus
one group transform.  :func:`materialize_saved_scenes` expands that compact
description into the ordinary flat ``Mobile3DProject.nodes`` ABI used by the
desktop oracle and every Android sidecar.

The materializer is pure, deterministic and idempotent.  It never adds a
runtime hierarchy that the current native engine could only pretend to obey.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import copy
import math
import re
from typing import Any, Iterable, Mapping, Sequence, TYPE_CHECKING

from .animation3d import (
    ANIMATION_LIBRARY_METADATA_KEY,
    ANIMATION_METADATA_KEY,
)
from .math3d import quat_inverse, quat_mul, quat_normalize, quat_rotate
from .visual_graph import VisualGraph

if TYPE_CHECKING:
    from .mobile3d import Mobile3DProject, Node3DRecord, Transform3DRecord


SAVED_SCENES_KEY = "saved_scenes"
SAVED_SCENE_INSTANCES_KEY = "saved_scene_instances"
SAVED_SCENE_SCHEMA = "ugts-studio-saved-scene-2"
SAVED_SCENE_INSTANCE_SCHEMA = "ugts-studio-saved-scene-instance-1"
SAVED_SCENE_RUNTIME_KEY = "saved_scene_runtime"
SAVED_SCENE_ID_SEPARATOR = "__"

MAX_SAVED_SCENES = 64
MAX_SAVED_SCENE_NODES = 64
MAX_SAVED_SCENE_DEFINITION_NODES = 1024
MAX_SAVED_SCENE_INSTANCES = 256
MAX_MATERIALIZED_SCENE_NODES = 4096
MAX_SAVED_SCENE_ID_BYTES = 96

_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_ENTITY_FIELDS = frozenset({"entity", "origin", "source", "target"})
_RELATIVE_ROOT = "@root"
_RELATIVE_NODE_PREFIX = "@node/"


class SavedSceneError(ValueError):
    """A linked Saved Scene cannot be represented safely."""


def _record_types() -> tuple[type[Any], type[Any]]:
    # Local import avoids a module cycle: mobile3d validates this authoring
    # extension, while this extension builds mobile3d records.
    from .mobile3d import Node3DRecord, Transform3DRecord

    return Node3DRecord, Transform3DRecord


def _validate_id(value: Any, label: str) -> str:
    result = str(value).strip()
    if not result:
        raise SavedSceneError(f"{label} is required")
    if len(result.encode("utf-8")) > MAX_SAVED_SCENE_ID_BYTES:
        raise SavedSceneError(
            f"{label} must fit in {MAX_SAVED_SCENE_ID_BYTES} UTF-8 bytes"
        )
    if (
        _ID_PATTERN.fullmatch(result) is None
        or SAVED_SCENE_ID_SEPARATOR in result
        or "/" in result
    ):
        raise SavedSceneError(
            f"{label} must start with a letter and use only letters, numbers, "
            "underscore, dash, or dot (double underscore is reserved)"
        )
    return result


def _copy_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(dict(metadata))


def _is_identity_rotation(rotation: Sequence[float]) -> bool:
    normalized = quat_normalize(tuple(float(value) for value in rotation))
    return math.isclose(abs(normalized[0]), 1.0, abs_tol=1.0e-10) and all(
        math.isclose(value, 0.0, abs_tol=1.0e-10) for value in normalized[1:]
    )


def _is_uniform_scale(scale: Sequence[float]) -> bool:
    values = tuple(float(value) for value in scale)
    return math.isclose(values[0], values[1], rel_tol=1.0e-9, abs_tol=1.0e-10) and math.isclose(
        values[1], values[2], rel_tol=1.0e-9, abs_tol=1.0e-10
    )


def _has_nonzero(values: Sequence[float]) -> bool:
    return any(abs(float(value)) > 1.0e-12 for value in values)


@dataclass(frozen=True)
class SavedSceneNode3D:
    """One parent-local ECS node inside a Saved Scene definition."""

    id: str
    parent_id: str | None
    node: "Node3DRecord"

    def __post_init__(self) -> None:
        local_id = _validate_id(self.id, "saved scene object id")
        parent_id = (
            None
            if self.parent_id is None
            else _validate_id(self.parent_id, "saved scene parent id")
        )
        object.__setattr__(self, "id", local_id)
        object.__setattr__(self, "parent_id", parent_id)
        # A definition is a true snapshot: nested metadata must never keep a
        # mutable alias to the authored source node or to serialized metadata.
        detached = copy.deepcopy(self.node)
        if getattr(detached, "id", None) != local_id:
            detached = replace(detached, id=local_id)
        object.__setattr__(self, "node", detached)

    def validate(self) -> None:
        self.node.validate()
        if self.parent_id == self.id:
            raise SavedSceneError(f"saved scene object {self.id!r} cannot parent itself")
        if SAVED_SCENES_KEY in self.node.metadata or SAVED_SCENE_INSTANCES_KEY in self.node.metadata:
            raise SavedSceneError(
                f"saved scene object {self.id!r} cannot contain another Saved Scene"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "node": copy.deepcopy(self.node.to_dict()),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SavedSceneNode3D":
        Node3DRecord, _ = _record_types()
        if not isinstance(data, Mapping):
            raise TypeError("each saved scene object must be an object")
        if "id" not in data:
            raise SavedSceneError("saved scene object is missing required id")
        raw_node = data.get("node")
        if raw_node is None:
            # Accept a readable inline legacy draft, while always writing the
            # canonical nested ``node`` shape.
            raw_node = {
                key: value
                for key, value in data.items()
                if key not in {"parent_id"}
            }
        if not isinstance(raw_node, Mapping):
            raise TypeError("saved scene object node must be an object")
        node_data = dict(raw_node)
        node_data["id"] = str(data["id"])
        try:
            node = Node3DRecord.from_dict(node_data)
        except KeyError as exc:
            raise SavedSceneError(
                f"saved scene object {data['id']!r} is missing required {exc.args[0]}"
            ) from exc
        result = cls(str(data["id"]), data.get("parent_id"), node)
        result.validate()
        return result


def _graph_dict(graph: VisualGraph | Mapping[str, Any]) -> dict[str, Any]:
    value = graph if isinstance(graph, VisualGraph) else VisualGraph.from_dict(graph)
    value.validate()
    return value.to_dict()


@dataclass(frozen=True)
class SavedScene3D:
    """One canonical linked-scene definition stored once in authoring metadata."""

    id: str
    label: str
    root_id: str
    nodes: tuple[SavedSceneNode3D, ...]
    graphs: tuple[VisualGraph, ...] = ()
    schema: str = SAVED_SCENE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _validate_id(self.id, "saved scene id"))
        label = str(self.label).strip()
        if not label:
            raise SavedSceneError("saved scene name is required")
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "root_id", _validate_id(self.root_id, "saved scene root id"))
        object.__setattr__(self, "nodes", tuple(self.nodes))
        object.__setattr__(
            self,
            "graphs",
            tuple(
                sorted(
                    (
                        graph
                        if isinstance(graph, VisualGraph)
                        else VisualGraph.from_dict(graph)
                        for graph in self.graphs
                    ),
                    key=lambda graph: graph.id,
                )
            ),
        )

    def ordered_nodes(self) -> tuple[SavedSceneNode3D, ...]:
        """Return deterministic root-first, parent-before-child records."""

        by_parent: dict[str | None, list[SavedSceneNode3D]] = {}
        for item in self.nodes:
            by_parent.setdefault(item.parent_id, []).append(item)
        for values in by_parent.values():
            values.sort(key=lambda item: item.id)
        ordered: list[SavedSceneNode3D] = []

        def visit(node_id: str) -> None:
            item = next(value for value in self.nodes if value.id == node_id)
            ordered.append(item)
            for child in by_parent.get(node_id, ()):
                visit(child.id)

        visit(self.root_id)
        return tuple(ordered)

    def validate(
        self,
        mesh_ids: Iterable[str] | None = None,
        material_ids: Iterable[str] | None = None,
    ) -> None:
        if self.schema != SAVED_SCENE_SCHEMA:
            raise SavedSceneError(f"unsupported saved scene schema {self.schema!r}")
        if not 1 <= len(self.nodes) <= MAX_SAVED_SCENE_NODES:
            raise SavedSceneError(
                f"a Saved Scene needs 1 to {MAX_SAVED_SCENE_NODES} objects"
            )
        ids = [item.id for item in self.nodes]
        if len(ids) != len(set(ids)):
            raise SavedSceneError(f"saved scene {self.id!r} repeats an object id")
        by_id = {item.id: item for item in self.nodes}
        if self.root_id not in by_id:
            raise SavedSceneError(f"saved scene {self.id!r} root is missing")
        roots = [item.id for item in self.nodes if item.parent_id is None]
        if roots != [self.root_id]:
            raise SavedSceneError(
                f"saved scene {self.id!r} needs exactly one root ({self.root_id!r})"
            )
        mesh_set = None if mesh_ids is None else set(mesh_ids)
        material_set = None if material_ids is None else set(material_ids)
        for item in self.nodes:
            item.validate()
            if item.parent_id is not None and item.parent_id not in by_id:
                raise SavedSceneError(
                    f"saved scene object {item.id!r} uses missing parent {item.parent_id!r}"
                )
            if mesh_set is not None and item.node.mesh_id not in mesh_set:
                raise SavedSceneError(
                    f"saved scene object {item.id!r} uses missing mesh {item.node.mesh_id!r}"
                )
            if material_set is not None and item.node.material_id not in material_set:
                raise SavedSceneError(
                    f"saved scene object {item.id!r} uses missing material {item.node.material_id!r}"
                )
            if "player" in item.node.tags:
                raise SavedSceneError(
                    f"saved scene {self.id!r} cannot contain the unique Player"
                )
            if item.node.metadata.get("packed_kinematic") is not None:
                raise SavedSceneError(
                    f"saved scene object {item.id!r} cannot use a world-centred Movement Pattern"
                )
        # Parent walk rejects cycles and disconnected subgraphs.
        for local_id in ids:
            seen: set[str] = set()
            current: str | None = local_id
            while current is not None:
                if current in seen:
                    raise SavedSceneError(
                        f"saved scene {self.id!r} contains a parent cycle at {current!r}"
                    )
                seen.add(current)
                parent = by_id.get(current)
                if parent is None:
                    raise SavedSceneError(
                        f"saved scene object {local_id!r} is disconnected from its root"
                    )
                current = parent.parent_id
            if self.root_id not in seen:
                raise SavedSceneError(
                    f"saved scene object {local_id!r} is disconnected from root {self.root_id!r}"
                )
        children = {item.id: [] for item in self.nodes}
        for item in self.nodes:
            if item.parent_id is not None:
                children[item.parent_id].append(item)
        for item in self.nodes:
            if not children[item.id]:
                continue
            node = item.node
            if node.dynamic:
                raise SavedSceneError(
                    f"saved scene parent {item.id!r} cannot use Dynamic physics; children would not follow during play"
                )
            if _has_nonzero(node.angular_velocity):
                raise SavedSceneError(
                    f"saved scene parent {item.id!r} cannot spin; children would not follow during play"
                )
            if (
                node.metadata.get(ANIMATION_METADATA_KEY) is not None
                or node.metadata.get(ANIMATION_LIBRARY_METADATA_KEY) is not None
            ):
                raise SavedSceneError(
                    f"saved scene parent {item.id!r} cannot animate yet; animate a leaf object instead"
                )
            for child in children[item.id]:
                if not _is_uniform_scale(node.transform.scale) and not _is_identity_rotation(
                    child.node.transform.rotation
                ):
                    raise SavedSceneError(
                        f"saved scene parent {item.id!r} needs the same X, Y and Z Scale before a rotated child"
                    )
        graph_ids = [graph.id for graph in self.graphs]
        if len(graph_ids) != len(set(graph_ids)):
            raise SavedSceneError(f"saved scene {self.id!r} repeats Logic Blocks")
        graph_set = set(graph_ids)
        graphs_by_id = {graph.id: graph for graph in self.graphs}
        from .mobile3d import visual_graph_binding_ids

        for graph in self.graphs:
            graph.validate()
            _validate_relative_graph(graph, set(ids), self.root_id)
        for item in self.nodes:
            bindings = visual_graph_binding_ids(
                item.node.metadata.get("visual_graph"),
                f"saved scene object {item.id} Logic Blocks",
            )
            missing = sorted(set(bindings) - graph_set)
            if missing:
                raise SavedSceneError(
                    f"saved scene object {item.id!r} uses Logic Blocks not stored with the scene: "
                    + ", ".join(missing)
                )
            if children[item.id] and any(
                _graph_writes_transform(graphs_by_id[graph_id])
                for graph_id in bindings
            ):
                raise SavedSceneError(
                    f"saved scene parent {item.id!r} cannot let Logic Blocks move it; "
                    "children would not follow during play"
                )
        # Also proves deterministic traversal reaches every record.
        if len(self.ordered_nodes()) != len(self.nodes):
            raise SavedSceneError(f"saved scene {self.id!r} hierarchy is incomplete")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "id": self.id,
            "label": self.label,
            "root_id": self.root_id,
            "nodes": [item.to_dict() for item in self.ordered_nodes()],
            "graphs": [graph.to_dict() for graph in self.graphs],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SavedScene3D":
        if not isinstance(data, Mapping):
            raise TypeError("each saved scene must be an object")
        if "id" not in data:
            raise SavedSceneError("saved scene is missing required id")
        raw_nodes = data.get("nodes")
        if not isinstance(raw_nodes, (list, tuple)):
            raise TypeError(f"saved scene {data['id']!r} nodes must be a list")
        raw_graphs = data.get("graphs", ())
        if not isinstance(raw_graphs, (list, tuple)):
            raise TypeError(f"saved scene {data['id']!r} graphs must be a list")
        root_id = data.get("root_id", data.get("root"))
        if root_id is None:
            raise SavedSceneError(f"saved scene {data['id']!r} root is required")
        result = cls(
            str(data["id"]),
            str(data.get("label", data["id"])),
            str(root_id),
            tuple(SavedSceneNode3D.from_dict(item) for item in raw_nodes),
            tuple(VisualGraph.from_dict(item) for item in raw_graphs),
            str(data.get("schema", SAVED_SCENE_SCHEMA)),
        )
        result.validate()
        return result


@dataclass(frozen=True)
class SavedSceneInstance3D:
    """One compact placement of a linked definition."""

    id: str
    scene_id: str
    transform: "Transform3DRecord"
    schema: str = SAVED_SCENE_INSTANCE_SCHEMA

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _validate_id(self.id, "linked scene instance id"))
        object.__setattr__(self, "scene_id", _validate_id(self.scene_id, "saved scene id"))

    def validate(self) -> None:
        if self.schema != SAVED_SCENE_INSTANCE_SCHEMA:
            raise SavedSceneError(
                f"unsupported saved scene instance schema {self.schema!r}"
            )
        self.transform.validate()

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "id": self.id,
            "scene_id": self.scene_id,
            "transform": self.transform.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SavedSceneInstance3D":
        _, Transform3DRecord = _record_types()
        if not isinstance(data, Mapping):
            raise TypeError("each linked Saved Scene must be an object")
        unknown = set(data) - {"schema", "id", "scene_id", "scene", "transform"}
        if unknown:
            raise SavedSceneError(
                "linked Saved Scene contains unsupported fields: "
                + ", ".join(sorted(str(value) for value in unknown))
            )
        if "id" not in data:
            raise SavedSceneError("linked Saved Scene is missing required id")
        scene_id = data.get("scene_id", data.get("scene"))
        if scene_id is None:
            raise SavedSceneError(
                f"linked Saved Scene {data['id']!r} is missing its saved scene id"
            )
        result = cls(
            str(data["id"]),
            str(scene_id),
            Transform3DRecord.from_dict(data.get("transform")),
            str(data.get("schema", SAVED_SCENE_INSTANCE_SCHEMA)),
        )
        result.validate()
        return result


def _raw_values(metadata: Mapping[str, Any], key: str, label: str) -> list[Mapping[str, Any]]:
    raw = metadata.get(key, ())
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        values: list[Mapping[str, Any]] = []
        for item_id, value in sorted(raw.items(), key=lambda pair: str(pair[0])):
            if not isinstance(value, Mapping):
                raise TypeError(f"{label} {item_id!r} must be an object")
            item = dict(value)
            item.setdefault("id", str(item_id))
            values.append(item)
        return values
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        values = []
        for index, value in enumerate(raw):
            if not isinstance(value, Mapping):
                raise TypeError(f"{label} {index} must be an object")
            values.append(value)
        return values
    raise TypeError(f"metadata.{key} must be a list or object")


def saved_scenes_from_metadata(metadata: Mapping[str, Any]) -> tuple[SavedScene3D, ...]:
    definitions = tuple(
        SavedScene3D.from_dict(value)
        for value in _raw_values(metadata, SAVED_SCENES_KEY, "saved scene")
    )
    if len(definitions) > MAX_SAVED_SCENES:
        raise SavedSceneError(f"projects support at most {MAX_SAVED_SCENES} Saved Scenes")
    ids = [definition.id for definition in definitions]
    if len(ids) != len(set(ids)):
        raise SavedSceneError("saved scene ids must be unique")
    total = sum(len(definition.nodes) for definition in definitions)
    if total > MAX_SAVED_SCENE_DEFINITION_NODES:
        raise SavedSceneError(
            f"Saved Scenes contain {total} objects; project limit is {MAX_SAVED_SCENE_DEFINITION_NODES}"
        )
    return tuple(sorted(definitions, key=lambda definition: definition.id))


def saved_scene_instances_from_metadata(
    metadata: Mapping[str, Any],
) -> tuple[SavedSceneInstance3D, ...]:
    instances = tuple(
        SavedSceneInstance3D.from_dict(value)
        for value in _raw_values(
            metadata, SAVED_SCENE_INSTANCES_KEY, "linked Saved Scene"
        )
    )
    if len(instances) > MAX_SAVED_SCENE_INSTANCES:
        raise SavedSceneError(
            f"projects support at most {MAX_SAVED_SCENE_INSTANCES} linked Saved Scenes"
        )
    ids = [instance.id for instance in instances]
    if len(ids) != len(set(ids)):
        raise SavedSceneError("linked Saved Scene ids must be unique")
    return tuple(sorted(instances, key=lambda instance: instance.id))


def metadata_with_saved_scenes(
    metadata: Mapping[str, Any], definitions: Iterable[SavedScene3D]
) -> dict[str, Any]:
    result = _copy_metadata(metadata)
    ordered = tuple(sorted(definitions, key=lambda definition: definition.id))
    # Parse through the public reader to apply all collection limits too.
    if ordered:
        result[SAVED_SCENES_KEY] = [definition.to_dict() for definition in ordered]
        saved_scenes_from_metadata(result)
    else:
        result.pop(SAVED_SCENES_KEY, None)
    return result


def metadata_with_saved_scene_instances(
    metadata: Mapping[str, Any], instances: Iterable[SavedSceneInstance3D]
) -> dict[str, Any]:
    result = _copy_metadata(metadata)
    ordered = tuple(sorted(instances, key=lambda instance: instance.id))
    if ordered:
        result[SAVED_SCENE_INSTANCES_KEY] = [instance.to_dict() for instance in ordered]
        saved_scene_instances_from_metadata(result)
    else:
        result.pop(SAVED_SCENE_INSTANCES_KEY, None)
    return result


def _semantic_constant_nodes(graph_data: Mapping[str, Any]) -> set[str]:
    return {
        str(link.get("source_node", ""))
        for link in graph_data.get("links", ())
        if isinstance(link, Mapping)
        and str(link.get("target_port", "")) in _ENTITY_FIELDS
    }


def _graph_writes_transform(graph: VisualGraph) -> bool:
    """Conservatively detect runtime transform authority on a flat parent."""

    for node in graph.nodes:
        if node.type != "action.set_component":
            continue
        component = node.properties.get("component")
        # A connected/dynamic component name is not statically provable safe.
        if component in (None, "", "transform"):
            return True
    return False


def _relative_value(value: Any, selected: Mapping[str, str], label: str) -> Any:
    if value in (None, ""):
        return value
    if not isinstance(value, str):
        return value
    if value in selected:
        return selected[value]
    if value.startswith(_RELATIVE_NODE_PREFIX) or value == _RELATIVE_ROOT:
        return value
    raise SavedSceneError(
        f"{label} points outside the selected objects ({value!r}); use This Object or include that object"
    )


def _capture_graph(
    graph: VisualGraph, selected: Mapping[str, str]
) -> VisualGraph:
    data = graph.to_dict()
    constants = _semantic_constant_nodes(data)
    for node in data.get("nodes", ()):
        if not isinstance(node, dict):
            continue
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            continue
        for key in tuple(properties):
            if key in _ENTITY_FIELDS:
                properties[key] = _relative_value(
                    properties[key], selected, f"Logic Block {node.get('id', '?')} {key}"
                )
        if node.get("id") in constants and node.get("type") == "value.constant":
            properties["value"] = _relative_value(
                properties.get("value"),
                selected,
                f"Logic Block {node.get('id', '?')} object value",
            )
    result = VisualGraph.from_dict(data)
    result.validate()
    return result


def _relative_transform(
    parent: "Transform3DRecord", child: "Transform3DRecord"
) -> "Transform3DRecord":
    _, Transform3DRecord = _record_types()
    parent_scale = tuple(float(value) for value in parent.scale)
    if any(abs(value) <= 1.0e-12 for value in parent_scale):
        raise SavedSceneError("Saved Scene parents cannot have zero scale")
    inverse_rotation = quat_inverse(parent.rotation)
    delta = tuple(
        float(child.translation[index]) - float(parent.translation[index])
        for index in range(3)
    )
    unrotated = quat_rotate(inverse_rotation, delta)
    translation = tuple(unrotated[index] / parent_scale[index] for index in range(3))
    rotation = quat_normalize(quat_mul(inverse_rotation, child.rotation))
    scale = tuple(float(child.scale[index]) / parent_scale[index] for index in range(3))
    result = Transform3DRecord(translation, rotation, scale)
    result.validate()
    return result


def make_saved_scene(
    scene_id: str,
    label: str,
    nodes: Iterable[SavedSceneNode3D | "Node3DRecord"],
    root_id: str,
    graphs: Iterable[VisualGraph | Mapping[str, Any]] = (),
) -> SavedScene3D:
    """Capture a definition; plain nodes are authored world-space records.

    Explicit :class:`SavedSceneNode3D` values are already parent-local.  The
    convenience plain-node form uses the named root as the pivot, preserving
    its rotation/scale while zeroing its translation, and makes other selected
    objects direct children with root-local transforms.
    """

    values = tuple(nodes)
    if not values:
        raise SavedSceneError("choose at least one object for the Saved Scene")
    explicit = [isinstance(value, SavedSceneNode3D) for value in values]
    if any(explicit) and not all(explicit):
        raise TypeError("use either parent-local SavedSceneNode3D values or plain scene nodes")
    if all(explicit):
        records = tuple(value for value in values if isinstance(value, SavedSceneNode3D))
    else:
        plain = tuple(values)
        by_id = {str(value.id): value for value in plain}
        if len(by_id) != len(plain):
            raise SavedSceneError("selected Saved Scene objects need unique ids")
        if root_id not in by_id:
            raise SavedSceneError("the Saved Scene root must be selected")
        root = by_id[root_id]
        _, Transform3DRecord = _record_types()
        root_local = Transform3DRecord(
            (0.0, 0.0, 0.0), root.transform.rotation, root.transform.scale
        )
        records_list: list[SavedSceneNode3D] = [
            SavedSceneNode3D(
                root_id,
                None,
                replace(root, id=root_id, transform=root_local),
            )
        ]
        inverse_root_rotation = quat_inverse(root.transform.rotation)
        for local_id in sorted(value for value in by_id if value != root_id):
            source = by_id[local_id]
            local_transform = _relative_transform(root.transform, source.transform)
            local_velocity = quat_rotate(inverse_root_rotation, source.velocity)
            local_angular = quat_rotate(
                inverse_root_rotation, source.angular_velocity
            )
            local_metadata = _copy_metadata(source.metadata)
            _localize_animation_metadata(local_metadata, root.transform)
            records_list.append(
                SavedSceneNode3D(
                    local_id,
                    root_id,
                    replace(
                        source,
                        id=local_id,
                        transform=local_transform,
                        velocity=local_velocity,
                        angular_velocity=local_angular,
                        metadata=local_metadata,
                    ),
                )
            )
        records = tuple(records_list)
    selected_refs = {
        item.id: (_RELATIVE_ROOT if item.id == root_id else _RELATIVE_NODE_PREFIX + item.id)
        for item in records
    }
    captured_graphs = tuple(
        _capture_graph(
            graph if isinstance(graph, VisualGraph) else VisualGraph.from_dict(graph),
            selected_refs,
        )
        for graph in graphs
    )
    result = SavedScene3D(
        str(scene_id), str(label), str(root_id), records, captured_graphs
    )
    result.validate()
    return result


def instantiate_saved_scene(
    definition: SavedScene3D,
    instance_id: str,
    transform: "Transform3DRecord | Mapping[str, Any] | None" = None,
) -> SavedSceneInstance3D:
    _, Transform3DRecord = _record_types()
    definition.validate()
    if transform is None:
        value = Transform3DRecord()
    elif isinstance(transform, Mapping):
        value = Transform3DRecord.from_dict(transform)
    else:
        value = transform
    result = SavedSceneInstance3D(str(instance_id), definition.id, value)
    result.validate()
    return result


def materialized_node_id(instance_id: str, local_id: str, root_id: str) -> str:
    return instance_id if local_id == root_id else f"{instance_id}{SAVED_SCENE_ID_SEPARATOR}{local_id}"


def _compose_transform(
    parent: "Transform3DRecord", local: "Transform3DRecord"
) -> "Transform3DRecord":
    _, Transform3DRecord = _record_types()
    if not _is_uniform_scale(parent.scale) and not _is_identity_rotation(
        local.rotation
    ):
        raise SavedSceneError(
            "a linked Saved Scene needs the same X, Y and Z group Scale before "
            "a rotated child; this flat runtime cannot represent shear"
        )
    scaled = tuple(
        float(local.translation[index]) * float(parent.scale[index])
        for index in range(3)
    )
    rotated = quat_rotate(parent.rotation, scaled)
    translation = tuple(
        float(parent.translation[index]) + rotated[index] for index in range(3)
    )
    rotation = quat_normalize(quat_mul(parent.rotation, local.rotation))
    scale = tuple(
        float(parent.scale[index]) * float(local.scale[index]) for index in range(3)
    )
    result = Transform3DRecord(translation, rotation, scale)
    result.validate()
    return result


def _token_value(value: Any, ids: Mapping[str, str], root_id: str) -> Any:
    if value == _RELATIVE_ROOT:
        return ids[root_id]
    if isinstance(value, str) and value.startswith(_RELATIVE_NODE_PREFIX):
        local_id = value[len(_RELATIVE_NODE_PREFIX) :]
        if local_id not in ids:
            raise SavedSceneError(
                f"Logic Blocks refer to missing Saved Scene object {local_id!r}"
            )
        return ids[local_id]
    if value in (None, ""):
        return value
    if isinstance(value, str) and value in ids:
        # Hand-authored v2 JSON may name a local member directly. Normalize it
        # just like the canonical @root/@node tokens instead of leaking a local
        # id into the flat runtime.
        return ids[value]
    if isinstance(value, str):
        raise SavedSceneError(
            f"Logic Blocks point outside this Saved Scene ({value!r}); "
            "use This Object or a member of the Saved Scene"
        )
    return value


def _validate_relative_graph(
    graph: VisualGraph, local_ids: set[str], root_id: str
) -> None:
    ids = {local_id: local_id for local_id in local_ids}
    ids[root_id] = root_id
    _materialized_graph(graph, graph.id, ids, root_id)


def _materialized_graph(
    graph: VisualGraph,
    graph_id: str,
    ids: Mapping[str, str],
    root_id: str,
) -> VisualGraph:
    data = graph.to_dict()
    data["id"] = graph_id
    constants = _semantic_constant_nodes(data)
    for node in data.get("nodes", ()):
        if not isinstance(node, dict):
            continue
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            continue
        for key in tuple(properties):
            if key in _ENTITY_FIELDS:
                properties[key] = _token_value(properties[key], ids, root_id)
        if node.get("id") in constants and node.get("type") == "value.constant":
            properties["value"] = _token_value(
                properties.get("value"), ids, root_id
            )
    result = VisualGraph.from_dict(data)
    result.validate()
    return result


def _graph_has_tokens(graph: VisualGraph) -> bool:
    data = graph.to_dict()
    constants = _semantic_constant_nodes(data)
    for node in data.get("nodes", ()):
        if not isinstance(node, Mapping):
            continue
        properties = node.get("properties", {})
        if not isinstance(properties, Mapping):
            continue
        values = [
            value for key, value in properties.items() if key in _ENTITY_FIELDS
        ]
        if node.get("id") in constants and node.get("type") == "value.constant":
            values.append(properties.get("value"))
        if any(
            value == _RELATIVE_ROOT
            or (isinstance(value, str) and value.startswith(_RELATIVE_NODE_PREFIX))
            for value in values
        ):
            return True
    return False


def _safe_graph_id(prefix: str, graph_id: str) -> str:
    # Visual graph IDs accept arbitrary non-empty text, but keeping generated
    # IDs readable makes native diagnostics and child-facing errors useful.
    return f"saved_scene{SAVED_SCENE_ID_SEPARATOR}{prefix}{SAVED_SCENE_ID_SEPARATOR}{graph_id}"


def _unique_graph_id(candidate: str, graphs: Mapping[str, VisualGraph]) -> str:
    if candidate not in graphs:
        return candidate
    suffix = 2
    while f"{candidate}_{suffix}" in graphs:
        suffix += 1
    return f"{candidate}_{suffix}"


def _remap_bindings(raw: Any, mapping: Mapping[str, str]) -> Any:
    if raw is None:
        return None
    if isinstance(raw, str):
        return mapping.get(raw, raw)
    if isinstance(raw, (list, tuple)):
        return [mapping.get(str(value), str(value)) for value in raw]
    return raw


def _rebase_animation_metadata(
    metadata: dict[str, Any], parent: "Transform3DRecord"
) -> None:
    """Rotate/scale relative animation translation keys into flat world axes."""

    def rebase_animation(raw: Any) -> None:
        if not isinstance(raw, dict):
            return
        keys = raw.get("keys", ())
        if not isinstance(keys, list):
            return
        for key in keys:
            if not isinstance(key, dict):
                continue
            values = key.get("translation")
            if not isinstance(values, (list, tuple)) or len(values) != 3:
                continue
            scaled = tuple(
                float(values[index]) * float(parent.scale[index])
                for index in range(3)
            )
            key["translation"] = list(quat_rotate(parent.rotation, scaled))

    legacy = metadata.get(ANIMATION_METADATA_KEY)
    rebase_animation(legacy)
    library = metadata.get(ANIMATION_LIBRARY_METADATA_KEY)
    if isinstance(library, dict):
        clips = library.get("clips", ())
        if isinstance(clips, list):
            for clip in clips:
                if isinstance(clip, dict):
                    rebase_animation(clip.get("animation"))


def _localize_animation_metadata(
    metadata: dict[str, Any], parent: "Transform3DRecord"
) -> None:
    """Convert authored world-axis animation offsets into parent-local axes."""

    inverse_rotation = quat_inverse(parent.rotation)
    parent_scale = tuple(float(value) for value in parent.scale)
    if any(abs(value) <= 1.0e-12 for value in parent_scale):
        raise SavedSceneError("Saved Scene parents cannot have zero scale")

    def localize_animation(raw: Any) -> None:
        if not isinstance(raw, dict):
            return
        keys = raw.get("keys", ())
        if not isinstance(keys, list):
            return
        for key in keys:
            if not isinstance(key, dict):
                continue
            values = key.get("translation")
            if not isinstance(values, (list, tuple)) or len(values) != 3:
                continue
            unrotated = quat_rotate(
                inverse_rotation, tuple(float(value) for value in values)
            )
            key["translation"] = [
                unrotated[index] / parent_scale[index] for index in range(3)
            ]

    localize_animation(metadata.get(ANIMATION_METADATA_KEY))
    library = metadata.get(ANIMATION_LIBRARY_METADATA_KEY)
    if isinstance(library, dict):
        clips = library.get("clips", ())
        if isinstance(clips, list):
            for clip in clips:
                if isinstance(clip, dict):
                    localize_animation(clip.get("animation"))


def _definition_nodes(
    definition: SavedScene3D,
    instance: SavedSceneInstance3D,
    graph_mapping: Mapping[str, str],
) -> tuple["Node3DRecord", ...]:
    world_transforms: dict[str, Any] = {}
    ids = {
        item.id: materialized_node_id(instance.id, item.id, definition.root_id)
        for item in definition.nodes
    }
    result: list[Any] = []
    for item in definition.ordered_nodes():
        parent_transform = (
            instance.transform
            if item.parent_id is None
            else world_transforms[item.parent_id]
        )
        transform = _compose_transform(parent_transform, item.node.transform)
        world_transforms[item.id] = transform
        metadata = _copy_metadata(item.node.metadata)
        binding = _remap_bindings(metadata.get("visual_graph"), graph_mapping)
        if binding is not None:
            metadata["visual_graph"] = binding
        _rebase_animation_metadata(metadata, parent_transform)
        metadata[SAVED_SCENE_RUNTIME_KEY] = {
            "scene_id": definition.id,
            "instance_id": instance.id,
            "local_id": item.id,
            "root_id": definition.root_id,
            "instance_root_id": instance.id,
        }
        result.append(
            replace(
                item.node,
                id=ids[item.id],
                transform=transform,
                velocity=quat_rotate(parent_transform.rotation, item.node.velocity),
                angular_velocity=quat_rotate(
                    parent_transform.rotation, item.node.angular_velocity
                ),
                metadata=metadata,
            )
        )
    return tuple(result)


def materialize_saved_scenes(project: "Mobile3DProject") -> "Mobile3DProject":
    """Return one flat, deterministic runtime project without authoring records."""

    candidate = copy.deepcopy(project)
    metadata = getattr(candidate, "metadata", None)
    if not isinstance(metadata, Mapping):
        raise TypeError("mobile 3D project metadata must be an object")
    if SAVED_SCENES_KEY not in metadata and SAVED_SCENE_INSTANCES_KEY not in metadata:
        return candidate
    definitions = saved_scenes_from_metadata(metadata)
    instances = saved_scene_instances_from_metadata(metadata)
    definition_map = {definition.id: definition for definition in definitions}
    for definition in definitions:
        definition.validate(candidate.meshes, candidate.materials)
    for instance in instances:
        instance.validate()
        if instance.scene_id not in definition_map:
            raise SavedSceneError(
                f"linked Saved Scene {instance.id!r} uses missing definition {instance.scene_id!r}"
            )
    existing_ids = {node.id for node in candidate.nodes}
    generated_ids: set[str] = set()
    for instance in instances:
        definition = definition_map[instance.scene_id]
        for item in definition.nodes:
            node_id = materialized_node_id(instance.id, item.id, definition.root_id)
            if node_id in existing_ids or node_id in generated_ids:
                raise SavedSceneError(
                    f"linked Saved Scene would create duplicate object id {node_id!r}"
                )
            generated_ids.add(node_id)
    if len(candidate.nodes) + len(generated_ids) > MAX_MATERIALIZED_SCENE_NODES:
        raise SavedSceneError(
            f"linked Saved Scenes expand to more than {MAX_MATERIALIZED_SCENE_NODES} runtime objects"
        )

    from .mobile3d import visual_graphs_from_metadata

    graph_map = {
        graph.id: graph for graph in visual_graphs_from_metadata(candidate.metadata)
    }
    shared_graph_ids: dict[tuple[str, str], str] = {}
    generated_nodes: list[Any] = []
    for instance in instances:
        definition = definition_map[instance.scene_id]
        ids = {
            item.id: materialized_node_id(instance.id, item.id, definition.root_id)
            for item in definition.nodes
        }
        binding_map: dict[str, str] = {}
        for graph in definition.graphs:
            if _graph_has_tokens(graph):
                graph_id = _unique_graph_id(
                    _safe_graph_id(instance.id, graph.id), graph_map
                )
                materialized_graph = _materialized_graph(
                    graph, graph_id, ids, definition.root_id
                )
                graph_map[graph_id] = materialized_graph
            else:
                key = (definition.id, graph.id)
                graph_id = shared_graph_ids.get(key, "")
                if not graph_id:
                    preferred = _safe_graph_id(definition.id, graph.id)
                    preferred_graph = _materialized_graph(
                        graph, preferred, ids, definition.root_id
                    )
                    existing = graph_map.get(preferred)
                    if existing is not None and existing.to_dict() == preferred_graph.to_dict():
                        graph_id = preferred
                    else:
                        graph_id = _unique_graph_id(preferred, graph_map)
                        graph_map[graph_id] = _materialized_graph(
                            graph, graph_id, ids, definition.root_id
                        )
                    shared_graph_ids[key] = graph_id
            binding_map[graph.id] = graph_id
        generated_nodes.extend(
            _definition_nodes(definition, instance, binding_map)
        )
    candidate.nodes = (*candidate.nodes, *generated_nodes)
    flat_metadata = _copy_metadata(candidate.metadata)
    flat_metadata.pop(SAVED_SCENES_KEY, None)
    flat_metadata.pop(SAVED_SCENE_INSTANCES_KEY, None)
    if graph_map:
        flat_metadata["visual_graphs"] = [
            graph_map[key].to_dict() for key in sorted(graph_map)
        ]
    elif "visual_graphs" in flat_metadata:
        flat_metadata["visual_graphs"] = []
    candidate.metadata = flat_metadata
    return candidate


def bake_saved_scene_instance(
    project: "Mobile3DProject", instance_id: str
) -> "Mobile3DProject":
    """Commit one linked copy as ordinary flat nodes and remove its descriptor."""

    wanted = str(instance_id)
    definitions = saved_scenes_from_metadata(project.metadata)
    instances = saved_scene_instances_from_metadata(project.metadata)
    chosen = next((instance for instance in instances if instance.id == wanted), None)
    if chosen is None:
        raise SavedSceneError(f"linked Saved Scene {wanted!r} is missing")
    temporary = copy.deepcopy(project)
    temporary.metadata = metadata_with_saved_scene_instances(
        temporary.metadata, (chosen,)
    )
    flat = materialize_saved_scenes(temporary)
    authored_count = len(project.nodes)
    baked_nodes = []
    for node in flat.nodes[authored_count:]:
        metadata = _copy_metadata(node.metadata)
        metadata.pop(SAVED_SCENE_RUNTIME_KEY, None)
        baked_nodes.append(replace(node, metadata=metadata))
    result = copy.deepcopy(project)
    result.nodes = (*result.nodes, *baked_nodes)
    metadata = _copy_metadata(flat.metadata)
    metadata = metadata_with_saved_scenes(metadata, definitions)
    metadata = metadata_with_saved_scene_instances(
        metadata, (instance for instance in instances if instance.id != wanted)
    )
    result.metadata = metadata
    return result


def unlink_saved_scene_instance(
    project: "Mobile3DProject", instance_id: str
) -> "Mobile3DProject":
    return bake_saved_scene_instance(project, instance_id)


def saved_scene_owner_id(node: "Node3DRecord") -> str | None:
    raw = node.metadata.get(SAVED_SCENE_RUNTIME_KEY)
    if not isinstance(raw, Mapping):
        return None
    value = raw.get("instance_root_id")
    return str(value) if isinstance(value, str) and value else None


__all__ = [
    "MAX_MATERIALIZED_SCENE_NODES",
    "MAX_SAVED_SCENE_DEFINITION_NODES",
    "MAX_SAVED_SCENE_INSTANCES",
    "MAX_SAVED_SCENE_NODES",
    "MAX_SAVED_SCENES",
    "SAVED_SCENE_INSTANCES_KEY",
    "SAVED_SCENE_INSTANCE_SCHEMA",
    "SAVED_SCENE_RUNTIME_KEY",
    "SAVED_SCENE_SCHEMA",
    "SAVED_SCENES_KEY",
    "SavedScene3D",
    "SavedSceneError",
    "SavedSceneInstance3D",
    "SavedSceneNode3D",
    "bake_saved_scene_instance",
    "instantiate_saved_scene",
    "make_saved_scene",
    "materialize_saved_scenes",
    "materialized_node_id",
    "metadata_with_saved_scene_instances",
    "metadata_with_saved_scenes",
    "saved_scene_instances_from_metadata",
    "saved_scene_owner_id",
    "saved_scenes_from_metadata",
    "unlink_saved_scene_instance",
]
