"""Bounded, dependency-free Wavefront OBJ import for mobile-3D authoring."""
from __future__ import annotations

from dataclasses import dataclass
import io
import math
from pathlib import Path
import re

from .mobile3d import Mesh3DRecord


_INTEGER = re.compile(r"[+-]?[0-9]+\Z")


class ObjImportError(ValueError):
    """An OBJ file cannot be represented safely as a ``Mesh3DRecord``."""


@dataclass(frozen=True)
class ObjImportLimits:
    max_bytes: int = 32 * 1024 * 1024
    max_lines: int = 1_000_000
    max_line_characters: int = 1_000_000
    max_vertices: int = 250_000
    max_texture_coordinates: int = 500_000
    max_normals: int = 500_000
    max_face_corners: int = 1_500_000
    max_corners_per_face: int = 16_384
    max_triangles: int = 500_000

    def validate(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in vars(self).values()
        ):
            raise ValueError("OBJ import limits must all be positive whole numbers")


DEFAULT_OBJ_LIMITS = ObjImportLimits()


@dataclass(frozen=True)
class _Corner:
    vertex: int
    texture: int | None
    normal: int | None


def _line_error(line_number: int, message: str) -> ObjImportError:
    return ObjImportError(f"Line {line_number}: {message}")


def _finite_float(value: str, line_number: int, label: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise _line_error(line_number, f"{label} must be a number, not {value!r}.") from exc
    if not math.isfinite(result):
        raise _line_error(line_number, f"{label} must be finite.")
    return result


def _index(
    value: str,
    count: int,
    line_number: int,
    label: str,
) -> int:
    if not _INTEGER.fullmatch(value):
        raise _line_error(line_number, f"{label} index {value!r} is not a whole number.")
    raw = int(value)
    if raw == 0:
        raise _line_error(line_number, f"{label} index 0 is invalid; OBJ indices start at 1.")
    resolved = raw - 1 if raw > 0 else count + raw
    if resolved < 0 or resolved >= count:
        raise _line_error(
            line_number,
            f"{label} index {raw} is out of range; {count} {label} record(s) exist so far.",
        )
    return resolved


def _corner(
    token: str,
    line_number: int,
    vertex_count: int,
    texture_count: int,
    normal_count: int,
) -> _Corner:
    parts = token.split("/")
    if len(parts) > 3 or not parts[0]:
        raise _line_error(line_number, f"face corner {token!r} is malformed.")
    vertex = _index(parts[0], vertex_count, line_number, "vertex")
    texture: int | None = None
    normal: int | None = None
    if len(parts) == 2:
        if not parts[1]:
            raise _line_error(line_number, f"face corner {token!r} has an empty texture index.")
        texture = _index(parts[1], texture_count, line_number, "texture coordinate")
    elif len(parts) == 3:
        if not parts[2]:
            raise _line_error(line_number, f"face corner {token!r} has an empty normal index.")
        if parts[1]:
            texture = _index(parts[1], texture_count, line_number, "texture coordinate")
        normal = _index(parts[2], normal_count, line_number, "normal")
    return _Corner(vertex, texture, normal)


def _decoded_obj(data: str | bytes, limits: ObjImportLimits) -> tuple[str, int]:
    if isinstance(data, bytes):
        byte_count = len(data)
        if byte_count > limits.max_bytes:
            raise ObjImportError(
                f"This OBJ is larger than the {limits.max_bytes:,}-byte import limit."
            )
        try:
            return data.decode("utf-8-sig"), byte_count
        except UnicodeDecodeError as exc:
            raise ObjImportError("This OBJ is not valid UTF-8 text.") from exc
    if not isinstance(data, str):
        raise TypeError("OBJ data must be text or bytes")
    encoded = data.encode("utf-8")
    if len(encoded) > limits.max_bytes:
        raise ObjImportError(
            f"This OBJ is larger than the {limits.max_bytes:,}-byte import limit."
        )
    return data.removeprefix("\ufeff"), len(encoded)


def parse_wavefront_obj(
    data: str | bytes,
    mesh_id: str,
    *,
    source_name: str = "",
    limits: ObjImportLimits = DEFAULT_OBJ_LIMITS,
) -> Mesh3DRecord:
    """Parse a bounded OBJ subset into one validated mobile-3D mesh.

    Position, texture-coordinate and normal index forms are validated. Material,
    object, group and smoothing records are intentionally ignored because the
    current ``Mesh3DRecord`` represents one shape and materials live on scene
    nodes. Faces are triangulated deterministically as a fan.
    """

    limits.validate()
    if not str(mesh_id).strip():
        raise ObjImportError("The imported 3D shape needs a resource name.")
    text, byte_count = _decoded_obj(data, limits)
    positions: list[tuple[float, float, float]] = []
    textures: list[tuple[float, ...]] = []
    source_normals: list[tuple[float, float, float]] = []
    output_vertices: list[tuple[float, float, float]] = []
    output_normals: list[tuple[float, float, float] | None] = []
    output_lookup: dict[tuple[int, int | None, int | None], int] = {}
    triangles: list[tuple[int, int, int]] = []
    face_count = 0
    face_corner_count = 0
    line_count = 0

    def output_index(corner: _Corner, line_number: int) -> int:
        key = (corner.vertex, corner.texture, corner.normal)
        existing = output_lookup.get(key)
        if existing is not None:
            return existing
        if len(output_vertices) >= limits.max_vertices:
            raise _line_error(
                line_number,
                f"the expanded mesh exceeds the {limits.max_vertices:,}-vertex import limit.",
            )
        result = len(output_vertices)
        output_lookup[key] = result
        output_vertices.append(positions[corner.vertex])
        output_normals.append(
            None if corner.normal is None else source_normals[corner.normal]
        )
        return result

    for line_number, raw_line in enumerate(io.StringIO(text), 1):
        line_count = line_number
        if line_count > limits.max_lines:
            raise ObjImportError(f"This OBJ exceeds the {limits.max_lines:,}-line import limit.")
        if len(raw_line) > limits.max_line_characters:
            raise _line_error(
                line_number,
                f"this line exceeds the {limits.max_line_characters:,}-character import limit.",
            )
        line = raw_line.partition("#")[0].strip()
        if not line:
            continue
        fields = line.split()
        record, values = fields[0], fields[1:]
        if record == "v":
            if len(values) not in (3, 4):
                raise _line_error(line_number, "a vertex needs three coordinates and an optional weight.")
            if len(positions) >= limits.max_vertices:
                raise _line_error(
                    line_number,
                    f"the file exceeds the {limits.max_vertices:,}-vertex import limit.",
                )
            coordinates = [
                _finite_float(value, line_number, f"vertex coordinate {axis + 1}")
                for axis, value in enumerate(values)
            ]
            weight = coordinates[3] if len(coordinates) == 4 else 1.0
            if abs(weight) <= 1.0e-12:
                raise _line_error(line_number, "the optional vertex weight cannot be zero.")
            position = tuple(value / weight for value in coordinates[:3])
            if not all(math.isfinite(value) for value in position):
                raise _line_error(line_number, "the weighted vertex is not finite.")
            positions.append(position)  # type: ignore[arg-type]
        elif record == "vt":
            if not 1 <= len(values) <= 3:
                raise _line_error(line_number, "a texture coordinate needs one to three numbers.")
            if len(textures) >= limits.max_texture_coordinates:
                raise _line_error(
                    line_number,
                    "the file has too many texture coordinates for this importer.",
                )
            textures.append(
                tuple(
                    _finite_float(value, line_number, f"texture coordinate {axis + 1}")
                    for axis, value in enumerate(values)
                )
            )
        elif record == "vn":
            if len(values) != 3:
                raise _line_error(line_number, "a normal needs exactly three numbers.")
            if len(source_normals) >= limits.max_normals:
                raise _line_error(line_number, "the file has too many normals for this importer.")
            normal = tuple(
                _finite_float(value, line_number, f"normal coordinate {axis + 1}")
                for axis, value in enumerate(values)
            )
            length = math.sqrt(sum(value * value for value in normal))
            if length <= 1.0e-12:
                raise _line_error(line_number, "a normal cannot be the zero vector.")
            source_normals.append(tuple(value / length for value in normal))  # type: ignore[arg-type]
        elif record == "f":
            if len(values) < 3:
                raise _line_error(line_number, "a face needs at least three corners.")
            if len(values) > limits.max_corners_per_face:
                raise _line_error(
                    line_number,
                    f"this face exceeds the {limits.max_corners_per_face:,}-corner limit.",
                )
            face_corner_count += len(values)
            if face_corner_count > limits.max_face_corners:
                raise _line_error(
                    line_number,
                    f"the file exceeds the {limits.max_face_corners:,}-face-corner import limit.",
                )
            corners = [
                _corner(
                    value,
                    line_number,
                    len(positions),
                    len(textures),
                    len(source_normals),
                )
                for value in values
            ]
            face_count += 1
            for index in range(1, len(corners) - 1):
                source_triangle = (corners[0], corners[index], corners[index + 1])
                if len({corner.vertex for corner in source_triangle}) < 3:
                    raise _line_error(line_number, "this face creates a triangle with repeated vertices.")
                if len(triangles) >= limits.max_triangles:
                    raise _line_error(
                        line_number,
                        f"the mesh exceeds the {limits.max_triangles:,}-triangle import limit.",
                    )
                triangles.append(tuple(output_index(corner, line_number) for corner in source_triangle))  # type: ignore[arg-type]
        # Other standard OBJ records are authoring hints that this mesh record
        # cannot retain. They are ignored deliberately rather than misparsed.

    if not positions:
        raise ObjImportError("This OBJ does not contain any vertex records.")
    if not triangles:
        raise ObjImportError("This OBJ does not contain any usable face records.")
    normals = (
        tuple(value for value in output_normals if value is not None)
        if output_normals and all(value is not None for value in output_normals)
        else ()
    )
    mesh = Mesh3DRecord(
        str(mesh_id),
        tuple(output_vertices),
        tuple(triangles),
        normals,
        {
            "source_format": "wavefront_obj",
            "source_name": str(source_name),
            "source_bytes": byte_count,
            "source_lines": line_count,
            "source_vertices": len(positions),
            "source_faces": face_count,
            "source_texture_coordinates": len(textures),
            "source_normals": len(source_normals),
        },
    )
    try:
        mesh.validate()
    except ValueError as exc:
        raise ObjImportError(f"The OBJ produced an invalid 3D shape: {exc}") from exc
    return mesh


def load_wavefront_obj(
    path: str | Path,
    mesh_id: str,
    *,
    limits: ObjImportLimits = DEFAULT_OBJ_LIMITS,
) -> Mesh3DRecord:
    """Load one OBJ file without allowing unbounded file reads."""

    limits.validate()
    source = Path(path)
    if not source.is_file():
        raise ObjImportError(f"OBJ file not found: {source}")
    try:
        size = source.stat().st_size
    except OSError as exc:
        raise ObjImportError(f"Could not inspect the OBJ file: {exc}") from exc
    if size > limits.max_bytes:
        raise ObjImportError(
            f"This OBJ is larger than the {limits.max_bytes:,}-byte import limit."
        )
    try:
        with source.open("rb") as stream:
            data = stream.read(limits.max_bytes + 1)
    except OSError as exc:
        raise ObjImportError(f"Could not read the OBJ file: {exc}") from exc
    return parse_wavefront_obj(
        data,
        mesh_id,
        source_name=source.name,
        limits=limits,
    )


__all__ = [
    "DEFAULT_OBJ_LIMITS",
    "ObjImportError",
    "ObjImportLimits",
    "load_wavefront_obj",
    "parse_wavefront_obj",
]
