"""Sparse deterministic visual-transform hierarchy asset for Android.

``KC3D392`` deliberately keeps its established flat node records byte-for-byte
compatible.  Projects that use parent-local transforms receive this separate
``KCHI392`` sidecar.  Each payload record is only the canonical KC3D child and
parent index; projects without parents produce ``b""`` and no asset.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import struct
from typing import Any, Mapping

from .hierarchy3d import MAX_HIERARCHY_DEPTH_3D, build_hierarchy3d


HIERARCHY_PACK_ASSET = "hierarchies.kchi"
HIERARCHY_PACK_MAGIC = b"KCHI392\0"
HIERARCHY_PACK_ENDIAN = 0x01020304
HIERARCHY_PACK_VERSION = 1
HIERARCHY_HEADER_BYTES = 24
HIERARCHY_LINK_BYTES = 8
MAX_HIERARCHY_DEPTH = MAX_HIERARCHY_DEPTH_3D
MAX_HIERARCHY_LINKS = 65535
MAX_HIERARCHY_PACK_BYTES = (
    HIERARCHY_HEADER_BYTES + MAX_HIERARCHY_LINKS * HIERARCHY_LINK_BYTES
)

_SAVED_SCENE_METADATA_KEYS = frozenset({"saved_scenes", "saved_scene_instances"})


class HierarchyPackError(ValueError):
    """An authoring or binary-format error in a native hierarchy pack."""


@dataclass(frozen=True)
class HierarchyLinkSpec:
    child_index: int
    parent_index: int
    depth: int


def _materialized_project(project: Any) -> Any:
    metadata = getattr(project, "metadata", {})
    if not isinstance(metadata, Mapping) or not any(
        key in metadata for key in _SAVED_SCENE_METADATA_KEYS
    ):
        return project
    from .saved_scene import materialize_saved_scenes

    return materialize_saved_scenes(project)


def _validated_links(
    pairs: tuple[tuple[int, int], ...], *, node_count: int | None
) -> tuple[HierarchyLinkSpec, ...]:
    if len(pairs) > MAX_HIERARCHY_LINKS:
        raise HierarchyPackError(
            f"Android hierarchy packs support at most {MAX_HIERARCHY_LINKS} links"
        )
    if node_count is not None:
        if isinstance(node_count, bool) or not isinstance(node_count, int):
            raise TypeError("node_count must be an integer or None")
        if node_count < 0:
            raise ValueError("node_count cannot be negative")

    parent_by_child: dict[int, int] = {}
    previous_child = -1
    for child_index, parent_index in pairs:
        if child_index <= previous_child:
            raise HierarchyPackError(
                "hierarchy links must use strictly increasing child indices"
            )
        previous_child = child_index
        if child_index == parent_index:
            raise HierarchyPackError("hierarchy child cannot parent itself")
        if node_count is not None and (
            child_index >= node_count or parent_index >= node_count
        ):
            raise HierarchyPackError("hierarchy link references a missing scene node")
        parent_by_child[child_index] = parent_index

    depths: dict[int, int] = {}
    for child_index in parent_by_child:
        if child_index in depths:
            continue
        path: list[int] = []
        path_indices: dict[int, int] = {}
        current = child_index
        while current in parent_by_child and current not in depths:
            if current in path_indices:
                raise HierarchyPackError("hierarchy links contain a cycle")
            path_indices[current] = len(path)
            path.append(current)
            current = parent_by_child[current]
        value = depths.get(current, 0)
        for item in reversed(path):
            value += 1
            if value > MAX_HIERARCHY_DEPTH:
                raise HierarchyPackError(
                    f"hierarchy depth exceeds {MAX_HIERARCHY_DEPTH} edges"
                )
            depths[item] = value
    return tuple(
        HierarchyLinkSpec(child, parent, depths[child]) for child, parent in pairs
    )


def _collect_materialized_links(project: Any) -> tuple[HierarchyLinkSpec, ...]:
    project.validate()
    nodes = tuple(getattr(project, "nodes", ()))
    hierarchy = build_hierarchy3d(nodes)
    node_indices = {str(node.id): index for index, node in enumerate(nodes)}
    pairs: list[tuple[int, int]] = []
    for child_index, node in enumerate(nodes):
        parent_id = hierarchy.parent_by_id[str(node.id)]
        if parent_id is None:
            continue
        try:
            parent_index = node_indices[parent_id]
        except KeyError as error:
            raise HierarchyPackError(
                f"node {node.id!r} references missing parent {parent_id!r}"
            ) from error
        pairs.append((child_index, parent_index))
    return _validated_links(tuple(pairs), node_count=len(nodes))


def collect_hierarchy_links(project: Any) -> tuple[HierarchyLinkSpec, ...]:
    """Return canonical KC3D-index links for a validated, materialized project."""

    return _collect_materialized_links(_materialized_project(project))


def compile_hierarchy_pack_bytes(project: Any) -> bytes:
    """Compile canonical parent links, or return ``b''`` when hierarchy is unused."""

    project = _materialized_project(project)
    links = _collect_materialized_links(project)
    if not links:
        return b""
    output = bytearray(HIERARCHY_PACK_MAGIC)
    output.extend(
        struct.pack(
            "<IIII",
            HIERARCHY_PACK_ENDIAN,
            HIERARCHY_PACK_VERSION,
            len(links),
            0,
        )
    )
    for link in links:
        output.extend(struct.pack("<II", link.child_index, link.parent_index))
    result = bytes(output)
    # Keep compiler and standalone reader on the exact same strict boundary.
    inspect_hierarchy_pack(result, node_count=len(getattr(project, "nodes", ())))
    return result


def write_hierarchy_pack(project: Any, path: str | Path) -> Path | None:
    """Write the optional KCHI sidecar; an unused hierarchy creates no file."""

    data = compile_hierarchy_pack_bytes(project)
    if not data:
        return None
    result = Path(path)
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_bytes(data)
    return result


def inspect_hierarchy_pack(
    data_or_path: bytes | str | Path, *, node_count: int | None = None
) -> dict[str, Any]:
    """Strictly inspect every fixed-size KCHI record and graph invariant."""

    data = (
        Path(data_or_path).read_bytes()
        if isinstance(data_or_path, (str, Path))
        else bytes(data_or_path)
    )
    if len(data) > MAX_HIERARCHY_PACK_BYTES:
        raise HierarchyPackError("hierarchy asset exceeds its byte limit")
    if len(data) < HIERARCHY_HEADER_BYTES:
        raise HierarchyPackError("truncated hierarchy asset")
    if data[:8] != HIERARCHY_PACK_MAGIC:
        raise HierarchyPackError("hierarchy magic mismatch")
    endian, version, link_count, reserved = struct.unpack_from("<IIII", data, 8)
    if endian != HIERARCHY_PACK_ENDIAN:
        raise HierarchyPackError("hierarchy endian marker mismatch")
    if version != HIERARCHY_PACK_VERSION:
        raise HierarchyPackError("unsupported hierarchy version")
    if reserved:
        raise HierarchyPackError("hierarchy header reserved field is nonzero")
    if link_count == 0:
        raise HierarchyPackError("empty hierarchy must omit the optional asset")
    if link_count > MAX_HIERARCHY_LINKS:
        raise HierarchyPackError("hierarchy link count exceeds its limit")
    expected_size = HIERARCHY_HEADER_BYTES + link_count * HIERARCHY_LINK_BYTES
    if len(data) < expected_size:
        raise HierarchyPackError("truncated hierarchy link records")
    if len(data) > expected_size:
        raise HierarchyPackError("hierarchy asset has trailing bytes")

    pairs = tuple(
        struct.unpack_from("<II", data, HIERARCHY_HEADER_BYTES + index * 8)
        for index in range(link_count)
    )
    links = _validated_links(pairs, node_count=node_count)
    topological = sorted(links, key=lambda link: (link.depth, link.child_index))
    return {
        "schema": "ugts-kc-native-transform-hierarchy-inspection-3.9.2",
        "format_version": version,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "link_count": link_count,
        "max_depth": max(link.depth for link in links),
        "record_bytes": HIERARCHY_LINK_BYTES,
        "links": [
            {
                "child_index": link.child_index,
                "parent_index": link.parent_index,
                "depth": link.depth,
            }
            for link in links
        ],
        "topological_child_indices": [link.child_index for link in topological],
    }


# Explicit long-form aliases keep the public API easy to discover without
# making the on-disk name or established pack-module naming inconsistent.
compile_transform_hierarchy_pack_bytes = compile_hierarchy_pack_bytes
inspect_transform_hierarchy_pack = inspect_hierarchy_pack
write_transform_hierarchy_pack = write_hierarchy_pack


__all__ = [
    "HIERARCHY_HEADER_BYTES",
    "HIERARCHY_LINK_BYTES",
    "HIERARCHY_PACK_ASSET",
    "HIERARCHY_PACK_ENDIAN",
    "HIERARCHY_PACK_MAGIC",
    "HIERARCHY_PACK_VERSION",
    "HierarchyLinkSpec",
    "HierarchyPackError",
    "MAX_HIERARCHY_DEPTH",
    "MAX_HIERARCHY_LINKS",
    "MAX_HIERARCHY_PACK_BYTES",
    "collect_hierarchy_links",
    "compile_hierarchy_pack_bytes",
    "compile_transform_hierarchy_pack_bytes",
    "inspect_hierarchy_pack",
    "inspect_transform_hierarchy_pack",
    "write_hierarchy_pack",
    "write_transform_hierarchy_pack",
]
