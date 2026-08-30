"""Sparse KCSP population sidecar for the native Android renderer."""
from __future__ import annotations

import hashlib
import math
from pathlib import Path
import struct
from typing import Any, Mapping

from .scatter import (
    MAX_SCATTER_GROUPS,
    MAX_SCATTER_INSTANCES_PER_GROUP,
    MAX_SCATTER_TOTAL_INSTANCES,
    ScatterError,
    collect_scatter_project_spec,
)


SCATTER_PACK_ASSET = "scatter_populations.kcsp"
SCATTER_PACK_MAGIC = b"KCSP392\0"
SCATTER_PACK_ENDIAN = 0x01020304
SCATTER_PACK_VERSION = 1
SCATTER_GROUP_BYTES = 36
MAX_SCATTER_PACK_BYTES = 64 * 1024
SCATTER_FLAG_RANDOM_YAW = 1 << 0

_SAVED_SCENE_METADATA_KEYS = frozenset({"saved_scenes", "saved_scene_instances"})


def _materialized_project(project: Any) -> Any:
    metadata = getattr(project, "metadata", {})
    if not isinstance(metadata, Mapping) or not any(
        key in metadata for key in _SAVED_SCENE_METADATA_KEYS
    ):
        return project
    from .saved_scene import materialize_saved_scenes

    return materialize_saved_scenes(project)


class ScatterPackError(ScatterError):
    """Invalid authoring data or a malformed KCSP sidecar."""


def compile_scatter_pack_bytes(project: Any) -> bytes:
    """Compile an optional constant-size-per-group KCSP asset."""

    project = _materialized_project(project)
    project.validate()
    spec = collect_scatter_project_spec(project)
    if not spec.groups:
        return b""
    output = bytearray()
    output.extend(SCATTER_PACK_MAGIC)
    output.extend(
        struct.pack(
            "<IIII",
            SCATTER_PACK_ENDIAN,
            SCATTER_PACK_VERSION,
            len(spec.groups),
            spec.total_instances,
        )
    )
    for group in spec.groups:
        population = group.population
        flags = SCATTER_FLAG_RANDOM_YAW if population.random_yaw else 0
        output.extend(
            struct.pack(
                "<IHHQ5f",
                group.prototype_node_index,
                population.instance_count,
                flags,
                population.seed,
                *population.size,
                population.scale_min,
                population.scale_max,
            )
        )
    result = bytes(output)
    if len(result) > MAX_SCATTER_PACK_BYTES:
        raise ScatterPackError(
            f"population pack is {len(result)} bytes; limit is {MAX_SCATTER_PACK_BYTES}"
        )
    # Run the same strict reader used by diagnostics before returning bytes to
    # the Android project generator.
    inspect_scatter_pack(result, node_count=len(getattr(project, "nodes", ())))
    return result


def write_scatter_pack(project: Any, path: str | Path) -> Path | None:
    data = compile_scatter_pack_bytes(project)
    if not data:
        return None
    result = Path(path)
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_bytes(data)
    return result


def inspect_scatter_pack(
    data_or_path: bytes | str | Path, *, node_count: int | None = None
) -> dict[str, Any]:
    """Validate every field and return human-readable population diagnostics."""

    data = (
        Path(data_or_path).read_bytes()
        if isinstance(data_or_path, (str, Path))
        else bytes(data_or_path)
    )
    if len(data) > MAX_SCATTER_PACK_BYTES:
        raise ScatterPackError("population asset exceeds its byte limit")
    if len(data) < 24:
        raise ScatterPackError("truncated population asset")
    if data[:8] != SCATTER_PACK_MAGIC:
        raise ScatterPackError("population magic mismatch")
    endian, version, group_count, total_instances = struct.unpack_from("<IIII", data, 8)
    if endian != SCATTER_PACK_ENDIAN:
        raise ScatterPackError("population endian marker mismatch")
    if version != SCATTER_PACK_VERSION:
        raise ScatterPackError("unsupported population version")
    if not 1 <= group_count <= MAX_SCATTER_GROUPS:
        raise ScatterPackError("population group count is invalid")
    expected_size = 24 + group_count * SCATTER_GROUP_BYTES
    if len(data) < expected_size:
        raise ScatterPackError("truncated population group record")
    if len(data) > expected_size:
        raise ScatterPackError(
            f"population asset has {len(data) - expected_size} trailing bytes"
        )

    groups: list[dict[str, Any]] = []
    previous_prototype: int | None = None
    counted_instances = 0
    offset = 24
    for _ in range(group_count):
        (
            prototype,
            instance_count,
            flags,
            seed,
            size_x,
            size_y,
            size_z,
            scale_min,
            scale_max,
        ) = struct.unpack_from("<IHHQ5f", data, offset)
        offset += SCATTER_GROUP_BYTES
        if previous_prototype is not None and prototype <= previous_prototype:
            raise ScatterPackError("population groups are not sparse-canonical")
        if node_count is not None and prototype >= node_count:
            raise ScatterPackError("population group has an invalid prototype node")
        if not 2 <= instance_count <= MAX_SCATTER_INSTANCES_PER_GROUP:
            raise ScatterPackError("population instance count is invalid")
        if flags & ~SCATTER_FLAG_RANDOM_YAW:
            raise ScatterPackError("population flags contain unsupported bits")
        if seed > 0xFFFFFFFF:
            raise ScatterPackError("population world number is outside the supported range")
        size = (size_x, size_y, size_z)
        if any(not math.isfinite(value) or value < 0 for value in size):
            raise ScatterPackError("population area size is invalid")
        if size_x <= 0 and size_z <= 0:
            raise ScatterPackError("population area width or depth must be positive")
        if (
            not math.isfinite(scale_min)
            or not math.isfinite(scale_max)
            or not 0.05 <= scale_min <= 8.0
            or not 0.05 <= scale_max <= 8.0
            or scale_min > scale_max
        ):
            raise ScatterPackError("population size variation is invalid")
        previous_prototype = prototype
        counted_instances += instance_count
        groups.append(
            {
                "prototype_node_index": prototype,
                "instance_count": instance_count,
                "generated_copy_count": instance_count - 1,
                "seed": seed,
                "size": list(size),
                "scale_min": scale_min,
                "scale_max": scale_max,
                "random_yaw": bool(flags & SCATTER_FLAG_RANDOM_YAW),
            }
        )
    if counted_instances != total_instances:
        raise ScatterPackError("population total does not match its group records")
    if total_instances > MAX_SCATTER_TOTAL_INSTANCES:
        raise ScatterPackError("population total exceeds the runtime safety limit")
    return {
        "schema": "ugts-kc-native-population-inspection-3.9.2",
        "format_version": SCATTER_PACK_VERSION,
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "group_count": group_count,
        "total_instances": total_instances,
        "generated_copy_count": total_instances - group_count,
        "groups": groups,
    }


__all__ = [
    "MAX_SCATTER_PACK_BYTES",
    "SCATTER_FLAG_RANDOM_YAW",
    "SCATTER_GROUP_BYTES",
    "SCATTER_PACK_ASSET",
    "SCATTER_PACK_ENDIAN",
    "SCATTER_PACK_MAGIC",
    "SCATTER_PACK_VERSION",
    "ScatterPackError",
    "compile_scatter_pack_bytes",
    "inspect_scatter_pack",
    "write_scatter_pack",
]
