"""Compact authoring-time reusable objects for mobile 3D projects.

Reusable objects are deliberately *not* a second runtime scene graph.  A
definition stores one validated :class:`~ugts_kc3.mobile3d.Node3DRecord` and an
instance becomes an ordinary flat ECS node.  Native KC3D export therefore pays
only for objects that are actually placed in the scene; the reusable library
stays in authoring metadata and never needs an Android runtime parser.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import copy
from typing import Any, Iterable, Mapping, Sequence

from .mobile3d import Node3DRecord, Transform3DRecord


REUSABLE_OBJECTS_KEY = "reusable_objects"
REUSABLE_INSTANCE_KEY = "reusable_object"
REUSABLE_OBJECT_SCHEMA = "ugts-studio-reusable-object-1"
MAX_REUSABLE_OBJECTS = 64


@dataclass(frozen=True)
class ReusableObject3D:
    """One readable authoring definition that flattens to an ordinary node."""

    id: str
    label: str
    node: Node3DRecord
    schema: str = REUSABLE_OBJECT_SCHEMA

    def validate(
        self,
        mesh_ids: Iterable[str] | None = None,
        material_ids: Iterable[str] | None = None,
    ) -> None:
        if self.schema != REUSABLE_OBJECT_SCHEMA:
            raise ValueError(
                f"unsupported reusable-object schema {self.schema!r}"
            )
        if not self.id.strip():
            raise ValueError("reusable object id is required")
        if not self.label.strip():
            raise ValueError("reusable object name is required")
        self.node.validate()
        if mesh_ids is not None and self.node.mesh_id not in set(mesh_ids):
            raise ValueError(
                f"reusable object {self.id!r} uses missing mesh "
                f"{self.node.mesh_id!r}"
            )
        if material_ids is not None and self.node.material_id not in set(material_ids):
            raise ValueError(
                f"reusable object {self.id!r} uses missing material "
                f"{self.node.material_id!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "id": self.id,
            "label": self.label,
            "node": self.node.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReusableObject3D":
        if "id" not in data:
            raise ValueError("reusable object is missing required id")
        raw_node = data.get("node")
        if not isinstance(raw_node, Mapping):
            raise TypeError("reusable object node must be an object")
        try:
            node = Node3DRecord.from_dict(raw_node)
        except KeyError as exc:
            raise ValueError(
                f"reusable object {data['id']!r} node is missing required {exc.args[0]}"
            ) from exc
        reusable = cls(
            str(data["id"]),
            str(data.get("label", data["id"])),
            node,
            str(data.get("schema", REUSABLE_OBJECT_SCHEMA)),
        )
        reusable.validate()
        return reusable


def _raw_reusable_values(metadata: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = metadata.get(REUSABLE_OBJECTS_KEY, ())
    if raw is None:
        return []
    if isinstance(raw, Mapping):
        values: list[Mapping[str, Any]] = []
        for reusable_id, value in sorted(raw.items(), key=lambda pair: str(pair[0])):
            if not isinstance(value, Mapping):
                raise TypeError(f"reusable object {reusable_id!r} must be an object")
            item = dict(value)
            item.setdefault("id", str(reusable_id))
            values.append(item)
        return values
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        values = []
        for index, value in enumerate(raw):
            if not isinstance(value, Mapping):
                raise TypeError(f"reusable object {index} must be an object")
            values.append(value)
        return values
    raise TypeError("metadata.reusable_objects must be a list or object")


def reusable_objects_from_metadata(
    metadata: Mapping[str, Any],
) -> tuple[ReusableObject3D, ...]:
    """Return validated definitions in deterministic id order."""

    definitions = tuple(
        ReusableObject3D.from_dict(value) for value in _raw_reusable_values(metadata)
    )
    if len(definitions) > MAX_REUSABLE_OBJECTS:
        raise ValueError(
            f"projects support at most {MAX_REUSABLE_OBJECTS} reusable objects"
        )
    ids = [definition.id for definition in definitions]
    if len(ids) != len(set(ids)):
        raise ValueError("reusable object ids must be unique")
    return tuple(sorted(definitions, key=lambda definition: definition.id))


def metadata_with_reusable_objects(
    metadata: Mapping[str, Any], definitions: Iterable[ReusableObject3D]
) -> dict[str, Any]:
    """Return a detached metadata snapshot with canonical sorted definitions."""

    result = copy.deepcopy(dict(metadata))
    ordered = tuple(sorted(definitions, key=lambda definition: definition.id))
    if len(ordered) > MAX_REUSABLE_OBJECTS:
        raise ValueError(
            f"projects support at most {MAX_REUSABLE_OBJECTS} reusable objects"
        )
    ids = [definition.id for definition in ordered]
    if len(ids) != len(set(ids)):
        raise ValueError("reusable object ids must be unique")
    for definition in ordered:
        definition.validate()
    if ordered:
        result[REUSABLE_OBJECTS_KEY] = [definition.to_dict() for definition in ordered]
    else:
        result.pop(REUSABLE_OBJECTS_KEY, None)
    return result


def reusable_source_id(node: Node3DRecord) -> str | None:
    """Return the source definition id for an instance, if it has one."""

    if REUSABLE_INSTANCE_KEY not in node.metadata:
        return None
    raw = node.metadata.get(REUSABLE_INSTANCE_KEY)
    if isinstance(raw, str) and raw.strip():
        return raw
    raise ValueError(
        f"node {node.id!r} metadata.{REUSABLE_INSTANCE_KEY} must be a "
        "non-empty saved object id string"
    )


def make_reusable_object(
    reusable_id: str, label: str, source: Node3DRecord
) -> ReusableObject3D:
    """Capture one source without recursively storing its prior instance link."""

    metadata = copy.deepcopy(source.metadata)
    metadata.pop(REUSABLE_INSTANCE_KEY, None)
    definition = ReusableObject3D(
        str(reusable_id),
        str(label).strip(),
        replace(source, metadata=metadata),
    )
    definition.validate()
    return definition


def instantiate_reusable_object(
    definition: ReusableObject3D,
    node_id: str,
    *,
    translation_offset: tuple[float, float, float] = (1.0, 0.0, 1.0),
) -> Node3DRecord:
    """Flatten a definition into a normal node; referenced resources stay shared."""

    definition.validate()
    source = definition.node
    offset = tuple(float(value) for value in translation_offset)
    if len(offset) != 3:
        raise ValueError("reusable object translation offset requires three values")
    translation = tuple(
        source.transform.translation[index] + offset[index] for index in range(3)
    )
    metadata = copy.deepcopy(source.metadata)
    metadata[REUSABLE_INSTANCE_KEY] = definition.id
    instance = replace(
        source,
        id=str(node_id),
        transform=Transform3DRecord(
            translation,
            source.transform.rotation,
            source.transform.scale,
        ),
        metadata=metadata,
    )
    instance.validate()
    return instance


__all__ = [
    "REUSABLE_INSTANCE_KEY",
    "MAX_REUSABLE_OBJECTS",
    "REUSABLE_OBJECTS_KEY",
    "REUSABLE_OBJECT_SCHEMA",
    "ReusableObject3D",
    "instantiate_reusable_object",
    "make_reusable_object",
    "metadata_with_reusable_objects",
    "reusable_objects_from_metadata",
    "reusable_source_id",
]
